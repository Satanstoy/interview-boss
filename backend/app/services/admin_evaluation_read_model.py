"""Read-model helpers for the admin evaluation control plane."""

from __future__ import annotations

import json
from typing import Any

from app.core.harness_registry import PROJECT_HARNESS_VERSION
from app.evaluation.adapters import AdapterNotConfigured
from app.evaluation.benchmark_catalog import BUILTIN_SUITES
from app.evaluation.metric_registry import (
    TARGET_METRIC_DICTIONARY,
    build_metric_cards,
    build_progress_distribution,
    classify_progress_outcome,
    quality_threshold_from_manifest,
)


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
               bs.release_key AS benchmark_suite_release_key,
               hr.harness_key AS project_harness_key,
               hr.version AS project_harness_version
        FROM eval_experiment_runs er
        JOIN eval_runs r ON r.id = er.run_id
        JOIN eval_releases tr ON tr.id = r.target_release_id
        LEFT JOIN eval_releases ev ON ev.id = r.evaluation_release_id
        LEFT JOIN eval_releases bs ON bs.id = r.benchmark_suite_release_id
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
    expired_runs = sum(row["status"] == "expired" for row in children)
    total_items = sum(row["total_items"] or 0 for row in children)
    completed_items = sum(row["completed_items"] or 0 for row in children)
    failed_items = sum(row["failed_items"] or 0 for row in children)
    if total_runs and completed_runs + failed_runs + cancelled_runs + expired_runs == total_runs:
        status = "failed" if failed_runs else "expired" if expired_runs else "cancelled" if cancelled_runs else "completed"
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
        "expired_runs": expired_runs,
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
        "total_runs", "completed_runs", "failed_runs", "cancelled_runs", "expired_runs",
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
                finished_at = CASE WHEN ? IN ('completed', 'failed', 'cancelled', 'expired')
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
        "expired_runs": expired_runs,
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

# Admin endpoint read models stay independent from FastAPI request wiring.


def build_overview_read_model(conn):
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


def build_capabilities_read_model(conn, adapter_loader):
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
            adapter = adapter_loader(spec["target_type"])
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
