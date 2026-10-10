"""Durable credential preflight ARQ handler."""

import asyncio
import logging

logger = logging.getLogger("interview-boss")


async def credential_preflight_task(ctx, job_id: int):
    """R01：凭据预检 ARQ 任务——真实 provider 探测，失败阻塞提取派发。"""

    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        claim_job_with_generation,
        JobFenceError,
        complete_job,
        default_worker_id,
        fail_job,
    )
    from app.services.credential_preflight import run_credential_preflight

    worker_id = default_worker_id()

    def _claim():
        with get_db_connection() as conn:
            task = claim_job_with_generation(
                conn, job_id, worker_id=worker_id, job_type="credential_preflight"
            )
            conn.commit()
            return dict(task) if task else None

    claimed = await asyncio.to_thread(_claim)
    if not claimed:
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    def _run_preflight():
        with get_db_connection() as conn:
            outcome = run_credential_preflight(conn, job_id=job_id, lease_generation=int(claimed["lease_generation"]))
            if outcome.status == "ok":
                complete_job(conn, job_id, worker_id, result="preflight ok")
            else:
                fail_job(
                    conn,
                    job_id,
                    worker_id,
                    f"{outcome.error_code}: {outcome.message}",
                    max_attempts=1,
                )
            conn.commit()
            return outcome

    try:
        outcome = await asyncio.to_thread(_run_preflight)
    except JobFenceError:
        return {"job_id": job_id, "status": "stale", "error_code": None}
    logger.info(
        "凭据预检完成: job_id=%s scope=%s status=%s",
        job_id,
        "credential",
        outcome.status,
    )
    if outcome.status == "ok":
        # 预检在上面的事务中创建首个业务 job。立刻尝试持久化 handoff，
        # 避免新上传只能等待周期 dispatcher；投递失败仍可由 cron 补偿。
        from app.worker_scheduled import scheduled_submit_job_dispatch_task

        await scheduled_submit_job_dispatch_task(ctx)
    return {"job_id": job_id, "status": outcome.status, "error_code": outcome.error_code}
