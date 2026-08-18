"""Dedicated Redis/ARQ transport for evaluation runs."""

from __future__ import annotations

import os

from arq.connections import RedisSettings

from app.core.config import build_redis_url

EVAL_QUEUE_NAME = os.environ.get("EVAL_QUEUE_NAME", "arq:eval")
REDIS_URL = build_redis_url(
    os.environ.get("REDIS_QUEUE_URL") or os.environ.get("REDIS_URL"),
    f"redis://{os.environ.get('REDIS_HOST', 'localhost')}:6379/0",
)


async def _get_eval_redis_pool():
    from arq.connections import create_pool

    return await create_pool(RedisSettings.from_dsn(REDIS_URL))


async def enqueue_eval_run_job(run_id: int, *, job_id: str | None = None):
    """Queue one durable Eval Run on the isolated queue.

    ``job_id`` defaults to a stable per-run id, but re-dispatching an already
    executed Run (e.g. retry-failed) MUST pass a fresh id: ARQ treats the job
    id as a unique key and keeps the result for ``keep_result`` (1h), so
    reusing "eval-run-{run_id}" within that window makes ``enqueue_job``
    return None and the retry would be silently dropped.
    """
    pool = await _get_eval_redis_pool()
    try:
        return await pool.enqueue_job(
            "eval_run_task",
            run_id,
            _queue_name=EVAL_QUEUE_NAME,
            _job_id=job_id or f"eval-run-{run_id}",
        )
    finally:
        await pool.close()
