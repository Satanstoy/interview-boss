"""Worker heartbeat and cron observability persistence helpers."""

from __future__ import annotations

import json
from contextlib import nullcontext
from functools import wraps

def _ensure_observability_tables(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_heartbeats (
            worker_name TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            queue_name TEXT NOT NULL DEFAULT '',
            last_seen_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_error TEXT NOT NULL DEFAULT '',
            metadata_json TEXT NOT NULL DEFAULT '{}'
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS worker_cron_runs (
            task_name TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            last_run_at TIMESTAMP,
            last_finished_at TIMESTAMP,
            last_error TEXT NOT NULL DEFAULT '',
            last_result_json TEXT NOT NULL DEFAULT '{}',
            run_count INTEGER NOT NULL DEFAULT 0
        )
        """
    )


def _connection_context(conn=None):
    if conn is not None:
        return nullcontext(conn)
    from app.db.connection import get_db_connection

    candidate = get_db_connection()
    if hasattr(candidate, "execute"):
        return nullcontext(candidate)
    return candidate


def record_worker_heartbeat(
    worker_name: str,
    *,
    status: str,
    queue_name: str = "",
    error: str = "",
    metadata: dict | None = None,
    conn=None,
):
    """Persist the latest worker state for offline-vs-empty diagnostics."""
    with _connection_context(conn) as connection:
        _ensure_observability_tables(connection)
        payload = json.dumps(
            metadata or {}, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        connection.execute(
            """
            INSERT INTO worker_heartbeats
                (worker_name, status, queue_name, last_seen_at, last_error, metadata_json)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP, ?, ?)
            ON CONFLICT(worker_name) DO UPDATE SET
                status = excluded.status,
                queue_name = excluded.queue_name,
                last_seen_at = CURRENT_TIMESTAMP,
                last_error = excluded.last_error,
                metadata_json = excluded.metadata_json
            """,
            (worker_name, status, queue_name, error[:500], payload),
        )
        connection.commit()
    return {
        "worker_name": worker_name,
        "status": status,
        "queue_name": queue_name,
        "last_error": error[:500],
        "metadata": metadata or {},
    }


async def record_worker_heartbeat_async(
    worker_name: str,
    *,
    status: str,
    queue_name: str = "",
    error: str = "",
    metadata: dict | None = None,
    fallback=None,
) -> bool:
    """Redis-first worker heartbeat; falls back to SQLite when Redis is down.

    关联 spec R1 / ADR 0046:心跳记帐优先走 Redis,避免与读端抢同一把
    SQLite 单写锁。返回 True=已写 Redis(本次不写 SQLite);False=Redis
    不可用,已回退到 record_worker_heartbeat(SQLite,fail-open)。
    """
    from app.core.cache import worker_status_set

    ok = await worker_status_set(worker_name, status)
    if not ok:
        (fallback or record_worker_heartbeat)(
            worker_name,
            status=status,
            queue_name=queue_name,
            error=error,
            metadata=metadata,
        )
        return False
    return True


def record_cron_execution(
    task_name: str,
    *,
    status: str,
    result=None,
    error: str = "",
    conn=None,
):
    """Persist the latest scheduled-task result, including failures."""
    with _connection_context(conn) as connection:
        _ensure_observability_tables(connection)
        result_json = json.dumps(result or {}, ensure_ascii=False, sort_keys=True, default=str)
        is_running = status == "running"
        connection.execute(
            """
            INSERT INTO worker_cron_runs
                (task_name, status, last_run_at, last_finished_at, last_error,
                 last_result_json, run_count)
            VALUES (?, ?, CURRENT_TIMESTAMP,
                    CASE WHEN ? = 1 THEN NULL ELSE CURRENT_TIMESTAMP END,
                    ?, ?, CASE WHEN ? = 1 THEN 1 ELSE 0 END)
            ON CONFLICT(task_name) DO UPDATE SET
                status = excluded.status,
                last_run_at = CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP
                                   ELSE worker_cron_runs.last_run_at END,
                last_finished_at = CASE WHEN ? = 1 THEN worker_cron_runs.last_finished_at
                                        ELSE CURRENT_TIMESTAMP END,
                last_error = excluded.last_error,
                last_result_json = excluded.last_result_json,
                run_count = worker_cron_runs.run_count + CASE WHEN ? = 1 THEN 1 ELSE 0 END
            """,
            (
                task_name,
                status,
                int(is_running),
                error[:500],
                result_json,
                int(is_running),
                int(is_running),
                int(is_running),
                int(is_running),
            ),
        )
        connection.commit()


def get_cron_status(task_name: str, *, conn=None) -> dict:
    """Return a stable status shape even when a task has never run."""
    with _connection_context(conn) as connection:
        _ensure_observability_tables(connection)
        row = connection.execute(
            "SELECT * FROM worker_cron_runs WHERE task_name = ?", (task_name,)
        ).fetchone()
    if row is None:
        return {"task_name": task_name, "status": "not_run", "run_count": 0}
    return dict(row)


def _cron_should_record_success(task_name: str) -> bool:
    """上一次持久化状态已是成功且无错误时,本次成功无需再写 SQLite。

    配合 observed_cron_task:成功且状态无变化时只刷 Redis,减少高频成功重写
    对 SQLite 单写锁的获取(spec R1)。
    """
    with _connection_context() as connection:
        _ensure_observability_tables(connection)
        row = connection.execute(
            "SELECT status, last_error FROM worker_cron_runs WHERE task_name = ?",
            (task_name,),
        ).fetchone()
    if not row:
        return False
    return row["status"] == "succeeded" and not row["last_error"]


def observed_cron_task(task, *, record_execution=None):
    """Wrap an ARQ cron task without swallowing errors or changing its name."""
    record_execution = record_execution or record_cron_execution

    @wraps(task)
    async def wrapped(ctx):
        from app.core.cache import worker_status_set

        task_name = task.__name__
        redis_ok = await worker_status_set(task_name, "running")
        if not redis_ok:
            record_execution(task_name, status="running")
        try:
            result = await task(ctx)
        except Exception as exc:
            record_execution(task_name, status="failed", error=str(exc))
            raise
        if redis_ok:
            await worker_status_set(task_name, "succeeded")
            if _cron_should_record_success(task_name):
                return result
        record_execution(task_name, status="succeeded", result=result)
        return result

    return wrapped


def get_eval_worker_status(*, conn=None) -> dict:
    """Classify an evaluation queue as empty, active, or worker-offline."""
    with _connection_context(conn) as connection:
        _ensure_observability_tables(connection)
        counts = {
            row["status"]: row["count"]
            for row in connection.execute(
                "SELECT status, COUNT(*) AS count FROM eval_runs GROUP BY status"
            ).fetchall()
        }
        heartbeat = connection.execute(
            "SELECT * FROM worker_heartbeats WHERE worker_name = 'eval-worker'"
        ).fetchone()
        stale_queued = connection.execute(
            "SELECT COUNT(*) FROM eval_runs "
            "WHERE status IN ('created', 'queued') "
            "AND created_at < datetime('now', '-10 minutes')"
        ).fetchone()[0]
    queued = sum(counts.get(status, 0) for status in ("created", "queued", "running"))
    if not queued:
        queue_state = "queue_empty"
    elif stale_queued:
        queue_state = "queued_stuck"
    elif heartbeat is None or heartbeat["status"] != "online":
        queue_state = "worker_offline"
    else:
        queue_state = "worker_online"
    return {
        "queue_state": queue_state,
        "counts": counts,
        "stale_queued_count": stale_queued,
        "heartbeat": dict(heartbeat) if heartbeat else None,
    }
