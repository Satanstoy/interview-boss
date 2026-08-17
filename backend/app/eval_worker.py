"""Low-concurrency ARQ worker for the isolated Eval Queue."""

from __future__ import annotations

import asyncio
import os

from arq.connections import RedisSettings

from app.evaluation.queue import EVAL_QUEUE_NAME, REDIS_URL


async def eval_run_task(ctx, run_id: int):
    from app.services.evaluation_executor import (
        execute_eval_run,
        reconcile_interrupted_eval_run,
    )
    from app.worker import record_worker_heartbeat

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
