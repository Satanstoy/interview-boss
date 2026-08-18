"""Execute one Eval Run using the Target Adapter boundary."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
from typing import Any, Callable

from app.db.connection import get_db_connection
from app.evaluation.adapters import get_target_adapter
from app.evaluation.judge import judge_observation
from app.evaluation.scoring import combine_hybrid_score, score_observation
from app.services.evaluation_service import append_event

logger = logging.getLogger("interview-boss.evaluation")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _snapshot_error(snapshot: dict[str, Any]) -> str | None:
    target = snapshot.get("target_release")
    evaluation = snapshot.get("evaluation_release")
    cases = snapshot.get("cases")
    if not isinstance(target, dict) or not target.get("release_key"):
        return "缺少 target_release 快照"
    if not isinstance(evaluation, dict) or not evaluation.get("release_key"):
        return "缺少 evaluation_release 快照"
    evaluation_manifest = evaluation.get("manifest")
    if not isinstance(evaluation_manifest, dict):
        return "缺少 evaluation manifest 快照"
    required_groups = {"benchmark", "protocol", "judge", "simulator_harness"}
    target_type = str(target.get("target_type") or evaluation.get("target_type") or "")
    target_groups = {
        "interview": {"candidate_simulator", "tool_evaluation", "intent_evaluation", "retrieval"},
        "experience_extraction": {"structured_evaluation"},
        "jd_extraction": {"structured_evaluation"},
        "resume_analysis": {"resume_evaluation"},
        "question_tagging": {"tagging_evaluation"},
    }
    required_groups |= target_groups.get(target_type, set())
    if not required_groups <= set(evaluation_manifest):
        return "Evaluation Release 快照缺少固定组件"
    if not isinstance(cases, list) or not cases:
        return "缺少 Benchmark Case 快照"
    for case in cases:
        if not isinstance(case, dict) or case.get("id") is None:
            return "Benchmark Case 快照格式无效"
        if not isinstance(case.get("input_snapshot"), dict) or not isinstance(case.get("contract"), dict):
            return "Benchmark Case 快照未包含输入与契约"
    return None


def _runtime_identity_error(target_snapshot: dict[str, Any]) -> str | None:
    expected = str(target_snapshot.get("git_sha") or "")
    actual = os.environ.get("EVAL_RUNTIME_GIT_SHA", "current-code-state")
    if expected and expected not in {"current-code-state", "local-baseline"} and expected != actual:
        return f"Target Release git_sha={expected} 与 Eval Worker={actual} 不一致"
    return None


def _aggregate_metric_summary(conn: sqlite3.Connection, run_id: int) -> dict[str, Any]:
    rows = conn.execute(
        "SELECT result_json FROM eval_items WHERE run_id = ? AND status = 'completed'",
        (run_id,),
    ).fetchall()
    tool_samples = []
    intent_samples = []
    content_samples = []
    resume_samples = []
    tagging_samples = []
    final_scores = []
    deterministic_scores = []
    judge_scores = []
    for row in rows:
        try:
            result = json.loads(row["result_json"] or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        observation = result.get("observation") or {}
        payload = observation.get("payload") or {}
        score = result.get("score") or {}
        if isinstance(score, dict):
            for bucket, target in (
                ("score", final_scores),
                ("deterministic_score", deterministic_scores),
                ("judge_score", judge_scores),
            ):
                value = score.get(bucket)
                if value is not None:
                    target.append(float(value))
        if isinstance(payload.get("tool_metrics"), dict):
            tool_samples.append(payload["tool_metrics"])
        if isinstance(payload.get("intent_metrics"), dict):
            intent_samples.append(payload["intent_metrics"])
        metrics = payload.get("metrics")
        if isinstance(metrics, dict):
            if "field_coverage" in metrics:
                content_samples.append(metrics)
            if "source_fact_coverage" in metrics:
                resume_samples.append(metrics)
            if "taxonomy_validity" in metrics:
                tagging_samples.append(metrics)

    tool_call_count = sum(int(item.get("call_count") or 0) for item in tool_samples)
    failed_call_count = sum(int(item.get("failed_call_count") or 0) for item in tool_samples)
    used_count = sum(bool(item.get("result_used")) for item in tool_samples)
    intent_accuracy = [
        float(item["accuracy"])
        for item in intent_samples
        if item.get("accuracy") is not None
    ]
    summary = {
        "score": {
            "items_evaluated": len(final_scores),
            "final_mean": round(sum(final_scores) / len(final_scores), 4) if final_scores else None,
            "deterministic_mean": round(sum(deterministic_scores) / len(deterministic_scores), 4) if deterministic_scores else None,
            "judge_mean": round(sum(judge_scores) / len(judge_scores), 4) if judge_scores else None,
        },
        "tool": {
            "items_evaluated": len(tool_samples),
            "call_count": tool_call_count,
            "failed_call_count": failed_call_count,
            "result_used_rate": round(used_count / len(tool_samples), 4) if tool_samples else None,
        },
        "intent": {
            "items_evaluated": len(intent_samples),
            "observed_turn_count": sum(int(item.get("observed_turn_count") or 0) for item in intent_samples),
            "intent_coverage": round(
                sum(float(item.get("intent_coverage") or 0) for item in intent_samples) / len(intent_samples),
                4,
            ) if intent_samples else None,
            "accuracy": round(sum(intent_accuracy) / len(intent_accuracy), 4) if intent_accuracy else None,
        },
    }
    if content_samples:
        summary["content"] = {
            "items_evaluated": len(content_samples),
            "field_coverage": round(sum(float(item.get("field_coverage") or 0) for item in content_samples) / len(content_samples), 4),
            "question_recall": round(sum(float(item.get("question_recall") or 0) for item in content_samples) / len(content_samples), 4),
            "question_precision": round(sum(float(item.get("question_precision") or 0) for item in content_samples) / len(content_samples), 4),
        }
    if resume_samples:
        summary["resume"] = {
            "items_evaluated": len(resume_samples),
            "source_fact_coverage": round(sum(float(item.get("source_fact_coverage") or 0) for item in resume_samples) / len(resume_samples), 4),
            "target_alignment": round(sum(float(item.get("target_alignment") or 0) for item in resume_samples) / len(resume_samples), 4),
            "forbidden_claim_count": sum(int(item.get("forbidden_claim_count") or 0) for item in resume_samples),
        }
    if tagging_samples:
        summary["tagging"] = {
            "items_evaluated": len(tagging_samples),
            "taxonomy_validity": round(sum(float(item.get("taxonomy_validity") or 0) for item in tagging_samples) / len(tagging_samples), 4),
            "classification_accuracy": round(sum(float(item.get("classification_accuracy") or 0) for item in tagging_samples) / len(tagging_samples), 4),
        }
    return summary


def _load_run(conn: sqlite3.Connection, run_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT r.*, b.id AS batch_id, b.batch_fingerprint,
               tr.release_key AS target_release_key,
               tr.target_type AS target_type,
               tr.manifest_json AS target_manifest_json,
               jr.judge_model AS judge_model,
               jr.manifest_json AS judge_manifest_json,
               sh.manifest_json AS harness_manifest_json,
               cs.manifest_json AS candidate_simulator_manifest_json,
               er.manifest_json AS evaluation_manifest_json
        FROM eval_runs r
        JOIN eval_batches b ON b.id = r.batch_id
        JOIN eval_releases tr ON tr.id = r.target_release_id
        JOIN eval_releases jr ON jr.id = r.judge_release_id
        JOIN eval_releases sh ON sh.id = r.simulator_harness_release_id
        JOIN eval_releases cs ON cs.id = r.candidate_simulator_release_id
        LEFT JOIN eval_releases er ON er.id = r.evaluation_release_id
        WHERE r.id = ?
        """,
        (run_id,),
    ).fetchone()
    result = _row_dict(row)
    if result is None:
        return None

    # New runs are immutable snapshots. The legacy component columns are kept
    # only so old rows and old readers remain readable during the migration.
    if result.get("evaluation_release_id") and result.get("snapshot_json"):
        try:
            snapshot = json.loads(result["snapshot_json"])
        except (TypeError, json.JSONDecodeError):
            snapshot = {}
        result["_snapshot_error"] = _snapshot_error(snapshot) or _runtime_identity_error(
            snapshot.get("target_release") or {}
        )
        target_snapshot = snapshot.get("target_release") or {}
        evaluation_snapshot = snapshot.get("evaluation_release") or {}
        evaluation_manifest = evaluation_snapshot.get("manifest") or {}
        if target_snapshot:
            result["target_release_key"] = target_snapshot.get(
                "release_key", result["target_release_key"]
            )
            result["target_type"] = target_snapshot.get(
                "target_type", result["target_type"]
            )
            result["target_manifest_json"] = _json_dumps(
                target_snapshot.get("manifest") or {}
            )
        if evaluation_manifest:
            judge_manifest = evaluation_manifest.get("judge") or {}
            harness_manifest = evaluation_manifest.get("simulator_harness") or {}
            candidate_manifest = evaluation_manifest.get("candidate_simulator") or {}
            result["judge_model"] = str(
                judge_manifest.get("model") or result.get("judge_model") or ""
            )
            result["judge_manifest_json"] = _json_dumps(judge_manifest)
            result["harness_manifest_json"] = _json_dumps(harness_manifest)
            result["candidate_simulator_manifest_json"] = _json_dumps(
                candidate_manifest
            )
        result["evaluation_manifest_json"] = _json_dumps(evaluation_manifest)
    return result


