"""Low-concurrency ARQ worker for the isolated Eval Queue."""

from __future__ import annotations

import asyncio
import contextlib
import os

from arq.connections import RedisSettings

from app.evaluation.queue import EVAL_QUEUE_NAME, REDIS_URL


async def _eval_run_heartbeat(run_id: int, stop: asyncio.Event):
    """Keep a long-running provider call distinguishable from a dead worker."""
    interval = max(5, int(os.environ.get("EVAL_HEARTBEAT_INTERVAL", "30")))
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            continue
        except asyncio.TimeoutError:
            pass

        def _touch():
            from app.db.connection import get_db_connection
            from app.services.evaluation_lifecycle import touch_eval_run_heartbeat

            with get_db_connection() as conn:
                changed = touch_eval_run_heartbeat(conn, run_id)
                conn.commit()
                return changed

        try:
            await asyncio.to_thread(_touch)
        except Exception:
            # The evaluator remains the source of truth; a later reaper will
            # expire the run if DB heartbeats cannot be persisted.
            continue


async def eval_run_task(ctx, run_id: int):
    from app.services.evaluation_executor import (
        execute_eval_run,
        reconcile_interrupted_eval_run,
    )
    from app.worker import record_worker_heartbeat

    stop = asyncio.Event()
    heartbeat_task = asyncio.create_task(_eval_run_heartbeat(int(run_id), stop))
    try:
        result = await execute_eval_run(int(run_id))
        record_worker_heartbeat(
            "eval-worker",
            status="online",
            queue_name=EVAL_QUEUE_NAME,
            metadata={"last_run_id": int(run_id)},
        )
        return result
    except asyncio.CancelledError:
        result = reconcile_interrupted_eval_run(
            int(run_id), reason="worker_cancelled"
        )
        record_worker_heartbeat(
            "eval-worker",
            status="degraded",
            queue_name=EVAL_QUEUE_NAME,
            error="eval run cancelled by worker timeout or shutdown",
            metadata={"last_run_id": int(run_id)},
        )
        return result
    except Exception as exc:
        record_worker_heartbeat(
            "eval-worker",
            status="degraded",
            queue_name=EVAL_QUEUE_NAME,
            error=str(exc),
            metadata={"last_run_id": int(run_id)},
        )
        raise
    finally:
        stop.set()
        heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat_task


async def startup(ctx):
    from app.db.connection import init_db
    from app.worker import record_worker_heartbeat

    init_db()
    record_worker_heartbeat(
        "eval-worker",
        status="online",
        queue_name=EVAL_QUEUE_NAME,
    )


async def shutdown(ctx):
    from app.worker import record_worker_heartbeat

    record_worker_heartbeat(
        "eval-worker",
        status="offline",
        queue_name=EVAL_QUEUE_NAME,
    )
    return None


class EvalWorkerSettings:
    functions = [eval_run_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    queue_name = EVAL_QUEUE_NAME
    max_jobs = 1
    queue_read_limit = 1
    job_timeout = max(6 * 60 * 60, int(os.environ.get("EVAL_JOB_TIMEOUT", "21600")))
    max_tries = 3
    keep_result = 3600
