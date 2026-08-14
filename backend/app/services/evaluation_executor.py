"""Execute one Eval Run using the Target Adapter boundary."""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import Any, Callable

from app.db.connection import get_db_connection
from app.evaluation.adapters import get_target_adapter
from app.evaluation.judge import judge_observation
from app.evaluation.scoring import score_observation
from app.services.evaluation_service import append_event

logger = logging.getLogger("interview-boss.evaluation")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


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
               cs.manifest_json AS candidate_simulator_manifest_json
        FROM eval_runs r
        JOIN eval_batches b ON b.id = r.batch_id
        JOIN eval_releases tr ON tr.id = r.target_release_id
        JOIN eval_releases jr ON jr.id = r.judge_release_id
        JOIN eval_releases sh ON sh.id = r.simulator_harness_release_id
        JOIN eval_releases cs ON cs.id = r.candidate_simulator_release_id
        WHERE r.id = ?
        """,
        (run_id,),
    ).fetchone()
    return _row_dict(row)


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
        attempt_cursor = connection.execute(
            """
            INSERT INTO eval_attempts (item_id, attempt_index, attempt_kind)
            VALUES (?, 1, 'target')
            """,
            (item["id"],),
        )
        attempt_id = attempt_cursor.lastrowid
        connection.commit()

        try:
            adapter = resolver(target_release["target_type"])
            case_snapshot = json.loads(item["input_snapshot_json"] or "{}")
            contract = json.loads(item["contract_json"] or "{}")
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
            score = score_observation(observation, contract)
            if run["target_type"] == "interview":
                if score["hard_gate_status"] == "passed":
                    judge_result = await judge_observation(
                        case_key=item["case_key"],
                        contract=contract,
                        observation=observation,
                        judge_model=run["judge_model"] or "",
                    )
                    score.update(judge_result)
                else:
                    score["judge_status"] = "skipped_hard_gate"
                    score["judge_model"] = run["judge_model"] or ""
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
                {"item_id": item["id"], "case_key": item["case_key"]},
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
                {"item_id": item["id"], "case_key": item["case_key"]},
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