def reconcile_interrupted_eval_run(
    run_id: int,
    *,
    conn: sqlite3.Connection | None = None,
    reason: str = "worker_cancelled",
) -> dict[str, Any]:
    """Close a run when the queue worker is cancelled before normal cleanup.

    ARQ can cancel a coroutine at its job timeout boundary. That cancellation
    bypasses the executor's per-item ``finally`` block, so the active item and
    run would otherwise remain permanently ``running``. Active work is marked
    failed, not-yet-started work is marked cancelled, and both run and batch
    receive one durable terminal summary.
    """
    connection = conn or get_db_connection()
    run_row = connection.execute(
        "SELECT r.*, b.id AS batch_id FROM eval_runs r "
        "JOIN eval_batches b ON b.id = r.batch_id WHERE r.id = ?",
        (run_id,),
    ).fetchone()
    if run_row is None:
        raise ValueError(f"Eval Run 不存在: {run_id}")
    if run_row["status"] in {"completed", "failed", "cancelled"}:
        return {"run_id": run_id, "status": run_row["status"]}

    failure_class = str(reason or "worker_cancelled")[:100]
    error_message = f"Eval Worker 中断了 Run（{failure_class}）"
    active_items = connection.execute(
        "SELECT id FROM eval_items WHERE run_id = ? AND status = 'running'",
        (run_id,),
    ).fetchall()
    for item in active_items:
        connection.execute(
            """
            UPDATE eval_attempts
            SET status = 'failed', failure_class = ?, error_message = ?,
                finished_at = CURRENT_TIMESTAMP
            WHERE item_id = ? AND status = 'running'
            """,
            (failure_class, error_message, item["id"]),
        )
        connection.execute(
            """
            UPDATE eval_items
            SET status = 'failed', result_json = ?, finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (_json_dumps({"error": error_message, "failure_class": failure_class}), item["id"]),
        )
        append_event(
            connection,
            run_id,
            "item.failed",
            {"item_id": item["id"], "failure_class": failure_class},
        )

    pending_items = connection.execute(
        "SELECT id FROM eval_items WHERE run_id = ? AND status = 'pending'",
        (run_id,),
    ).fetchall()
    for item in pending_items:
        connection.execute(
            """
            UPDATE eval_items
            SET status = 'cancelled', result_json = ?, finished_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (_json_dumps({"error": error_message, "failure_class": failure_class}), item["id"]),
        )
        append_event(
            connection,
            run_id,
            "item.cancelled",
            {"item_id": item["id"], "failure_class": failure_class},
        )

    counts = connection.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled
        FROM eval_items WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    summary = {
        "total_items": run_row["total_items"],
        "completed_items": int(counts["completed"] or 0),
        "failed_items": int(counts["failed"] or 0),
        "cancelled_items": int(counts["cancelled"] or 0),
        "failure_class": failure_class,
        "error": error_message,
        "metric_summary": _aggregate_metric_summary(connection, run_id),
    }
    connection.execute(
        """
        UPDATE eval_runs
        SET status = 'failed', completed_items = ?, failed_items = ?,
            summary_json = ?, finished_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (summary["completed_items"], summary["failed_items"], _json_dumps(summary), run_id),
    )
    connection.execute(
        """
        UPDATE eval_batches
        SET status = 'failed', completed_items = ?, failed_items = ?,
            summary_json = ?, finished_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (
            summary["completed_items"],
            summary["failed_items"],
            _json_dumps(summary),
            run_row["batch_id"],
        ),
    )
    append_event(connection, run_id, "run.failed", summary)
    connection.commit()
    return {"run_id": run_id, "status": "failed", **summary}


