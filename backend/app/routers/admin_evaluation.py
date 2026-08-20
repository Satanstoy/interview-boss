"""Admin-only Evaluation Control Plane API."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Literal

from app.core.auth import get_admin_user
from app.core.harness_registry import PROJECT_HARNESS_VERSION
from app.db.connection import get_db_connection, run_db
from app.evaluation.adapters import AdapterNotConfigured, get_target_adapter
from app.evaluation.benchmark_catalog import BUILTIN_SUITES
from app.evaluation.evidence_contract import CaseEvidenceView, build_case_evidence_view
from app.evaluation.metric_registry import (
    TARGET_METRIC_DICTIONARY,
    build_metric_cards,
    build_progress_distribution,
    classify_progress_outcome,
    quality_threshold_from_manifest,
)
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
    project_harness_release_id: int | None = None
    candidate_simulator_release_id: int | None = None
    replication_count: int = Field(default=5, ge=1, le=100)
    seed: int = 1
    environment_fingerprint: str = ""
    comparison_group: str = ""
    idempotency_key: str | None = None
    case_keys: list[str] | None = None


class CreateEvalExperimentRequest(BaseModel):
    target_types: list[str] | None = Field(default=None, min_length=1, max_length=5)
    replication_count: int = Field(default=5, ge=1, le=100)
    seed: int = 1
    environment_fingerprint: str = ""
    comparison_group: str = ""


class CreateHumanReviewRequest(BaseModel):
    comparison_group: str = Field(min_length=1, max_length=200)
    run_a_id: int = Field(gt=0)
    run_b_id: int = Field(gt=0)
    item_key: str = Field(min_length=1, max_length=200)
    choice: Literal["a", "b", "tie", "both_fail"]
    dimensions: dict[str, Any] = Field(default_factory=dict)
    comment: str = Field(default="", max_length=4000)


def _capability_release(row, harness=None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "release_key": row["release_key"],
        "version": row["version"],
        "target_type": row["target_type"],
        "status": row["status"],
        "judge_model": row["judge_model"],
        "manifest_digest": row["manifest_digest"],
        "project_harness_release_id": harness["id"] if harness else None,
        "project_harness_release_key": (
            f"{harness['harness_key']}@{harness['version']}" if harness else None
        ),
        "project_harness_version": harness["version"] if harness else None,
    }


def _experiment_event(conn, experiment_id: int, event_type: str, payload: dict[str, Any] | None = None):
    sequence = conn.execute(
        "SELECT COALESCE(MAX(sequence), 0) + 1 FROM eval_experiment_events WHERE experiment_id = ?",
        (experiment_id,),
    ).fetchone()[0]
    conn.execute(
        """
        INSERT INTO eval_experiment_events (experiment_id, sequence, event_type, payload_json)
        VALUES (?, ?, ?, ?)
        """,
        (experiment_id, sequence, event_type, json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)),
    )


def _refresh_experiment(conn, experiment_id: int) -> dict[str, Any] | None:
    experiment = conn.execute(
        "SELECT * FROM eval_experiments WHERE id = ?", (experiment_id,)
    ).fetchone()
    if experiment is None:
        return None
    children = conn.execute(
        """
        SELECT er.target_type, er.display_order, r.id AS run_id, r.status,
               r.total_items, r.completed_items, r.failed_items,
               r.created_at, r.started_at, r.finished_at,
               tr.release_key AS target_release_key,
               ev.release_key AS evaluation_release_key,
               hr.harness_key AS project_harness_key,
               hr.version AS project_harness_version
        FROM eval_experiment_runs er
        JOIN eval_runs r ON r.id = er.run_id
        JOIN eval_releases tr ON tr.id = r.target_release_id
        LEFT JOIN eval_releases ev ON ev.id = r.evaluation_release_id
        LEFT JOIN harness_releases hr ON hr.id = r.harness_release_id
        WHERE er.experiment_id = ?
        ORDER BY er.display_order, er.id
        """,
        (experiment_id,),
    ).fetchall()
    total_runs = len(children)
    completed_runs = sum(row["status"] == "completed" for row in children)
    failed_runs = sum(row["status"] == "failed" for row in children)
    cancelled_runs = sum(row["status"] == "cancelled" for row in children)
    total_items = sum(row["total_items"] or 0 for row in children)
    completed_items = sum(row["completed_items"] or 0 for row in children)
    failed_items = sum(row["failed_items"] or 0 for row in children)
    if total_runs and completed_runs + failed_runs + cancelled_runs == total_runs:
        status = "failed" if failed_runs else "cancelled" if cancelled_runs else "completed"
    elif any(row["status"] == "running" for row in children):
        status = "running"
    elif any(row["status"] == "queued" for row in children):
        status = "queued"
    else:
        status = "created"
    summary = {
        "total_runs": total_runs,
        "completed_runs": completed_runs,
        "failed_runs": failed_runs,
        "cancelled_runs": cancelled_runs,
        "total_items": total_items,
        "completed_items": completed_items,
        "failed_items": failed_items,
    }
    child_payloads = []
    quality_metadata = _run_quality_metadata(conn, [row["run_id"] for row in children])
    for row in children:
        child = dict(row)
        metadata = quality_metadata.get(row["run_id"], {})
        child["quality_status"] = metadata.get("quality_status", "pending")
        child["distribution"] = metadata.get("distribution", _empty_distribution())
        child_payloads.append(child)
    child_quality = [child["quality_status"] for child in child_payloads]
    quality_status = (
        "pending" if any(value == "pending" for value in child_quality)
        else "failed" if any(value == "failed" for value in child_quality)
        else "not_evaluated" if any(value == "not_evaluated" for value in child_quality)
        else "passed"
    )
    summary["quality_status"] = quality_status
    previous_summary = _decode_json(experiment["summary_json"], {})
    previous_status = experiment["status"]
    progress_keys = (
        "total_runs", "completed_runs", "failed_runs", "cancelled_runs",
        "total_items", "completed_items", "failed_items", "quality_status",
    )
    derived_progress = {key: summary[key] for key in progress_keys}
    progress_changed = any(
        previous_summary.get(key) != summary.get(key) for key in progress_keys
    )
    # Read-only polls (GET/SSE) must not write the row or append events when
    # nothing changed: derive first, persist only on actual change.
    if previous_status != status or progress_changed:
        conn.execute(
            """
            UPDATE eval_experiments
            SET status = ?, total_runs = ?, completed_runs = ?, failed_runs = ?,
                cancelled_runs = ?, summary_json = ?,
                started_at = CASE WHEN ? IN ('running', 'completed', 'failed')
                                  THEN COALESCE(started_at, CURRENT_TIMESTAMP) ELSE started_at END,
                finished_at = CASE WHEN ? IN ('completed', 'failed', 'cancelled')
                                   THEN COALESCE(finished_at, CURRENT_TIMESTAMP) ELSE NULL END
            WHERE id = ?
            """,
            (
                status,
                total_runs,
                completed_runs,
                failed_runs,
                cancelled_runs,
                json.dumps(summary, ensure_ascii=False, sort_keys=True),
                status,
                status,
                experiment_id,
            ),
        )
        if previous_status != status:
            _experiment_event(
                conn,
                experiment_id,
                "experiment.status_changed",
                {"from": previous_status, "to": status},
            )
        if progress_changed:
            _experiment_event(
                conn,
                experiment_id,
                "experiment.progress",
                derived_progress,
            )
    return {
        **dict(experiment),
        "status": status,
        "target_types": _decode_json(experiment["target_types_json"], []),
        "summary": summary,
        "total_runs": total_runs,
        "completed_runs": completed_runs,
        "failed_runs": failed_runs,
        "cancelled_runs": cancelled_runs,
        "total_items": total_items,
        "completed_items": completed_items,
        "failed_items": failed_items,
        "quality_status": quality_status,
        "runs": child_payloads,
    }


def _decode_json(value: str | None, default: Any):
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


def _empty_distribution() -> dict[str, int]:
    return {"total": 0, "passed": 0, "poor": 0, "failed": 0, "pending": 0}


def _run_evaluation_manifest(conn, run_id: int) -> dict[str, Any]:
    """Read the frozen evaluation manifest before falling back to the live release."""
    row = conn.execute(
        """
        SELECT r.snapshot_json, er.manifest_json
        FROM eval_runs r
        LEFT JOIN eval_releases er ON er.id = r.evaluation_release_id
        WHERE r.id = ?
        """,
        (run_id,),
    ).fetchone()
    if row is None:
        return {}
    snapshot = _decode_json(row["snapshot_json"], {})
    evaluation = snapshot.get("evaluation_release") if isinstance(snapshot, dict) else None
    frozen_manifest = evaluation.get("manifest") if isinstance(evaluation, dict) else None
    if isinstance(frozen_manifest, dict):
        return frozen_manifest
    return _decode_json(row["manifest_json"], {})


def _run_progress_distribution(conn, run_id: int) -> dict[str, int]:
    run = conn.execute(
        """
        SELECT r.total_items
        FROM eval_runs r
        WHERE r.id = ?
        """,
        (run_id,),
    ).fetchone()
    if run is None:
        return _empty_distribution()
    items = []
    for row in conn.execute(
        """
        SELECT status, contract_status, hard_gate_status, judge_status, score, result_json
        FROM eval_items WHERE run_id = ?
        """,
        (run_id,),
    ).fetchall():
        item = dict(row)
        result = _decode_json(item.pop("result_json", "{}"), {})
        item["result"] = result
        items.append(item)
    manifest = _run_evaluation_manifest(conn, run_id)
    return build_progress_distribution(
        items,
        total=run["total_items"],
        poor_score_below=quality_threshold_from_manifest(manifest),
    )


def _run_metric_cards(conn, run_id: int, target_type: str) -> list[dict[str, Any]]:
    definition = TARGET_METRIC_DICTIONARY.get(target_type)
    if definition is None:
        return []
    row = conn.execute(
        "SELECT summary_json FROM eval_runs WHERE id = ?", (run_id,)
    ).fetchone()
    summary = _decode_json(row["summary_json"] if row else "{}", {})
    return build_metric_cards(target_type, summary.get("metric_summary"), thresholds={})


def _run_attention_cases(conn, run_id: int, target_type: str) -> list[dict[str, Any]]:
    manifest = _run_evaluation_manifest(conn, run_id)
    threshold = quality_threshold_from_manifest(manifest)
    items = []
    for row in conn.execute(
        """
        SELECT i.id, i.case_id, c.case_key, c.scenario_key,
               i.replication_index, i.seed, i.status,
               i.contract_status, i.hard_gate_status, i.judge_status,
               i.score, i.result_json
        FROM eval_items i
        JOIN eval_benchmark_cases c ON c.id = i.case_id
        WHERE i.run_id = ? ORDER BY i.id
        """,
        (run_id,),
    ).fetchall():
        item = dict(row)
        result = _decode_json(item.pop("result_json", "{}"), {})
        item["result"] = result
        items.append(item)
    return _attention_cases_from_items(items, run_id, target_type, threshold)


def _attention_cases_from_items(
    items: list[dict[str, Any]],
    run_id: int,
    target_type: str,
    threshold: float | None,
) -> list[dict[str, Any]]:
    attention = []
    for item in items:
        outcome = classify_progress_outcome(item, threshold)
        if outcome == "passed":
            continue
        result = item.get("result")
        observation = result.get("observation") if isinstance(result, dict) else {}
        reason = None
        for assertion in (observation or {}).get("hard_assertions") or []:
            if isinstance(assertion, dict) and not assertion.get("passed") and assertion.get("evidence"):
                reason = str(assertion["evidence"])
                break
        if not reason:
            reason = {
                "poor": "综合表现低于目标线",
                "failed": "执行或硬性要求未通过",
                "pending": "评测尚未完成",
            }[outcome]
        attention.append(
            {
                "run_id": run_id,
                "item_id": item["id"],
                "target_type": target_type,
                "case_key": item.get("case_key") or "",
                "scenario_key": item.get("scenario_key"),
                "replication_index": item.get("replication_index"),
                "score": item.get("score"),
                "outcome": outcome,
                "primary_failure_reason": reason,
            }
        )
    order = {"failed": 0, "poor": 1, "pending": 2}
    return sorted(attention, key=lambda item: (order[item["outcome"]], item["item_id"]))[:20]


def _quality_status_from_items(
    items: list[dict[str, Any]],
    execution_status: str,
    distribution: dict[str, int],
) -> str:
    if not items or any(item.get("status") in {"pending", "running"} for item in items):
        return "pending"
    if execution_status == "cancelled":
        return "not_evaluated"
    if execution_status != "completed":
        return "failed"
    if distribution["poor"]:
        return "failed"
    return "passed" if all(
        item.get("status") == "completed"
        and item.get("contract_status") == "valid"
        and item.get("hard_gate_status") == "passed"
        and item.get("judge_status") == "succeeded"
        for item in items
    ) else "failed"


def _run_quality_metadata(conn, run_ids: list[int]) -> dict[int, dict[str, Any]]:
    """Build list/overview quality fields with one run query and one item query."""
    if not run_ids:
        return {}
    placeholders = ",".join("?" for _ in run_ids)
    runs = conn.execute(
        f"""
        SELECT r.id, r.status, r.total_items, r.snapshot_json, r.summary_json,
               er.manifest_json, tr.target_type
        FROM eval_runs r
        LEFT JOIN eval_releases er ON er.id = r.evaluation_release_id
        LEFT JOIN eval_releases tr ON tr.id = r.target_release_id
        WHERE r.id IN ({placeholders})
        """,
        run_ids,
    ).fetchall()
    items_by_run: dict[int, list[dict[str, Any]]] = {run_id: [] for run_id in run_ids}
    item_rows = conn.execute(
        f"""
        SELECT i.run_id, i.id, i.case_id, c.case_key, c.scenario_key,
               i.replication_index, i.seed, i.status,
               i.contract_status, i.hard_gate_status, i.judge_status,
               i.score, i.result_json
        FROM eval_items i
        JOIN eval_benchmark_cases c ON c.id = i.case_id
        WHERE i.run_id IN ({placeholders})
        ORDER BY i.run_id, i.id
        """,
        run_ids,
    ).fetchall()
    for row in item_rows:
        item = dict(row)
        item["result"] = _decode_json(item.pop("result_json", "{}"), {})
        items_by_run.setdefault(item["run_id"], []).append(item)

    metadata: dict[int, dict[str, Any]] = {}
    for row in runs:
        run_id = int(row["id"])
        items = items_by_run.get(run_id, [])
        snapshot = _decode_json(row["snapshot_json"], {})
        evaluation = snapshot.get("evaluation_release") if isinstance(snapshot, dict) else None
        frozen_manifest = evaluation.get("manifest") if isinstance(evaluation, dict) else None
        manifest = frozen_manifest if isinstance(frozen_manifest, dict) else _decode_json(row["manifest_json"], {})
        distribution = build_progress_distribution(
            items,
            total=row["total_items"],
            poor_score_below=quality_threshold_from_manifest(manifest),
        )
        target_type = str(row["target_type"] or "")
        summary = _decode_json(row["summary_json"], {})
        metadata[run_id] = {
            "quality_status": _quality_status_from_items(items, row["status"], distribution),
            "distribution": distribution,
            "metric_cards": build_metric_cards(target_type, summary.get("metric_summary"), thresholds={}) if target_type in TARGET_METRIC_DICTIONARY else [],
            "attention_cases": _attention_cases_from_items(
                items,
                run_id,
                target_type,
                quality_threshold_from_manifest(manifest),
            ),
        }
    return metadata


def _serialize_run(row) -> dict[str, Any]:
    result = dict(row)
    result["summary"] = _decode_json(result.pop("summary_json", "{}"), {})
    result["snapshot"] = _decode_json(result.pop("snapshot_json", "{}"), {})
    result["cancel_requested"] = bool(result.get("cancel_requested"))
    return result


def _quality_status(conn, run_id: int, execution_status: str) -> str:
    """Separate quality outcome from whether the execution job finished."""
    rows = conn.execute(
        "SELECT status, contract_status, hard_gate_status, judge_status FROM eval_items WHERE run_id = ?",
        (run_id,),
    ).fetchall()
    return _quality_status_from_items(
        [dict(row) for row in rows],
        execution_status,
        _run_progress_distribution(conn, run_id),
    )


def _run_query(conn, run_id: int):
    return conn.execute(
        """
        SELECT r.*, b.batch_fingerprint, b.replication_count,
               b.environment_fingerprint, b.seed,
               tr.release_key AS target_release_key,
               tr.target_type AS target_type,
               er.release_key AS evaluation_release_key,
               bs.release_key AS benchmark_suite_release_key,
               ep.release_key AS eval_protocol_release_key,
               jr.release_key AS judge_release_key,
               jr.judge_model,
               sh.release_key AS simulator_harness_release_key,
               hr.harness_key AS project_harness_key,
               hr.version AS project_harness_version,
               hr.display_name AS project_harness_display_name,
               hr.manifest_digest AS project_harness_manifest_digest,
               cs.release_key AS candidate_simulator_release_key
        FROM eval_runs r
        JOIN eval_batches b ON b.id = r.batch_id
        JOIN eval_releases tr ON tr.id = r.target_release_id
        JOIN eval_releases bs ON bs.id = r.benchmark_suite_release_id
        JOIN eval_releases ep ON ep.id = r.eval_protocol_release_id
        JOIN eval_releases jr ON jr.id = r.judge_release_id
        JOIN eval_releases sh ON sh.id = r.simulator_harness_release_id
        JOIN eval_releases cs ON cs.id = r.candidate_simulator_release_id
        LEFT JOIN harness_releases hr ON hr.id = r.harness_release_id
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


