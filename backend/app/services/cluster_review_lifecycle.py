"""Durable, version-aware lifecycle for public cluster quality review.

The database is the source of truth.  This module deliberately keeps ARQ out
of mutation transactions: callers update a cluster and call
``mark_cluster_review_pending`` in the same SQLite transaction, then a
dispatcher later delivers the durable task to ARQ.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("interview-boss")

ACTIVE_PUBLIC_CLUSTER_SQL = (
    "owner_id IS NULL AND deleted_at IS NULL AND status = 'approved'"
)
REVIEWABLE_ISSUE_STATUSES = ("pending", "approved")
MAX_REVIEW_ATTEMPTS = 3
DISPATCH_LEASE_SECONDS = 300
WORKER_LEASE_SECONDS = 900


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def _json_list(value: Any) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        result = json.loads(value)
    except (TypeError, ValueError):
        return []
    return result if isinstance(result, list) else []


def _unique_strings(values: list) -> list[str]:
    seen = set()
    result = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _row_value(row: Any, key: str, default: Any = "") -> Any:
    """Read a SQLite row or a lightweight test mapping compatibly."""
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def cluster_version_from_row(row: Any) -> str:
    """Return the stable version hash defined by the lifecycle spec."""
    originals = sorted(_unique_strings(_json_list(_row_value(row, "original_questions"))))
    payload = {
        "question": str(_row_value(row, "question") or "").strip(),
        "original_questions": originals,
        "cat1": str(_row_value(row, "cat1") or "").strip(),
        "cat2": str(_row_value(row, "cat2") or "").strip(),
        "job_position": str(_row_value(row, "job_position") or "").strip(),
    }
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def get_active_cluster(conn, cluster_id: int):
    return conn.execute(
        "SELECT id, question, cat1, cat2, job_position, frequency, "
        "original_questions, owner_id, deleted_at, status "
        "FROM question_bank WHERE id = ? AND " + ACTIVE_PUBLIC_CLUSTER_SQL,
        (cluster_id,),
    ).fetchone()


def get_current_cluster_version(conn, cluster_id: int) -> str | None:
    row = get_active_cluster(conn, cluster_id)
    return cluster_version_from_row(row) if row else None


def _insert_or_reset_task(
    conn,
    cluster_id: int,
    review_version: str,
    trigger_reason: str,
    now: str,
    force: bool = False,
) -> tuple[str, bool]:
    """Create a task, or reset a terminal same-version task for retry.

    The unique constraint is the final idempotency guard.  ``created`` tells
    callers whether a new durable outbox row was added/reset.
    """
    row = conn.execute(
        "SELECT id, status FROM cluster_review_tasks "
        "WHERE cluster_id = ? AND review_version = ?",
        (cluster_id, review_version),
    ).fetchone()
    if row and (
        _row_value(row, "id", None) is None
        or _row_value(row, "status", None) is None
    ):
        # Some legacy callers/tests provide a partial row stub.  Treat it as
        # absent; real SQLite rows always contain both columns.
        row = None
    if row:
        if row["status"] in ("failed", "superseded") or (
            force and row["status"] in ("completed", "passed")
        ):
            conn.execute(
                "UPDATE cluster_review_tasks SET status = 'pending', "
                "trigger_reason = ?, available_at = ?, locked_until = NULL, "
                "arq_job_id = NULL, last_error = NULL, finished_at = NULL "
                "WHERE id = ?",
                (trigger_reason, now, row["id"]),
            )
            return row["id"], True
        return row["id"], False

    task_id = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO cluster_review_tasks "
        "(id, cluster_id, review_version, trigger_reason, status, available_at) "
        "VALUES (?, ?, ?, ?, 'pending', ?)",
        (task_id, cluster_id, review_version, trigger_reason, now),
    )
    return task_id, True


def mark_cluster_review_pending(
    conn,
    cluster_id: int,
    trigger_reason: str,
    priority: int = 50,
    force: bool = False,
) -> dict | None:
    """Mark one active public cluster pending and enqueue its version once.

    No commit is performed.  The caller must invoke this inside the same
    transaction as the cluster mutation.
    """
    cluster = get_active_cluster(conn, cluster_id)
    if not cluster:
        return None

    now = _now()
    version = cluster_version_from_row(cluster)
    state = conn.execute(
        "SELECT * FROM cluster_review_state WHERE cluster_id = ?", (cluster_id,)
    ).fetchone()
    state_version = _row_value(state, "current_version", None) if state else None
    state_status = _row_value(state, "status", None) if state else None
    version_changed = not state or state_version != version
    review_reset = version_changed or force

    if not state:
        conn.execute(
            "INSERT INTO cluster_review_state "
            "(cluster_id, current_version, status, priority, last_trigger_reason, "
            "created_at, updated_at) VALUES (?, ?, 'needs_review', ?, ?, ?, ?)",
            (cluster_id, version, priority, trigger_reason, now, now),
        )
    elif review_reset:
        conn.execute(
            "UPDATE cluster_review_state SET current_version = ?, "
            "reviewed_version = NULL, status = 'needs_review', priority = ?, "
            "last_trigger_reason = ?, last_error = NULL, updated_at = ? "
            "WHERE cluster_id = ?",
            (version, priority, trigger_reason, now, cluster_id),
        )
    elif state_status == "failed":
        conn.execute(
            "UPDATE cluster_review_state SET status = 'needs_review', "
            "priority = ?, last_trigger_reason = ?, last_error = NULL, updated_at = ? "
            "WHERE cluster_id = ?",
            (priority, trigger_reason, now, cluster_id),
        )
    else:
        conn.execute(
            "UPDATE cluster_review_state SET priority = ?, last_trigger_reason = ?, "
            "updated_at = ? WHERE cluster_id = ?",
            (priority, trigger_reason, now, cluster_id),
        )

    task_id, task_changed = _insert_or_reset_task(
        conn, cluster_id, version, trigger_reason, now, force=force
    )
    return {
        "cluster_id": cluster_id,
        "review_version": version,
        "task_id": task_id,
        "version_changed": version_changed,
        "task_changed": task_changed,
    }


def mark_clusters_review_pending(
    conn,
    cluster_ids: list[int],
    trigger_reason: str,
    priority: int = 50,
    force: bool = False,
) -> list[dict]:
    results = []
    seen = set()
    for cluster_id in cluster_ids:
        if cluster_id in seen:
            continue
        seen.add(cluster_id)
        result = mark_cluster_review_pending(
            conn, int(cluster_id), trigger_reason, priority=priority, force=force
        )
        if result:
            results.append(result)
    return results


def backfill_cluster_review_state(conn, dry_run: bool = True) -> dict:
    """Backfill active public clusters without touching legacy business data.

    Legacy pending issues are preserved as human work and do not receive a
    duplicate AI task.  Legacy done/rejected rows have no provable version, so
    their clusters receive one safe baseline task.
    """
    rows = conn.execute(
        "SELECT id, question, cat1, cat2, job_position, frequency, "
        "original_questions, owner_id, deleted_at, status "
        "FROM question_bank WHERE " + ACTIVE_PUBLIC_CLUSTER_SQL + " ORDER BY id"
    ).fetchall()
    report = {
        "dry_run": dry_run,
        "active_clusters": len(rows),
        "states_created": 0,
        "states_updated": 0,
        "tasks_created": 0,
        "pending_preserved": 0,
        "baseline_tasks": 0,
    }

    for cluster in rows:
        cluster_id = cluster["id"]
        version = cluster_version_from_row(cluster)
        state = conn.execute(
            "SELECT current_version, status FROM cluster_review_state "
            "WHERE cluster_id = ?",
            (cluster_id,),
        ).fetchone()
        task = conn.execute(
            "SELECT status FROM cluster_review_tasks WHERE cluster_id = ? "
            "AND review_version = ?",
            (cluster_id, version),
        ).fetchone()
        pending = conn.execute(
            "SELECT COUNT(*) FROM quality_issue WHERE qb_id = ? "
            "AND status IN ('pending', 'approved')",
            (cluster_id,),
        ).fetchone()[0]

        if pending:
            report["pending_preserved"] += 1
        if not state:
            report["states_created"] += 1
        elif state["current_version"] != version:
            report["states_updated"] += 1

        needs_task = not pending and (
            not state
            or state["current_version"] != version
            or (
                state["status"] in ("needs_review", "failed")
                and (not task or task["status"] in ("failed", "superseded"))
            )
        )
        if needs_task:
            report["tasks_created"] += 1
            report["baseline_tasks"] += 1

        if dry_run:
            continue

        if pending:
            now = _now()
            conn.execute(
                "INSERT INTO cluster_review_state "
                "(cluster_id, current_version, reviewed_version, status, priority, "
                "last_trigger_reason, created_at, updated_at) VALUES (?, ?, NULL, "
                "'needs_human', 60, 'migration_pending_preserved', ?, ?) "
                "ON CONFLICT(cluster_id) DO UPDATE SET current_version = excluded.current_version, "
                "reviewed_version = NULL, status = 'needs_human', priority = 60, "
                "last_trigger_reason = excluded.last_trigger_reason, updated_at = excluded.updated_at",
                (cluster_id, version, now, now),
            )
            continue

        mark_cluster_review_pending(
            conn, cluster_id, "migration_backfill", priority=60 if cluster["frequency"] > 1 else 40
        )

    return report


def claim_review_dispatch_batch(
    conn, limit: int = 10, lease_seconds: int = DISPATCH_LEASE_SECONDS
) -> list[dict]:
    """Recover expired dispatcher leases and reserve due outbox rows."""
    now = _now()
    conn.execute(
        "UPDATE cluster_review_tasks SET status = 'pending', locked_until = NULL, "
        "arq_job_id = NULL, available_at = ? "
        "WHERE status IN ('queued', 'running') AND locked_until IS NOT NULL "
        "AND locked_until < ?",
        (now, now),
    )
    rows = conn.execute(
        "SELECT t.id, t.cluster_id, t.review_version, t.trigger_reason "
        "FROM cluster_review_tasks t LEFT JOIN cluster_review_state s "
        "ON s.cluster_id = t.cluster_id "
        "WHERE t.status = 'pending' AND t.available_at <= ? "
        "ORDER BY COALESCE(s.priority, 50) DESC, t.available_at, t.created_at "
        "LIMIT ?",
        (now, limit),
    ).fetchall()
    if not rows:
        return []

    locked_until = f"datetime('now', '+{int(lease_seconds)} seconds')"
    result = []
    for row in rows:
        updated = conn.execute(
            "UPDATE cluster_review_tasks SET status = 'queued', locked_until = "
            + locked_until
            + " WHERE id = ? AND status = 'pending'",
            (row["id"],),
        )
        if updated.rowcount:
            result.append(dict(row))
    return result


def mark_review_task_dispatched(conn, task_id: str, arq_job_id: str | None) -> None:
    now = _now()
    if arq_job_id:
        conn.execute(
            "UPDATE cluster_review_tasks SET arq_job_id = ?, last_error = NULL "
            "WHERE id = ? AND status = 'queued'",
            (arq_job_id, task_id),
        )
    else:
        conn.execute(
            "UPDATE cluster_review_tasks SET status = 'pending', locked_until = NULL, "
            "available_at = ?, last_error = 'ARQ enqueue failed' WHERE id = ? "
            "AND status = 'queued'",
            (now, task_id),
        )


def claim_review_task(conn, task_id: str, lease_seconds: int = WORKER_LEASE_SECONDS):
    """Atomically let one ARQ delivery own a task."""
    updated = conn.execute(
        "UPDATE cluster_review_tasks SET status = 'running', attempts = attempts + 1, "
        "started_at = COALESCE(started_at, CURRENT_TIMESTAMP), "
        "locked_until = datetime('now', ?), last_error = NULL "
        "WHERE id = ? AND status IN ('pending', 'queued')",
        (f"+{int(lease_seconds)} seconds", task_id),
    )
    if not updated.rowcount:
        return None
    return conn.execute(
        "SELECT * FROM cluster_review_tasks WHERE id = ?", (task_id,)
    ).fetchone()


def finish_review_task(conn, task: Any, outcome: str = "completed") -> dict:
    """Persist evaluator completion and update the cluster read model."""
    now = _now()
    current_version = get_current_cluster_version(conn, task["cluster_id"])
    if current_version != task["review_version"]:
        conn.execute(
            "UPDATE cluster_review_tasks SET status = 'superseded', locked_until = NULL, "
            "finished_at = ?, last_error = 'review version superseded' WHERE id = ?",
            (now, task["id"]),
        )
        return {"status": "superseded", "cluster_id": task["cluster_id"]}

    pending = conn.execute(
        "SELECT COUNT(*) FROM quality_issue WHERE qb_id = ? "
        "AND status IN ('pending', 'approved')",
        (task["cluster_id"],),
    ).fetchone()[0]
    state_status = "needs_human" if pending else "passed"
    reviewed_version = None if pending else task["review_version"]
    conn.execute(
        "UPDATE cluster_review_state SET current_version = ?, reviewed_version = ?, "
        "status = ?, last_reviewed_at = ?, last_error = NULL, updated_at = ? "
        "WHERE cluster_id = ?",
        (
            task["review_version"],
            reviewed_version,
            state_status,
            now,
            now,
            task["cluster_id"],
        ),
    )
    conn.execute(
        "UPDATE cluster_review_tasks SET status = ?, locked_until = NULL, "
        "finished_at = ?, last_error = NULL WHERE id = ?",
        (outcome, now, task["id"]),
    )
    return {
        "status": state_status,
        "cluster_id": task["cluster_id"],
        "review_version": task["review_version"],
        "pending_issues": pending,
    }


def fail_review_task(
    conn, task: Any, error: str, max_attempts: int = MAX_REVIEW_ATTEMPTS
) -> dict:
    """Retry with backoff, or make the failure visible for compensation."""
    now = _now()
    attempts = int(task["attempts"] or 0)
    if attempts < max_attempts:
        delay = min(3600, 2 ** max(0, attempts - 1) * 60)
        conn.execute(
            "UPDATE cluster_review_tasks SET status = 'pending', available_at = "
            "datetime('now', ?), locked_until = NULL, last_error = ? WHERE id = ?",
            (f"+{delay} seconds", str(error)[:500], task["id"]),
        )
        status = "retrying"
    else:
        conn.execute(
            "UPDATE cluster_review_tasks SET status = 'failed', locked_until = NULL, "
            "finished_at = ?, last_error = ? WHERE id = ?",
            (now, str(error)[:500], task["id"]),
        )
        conn.execute(
            "UPDATE cluster_review_state SET status = 'failed', last_error = ?, "
            "updated_at = ? WHERE cluster_id = ?",
            (str(error)[:500], now, task["cluster_id"]),
        )
        status = "failed"
    return {"status": status, "task_id": task["id"], "attempts": attempts}


def review_state_summary(conn) -> dict:
    rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM cluster_review_state GROUP BY status"
    ).fetchall()
    tasks = conn.execute(
        "SELECT status, COUNT(*) AS count FROM cluster_review_tasks GROUP BY status"
    ).fetchall()
    return {
        "states": {row["status"]: row["count"] for row in rows},
        "tasks": {row["status"]: row["count"] for row in tasks},
    }


SINGLETON_REVIEW_PROMPT = """你是面试题题库管理专家。下面是一道公共题库中的独立题目。