async def execute_eval_run(
    run_id: int,
    *,
    conn: sqlite3.Connection | None = None,
    adapter_resolver: Callable[[str], Any] | None = None,
) -> dict[str, Any]:
    """Run all materialized Items and persist every Attempt and progress event."""
    connection = conn or get_db_connection()
    run = _load_run(connection, run_id)
    if run is None:
        raise ValueError(f"Eval Run 不存在: {run_id}")
    if run["status"] in {"completed", "failed", "cancelled"}:
        return {"run_id": run_id, "status": run["status"]}
    if run.get("_snapshot_error"):
        error = run["_snapshot_error"]
        summary = {"error": error, "total_items": run["total_items"]}
        connection.execute(
            "UPDATE eval_runs SET status = 'failed', summary_json = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ?",
            (_json_dumps(summary), run_id),
        )
        connection.execute(
            "UPDATE eval_batches SET status = 'failed', summary_json = ?, finished_at = CURRENT_TIMESTAMP WHERE id = ?",
            (_json_dumps(summary), run["batch_id"]),
        )
        append_event(connection, run_id, "run.failed", summary)
        connection.commit()
        return {"run_id": run_id, "status": "failed", **summary}

    connection.execute(
        """
        UPDATE eval_runs
        SET status = 'running', started_at = COALESCE(started_at, CURRENT_TIMESTAMP)
        WHERE id = ?
        """,
        (run_id,),
    )
    connection.execute(
        """
        UPDATE eval_batches
        SET status = 'running', started_at = COALESCE(started_at, CURRENT_TIMESTAMP)
        WHERE id = ?
        """,
        (run["batch_id"],),
    )
    append_event(connection, run_id, "run.started", {"total_items": run["total_items"]})
    connection.commit()

    resolver = adapter_resolver or get_target_adapter
    target_release = {
        "id": run["target_release_id"],
        "release_key": run["target_release_key"],
        "target_type": run["target_type"],
        "manifest": json.loads(run["target_manifest_json"] or "{}"),
        "created_by": run.get("created_by"),
        "judge_model": run.get("judge_model") or "",
        "judge_manifest": json.loads(run.get("judge_manifest_json") or "{}"),
        "harness_manifest": json.loads(run.get("harness_manifest_json") or "{}"),
        "candidate_simulator_manifest": json.loads(
            run.get("candidate_simulator_manifest_json") or "{}"
        ),
        "evaluation_release_id": run.get("evaluation_release_id"),
        "evaluation_manifest": json.loads(run.get("evaluation_manifest_json") or "{}"),
    }
    try:
        run_snapshot = json.loads(run.get("snapshot_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        run_snapshot = {}
    case_snapshots = {
        case.get("id"): case
        for case in run_snapshot.get("cases", [])
        if isinstance(case, dict) and case.get("id") is not None
    }
    items = connection.execute(
        """
        SELECT i.*, c.case_key, c.input_snapshot_json, c.contract_json
        FROM eval_items i
        JOIN eval_benchmark_cases c ON c.id = i.case_id
        WHERE i.run_id = ? AND i.status = 'pending'
        ORDER BY i.id
        """,
        (run_id,),
    ).fetchall()

    for item in items:
        cancelled = connection.execute(
            "SELECT cancel_requested FROM eval_runs WHERE id = ?", (run_id,)
        ).fetchone()[0]
        if cancelled:
            connection.execute(
                "UPDATE eval_items SET status = 'cancelled', finished_at = CURRENT_TIMESTAMP "
                "WHERE run_id = ? AND status = 'pending'",
                (run_id,),
            )
            break

        connection.execute(
            "UPDATE eval_items SET status = 'running', started_at = CURRENT_TIMESTAMP WHERE id = ?",
            (item["id"],),
        )
        attempt_index = connection.execute(
            "SELECT COALESCE(MAX(attempt_index), 0) + 1 FROM eval_attempts WHERE item_id = ?",
            (item["id"],),
        ).fetchone()[0]
        attempt_cursor = connection.execute(
            """
            INSERT INTO eval_attempts (item_id, attempt_index, attempt_kind)
            VALUES (?, ?, 'target')
            """,
            (item["id"], attempt_index),
        )
        attempt_id = attempt_cursor.lastrowid
        connection.commit()

        case_key = item["case_key"]
        try:
            adapter = resolver(target_release["target_type"])
            frozen_case = case_snapshots.get(item["case_id"])
            if run.get("evaluation_release_id") and frozen_case is None:
                raise RuntimeError(f"Run 快照缺少 Case: {item['case_id']}")
            case_key = frozen_case.get("case_key", item["case_key"]) if frozen_case else item["case_key"]
            case_snapshot = (
                frozen_case.get("input_snapshot")
                if frozen_case
                else json.loads(item["input_snapshot_json"] or "{}")
            )
            contract = (
                frozen_case.get("contract")
                if frozen_case
                else json.loads(item["contract_json"] or "{}")
            )
            case_snapshot = case_snapshot if isinstance(case_snapshot, dict) else {}
            contract = contract if isinstance(contract, dict) else {}
            # The adapter receives the private contract for observation only;
            # InterviewE2EAdapter never passes it to the candidate simulator.
            case_snapshot["_eval_contract"] = contract
            case_snapshot["_eval_seed"] = item["seed"]
            case_snapshot["_eval_replication_index"] = item["replication_index"]
            prepared = await adapter.prepare(case_snapshot, target_release)
            raw_result = await adapter.run(prepared, target_release)
            observation = await adapter.observe(raw_result)
            if observation.get("status") not in {"succeeded", "completed"}:
                errors = observation.get("payload", {}).get("errors", [])
                detail = "; ".join(str(error) for error in errors[:2]) if errors else "observation status is not succeeded"
                raise RuntimeError(f"target_observation_failed: {detail}")
            evaluation_manifest = json.loads(run.get("evaluation_manifest_json") or "{}")
            protocol = evaluation_manifest.get("protocol")
            score = score_observation(observation, contract, protocol=protocol)
            # Hard gates remain an independent deterministic result. They must
            # not suppress the Judge: a failed contract still needs a durable
            # quality explanation and a fixed-model score where possible.
            judge_result = await judge_observation(
                case_key=case_key,
                contract=contract,
                observation=observation,
                judge_model=run["judge_model"] or "",
            )
            score.update(judge_result)
            score.update(combine_hybrid_score(score, judge_result.get("score")))
            result_json = _json_dumps({"observation": observation, "score": score})
            connection.execute(
                """
                UPDATE eval_attempts
                SET status = 'succeeded', raw_observation_json = ?,
                    finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (result_json, attempt_id),
            )
            connection.execute(
                """
                UPDATE eval_items
                SET status = 'completed', selected_attempt_id = ?,
                    contract_status = ?, hard_gate_status = ?, judge_status = ?,
                    score = ?, result_json = ?, finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    attempt_id,
                    score["contract_status"],
                    score["hard_gate_status"],
                    score["judge_status"],
                    score["score"],
                    result_json,
                    item["id"],
                ),
            )
            append_event(
                connection,
                run_id,
                "item.completed",
                {"item_id": item["id"], "case_key": case_key},
            )
            # Materialize the durable evidence index. The transcript/observation
            # itself lives in the attempt's raw_observation_json / item result;
            # this row is what the control plane surfaces as the artifact index
            # (ADR 0026/0027). Digest guards against later mutation.
            try:
                artifact_digest = hashlib.sha256(
                    (result_json or "").encode("utf-8")
                ).hexdigest()
                connection.execute(
                    """
                    INSERT INTO eval_artifacts
                        (run_id, item_id, attempt_id, artifact_type, storage_path,
                         digest, size_bytes, retention_class)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'official')
                    """,
                    (
                        run_id,
                        item["id"],
                        attempt_id,
                        "transcript",
                        f"eval_runs/{run_id}/items/{item['id']}/attempts/{attempt_id}",
                        artifact_digest,
                        len(result_json or ""),
                    ),
                )
            except Exception:
                logger.exception(
                    "评测 Artifact 索引写入失败: run_id=%s item_id=%s",
                    run_id,
                    item["id"],
                )
        except Exception as exc:
            logger.exception("评测 Item 执行失败: run_id=%s item_id=%s", run_id, item["id"])
            connection.execute(
                """
                UPDATE eval_attempts
                SET status = 'failed', failure_class = 'target_execution',
                    error_message = ?, finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (str(exc)[:500], attempt_id),
            )
            connection.execute(
                """
                UPDATE eval_items
                SET status = 'failed', result_json = ?, finished_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (_json_dumps({"error": str(exc)[:500]}), item["id"]),
            )
            append_event(
                connection,
                run_id,
                "item.failed",
                {"item_id": item["id"], "case_key": case_key},
            )
        finally:
            counts = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed
                FROM eval_items WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            completed = int(counts["completed"] or 0)
            failed = int(counts["failed"] or 0)
            connection.execute(
                """
                UPDATE eval_runs
                SET completed_items = ?, failed_items = ?
                WHERE id = ?
                """,
                (completed, failed, run_id),
            )
            connection.execute(
                """
                UPDATE eval_batches
                SET completed_items = ?, failed_items = ?
                WHERE id = ?
                """,
                (completed, failed, run["batch_id"]),
            )
            connection.commit()

    remaining_cancelled = connection.execute(
        "SELECT cancel_requested FROM eval_runs WHERE id = ?", (run_id,)
    ).fetchone()[0]
    counts = connection.execute(
        """
        SELECT
            SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed,
            SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
            SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled
        FROM eval_items WHERE run_id = ?
        """,
        (run_id,),
    ).fetchone()
    completed = int(counts["completed"] or 0)
    failed = int(counts["failed"] or 0)
    cancelled = int(counts["cancelled"] or 0)
    status = "cancelled" if remaining_cancelled or cancelled else "failed" if failed else "completed"
    summary = {
        "total_items": run["total_items"],
        "completed_items": completed,
        "failed_items": failed,
        "cancelled_items": cancelled,
        "metric_summary": _aggregate_metric_summary(connection, run_id),
    }
    connection.execute(
        """
        UPDATE eval_runs
        SET status = ?, completed_items = ?, failed_items = ?, summary_json = ?,
            finished_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, completed, failed, _json_dumps(summary), run_id),
    )
    connection.execute(
        """
        UPDATE eval_batches
        SET status = ?, completed_items = ?, failed_items = ?, summary_json = ?,
            finished_at = CURRENT_TIMESTAMP
        WHERE id = ?
        """,
        (status, completed, failed, _json_dumps(summary), run["batch_id"]),
    )
    append_event(connection, run_id, f"run.{status}", summary)
    connection.commit()
    return {"run_id": run_id, "status": status, **summary}