def _ab_harness_identity(row) -> tuple[Any, ...]:
    """Return the Harness identity that A/B is intentionally comparing."""
    snapshot = _decode_json(row["snapshot_json"], {})
    harness = snapshot.get("harness_release") or {}
    if harness:
        return harness.get("id"), harness.get("manifest_digest")
    # Legacy runs only have the old simulator Harness foreign key. Keep the
    # fallback for old human-review data without pretending it is a project
    # registry snapshot.
    return row["simulator_harness_release_id"], None


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
            all_runs = conn.execute(
                """
                SELECT r.id, r.status, r.summary_json, tr.target_type, tr.release_key
                FROM eval_runs r
                JOIN eval_releases tr ON tr.id = r.target_release_id
                ORDER BY r.id
                """
            ).fetchall()
            quality_metadata = _run_quality_metadata(conn, [run["id"] for run in all_runs])
            by_target: dict[str, dict[str, Any]] = {}
            for run in all_runs:
                tt = run["target_type"] or "未分类"
                agg = by_target.setdefault(
                    tt,
                    {
                        "target_type": tt,
                        "target_release_key": run["release_key"],
                        "run_count": 0,
                        "passed_count": 0,
                        "failed_count": 0,
                        "pending_count": 0,
                        "distribution": {
                            "total": 0,
                            "passed": 0,
                            "poor": 0,
                            "failed": 0,
                            "pending": 0,
                        },
                        "total_score_sum": 0.0,
                        "scored_run_count": 0,
                    },
                )
                agg["run_count"] += 1
                metadata = quality_metadata.get(run["id"], {})
                quality = metadata.get("quality_status", "pending")
                if quality == "passed":
                    agg["passed_count"] += 1
                elif quality == "failed":
                    agg["failed_count"] += 1
                else:
                    agg["pending_count"] += 1
                distribution = metadata.get("distribution", _empty_distribution())
                for key in ("total", "passed", "poor", "failed", "pending"):
                    agg["distribution"][key] += distribution[key]
                summary = _decode_json(run["summary_json"], {})
                final_mean = (summary.get("metric_summary") or {}).get("score") or {}
                final_mean = final_mean.get("final_mean")
                if final_mean is not None:
                    agg["total_score_sum"] += float(final_mean)
                    agg["scored_run_count"] += 1
            for agg in by_target.values():
                agg["avg_score"] = (
                    round(agg["total_score_sum"] / agg["scored_run_count"], 3)
                    if agg["scored_run_count"]
                    else None
                )
                agg.pop("total_score_sum", None)
                agg.pop("scored_run_count", None)
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
                "by_target": sorted(by_target.values(), key=lambda x: x["target_type"]),
            }

    return await run_db(_query)