请只检查它是否适合作为脱离面经上下文的规范面试题：题意是否自明、上下文是否完整、
是否存在明显口语/截断/面经残留。独立题不需要为了覆盖其它题而改写。

【题目】
{representative}

输出严格 JSON：{{"issue": true 或 false, "suggested": "规范题面或 null",
"confidence": 0.0-1.0, "reason": "一句话原因"}}"""


async def _evaluate_singleton(
    cluster_id: int,
    review_version: str,
    review_task_id: str,
    trigger_reason: str,
    user_id: int | None,
) -> int:
    """Evaluate one singleton; only a real defect enters human review."""
    import asyncio

    from app.db.connection import get_db_connection
    from app.services.llm import _call_llm_with_retry
    from app.services.llm_judge import parse_json_object

    def _load():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, question FROM question_bank WHERE id = ? AND "
                + ACTIVE_PUBLIC_CLUSTER_SQL,
                (cluster_id,),
            ).fetchone()

    row = await asyncio.to_thread(_load)
    if not row:
        return 0
    raw = await _call_llm_with_retry(
        SINGLETON_REVIEW_PROMPT.format(representative=row["question"]),
        system_msg="你是一个面试题题库管理专家。",
        response_format=None,
        user_id=user_id,
        model=None,
    )
    data = parse_json_object(raw) or {}
    suggested = str(data.get("suggested") or "").strip()
    confidence = float(data.get("confidence") or 0)
    if not data.get("issue") or not suggested or suggested == row["question"]:
        return 0

    def _insert():
        with get_db_connection() as conn:
            # The task may have become stale while the model was running.
            if get_current_cluster_version(conn, cluster_id) != review_version:
                return False
            cur = conn.execute(
                "INSERT OR IGNORE INTO quality_issue "
                "(qb_id, variant_index, issue_type, suggested_action, reason, "
                "suggested_value, confidence, status, created_at, review_version, "
                "review_task_id, trigger_reason, variant_key) "
                "VALUES (?, NULL, 'new_representative', 'refine_representative', ?, ?, ?, "
                "'pending', datetime('now'), ?, ?, ?, '')",
                (
                    cluster_id,
                    str(data.get("reason") or "")[:300],
                    suggested,
                    max(0.0, min(confidence, 1.0)),
                    review_version,
                    review_task_id,
                    trigger_reason,
                ),
            )
            conn.commit()
            return bool(cur.rowcount)

    return int(await asyncio.to_thread(_insert))


async def run_cluster_review_task(task_id: str, user_id: int | None = None) -> dict:
    """Claim and evaluate one durable task, with DB-owned retry state."""
    import asyncio

    from app.db.connection import get_db_connection

    def _claim():
        conn = get_db_connection()
        task = claim_review_task(conn, task_id)
        conn.commit()
        return dict(task) if task else None

    task = await asyncio.to_thread(_claim)
    if not task:
        return {"status": "already_claimed_or_finished", "task_id": task_id}

    try:
        def _load_cluster():
            with get_db_connection() as conn:
                row = get_active_cluster(conn, task["cluster_id"])
                if not row:
                    return None, None
                return dict(row), cluster_version_from_row(row)

        cluster, current_version = await asyncio.to_thread(_load_cluster)
        if not cluster or current_version != task["review_version"]:
            def _supersede():
                conn = get_db_connection()
                result = finish_review_task(conn, task)
                conn.commit()
                return result

            return await asyncio.to_thread(_supersede)

        if int(cluster.get("frequency") or 1) > 1:
            from app.services.clustering_maintenance import (
                generate_quality_issues,
                generate_weak_representative_issues,
            )

            await generate_quality_issues(
                user_id=user_id,
                cluster_ids=[task["cluster_id"]],
                review_version=task["review_version"],
                review_task_id=task["id"],
                trigger_reason=task["trigger_reason"],
            )
            await generate_weak_representative_issues(
                user_id=user_id,
                cluster_ids=[task["cluster_id"]],
                review_version=task["review_version"],
                review_task_id=task["id"],
                trigger_reason=task["trigger_reason"],
            )
        else:
            await _evaluate_singleton(
                task["cluster_id"],
                task["review_version"],
                task["id"],
                task["trigger_reason"],
                user_id,
            )

        def _finish():
            conn = get_db_connection()
            result = finish_review_task(conn, task)
            conn.commit()
            return result

        return await asyncio.to_thread(_finish)
    except Exception as exc:
        logger.warning("cluster review task failed: %s (%s)", task_id, exc)

        def _fail():
            conn = get_db_connection()
            result = fail_review_task(conn, task, str(exc))
            conn.commit()
            return result

        return await asyncio.to_thread(_fail)
