"""Admin-only Evaluation Control Plane API."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.auth import get_admin_user
from app.db.connection import get_db_connection, run_db
from app.evaluation.queue import enqueue_eval_run_job
from app.services.evaluation_service import (
    append_event,
    create_eval_run,
    list_events_after,
)

router = APIRouter(prefix="/api/admin/evals", tags=["admin-evaluation"])


class CreateEvalRunRequest(BaseModel):
    target_release_id: int
    benchmark_suite_release_id: int
    eval_protocol_release_id: int
    judge_release_id: int
    simulator_harness_release_id: int
    candidate_simulator_release_id: int
    replication_count: int = Field(default=5, ge=1, le=100)
    seed: int = 1
    environment_fingerprint: str = ""
    comparison_group: str = ""
    idempotency_key: str | None = None


def _decode_json(value: str | None, default: Any):
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


def _serialize_run(row) -> dict[str, Any]:
    result = dict(row)
    result["summary"] = _decode_json(result.pop("summary_json", "{}"), {})
    result["cancel_requested"] = bool(result.get("cancel_requested"))
    return result


def _run_query(conn, run_id: int):
    return conn.execute(
        """
        SELECT r.*, b.batch_fingerprint, b.replication_count,
               b.environment_fingerprint, b.seed,
               tr.release_key AS target_release_key,
               bs.release_key AS benchmark_suite_release_key,
               ep.release_key AS eval_protocol_release_key,
               jr.release_key AS judge_release_key,
               jr.judge_model,
               sh.release_key AS simulator_harness_release_key,
               cs.release_key AS candidate_simulator_release_key
        FROM eval_runs r
        JOIN eval_batches b ON b.id = r.batch_id
        JOIN eval_releases tr ON tr.id = r.target_release_id
        JOIN eval_releases bs ON bs.id = r.benchmark_suite_release_id
        JOIN eval_releases ep ON ep.id = r.eval_protocol_release_id
        JOIN eval_releases jr ON jr.id = r.judge_release_id
        JOIN eval_releases sh ON sh.id = r.simulator_harness_release_id
        JOIN eval_releases cs ON cs.id = r.candidate_simulator_release_id
        WHERE r.id = ?
        """,
        (run_id,),
    ).fetchone()


@router.get("/overview")
async def overview(admin: dict = Depends(get_admin_user)):
    def _query():
        with get_db_connection() as conn:
            counts = conn.execute(
                "SELECT status, COUNT(*) AS count FROM eval_runs GROUP BY status"
            ).fetchall()
            latest = conn.execute(
                "SELECT id, status, target_release_id, summary_json, created_at "
                "FROM eval_runs ORDER BY id DESC LIMIT 10"
            ).fetchall()
            return {
                "counts": {row["status"]: row["count"] for row in counts},
                "latest_runs": [
                    {
                        "id": row["id"],
                        "status": row["status"],
                        "target_release_id": row["target_release_id"],
                        "summary": _decode_json(row["summary_json"], {}),
                        "created_at": row["created_at"],
                    }
                    for row in latest
                ],
            }

    return await run_db(_query)


@router.get("/releases")
async def list_releases(
    release_type: str | None = Query(default=None),
    status: str | None = Query(default=None),
    admin: dict = Depends(get_admin_user),
):
    def _query():
        with get_db_connection() as conn:
            clauses = []
            params = []
            if release_type:
                clauses.append("release_type = ?")
                params.append(release_type)
            if status:
                clauses.append("status = ?")
                params.append(status)
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"SELECT * FROM eval_releases {where} ORDER BY id DESC", params
            ).fetchall()
            return [dict(row) for row in rows]

    return {"releases": await run_db(_query)}


@router.get("/benchmarks")
async def list_benchmarks(admin: dict = Depends(get_admin_user)):
    def _query():
        with get_db_connection() as conn:
            suites = conn.execute(
                """
                SELECT s.*, r.release_key, r.version, r.status AS release_status,
                       r.manifest_digest
                FROM eval_benchmark_suites s
                JOIN eval_releases r ON r.id = s.release_id
                ORDER BY s.id DESC
                """
            ).fetchall()
            result = []
            for suite in suites:
                cases = conn.execute(
                    """
                    SELECT id, case_key, scenario_key, input_digest, active,
                           input_snapshot_json, contract_json
                    FROM eval_benchmark_cases WHERE suite_id = ? ORDER BY id
                    """,
                    (suite["id"],),
                ).fetchall()
                item = dict(suite)
                item["cases"] = [
                    {
                        **dict(case),
                        "input_snapshot": _decode_json(case["input_snapshot_json"], {}),
                        "contract": _decode_json(case["contract_json"], {}),
                    }
                    for case in cases
                ]
                for case in item["cases"]:
                    case.pop("input_snapshot_json", None)
                    case.pop("contract_json", None)
                result.append(item)
            return result

    return {"suites": await run_db(_query)}


@router.post("/runs")
async def create_run(body: CreateEvalRunRequest, admin: dict = Depends(get_admin_user)):
    def _create():
        with get_db_connection() as conn:
            result = create_eval_run(
                conn,
                created_by=admin["id"],
                target_release_id=body.target_release_id,
                benchmark_suite_release_id=body.benchmark_suite_release_id,
                eval_protocol_release_id=body.eval_protocol_release_id,
                judge_release_id=body.judge_release_id,
                simulator_harness_release_id=body.simulator_harness_release_id,
                candidate_simulator_release_id=body.candidate_simulator_release_id,
                replication_count=body.replication_count,
                seed=body.seed,
                environment_fingerprint=body.environment_fingerprint,
                comparison_group=body.comparison_group,
                idempotency_key=body.idempotency_key,
            )
            append_event(
                conn,
                result["id"],
                "run.created",
                {"batch_fingerprint": result["batch_fingerprint"]},
            )
            conn.commit()
            return result

    try:
        result = await run_db(_create)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    dispatch_error = None
    status = "created"
    try:
        job = await enqueue_eval_run_job(result["id"])
        arq_job_id = getattr(job, "job_id", None)

        def _mark_queued():
            with get_db_connection() as conn:
                conn.execute(
                    "UPDATE eval_runs SET status = 'queued' WHERE id = ? AND status = 'created'",
                    (result["id"],),
                )
                conn.execute(
                    "UPDATE eval_batches SET status = 'queued' WHERE id = ? AND status = 'created'",
                    (result["batch_id"],),
                )
                append_event(conn, result["id"], "run.queued", {"arq_job_id": arq_job_id})
                conn.commit()

        await run_db(_mark_queued)
        status = "queued"
    except Exception as exc:
        dispatch_error = str(exc)[:300]

    return {
        "run_id": result["id"],
        "batch_id": result["batch_id"],
        "batch_fingerprint": result["batch_fingerprint"],
        "status": status,
        "total_items": result["total_items"],
        "dispatch_error": dispatch_error,
    }


@router.get("/runs")
async def list_runs(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    admin: dict = Depends(get_admin_user),
):
    def _query():
        with get_db_connection() as conn:
            params = []
            where = ""
            if status:
                where = "WHERE r.status = ?"
                params.append(status)
            params.append(limit)
            rows = conn.execute(
                f"SELECT r.id, r.status, r.total_items, r.completed_items, r.failed_items, "
                f"r.comparison_group, r.created_at, r.started_at, r.finished_at, "
                f"tr.release_key AS target_release_key, br.release_key AS benchmark_suite_release_key "
                f"FROM eval_runs r JOIN eval_releases tr ON tr.id = r.target_release_id "
                f"JOIN eval_releases br ON br.id = r.benchmark_suite_release_id {where} "
                "ORDER BY r.id DESC LIMIT ?",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    return {"runs": await run_db(_query)}


@router.get("/runs/{run_id}")
async def get_run(run_id: int, admin: dict = Depends(get_admin_user)):
    def _query():
        with get_db_connection() as conn:
            row = _run_query(conn, run_id)
            if row is None:
                return None
            result = _serialize_run(row)
            items = conn.execute(
                """
                SELECT i.*, c.case_key, c.scenario_key
                FROM eval_items i JOIN eval_benchmark_cases c ON c.id = i.case_id
                WHERE i.run_id = ? ORDER BY i.id
                """,
                (run_id,),
            ).fetchall()
            result["items"] = []
            for item in items:
                serialized = dict(item)
                serialized["result"] = _decode_json(serialized.pop("result_json", "{}"), {})
                serialized["cancel_requested"] = bool(serialized.get("cancel_requested", 0))
                result["items"].append(serialized)
            return result

    result = await run_db(_query)
    if result is None:
        raise HTTPException(status_code=404, detail="Eval Run 不存在")
    return result


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: int, admin: dict = Depends(get_admin_user)):
    def _cancel():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT id, batch_id, status FROM eval_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            if row["status"] in {"completed", "failed", "cancelled"}:
                return {"run_id": run_id, "status": row["status"], "cancel_requested": True}
            conn.execute(
                "UPDATE eval_runs SET cancel_requested = 1, status = CASE "
                "WHEN status IN ('created', 'queued') THEN 'cancelled' ELSE status END WHERE id = ?",
                (run_id,),
            )
            conn.execute(
                "UPDATE eval_batches SET cancel_requested = 1, status = CASE "
                "WHEN status IN ('created', 'queued') THEN 'cancelled' ELSE status END WHERE id = ?",
                (row["batch_id"],),
            )
            append_event(conn, run_id, "run.cancel_requested", {"admin_id": admin["id"]})
            conn.commit()
            current = conn.execute(
                "SELECT status, cancel_requested FROM eval_runs WHERE id = ?", (run_id,)
            ).fetchone()
            return {
                "run_id": run_id,
                "status": current["status"],
                "cancel_requested": bool(current["cancel_requested"]),
            }

    result = await run_db(_cancel)
    if result is None:
        raise HTTPException(status_code=404, detail="Eval Run 不存在")
    return result


@router.get("/runs/{run_id}/events")
async def run_events(
    request: Request,
    run_id: int,
    after_sequence: int = Query(default=0, ge=0),
    admin: dict = Depends(get_admin_user),
):
    header_value = request.headers.get("last-event-id")
    if header_value and header_value.isdigit():
        after_sequence = max(after_sequence, int(header_value))

    async def stream():
        cursor = after_sequence
        while True:
            def _read():
                with get_db_connection() as conn:
                    run = conn.execute(
                        "SELECT status FROM eval_runs WHERE id = ?", (run_id,)
                    ).fetchone()
                    events = list_events_after(conn, run_id, after_sequence=cursor)
                    return run, events

            run, events = await run_db(_read)
            if run is None:
                return
            for event in events:
                cursor = event["sequence"]
                yield (
                    f"id: {cursor}\n"
                    f"event: {event['event_type']}\n"
                    f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                )
            if run["status"] in {"completed", "failed", "cancelled"}:
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