@router.get("/capabilities")
async def capabilities(admin: dict = Depends(get_admin_user)):
    """Return the frontend's actual runnable evaluation capabilities."""

    def _query():
        with get_db_connection() as conn:
            result = []
            for spec in BUILTIN_SUITES:
                target = conn.execute(
                    """
                    SELECT id, release_key, version, target_type, status,
                           judge_model, manifest_digest
                    FROM eval_releases
                    WHERE release_type = 'target'
                      AND target_type = ?
                      AND status = 'published'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (spec["target_type"],),
                ).fetchone()
                evaluation = conn.execute(
                    """
                    SELECT id, release_key, version, target_type, status,
                           judge_model, manifest_digest
                    FROM eval_releases
                    WHERE release_type = 'evaluation'
                      AND target_type = ?
                      AND status = 'published'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (spec["target_type"],),
                ).fetchone()
                harness = conn.execute(
                    "SELECT id, harness_key, version, status FROM harness_releases "
                    "WHERE target_type = ? AND version = ? AND status = 'published' "
                    "ORDER BY id DESC LIMIT 1",
                    (spec["target_type"], PROJECT_HARNESS_VERSION),
                ).fetchone()
                case_count = 0
                if evaluation is not None:
                    case_count = conn.execute(
                        """
                        SELECT COUNT(*)
                        FROM eval_benchmark_cases c
                        JOIN eval_benchmark_suites s ON s.id = c.suite_id
                        WHERE s.release_id = ? AND c.active = 1
                        """,
                        (evaluation["id"],),
                    ).fetchone()[0]
                adapter_available = True
                adapter_name = spec["adapter"]
                reason = None
                try:
                    adapter = get_target_adapter(spec["target_type"])
                    adapter_name = type(adapter).__name__
                except AdapterNotConfigured as exc:
                    adapter_available = False
                    reason = str(exc)
                if not target:
                    reason = reason or "没有已发布的被测版本"
                elif not evaluation:
                    reason = reason or "没有已发布的完整评测版本"
                elif not case_count:
                    reason = reason or "完整评测版本没有可执行 Case"
                elif not adapter_available:
                    reason = reason or "没有注册评测 Adapter"
                result.append(
                    {
                        "target_type": spec["target_type"],
                        "target_key": spec["target_key"],
                        "evaluation_key": spec["evaluation_key"],
                        "workflow": spec["workflow"],
                        "adapter": adapter_name,
                        "adapter_available": adapter_available,
                        "target_release": _capability_release(target, harness),
                        "evaluation_release": _capability_release(evaluation, harness),
                        "project_harness": dict(harness) if harness else None,
                        "case_count": int(case_count),
                        "can_run": bool(
                            adapter_available and target and evaluation and case_count
                        ),
                        "reason": reason,
                    }
                )
            return {"targets": result}

    return await run_db(_query)


