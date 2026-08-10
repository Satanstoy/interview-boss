"""Durable interview reprocessing submission helpers."""

from __future__ import annotations

import logging

from app.db.connection import get_db_connection
from app.services.job_lifecycle import (
    INTERVIEW_REPROCESS_JOB_TYPE,
    create_interview_reprocess_job,
    mark_job_dispatched,
)

logger = logging.getLogger("interview-boss")


async def submit_interview_reprocess_job(
    interview_id: int,
    user_id: int | None = None,
) -> dict:
    """Persist one reprocess request and best-effort enqueue it to ARQ.

    The returned ``jobs`` row is authoritative.  A Redis outage therefore
    yields ``pending`` rather than executing the LLM call in the web process.
    """

    def _create():
        with get_db_connection() as conn:
            job_id, status = create_interview_reprocess_job(
                conn, interview_id=interview_id, user_id=user_id
            )
            conn.commit()
            return job_id, status

    job_id, existing_status = _create()
    if existing_status in {"queued", "running"}:
        return {"job_id": job_id, "status": existing_status, "reused": True}

    try:
        from app.worker import enqueue_interview_reprocess_job

        arq_job = await enqueue_interview_reprocess_job(job_id)
        arq_job_id = getattr(arq_job, "job_id", None)
        if not arq_job_id:
            raise RuntimeError("ARQ 未返回 job_id")

        with get_db_connection() as conn:
            if not mark_job_dispatched(conn, job_id, str(arq_job_id)):
                raise RuntimeError(f"面经重分析任务不可再投递: job_id={job_id}")
            conn.commit()
        return {
            "job_id": job_id,
            "status": "queued",
            "arq_job_id": str(arq_job_id),
            "reused": False,
        }
    except Exception as exc:
        logger.warning(
            "面经重分析 ARQ 调度失败，任务保留 pending: job_id=%s, %s",
            job_id,
            exc,
        )
        return {
            "job_id": job_id,
            "status": "pending",
            "error": str(exc)[:200],
            "reused": False,
        }


def load_reprocess_job(job_id: int, user_id: int, is_admin: bool = False):
    """Load a reprocess job for the SSE adapter with ownership checks."""
    conn = get_db_connection()
    return conn.execute(
        "SELECT j.id, j.status, j.progress_current, j.progress_total, "
        "j.progress_message, j.result, j.error, j.created_by "
        "FROM jobs j WHERE j.id = ? AND j.job_type = ? "
        "AND (? = 1 OR j.created_by = ?)",
        (job_id, INTERVIEW_REPROCESS_JOB_TYPE, int(is_admin), user_id),
    ).fetchone()
