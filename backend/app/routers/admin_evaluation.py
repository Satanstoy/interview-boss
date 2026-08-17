"""Admin-only Evaluation Control Plane API."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Literal

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
    evaluation_release_id: int | None = None
    benchmark_suite_release_id: int | None = None
    eval_protocol_release_id: int | None = None
    judge_release_id: int | None = None
    simulator_harness_release_id: int | None = None
    candidate_simulator_release_id: int | None = None
    replication_count: int = Field(default=5, ge=1, le=100)
    seed: int = 1
    environment_fingerprint: str = ""
    comparison_group: str = ""
    idempotency_key: str | None = None


class CreateHumanReviewRequest(BaseModel):
    comparison_group: str = Field(min_length=1, max_length=200)
    run_a_id: int = Field(gt=0)
    run_b_id: int = Field(gt=0)
    item_key: str = Field(min_length=1, max_length=200)
    choice: Literal["a", "b", "tie", "both_fail"]
    dimensions: dict[str, Any] = Field(default_factory=dict)
    comment: str = Field(default="", max_length=4000)


def _decode_json(value: str | None, default: Any):
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


def _serialize_run(row) -> dict[str, Any]:
    result = dict(row)
    result["summary"] = _decode_json(result.pop("summary_json", "{}"), {})
    result["snapshot"] = _decode_json(result.pop("snapshot_json", "{}"), {})
    result["cancel_requested"] = bool(result.get("cancel_requested"))
    return result


def _run_query(conn, run_id: int):
    return conn.execute(
        """
        SELECT r.*, b.batch_fingerprint, b.replication_count,
               b.environment_fingerprint, b.seed,
               tr.release_key AS target_release_key,
               er.release_key AS evaluation_release_key,
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
        LEFT JOIN eval_releases er ON er.id = r.evaluation_release_id
        WHERE r.id = ?
        """,
        (run_id,),
    ).fetchone()


def _ab_snapshot_context(row) -> tuple[Any, ...] | None:
    """Return the immutable context fields that must match for human A/B."""
    if row["evaluation_release_id"] is None:
        return None
    snapshot = _decode_json(row["snapshot_json"], {})
    resolved = snapshot.get("resolved") or {}
    cases = tuple(
        (case.get("id"), case.get("input_digest"))
        for case in snapshot.get("cases", [])
        if isinstance(case, dict)
    )
    return (
        row["evaluation_release_id"],
        resolved.get("replication_count"),
        resolved.get("seed"),
        resolved.get("environment_fingerprint"),
        tuple(resolved.get("case_ids") or []),
        cases,
    )


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
            review_rows = conn.execute(
                """
                WITH review_groups AS (
                    SELECT
                        comparison_group,
                        run_a_id,
                        run_b_id,
                        COUNT(*) AS review_count,
                        SUM(CASE WHEN choice = 'a' THEN 1 ELSE 0 END) AS a_wins,
                        SUM(CASE WHEN choice = 'b' THEN 1 ELSE 0 END) AS b_wins,
                        SUM(CASE WHEN choice = 'tie' THEN 1 ELSE 0 END) AS ties,
                        SUM(CASE WHEN choice = 'both_fail' THEN 1 ELSE 0 END) AS both_fail,
                        MAX(created_at) AS last_review_at
                    FROM eval_human_reviews
                    GROUP BY comparison_group, run_a_id, run_b_id
                ), run_scores AS (
                    SELECT run_id, AVG(score) AS avg_score
                    FROM eval_items
                    WHERE status = 'completed' AND score IS NOT NULL
                    GROUP BY run_id
                )
                SELECT
                    g.comparison_group,
                    g.run_a_id,
                    g.run_b_id,
                    a_target.release_key AS run_a_target_release_key,
                    b_target.release_key AS run_b_target_release_key,
                    g.review_count,
                    g.a_wins,
                    g.b_wins,
                    g.ties,
                    g.both_fail,
                    g.last_review_at,
                    a_scores.avg_score AS run_a_avg_score,
                    b_scores.avg_score AS run_b_avg_score
                FROM review_groups g
                JOIN eval_runs run_a ON run_a.id = g.run_a_id
                JOIN eval_runs run_b ON run_b.id = g.run_b_id
                JOIN eval_releases a_target ON a_target.id = run_a.target_release_id
                JOIN eval_releases b_target ON b_target.id = run_b.target_release_id
                LEFT JOIN run_scores a_scores ON a_scores.run_id = g.run_a_id
                LEFT JOIN run_scores b_scores ON b_scores.run_id = g.run_b_id
                ORDER BY g.last_review_at DESC
                LIMIT 20
                """
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
                "human_reviews": {
                    "total": sum(row["review_count"] for row in review_rows),
                    "comparison_groups": [dict(row) for row in review_rows],
                },
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
            if release_type is None:
                clauses.append("release_type IN ('target', 'evaluation')")
            where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
            rows = conn.execute(
                f"SELECT * FROM eval_releases {where} ORDER BY id DESC", params
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["manifest"] = _decode_json(item.pop("manifest_json", "{}"), {})
                result.append(item)
            return result

    return {"releases": await run_db(_query)}


@router.get("/benchmarks")
async def list_benchmarks(admin: dict = Depends(get_admin_user)):
    def _query():
        with get_db_connection() as conn:
            suites = conn.execute(
                """
                SELECT s.*, r.release_key, r.version, r.status AS release_status,
                       r.release_type, r.target_type AS release_target_type,
                       r.manifest_digest, r.manifest_json
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
                item["manifest"] = _decode_json(item.pop("manifest_json", "{}"), {})
                item["evaluation_release_key"] = item.get("release_key")
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
                evaluation_release_id=body.evaluation_release_id,
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
                require_published=True,
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
                f"tr.release_key AS target_release_key, "
                f"COALESCE(er.release_key, br.release_key) AS evaluation_release_key, "
                f"br.release_key AS benchmark_suite_release_key "
                f"FROM eval_runs r JOIN eval_releases tr ON tr.id = r.target_release_id "
                f"JOIN eval_releases br ON br.id = r.benchmark_suite_release_id "
                f"LEFT JOIN eval_releases er ON er.id = r.evaluation_release_id "
                f"{where} "
                "ORDER BY r.id DESC LIMIT ?",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    return {"runs": await run_db(_query)}