@router.get("/experiments")
async def list_experiments(
    status: str | None = None,
    limit: int = 50,
    admin: dict = Depends(get_admin_user),
):
    """List Eval Experiments with per-child Run summaries (browse + restore)."""

    def _query():
        with get_db_connection() as conn:
            params = []
            where = ""
            if status:
                where = "WHERE e.status = ?"
                params.append(status)
            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT e.id, e.experiment_key, e.status, e.total_runs,
                       e.completed_runs, e.failed_runs, e.cancelled_runs,
                       e.replication_count, e.environment_fingerprint,
                       e.comparison_group, e.created_at, e.started_at, e.finished_at,
                       e.summary_json
                FROM eval_experiments e
                {where}
                ORDER BY e.id DESC LIMIT ?
                """,
                params,
            ).fetchall()
            experiments = []
            for row in rows:
                item = dict(row)
                item["summary"] = _decode_json(item.pop("summary_json"), {})
                item["runs"] = []
                child_quality = []
                for child in conn.execute(
                    """
                    SELECT er.run_id, er.target_type,
                           r.status, r.total_items, r.completed_items, r.failed_items,
                           r.created_at, r.started_at, r.finished_at,
                           tr.release_key AS target_release_key,
                           ev.release_key AS evaluation_release_key
                    FROM eval_experiment_runs er
                    JOIN eval_runs r ON r.id = er.run_id
                    JOIN eval_releases tr ON tr.id = r.target_release_id
                    LEFT JOIN eval_releases ev ON ev.id = r.evaluation_release_id
                    WHERE er.experiment_id = ?
                    ORDER BY er.display_order, er.id
                    """,
                    (item["id"],),
                ).fetchall():
                    child = dict(child)
                    child["quality_status"] = _quality_status(conn, child["run_id"], child["status"])
                    child_quality.append(child["quality_status"])
                    item["runs"].append(child)
                item["quality_status"] = (
                    "pending" if any(v == "pending" for v in child_quality)
                    else "failed" if any(v == "failed" for v in child_quality)
                    else "not_evaluated" if any(v == "not_evaluated" for v in child_quality)
                    else "passed"
                )
                experiments.append(item)
            return {"experiments": experiments}

    return await run_db(_query)


@router.post("/experiments")
async def create_experiment(
    body: CreateEvalExperimentRequest,
    admin: dict = Depends(get_admin_user),
):
    """Create and dispatch one frontend experiment with multiple child Runs."""

    def _create():
        with get_db_connection() as conn:
            specs_by_type = {spec["target_type"]: spec for spec in BUILTIN_SUITES}
            requested = body.target_types or list(specs_by_type)
            if len(set(requested)) != len(requested):
                raise ValueError("target_types 不能重复")
            unknown = [target_type for target_type in requested if target_type not in specs_by_type]
            if unknown:
                raise ValueError(f"不支持的评测对象: {', '.join(unknown)}")

            pairs = []
            for target_type in requested:
                spec = specs_by_type[target_type]
                try:
                    get_target_adapter(target_type)
                except AdapterNotConfigured as exc:
                    raise ValueError(str(exc)) from exc
                target = conn.execute(
                    """
                    SELECT * FROM eval_releases
                    WHERE release_type = 'target' AND target_type = ? AND status = 'published'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (target_type,),
                ).fetchone()
                evaluation = conn.execute(
                    """
                    SELECT * FROM eval_releases
                    WHERE release_type = 'evaluation' AND target_type = ? AND status = 'published'
                    ORDER BY id DESC LIMIT 1
                    """,
                    (target_type,),
                ).fetchone()
                if target is None or evaluation is None:
                    raise ValueError(f"{target_type} 没有可用的已发布版本")
                case_count = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM eval_benchmark_cases c
                    JOIN eval_benchmark_suites s ON s.id = c.suite_id
                    WHERE s.release_id = ? AND c.active = 1
                    """,
                    (evaluation["id"],),
                ).fetchone()[0]
                if not case_count:
                    raise ValueError(f"{target_type} 没有可执行的 Benchmark Case")
                pairs.append((spec, target, evaluation))

            experiment_key = f"frontend-{uuid.uuid4().hex}"
            comparison_group = body.comparison_group or experiment_key
            cursor = conn.execute(
                """
                INSERT INTO eval_experiments
                    (experiment_key, target_types_json, comparison_group,
                     environment_fingerprint, seed, replication_count,
                     total_runs, created_by)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    experiment_key,
                    json.dumps(requested, ensure_ascii=False),
                    comparison_group,
                    body.environment_fingerprint,
                    body.seed,
                    body.replication_count,
                    len(pairs),
                    admin["id"],
                ),
            )
            experiment_id = cursor.lastrowid
            _experiment_event(
                conn,
                experiment_id,
                "experiment.created",
                {"target_types": requested},
            )
            runs = []
            for display_order, (spec, target, evaluation) in enumerate(pairs):
                run = create_eval_run(
                    conn,
                    created_by=admin["id"],
                    target_release_id=target["id"],
                    evaluation_release_id=evaluation["id"],
                    replication_count=body.replication_count,
                    seed=body.seed,
                    environment_fingerprint=body.environment_fingerprint,
                    comparison_group=comparison_group,
                    idempotency_key=f"{experiment_key}:{spec['target_type']}",
                    require_published=True,
                )
                conn.execute(
                    """
                    INSERT INTO eval_experiment_runs
                        (experiment_id, run_id, target_type, display_order)
                    VALUES (?, ?, ?, ?)
                    """,
                    (experiment_id, run["id"], spec["target_type"], display_order),
                )
                append_event(conn, run["id"], "run.created", {"experiment_id": experiment_id})
                runs.append(
                    {
                        "run_id": run["id"],
                        "batch_id": run["batch_id"],
                        "target_type": spec["target_type"],
                        "target_release_key": target["release_key"],
                        "evaluation_release_key": evaluation["release_key"],
                        "total_items": run["total_items"],
                        "status": run["status"],
                    }
                )
            conn.commit()
            return {"experiment_id": experiment_id, "experiment_key": experiment_key, "runs": runs}

    try:
        result = await run_db(_create)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    dispatch_errors = []
    for child in result["runs"]:
        try:
            job = await enqueue_eval_run_job(child["run_id"])
            arq_job_id = getattr(job, "job_id", None)

            def _mark_child_queued(run_id=child["run_id"], job_id=arq_job_id):
                with get_db_connection() as conn:
                    conn.execute(
                        "UPDATE eval_runs SET status = 'queued' WHERE id = ? AND status = 'created'",
                        (run_id,),
                    )
                    conn.execute(
                        "UPDATE eval_batches SET status = 'queued' WHERE id = (SELECT batch_id FROM eval_runs WHERE id = ?)",
                        (run_id,),
                    )
                    append_event(conn, run_id, "run.queued", {"arq_job_id": job_id})
                    experiment_id = conn.execute(
                        "SELECT experiment_id FROM eval_experiment_runs WHERE run_id = ?", (run_id,)
                    ).fetchone()[0]
                    _experiment_event(conn, experiment_id, "experiment.run_queued", {"run_id": run_id})
                    conn.commit()

            await run_db(_mark_child_queued)
        except Exception as exc:
            dispatch_errors.append({"run_id": child["run_id"], "error": str(exc)[:300]})

    def _refresh():
        with get_db_connection() as conn:
            refreshed = _refresh_experiment(conn, result["experiment_id"])
            conn.commit()
            return refreshed

    refreshed = await run_db(_refresh)
    return {
        **(refreshed or {}),
        "experiment_id": result["experiment_id"],
        "experiment_key": result["experiment_key"],
        "runs": (refreshed or {}).get("runs", result["runs"]),
        "dispatch_errors": dispatch_errors,
    }


