"""Evaluation heartbeat, expiry and immutable restart helpers."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import uuid
from typing import Any

from app.services.evaluation_service import append_event

DEFAULT_QUEUE_TIMEOUT_SECONDS = 15 * 60
DEFAULT_RUNNING_TIMEOUT_SECONDS = 30 * 60


def _parse_timestamp(value: Any) -> dt.datetime | None:
    if not value:
        return None
    if isinstance(value, dt.datetime):
        return value.replace(tzinfo=None)
    try:
        return dt.datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(
            tzinfo=None
        )
    except ValueError:
        return None


def _decode_json(value: str | None) -> dict[str, Any]:
    try:
        payload = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def touch_eval_run_heartbeat(conn: sqlite3.Connection, run_id: int) -> bool:
    """Refresh a Run and its Batch lease without appending noisy SSE events."""
    cursor = conn.execute(
        """
        UPDATE eval_runs
        SET last_heartbeat_at = CURRENT_TIMESTAMP
        WHERE id = ? AND status IN ('created', 'queued', 'running')
        """,
        (run_id,),
    )
    if cursor.rowcount:
        conn.execute(
            """
            UPDATE eval_batches
            SET last_heartbeat_at = CURRENT_TIMESTAMP
            WHERE id = (
                SELECT batch_id FROM eval_runs WHERE id = ?
            ) AND status IN ('created', 'queued', 'running')
            """,
            (run_id,),
        )
    return bool(cursor.rowcount)


def expire_stale_eval_runs(
    conn: sqlite3.Connection,
    *,
    now: dt.datetime | None = None,
    queued_timeout_seconds: int = DEFAULT_QUEUE_TIMEOUT_SECONDS,
    running_timeout_seconds: int = DEFAULT_RUNNING_TIMEOUT_SECONDS,
) -> list[int]:
    """Mark abandoned queued/running Runs as expired, preserving all evidence."""
    current = (now or dt.datetime.now(dt.UTC)).replace(tzinfo=None)
    rows = conn.execute(
        """
        SELECT id, batch_id, status, created_at, started_at, last_heartbeat_at,
               summary_json
        FROM eval_runs
        WHERE status IN ('created', 'queued', 'running')
        ORDER BY id
        """
    ).fetchall()
    expired: list[int] = []
    for row in rows:
        reference = _parse_timestamp(row["last_heartbeat_at"])
        if row["status"] == "running":
            reference = reference or _parse_timestamp(row["started_at"])
            timeout = running_timeout_seconds
            reason = "running_heartbeat_timeout"
        else:
            reference = reference or _parse_timestamp(row["created_at"])
            timeout = queued_timeout_seconds
            reason = "queued_timeout"
        if reference is None or (current - reference).total_seconds() < timeout:
            continue

        summary = _decode_json(row["summary_json"])
        summary.update(
            {
                "expiration_reason": reason,
                "expired_at": current.isoformat(timespec="seconds"),
            }
        )
        conn.execute(
            """
            UPDATE eval_runs
            SET status = 'expired', cancel_requested = 1,
                summary_json = ?, finished_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status IN ('created', 'queued', 'running')
            """,
            (json.dumps(summary, ensure_ascii=False, sort_keys=True), row["id"]),
        )
        if conn.execute("SELECT changes()").fetchone()[0] != 1:
            continue
        conn.execute(
            """
            UPDATE eval_batches
            SET status = 'expired', cancel_requested = 1,
                summary_json = ?, finished_at = CURRENT_TIMESTAMP
            WHERE id = ? AND status IN ('created', 'queued', 'running')
            """,
            (json.dumps(summary, ensure_ascii=False, sort_keys=True), row["batch_id"]),
        )
        append_event(
            conn,
            row["id"],
            "run.expired",
            {"reason": reason, "expired_at": summary["expired_at"]},
        )
        expired.append(row["id"])
    if expired:
        conn.commit()
    return expired


def restart_eval_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    created_by: int | None = None,
) -> dict[str, Any]:
    """Create a new Run from an expired Run's immutable snapshot.

    The original Run, attempts, items and events remain untouched. The new
    Run gets a fresh Batch fingerprint and starts with every materialized Item
    pending so a partial/stuck execution cannot silently lose coverage.
    """
    source = conn.execute("SELECT * FROM eval_runs WHERE id = ?", (run_id,)).fetchone()
    if source is None:
        raise ValueError("Eval Run 不存在")
    if source["status"] != "expired":
        expired_event = conn.execute(
            "SELECT 1 FROM eval_events WHERE run_id = ? AND event_type = 'run.expired' LIMIT 1",
            (run_id,),
        ).fetchone()
        if expired_event is None:
            raise ValueError("只有已失效的 Eval Run 可以重启")
    batch = conn.execute(
        "SELECT * FROM eval_batches WHERE id = ?", (source["batch_id"],)
    ).fetchone()
    if batch is None:
        raise ValueError("Eval Run 的 Batch 不存在")

    fingerprint = hashlib.sha256(
        f"{batch['batch_fingerprint']}:restart:{run_id}:{uuid.uuid4().hex}".encode()
    ).hexdigest()
    batch_cursor = conn.execute(
        """
        INSERT INTO eval_batches (
            batch_fingerprint, target_release_id, evaluation_release_id,
            benchmark_suite_release_id, eval_protocol_release_id, judge_release_id,
            simulator_harness_release_id, candidate_simulator_release_id,
            harness_release_id, environment_fingerprint, seed, replication_count,
            status, total_items, completed_items, failed_items, created_by,
            summary_json, snapshot_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', ?, 0, 0, ?, '{}', ?)
        """,
        (
            fingerprint,
            batch["target_release_id"],
            batch["evaluation_release_id"],
            batch["benchmark_suite_release_id"],
            batch["eval_protocol_release_id"],
            batch["judge_release_id"],
            batch["simulator_harness_release_id"],
            batch["candidate_simulator_release_id"],
            batch["harness_release_id"],
            batch["environment_fingerprint"],
            batch["seed"],
            batch["replication_count"],
            source["total_items"],
            created_by,
            batch["snapshot_json"],
        ),
    )
    batch_id = batch_cursor.lastrowid
    run_cursor = conn.execute(
        """
        INSERT INTO eval_runs (
            batch_id, target_release_id, evaluation_release_id,
            benchmark_suite_release_id, eval_protocol_release_id, judge_release_id,
            simulator_harness_release_id, candidate_simulator_release_id,
            harness_release_id, comparison_group, status, total_items,
            summary_json, created_by, snapshot_json, restart_of_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', ?, '{}', ?, ?, ?)
        """,
        (
            batch_id,
            source["target_release_id"],
            source["evaluation_release_id"],
            source["benchmark_suite_release_id"],
            source["eval_protocol_release_id"],
            source["judge_release_id"],
            source["simulator_harness_release_id"],
            source["candidate_simulator_release_id"],
            source["harness_release_id"],
            source["comparison_group"],
            source["total_items"],
            created_by,
            source["snapshot_json"],
            run_id,
        ),
    )
    new_run_id = run_cursor.lastrowid
    items = conn.execute(
        "SELECT case_id, replication_index, seed FROM eval_items WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
    conn.executemany(
        """
        INSERT INTO eval_items (run_id, case_id, replication_index, seed)
        VALUES (?, ?, ?, ?)
        """,
        [(new_run_id, item["case_id"], item["replication_index"], item["seed"]) for item in items],
    )
    append_event(
        conn,
        run_id,
        "run.restart_requested",
        {"new_run_id": new_run_id},
    )
    append_event(
        conn,
        new_run_id,
        "run.created",
        {"status": "created", "restart_of_run_id": run_id},
    )
    conn.commit()
    result = dict(conn.execute("SELECT * FROM eval_runs WHERE id = ?", (new_run_id,)).fetchone())
    result["batch_id"] = batch_id
    result["batch_fingerprint"] = fingerprint
    return result


def resume_eval_run(
    conn: sqlite3.Connection,
    run_id: int,
    *,
    created_by: int | None = None,
) -> dict[str, Any]:
    """Create an immutable continuation Run from an interrupted Run.

    Completed Items, Attempts and Artifact indexes are copied as evidence and
    remain completed. Interrupted, failed, cancelled and pending Items become
    fresh pending work in the new Run. The source Run is never rewritten.
    """
    conn.execute("BEGIN IMMEDIATE")
    source = conn.execute("SELECT * FROM eval_runs WHERE id = ?", (run_id,)).fetchone()
    if source is None:
        conn.rollback()
        raise ValueError("Eval Run 不存在")
    if source["status"] not in {"failed", "cancelled", "expired"}:
        conn.rollback()
        raise ValueError("只有中断、失败、取消或失效的 Eval Run 可以续作")
    existing = conn.execute(
        """
        SELECT * FROM eval_runs
        WHERE resume_of_run_id = ? AND status IN ('created', 'queued', 'running')
        ORDER BY id
        LIMIT 1
        """,
        (run_id,),
    ).fetchone()
    if existing is not None:
        summary = _decode_json(existing["summary_json"])
        result = dict(existing)
        result["batch_id"] = existing["batch_id"]
        result["reused_completed_items"] = int(summary.get("reused_completed_items", 0))
        result["rerun_items"] = int(summary.get("rerun_items", 0))
        result["already_exists"] = True
        conn.commit()
        return result
    batch = conn.execute(
        "SELECT * FROM eval_batches WHERE id = ?", (source["batch_id"],)
    ).fetchone()
    if batch is None:
        conn.rollback()
        raise ValueError("Eval Run 的 Batch 不存在")

    source_items = conn.execute(
        "SELECT * FROM eval_items WHERE run_id = ? ORDER BY id", (run_id,)
    ).fetchall()
    if not source_items:
        conn.rollback()
        raise ValueError("Eval Run 没有可续作的 Case")
    reused_count = sum(item["status"] == "completed" for item in source_items)
    rerun_count = len(source_items) - reused_count
    source_summary = _decode_json(source["summary_json"])
    fingerprint = hashlib.sha256(
        f"{batch['batch_fingerprint']}:resume:{run_id}:{uuid.uuid4().hex}".encode()
    ).hexdigest()
    batch_cursor = conn.execute(
        """
        INSERT INTO eval_batches (
            batch_fingerprint, target_release_id, evaluation_release_id,
            benchmark_suite_release_id, eval_protocol_release_id, judge_release_id,
            simulator_harness_release_id, candidate_simulator_release_id,
            harness_release_id, environment_fingerprint, seed, replication_count,
            status, total_items, completed_items, failed_items, created_by,
            summary_json, snapshot_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', ?, ?, 0, ?, ?, ?)
        """,
        (
            fingerprint,
            batch["target_release_id"],
            batch["evaluation_release_id"],
            batch["benchmark_suite_release_id"],
            batch["eval_protocol_release_id"],
            batch["judge_release_id"],
            batch["simulator_harness_release_id"],
            batch["candidate_simulator_release_id"],
            batch["harness_release_id"],
            batch["environment_fingerprint"],
            batch["seed"],
            batch["replication_count"],
            len(source_items),
            reused_count,
            created_by,
            json.dumps(
                {
                    "resume_of_run_id": run_id,
                    "reused_completed_items": reused_count,
                    "rerun_items": rerun_count,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            batch["snapshot_json"],
        ),
    )
    batch_id = batch_cursor.lastrowid
    run_cursor = conn.execute(
        """
        INSERT INTO eval_runs (
            batch_id, target_release_id, evaluation_release_id,
            benchmark_suite_release_id, eval_protocol_release_id, judge_release_id,
            simulator_harness_release_id, candidate_simulator_release_id,
            harness_release_id, comparison_group, status, total_items,
            completed_items, failed_items, summary_json, created_by, snapshot_json,
            resume_of_run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', ?, ?, 0, ?, ?, ?, ?)
        """,
        (
            batch_id,
            source["target_release_id"],
            source["evaluation_release_id"],
            source["benchmark_suite_release_id"],
            source["eval_protocol_release_id"],
            source["judge_release_id"],
            source["simulator_harness_release_id"],
            source["candidate_simulator_release_id"],
            source["harness_release_id"],
            source["comparison_group"],
            len(source_items),
            reused_count,
            json.dumps(
                {
                    "resume_of_run_id": run_id,
                    "reused_completed_items": reused_count,
                    "rerun_items": rerun_count,
                    "source_status": source["status"],
                    "source_failure_class": source_summary.get("failure_class"),
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            created_by,
            source["snapshot_json"],
            run_id,
        ),
    )
    new_run_id = run_cursor.lastrowid
    item_map: dict[int, int] = {}
    completed_item_maps: list[tuple[sqlite3.Row, int]] = []
    for item in source_items:
        completed = item["status"] == "completed"
        item_cursor = conn.execute(
            """
            INSERT INTO eval_items (
                run_id, case_id, replication_index, seed, status,
                contract_status, hard_gate_status, judge_status, score, result_json,
                started_at, finished_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                new_run_id,
                item["case_id"],
                item["replication_index"],
                item["seed"],
                "completed" if completed else "pending",
                item["contract_status"] if completed else "pending",
                item["hard_gate_status"] if completed else "pending",
                item["judge_status"] if completed else "pending",
                item["score"] if completed else None,
                item["result_json"] if completed else "{}",
                item["started_at"] if completed else None,
                item["finished_at"] if completed else None,
            ),
        )
        new_item_id = item_cursor.lastrowid
        item_map[item["id"]] = new_item_id
        if completed:
            completed_item_maps.append((item, new_item_id))

    for source_item, new_item_id in completed_item_maps:
        attempt_map: dict[int, int] = {}
        attempts = conn.execute(
            "SELECT * FROM eval_attempts WHERE item_id = ? ORDER BY attempt_index",
            (source_item["id"],),
        ).fetchall()
        for attempt in attempts:
            attempt_cursor = conn.execute(
                """
                INSERT INTO eval_attempts (
                    item_id, attempt_index, attempt_kind, status, failure_class,
                    raw_observation_json, error_message, started_at, finished_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_item_id,
                    attempt["attempt_index"],
                    attempt["attempt_kind"],
                    attempt["status"],
                    attempt["failure_class"],
                    attempt["raw_observation_json"],
                    attempt["error_message"],
                    attempt["started_at"],
                    attempt["finished_at"],
                ),
            )
            attempt_map[attempt["id"]] = attempt_cursor.lastrowid
        selected_attempt_id = attempt_map.get(source_item["selected_attempt_id"])
        if selected_attempt_id is not None:
            conn.execute(
                "UPDATE eval_items SET selected_attempt_id = ? WHERE id = ?",
                (selected_attempt_id, new_item_id),
            )
        for artifact in conn.execute(
            "SELECT * FROM eval_artifacts WHERE item_id = ? ORDER BY id",
            (source_item["id"],),
        ).fetchall():
            conn.execute(
                """
                INSERT INTO eval_artifacts (
                    run_id, item_id, attempt_id, artifact_type, storage_path,
                    digest, size_bytes, retention_class
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    new_run_id,
                    new_item_id,
                    attempt_map.get(artifact["attempt_id"]),
                    artifact["artifact_type"],
                    artifact["storage_path"],
                    artifact["digest"],
                    artifact["size_bytes"],
                    artifact["retention_class"],
                ),
            )

    append_event(
        conn,
        run_id,
        "run.resume_requested",
        {
            "new_run_id": new_run_id,
            "reused_completed_items": reused_count,
            "rerun_items": rerun_count,
        },
    )
    append_event(
        conn,
        new_run_id,
        "run.created",
        {
            "status": "created",
            "resume_of_run_id": run_id,
            "reused_completed_items": reused_count,
            "rerun_items": rerun_count,
        },
    )
    if reused_count:
        append_event(
            conn,
            new_run_id,
            "run.items_reused",
            {"source_run_id": run_id, "item_count": reused_count},
        )
    conn.commit()
    result = dict(conn.execute("SELECT * FROM eval_runs WHERE id = ?", (new_run_id,)).fetchone())
    result["batch_id"] = batch_id
    result["batch_fingerprint"] = fingerprint
    result["reused_completed_items"] = reused_count
    result["rerun_items"] = rerun_count
    result["already_exists"] = False
    return result