@router.get("/reviews")
async def list_reviews(
    comparison_group: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    admin: dict = Depends(get_admin_user),
):
    def _query():
        with get_db_connection() as conn:
            if comparison_group:
                rows = conn.execute(
                    "SELECT * FROM eval_human_reviews "
                    "WHERE comparison_group = ? ORDER BY id DESC LIMIT ?",
                    (comparison_group, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM eval_human_reviews ORDER BY id DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            reviews = []
            for row in rows:
                review = dict(row)
                review["dimensions"] = _decode_json(review.pop("dimensions_json", "{}"), {})
                reviews.append(review)
            return reviews

    return {"reviews": await run_db(_query)}


@router.post("/reviews")
async def create_review(
    body: CreateHumanReviewRequest,
    admin: dict = Depends(get_admin_user),
):
    if body.run_a_id == body.run_b_id:
        raise HTTPException(status_code=400, detail="A/B 两条 Run 不能相同")

    def _create():
        with get_db_connection() as conn:
            runs = conn.execute(
                "SELECT id, target_release_id, comparison_group, evaluation_release_id, snapshot_json, benchmark_suite_release_id, eval_protocol_release_id, "
                "judge_release_id, simulator_harness_release_id, candidate_simulator_release_id "
                "FROM eval_runs WHERE id IN (?, ?)",
                (body.run_a_id, body.run_b_id),
            ).fetchall()
            if len(runs) != 2:
                raise HTTPException(status_code=404, detail="A/B Run 不存在")
            stored_groups = {row["comparison_group"] for row in runs if row["comparison_group"]}
            if stored_groups and stored_groups != {body.comparison_group}:
                raise HTTPException(status_code=400, detail="A/B Run 不属于指定 comparison group")
            dual_contexts = [_ab_snapshot_context(row) for row in runs]
            if any(context is not None for context in dual_contexts):
                if any(context is None for context in dual_contexts):
                    raise HTTPException(status_code=400, detail="A/B Run 必须使用同一种版本绑定模式")
                if len(set(dual_contexts)) != 1:
                    raise HTTPException(status_code=400, detail="A/B Run 的完整评测上下文不一致")
                if runs[0]["target_release_id"] == runs[1]["target_release_id"]:
                    raise HTTPException(status_code=400, detail="A/B Run 必须比较两个不同的被测版本")
            context_fields = ("evaluation_release_id",) if any(
                row["evaluation_release_id"] is not None for row in runs
            ) else (
                "benchmark_suite_release_id",
                "eval_protocol_release_id",
                "judge_release_id",
                "simulator_harness_release_id",
                "candidate_simulator_release_id",
            )
            if len({tuple(row[field] for field in context_fields) for row in runs}) != 1:
                raise HTTPException(status_code=400, detail="A/B Run 的评测上下文不一致")
            try:
                case_key, replication_text = body.item_key.rsplit("#", 1)
                replication_index = int(replication_text)
            except (ValueError, TypeError):
                raise HTTPException(status_code=400, detail="item_key 必须是 case_key#replication_index") from None
            allowed_statuses = {"completed", "failed"} if body.choice == "both_fail" else {"completed"}
            for run in runs:
                item = conn.execute(
                    "SELECT i.status FROM eval_items i "
                    "JOIN eval_benchmark_cases c ON c.id = i.case_id "
                    "WHERE i.run_id = ? AND c.case_key = ? AND i.replication_index = ?",
                    (run["id"], case_key, replication_index),
                ).fetchone()
                if item is None or item["status"] not in allowed_statuses:
                    raise HTTPException(status_code=400, detail="A/B Item 不存在或尚未完成")
            try:
                cursor = conn.execute(
                    "INSERT INTO eval_human_reviews "
                    "(comparison_group, run_a_id, run_b_id, item_key, reviewer_id, choice, dimensions_json, comment) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        body.comparison_group,
                        body.run_a_id,
                        body.run_b_id,
                        body.item_key,
                        admin["id"],
                        body.choice,
                        json.dumps(body.dimensions, ensure_ascii=False, sort_keys=True),
                        body.comment,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(status_code=400, detail="人工评测记录无效") from exc
            conn.commit()
            row = conn.execute(
                "SELECT * FROM eval_human_reviews WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
            result = dict(row)
            result["dimensions"] = _decode_json(result.pop("dimensions_json", "{}"), {})
            return result

    return await run_db(_create)


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