@router.get("/experiments/{experiment_id}")
async def get_experiment(experiment_id: int, admin: dict = Depends(get_admin_user)):
    def _query():
        with get_db_connection() as conn:
            result = _refresh_experiment(conn, experiment_id)
            conn.commit()
            return result

    result = await run_db(_query)
    if result is None:
        raise HTTPException(status_code=404, detail="Eval Experiment 不存在")
    result.pop("target_types_json", None)
    return result


@router.post("/experiments/{experiment_id}/cancel")
async def cancel_experiment(experiment_id: int, admin: dict = Depends(get_admin_user)):
    def _cancel():
        with get_db_connection() as conn:
            experiment = conn.execute(
                "SELECT id FROM eval_experiments WHERE id = ?", (experiment_id,)
            ).fetchone()
            if experiment is None:
                return None
            child_runs = conn.execute(
                "SELECT run_id FROM eval_experiment_runs WHERE experiment_id = ?",
                (experiment_id,),
            ).fetchall()
            for child in child_runs:
                run_id = child["run_id"]
                row = conn.execute(
                    "SELECT batch_id, status FROM eval_runs WHERE id = ?", (run_id,)
                ).fetchone()
                if row is None or row["status"] in {"completed", "failed", "cancelled"}:
                    continue
                conn.execute(
                    "UPDATE eval_runs SET cancel_requested = 1, status = CASE "
                    "WHEN status IN ('created', 'queued') THEN 'cancelled' ELSE status END "
                    "WHERE id = ?",
                    (run_id,),
                )
                conn.execute(
                    "UPDATE eval_batches SET cancel_requested = 1, status = CASE "
                    "WHEN status IN ('created', 'queued') THEN 'cancelled' ELSE status END "
                    "WHERE id = ?",
                    (row["batch_id"],),
                )
                append_event(conn, run_id, "run.cancel_requested", {"admin_id": admin["id"]})
            _experiment_event(conn, experiment_id, "experiment.cancel_requested", {"admin_id": admin["id"]})
            result = _refresh_experiment(conn, experiment_id)
            conn.commit()
            return result

    result = await run_db(_cancel)
    if result is None:
        raise HTTPException(status_code=404, detail="Eval Experiment 不存在")
    result.pop("target_types_json", None)
    return result


