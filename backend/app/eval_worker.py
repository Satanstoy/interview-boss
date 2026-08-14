"""Low-concurrency ARQ worker for the isolated Eval Queue."""

from __future__ import annotations

from arq.connections import RedisSettings

from app.evaluation.queue import EVAL_QUEUE_NAME, REDIS_URL


async def eval_run_task(ctx, run_id: int):
    from app.services.evaluation_executor import execute_eval_run

    return await execute_eval_run(int(run_id))


async def startup(ctx):
    from app.db.connection import init_db

    init_db()


async def shutdown(ctx):
    return None


class EvalWorkerSettings:
    functions = [eval_run_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    queue_name = EVAL_QUEUE_NAME
    max_jobs = 1
    queue_read_limit = 1
    job_timeout = 3600
    max_tries = 1
    keep_result = 3600