@router.get("/experiments/{experiment_id}/events")
async def experiment_events(
    request: Request,
    experiment_id: int,
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
                    experiment = _refresh_experiment(conn, experiment_id)
                    if experiment is None:
                        return None, []
                    events = [dict(row) for row in conn.execute(
                        """
                        SELECT sequence, event_type, payload_json, created_at
                        FROM eval_experiment_events
                        WHERE experiment_id = ? AND sequence > ?
                        ORDER BY sequence
                        """,
                        (experiment_id, cursor),
                    ).fetchall()]
                    conn.commit()
                    return experiment, events

            experiment, events = await run_db(_read)
            if experiment is None:
                return
            for event in events:
                cursor = event["sequence"]
                event["payload"] = _decode_json(event.pop("payload_json"), {})
                yield (
                    f"id: {cursor}\n"
                    f"event: {event['event_type']}\n"
                    f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                )
            if experiment["status"] in {"completed", "failed", "cancelled"}:
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
            harnesses = {
                row["target_type"]: row
                for row in conn.execute(
                "SELECT id, target_type, harness_key, version, status "
                "FROM harness_releases WHERE version = ? AND status = 'published'",
                (PROJECT_HARNESS_VERSION,),
                ).fetchall()
            }
            result = []
            for row in rows:
                item = dict(row)
                item["manifest"] = _decode_json(item.pop("manifest_json", "{}"), {})
                harness = harnesses.get(item.get("target_type"))
                item["project_harness_release_id"] = harness["id"] if harness else None
                item["project_harness_release_key"] = (
                    f"{harness['harness_key']}@{harness['version']}" if harness else None
                )
                item["project_harness_version"] = harness["version"] if harness else None
                result.append(item)
            return result

    return {"releases": await run_db(_query)}


@router.get("/harness-releases")
async def list_harness_releases(admin: dict = Depends(get_admin_user)):
    """List the project Harness registry, independent of Eval manifests."""

    def _query():
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM harness_releases ORDER BY target_type, id DESC"
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["manifest"] = _decode_json(item.pop("manifest_json", "{}"), {})
                result.append(item)
            return result

    return {"harness_releases": await run_db(_query)}


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
                project_harness_release_id=body.project_harness_release_id,
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
                case_keys=body.case_keys,
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
                f"r.summary_json, "
                f"tr.release_key AS target_release_key, tr.target_type, "
                f"COALESCE(er.release_key, br.release_key) AS evaluation_release_key, "
                f"br.release_key AS benchmark_suite_release_key, "
                f"hr.harness_key AS project_harness_key, "
                f"hr.version AS project_harness_version "
                f"FROM eval_runs r JOIN eval_releases tr ON tr.id = r.target_release_id "
                f"JOIN eval_releases br ON br.id = r.benchmark_suite_release_id "
                f"LEFT JOIN eval_releases er ON er.id = r.evaluation_release_id "
                f"LEFT JOIN harness_releases hr ON hr.id = r.harness_release_id "
                f"{where} "
                "ORDER BY r.id DESC LIMIT ?",
                params,
            ).fetchall()
            quality_metadata = _run_quality_metadata(conn, [row["id"] for row in rows])
            result = []
            for row in rows:
                item = dict(row)
                metadata = quality_metadata.get(row["id"], {})
                item["quality_status"] = metadata.get("quality_status", "pending")
                summary = _decode_json(item.pop("summary_json", "{}"), {})
                metric_score = (summary.get("metric_summary") or {}).get("score") or {}
                item["score"] = {
                    "final_mean": metric_score.get("final_mean"),
                    "deterministic_mean": metric_score.get("deterministic_mean"),
                    "judge_mean": metric_score.get("judge_mean"),
                } or None
                item["distribution"] = metadata.get("distribution", _empty_distribution())
                item["metric_cards"] = metadata.get("metric_cards", [])
                item["attention_cases"] = metadata.get("attention_cases", [])
                result.append(item)
            return result

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
            if runs[0]["target_release_id"] != runs[1]["target_release_id"]:
                raise HTTPException(status_code=400, detail="Harness A/B 必须使用同一个 Target")
            dual_contexts = [_ab_snapshot_context(row) for row in runs]
            if any(context is not None for context in dual_contexts):
                if any(context is None for context in dual_contexts):
                    raise HTTPException(status_code=400, detail="A/B Run 必须使用同一种版本绑定模式")
                if len(set(dual_contexts)) != 1:
                    raise HTTPException(status_code=400, detail="A/B Run 的完整评测上下文不一致")
            context_fields = ("evaluation_release_id",) if any(
                row["evaluation_release_id"] is not None for row in runs
            ) else (
                "benchmark_suite_release_id",
                "eval_protocol_release_id",
                "judge_release_id",
                "candidate_simulator_release_id",
            )
            if len({tuple(row[field] for field in context_fields) for row in runs}) != 1:
                raise HTTPException(status_code=400, detail="A/B Run 的评测上下文不一致")
            harness_contexts = [_ab_harness_identity(row) for row in runs]
            if any(identity[0] is None for identity in harness_contexts):
                raise HTTPException(status_code=400, detail="A/B Run 缺少项目 Harness 版本")
            if len(set(harness_contexts)) != 2:
                raise HTTPException(status_code=400, detail="A/B Run 必须比较两个不同的 Harness 版本")
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
            evaluation_manifest = _run_evaluation_manifest(conn, run_id)
            poor_score_below = quality_threshold_from_manifest(evaluation_manifest)
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
                serialized["outcome"] = classify_progress_outcome(serialized, poor_score_below)
                result["items"].append(serialized)
            result["quality_status"] = _quality_status(conn, run_id, result["status"])
            result["distribution"] = _run_progress_distribution(conn, run_id)
            result["metric_cards"] = _run_metric_cards(
                conn, run_id, str(result.get("target_type") or "")
            )
            return result

    result = await run_db(_query)
    if result is None:
        raise HTTPException(status_code=404, detail="Eval Run 不存在")
    return result


@router.get("/runs/{run_id}/items/{item_id}")
async def get_run_item(
    run_id: int,
    item_id: int,
    admin: dict = Depends(get_admin_user),
):
    """Return one Case's frozen input, result, attempts and artifact index."""

    def _query():
        with get_db_connection() as conn:
            row = conn.execute(
                """
                SELECT i.*, c.case_key, c.scenario_key,
                       c.input_snapshot_json, c.contract_json, c.input_digest
                FROM eval_items i
                JOIN eval_benchmark_cases c ON c.id = i.case_id
                WHERE i.run_id = ? AND i.id = ?
                """,
                (run_id, item_id),
            ).fetchone()
            if row is None:
                return None
            item = dict(row)
            item["result"] = _decode_json(item.pop("result_json", "{}"), {})
            item.pop("input_snapshot_json", None)
            item.pop("contract_json", None)
            item["cancel_requested"] = bool(item.get("cancel_requested", 0))

            case_row = conn.execute(
                """
                SELECT case_key, scenario_key, input_snapshot_json,
                       contract_json, input_digest, active
                FROM eval_benchmark_cases WHERE id = ?
                """,
                (row["case_id"],),
            ).fetchone()
            # Prefer the immutable run snapshot for dual-axis evidence: the live
            # eval_benchmark_cases row is authoritative only for legacy runs and
            # may drift after the Run exists (ADR 0022/0024 immutable context).
            base_case = dict(case_row)
            case = dict(base_case)
            snapshot = _decode_json(conn.execute(
                "SELECT snapshot_json FROM eval_runs WHERE id = ?", (run_id,)
            ).fetchone()["snapshot_json"], {})
            frozen_cases = snapshot.get("cases") if isinstance(snapshot, dict) else None
            frozen = None
            if isinstance(frozen_cases, list):
                frozen = next(
                    (c for c in frozen_cases if isinstance(c, dict) and c.get("id") == row["case_id"]),
                    None,
                )
            if frozen is not None:
                case["case_key"] = frozen.get("case_key", case["case_key"])
                case["scenario_key"] = frozen.get("scenario_key", case["scenario_key"])
                frozen_input = frozen.get("input_snapshot")
                frozen_contract = frozen.get("contract")
                case["input_snapshot"] = frozen_input if isinstance(frozen_input, dict) else _decode_json(frozen_input, {})
                case["contract"] = frozen_contract if isinstance(frozen_contract, dict) else _decode_json(frozen_contract, {})
                if frozen.get("input_digest"):
                    case["input_digest"] = frozen["input_digest"]
            else:
                case["input_snapshot"] = _decode_json(base_case.get("input_snapshot_json"), {})
                case["contract"] = _decode_json(base_case.get("contract_json"), {})
            case["active"] = bool(base_case.get("active"))

            attempts = []
            for attempt_row in conn.execute(
                """
                SELECT id, item_id, attempt_index, attempt_kind, status,
                       failure_class, raw_observation_json, error_message,
                       started_at, finished_at
                FROM eval_attempts WHERE item_id = ? ORDER BY attempt_index
                """,
                (item_id,),
            ).fetchall():
                attempt = dict(attempt_row)
                attempt["raw_observation"] = _decode_json(
                    attempt.pop("raw_observation_json"), {}
                )
                attempts.append(attempt)

            artifacts = [
                dict(artifact_row)
                for artifact_row in conn.execute(
                    """
                    SELECT id, run_id, item_id, attempt_id, artifact_type,
                           storage_path, digest, size_bytes, retention_class, created_at
                    FROM eval_artifacts
                    WHERE run_id = ? AND item_id = ? ORDER BY id
                    """,
                    (run_id, item_id),
                ).fetchall()
            ]
            return {"item": item, "case": case, "attempts": attempts, "artifacts": artifacts}

    result = await run_db(_query)
    if result is None:
        raise HTTPException(status_code=404, detail="Eval Case 不存在")
    return result


@router.get(
    "/runs/{run_id}/items/{item_id}/evidence",
    response_model=CaseEvidenceView,
)
async def get_run_item_evidence(
    run_id: int,
    item_id: int,
    admin: dict = Depends(get_admin_user),
):
    """Return the versioned, business-facing Case Evidence View."""
    raw = await get_run_item(run_id, item_id, admin)

    def _query():
        with get_db_connection() as conn:
            row = _run_query(conn, run_id)
            if row is None:
                return None
            result = _serialize_run(row)
            result["quality_status"] = _quality_status(conn, run_id, result["status"])
            return result

    run = await run_db(_query)
    if run is None:
        raise HTTPException(status_code=404, detail="Eval Run 不存在")
    return build_case_evidence_view(
        raw,
        run=run,
        target_type=str(run.get("target_type") or "unknown"),
    )


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


@router.post("/runs/{run_id}/retry-failed")
async def retry_failed_run(run_id: int, admin: dict = Depends(get_admin_user)):
    """Requeue a Run that never finished (failed cases or a dispatch-failed orphan).

    Preserves the Run's immutable context. ``created`` runs whose enqueue failed
    at creation time are re-dispatched here too; every re-dispatch uses a fresh
    ARQ job id so ARQ's retained result (keep_result) can never swallow the job.
    """

    def _prepare_retry():
        with get_db_connection() as conn:
            run = conn.execute(
                "SELECT id, batch_id, status FROM eval_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if run is None:
                return None
            if run["status"] in {"queued", "running"}:
                raise HTTPException(status_code=409, detail="当前 Run 仍在执行，不能重跑")
            failed_count = conn.execute(
                "SELECT COUNT(*) FROM eval_items WHERE run_id = ? AND status = 'failed'",
                (run_id,),
            ).fetchone()[0]
            pending_count = conn.execute(
                "SELECT COUNT(*) FROM eval_items WHERE run_id = ? AND status = 'pending'",
                (run_id,),
            ).fetchone()[0]
            if not failed_count and not pending_count:
                raise HTTPException(status_code=409, detail="当前 Run 没有可重跑或待执行的 Case")

            conn.execute(
                """
                UPDATE eval_items
                SET status = 'pending', selected_attempt_id = NULL,
                    contract_status = 'pending', hard_gate_status = 'pending',
                    judge_status = 'pending', score = NULL, result_json = '{}',
                    started_at = NULL, finished_at = NULL
                WHERE run_id = ? AND status = 'failed'
                """,
                (run_id,),
            )
            completed_count = conn.execute(
                "SELECT COUNT(*) FROM eval_items WHERE run_id = ? AND status = 'completed'",
                (run_id,),
            ).fetchone()[0]
            conn.execute(
                """
                UPDATE eval_runs
                SET status = 'created', completed_items = ?, failed_items = 0,
                    summary_json = '{}', cancel_requested = 0,
                    started_at = NULL, finished_at = NULL
                WHERE id = ?
                """,
                (completed_count, run_id),
            )
            conn.execute(
                """
                UPDATE eval_batches
                SET status = 'created', completed_items = ?, failed_items = 0,
                    summary_json = '{}', cancel_requested = 0,
                    started_at = NULL, finished_at = NULL
                WHERE id = ?
                """,
                (completed_count, run["batch_id"]),
            )
            append_event(
                conn,
                run_id,
                "run.retry_requested",
                {"admin_id": admin["id"], "failed_items": failed_count, "pending_items": pending_count},
            )
            conn.commit()
            return {
                "run_id": run_id,
                "batch_id": run["batch_id"],
                "retried_items": failed_count,
                "requeued_pending": pending_count,
            }

    result = await run_db(_prepare_retry)
    if result is None:
        raise HTTPException(status_code=404, detail="Eval Run 不存在")
    dispatch_error = None
    status = "created"
    try:
        # Fresh per-dispatch job id: ARQ keeps the previous result for keep_result
        # (1h), so reusing "eval-run-{run_id}" would make enqueue_job return None.
        job = await enqueue_eval_run_job(run_id, job_id=f"eval-run-{run_id}-{uuid.uuid4().hex[:8]}")
        arq_job_id = getattr(job, "job_id", None)
        if job is None:
            dispatch_error = "ARQ 未接受入队（job id 冲突或排队被拒），Run 保持 created，可稍后重试"

        def _mark_queued():
            with get_db_connection() as conn:
                conn.execute(
                    "UPDATE eval_runs SET status = 'queued' WHERE id = ? AND status = 'created'",
                    (run_id,),
                )
                conn.execute(
                    "UPDATE eval_batches SET status = 'queued' WHERE id = ? AND status = 'created'",
                    (result["batch_id"],),
                )
                append_event(conn, run_id, "run.queued", {"arq_job_id": arq_job_id})
                conn.commit()

        if job is not None:
            await run_db(_mark_queued)
            status = "queued"
    except Exception as exc:
        dispatch_error = str(exc)[:300]
    return {**result, "status": status, "dispatch_error": dispatch_error}

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
