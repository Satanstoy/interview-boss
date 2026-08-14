"""Database-owned lifecycle for long-running ARQ-backed application jobs.

The ``jobs`` row is the durable outbox and execution state.  Redis/ARQ is only
the delivery mechanism, so enqueue races, worker restarts and process crashes
can be recovered by a later dispatcher run.
"""

from __future__ import annotations

import os
import socket
import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

SUBMIT_IMPORT_JOB_TYPE = "submit_import"
ANSWER_GENERATION_JOB_TYPE = "generate_answer"
ANSWER_BATCH_JOB_TYPE = "generate_answer_batch"
CLUSTER_BATCH_JOB_TYPE = "cluster_batch"
CLUSTER_REBUILD_JOB_TYPE = "cluster_rebuild"
INTERVIEW_REPROCESS_JOB_TYPE = "reprocess_interview"
BUILD_MASTER_BANK_JOB_TYPE = "build_master_bank"
RECOMPUTE_EMBEDDING_JOB_TYPE = "recompute_embedding"
RECITATION_GENERATION_JOB_TYPE = "generate_recitation"
QUALITY_REVIEW_SCAN_JOB_TYPE = "quality_review_scan"
INTERVIEW_IMPORT_ANALYSIS_JOB_TYPE = "interview_import_analysis"
DISPATCHABLE_JOB_TYPES = (
    SUBMIT_IMPORT_JOB_TYPE,
    ANSWER_GENERATION_JOB_TYPE,
    CLUSTER_BATCH_JOB_TYPE,
    CLUSTER_REBUILD_JOB_TYPE,
    INTERVIEW_REPROCESS_JOB_TYPE,
    BUILD_MASTER_BANK_JOB_TYPE,
    RECOMPUTE_EMBEDDING_JOB_TYPE,
    RECITATION_GENERATION_JOB_TYPE,
    QUALITY_REVIEW_SCAN_JOB_TYPE,
    INTERVIEW_IMPORT_ANALYSIS_JOB_TYPE,
)


def create_cluster_rebuild_job(conn, user_id: int | None = None) -> tuple[int, str]:
    """Create or reuse the single durable full-cluster rebuild job.

    A rebuild consumes the shared analysis queue, so overlapping rebuilds would
    compete for the same rows and make progress difficult to explain.  Keep one
    active job globally and let the dispatcher recover it when Redis is down.
    """
    existing = conn.execute(
        "SELECT id, status FROM jobs WHERE job_type = ? "
        "AND status IN ('pending', 'queued', 'running') ORDER BY id LIMIT 1",
        (CLUSTER_REBUILD_JOB_TYPE,),
    ).fetchone()
    if existing:
        return int(existing["id"]), str(existing["status"])

    pending = conn.execute(
        "SELECT COUNT(*) AS c FROM analysis_queue WHERE status IN ('pending', 'processing')"
    ).fetchone()["c"]
    cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, progress_total, created_by, idempotency_key) "
        "VALUES (?, 'pending', ?, ?, ?)",
        (
            CLUSTER_REBUILD_JOB_TYPE,
            max(int(pending), 1),
            user_id,
            f"cluster-rebuild:{uuid4().hex}",
        ),
    )
    job_id = int(cursor.lastrowid)
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (job_id, json.dumps({"user_id": user_id}, ensure_ascii=False)),
    )
    return job_id, "pending"


def create_quality_review_scan_job(
    conn,
    user_id: int | None = None,
    mismerge_limit: int = 1000,
    singleton_limit: int = 1000,
    candidate_limit: int = 3,
    similarity_threshold: float = 0.30,
) -> tuple[int, str, bool]:
    """Create or reuse one durable full quality-review scan.

    The scan is intentionally global: it only evaluates the public question
    bank, so an active scan is shared by administrators.  A completed scan
    does not block the next manual run; only pending/queued/running scans are
    reused.
    """
    existing = conn.execute(
        "SELECT id, status FROM jobs WHERE job_type = ? "
        "AND status IN ('pending', 'queued', 'running') ORDER BY id DESC LIMIT 1",
        (QUALITY_REVIEW_SCAN_JOB_TYPE,),
    ).fetchone()
    if existing:
        return int(existing["id"]), str(existing["status"]), True

    payload = {
        "user_id": user_id,
        "mismerge_limit": max(1, min(int(mismerge_limit), 5000)),
        "singleton_limit": max(1, min(int(singleton_limit), 5000)),
        "candidate_limit": max(1, min(int(candidate_limit), 10)),
        "similarity_threshold": max(0.0, min(float(similarity_threshold), 1.0)),
    }
    cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, progress_total, created_by, idempotency_key) "
        "VALUES (?, 'pending', 2, ?, ?)",
        (QUALITY_REVIEW_SCAN_JOB_TYPE, user_id, f"quality-review:{uuid4().hex}"),
    )
    job_id = int(cursor.lastrowid)
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (job_id, json.dumps(payload, ensure_ascii=False)),
    )
    return job_id, "pending", False


def create_interview_reprocess_job(
    conn,
    interview_id: int,
    user_id: int | None = None,
) -> tuple[int, str]:
    """Create or reuse a durable job for reprocessing one interview."""
    existing = conn.execute(
        "SELECT j.id, j.status FROM jobs j "
        "JOIN job_payloads p ON p.job_id = j.id "
        "WHERE j.job_type = ? AND j.status IN ('pending', 'queued', 'running') "
        "AND json_extract(p.payload, '$.interview_id') = ? "
        "ORDER BY j.id DESC LIMIT 1",
        (INTERVIEW_REPROCESS_JOB_TYPE, interview_id),
    ).fetchone()
    if existing:
        return int(existing["id"]), str(existing["status"])

    cursor = conn.execute(
        "INSERT INTO jobs (job_type, status, progress_total, created_by, idempotency_key) "
        "VALUES (?, 'pending', 1, ?, ?)",
        (
            INTERVIEW_REPROCESS_JOB_TYPE,
            user_id,
            f"reprocess-interview:{interview_id}:{uuid4().hex}",
        ),
    )
    job_id = int(cursor.lastrowid)
    conn.execute(
        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (
            job_id,
            json.dumps(
                {"interview_id": interview_id, "user_id": user_id},
                ensure_ascii=False,
            ),
        ),
    )
    return job_id, "pending"


def create_interview_import_analysis_job(
    conn,
    import_id: str,
    user_id: int,
    attempt: int,
    parent_job_id: int | None = None,
) -> tuple[int, str]:
    """Create one durable analysis attempt for an external interview import."""
    idempotency_key = f"interview-import:{import_id}:analysis:{int(attempt)}"
    conn.execute(
        "INSERT OR IGNORE INTO jobs "
        "(job_type, status, progress_total, created_by, idempotency_key, parent_job_id) "
        "VALUES (?, 'pending', 1, ?, ?, ?)",
        (
            INTERVIEW_IMPORT_ANALYSIS_JOB_TYPE,
            int(user_id),
            idempotency_key,
            parent_job_id,
        ),
    )
    row = conn.execute(
        "SELECT id, status FROM jobs WHERE job_type = ? AND idempotency_key = ?",
        (INTERVIEW_IMPORT_ANALYSIS_JOB_TYPE, idempotency_key),
    ).fetchone()
    if not row:
        raise RuntimeError(f"面试导入分析任务创建失败: import_id={import_id}")
    job_id = int(row["id"])
    conn.execute(
        "INSERT OR IGNORE INTO job_payloads (job_id, payload) VALUES (?, ?)",
        (
            job_id,
            json.dumps(
                {"import_id": import_id, "user_id": int(user_id)},
                ensure_ascii=False,
            ),
        ),
    )
    return job_id, str(row["status"])
DISPATCH_LEASE_SECONDS = 300
WORKER_LEASE_SECONDS = 1800
MAX_JOB_ATTEMPTS = 3


def create_answer_generation_jobs(
    conn,
    parent_job_id: int,
    answer_tasks: list[tuple[int, str]],
    user_id: int | None,
    skip_search: bool = False,
    llm_scope: str = "user",
    search_scope: str = "user",
) -> list[int]:
    """Persist one idempotent answer job per newly imported question."""
    job_ids: list[int] = []
    for question_id, question_text in answer_tasks:
        idempotency_key = f"submit:{parent_job_id}:answer:{question_id}"
        conn.execute(
            "INSERT OR IGNORE INTO jobs "
            "(job_type, status, progress_total, created_by, idempotency_key) "
            "VALUES (?, 'pending', 1, ?, ?)",
            (ANSWER_GENERATION_JOB_TYPE, user_id, idempotency_key),
        )
        row = conn.execute(
            "SELECT id FROM jobs WHERE job_type = ? AND idempotency_key = ?",
            (ANSWER_GENERATION_JOB_TYPE, idempotency_key),
        ).fetchone()
        if not row:
            raise RuntimeError(
                f"答案任务创建失败: parent_job_id={parent_job_id}, "
                f"question_id={question_id}"
            )
        answer_job_id = int(row["id"])
        conn.execute(
            "INSERT OR IGNORE INTO job_payloads (job_id, payload) VALUES (?, ?)",
            (
                answer_job_id,
                json.dumps(
                    {
                        "question_id": question_id,
                        "question_text": question_text,
                        "user_id": user_id,
                        "parent_job_id": parent_job_id,
                        "skip_search": skip_search,
                        "llm_scope": llm_scope,
                        "search_scope": search_scope,
                    },
                    ensure_ascii=False,
                ),
            ),
        )
        job_ids.append(answer_job_id)
    return job_ids


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


def default_worker_id() -> str:
    return f"{socket.gethostname()}:{os.getpid()}"


def recover_expired_jobs(conn, job_type: str = SUBMIT_IMPORT_JOB_TYPE) -> int:
    """Return queued/running jobs whose lease expired to durable pending."""
    cur = conn.execute(
        "UPDATE jobs SET status = 'pending', locked_until = NULL, arq_job_id = NULL, "
        "worker_id = NULL, available_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
        "WHERE job_type = ? AND status IN ('queued', 'running') "
        "AND locked_until IS NOT NULL AND locked_until < CURRENT_TIMESTAMP",
        (job_type,),
    )
    return cur.rowcount


def claim_dispatch_batch(
    conn,
    job_type: str = SUBMIT_IMPORT_JOB_TYPE,
    limit: int = 10,
    lease_seconds: int = DISPATCH_LEASE_SECONDS,
) -> list[dict]:
    """Reserve due pending jobs before attempting ARQ enqueue."""
    recover_expired_jobs(conn, job_type)
    rows = conn.execute(
        "SELECT id, job_type, attempts, available_at "
        "FROM jobs WHERE job_type = ? AND status = 'pending' "
        "AND available_at <= CURRENT_TIMESTAMP "
        "ORDER BY created_at, id LIMIT ?",
        (job_type, limit),
    ).fetchall()
    reserved = []
    for row in rows:
        cur = conn.execute(
            "UPDATE jobs SET status = 'queued', locked_until = "
            f"datetime('now', '+{int(lease_seconds)} seconds'), updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status = 'pending'",
            (row["id"],),
        )
        if cur.rowcount:
            reserved.append(dict(row))
    return reserved


def mark_job_dispatched(
    conn,
    job_id: int,
    arq_job_id: str,
    lease_seconds: int = DISPATCH_LEASE_SECONDS,
) -> bool:
    """Record a successful ARQ enqueue without claiming worker execution."""
    cur = conn.execute(
        "UPDATE jobs SET status = 'queued', arq_job_id = ?, "
        "locked_until = "
        f"datetime('now', '+{int(lease_seconds)} seconds'), updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND status IN ('pending', 'queued')",
        (str(arq_job_id), job_id),
    )
    return bool(cur.rowcount)


def mark_dispatch_failed(conn, job_id: int, error: str) -> None:
    """Make an enqueue failure visible and retryable by the next dispatcher."""
    conn.execute(
        "UPDATE jobs SET status = 'pending', arq_job_id = NULL, locked_until = NULL, "
        "worker_id = NULL, available_at = datetime('now', '+30 seconds'), "
        "last_error = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND status = 'queued'",
        (str(error)[:500], job_id),
    )


def claim_job(
    conn,
    job_id: int,
    worker_id: str,
    job_type: str = SUBMIT_IMPORT_JOB_TYPE,
    lease_seconds: int = WORKER_LEASE_SECONDS,
):
    """Atomically let one worker own a queued job."""
    cur = conn.execute(
        "UPDATE jobs SET status = 'running', attempts = attempts + 1, "
        "started_at = COALESCE(started_at, CURRENT_TIMESTAMP), worker_id = ?, "
        "locked_until = "
        f"datetime('now', '+{int(lease_seconds)} seconds'), updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND job_type = ? AND status IN ('pending', 'queued')",
        (worker_id, job_id, job_type),
    )
    if not cur.rowcount:
        return None
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def touch_job(
    conn,
    job_id: int,
    worker_id: str,
    progress_current: int | None = None,
    progress_total: int | None = None,
    progress_message: str | None = None,
    lease_seconds: int = WORKER_LEASE_SECONDS,
) -> bool:
    """Refresh the worker lease and optionally persist visible progress."""
    fields = [
        "locked_until = "
        f"datetime('now', '+{int(lease_seconds)} seconds')",
        "updated_at = CURRENT_TIMESTAMP",
    ]
    params: list[Any] = []
    if progress_current is not None:
        fields.append("progress_current = ?")
        params.append(progress_current)
    if progress_total is not None:
        fields.append("progress_total = ?")
        params.append(progress_total)
    if progress_message is not None:
        fields.append("progress_message = ?")
        params.append(progress_message)
    params.extend([job_id, worker_id])
    cur = conn.execute(
        "UPDATE jobs SET status = 'running', " + ", ".join(fields) +
        " WHERE id = ? AND worker_id = ? AND status = 'running'",
        params,
    )
    return bool(cur.rowcount)


def complete_job(
    conn,
    job_id: int,
    worker_id: str,
    result: str | None = None,
) -> bool:
    cur = conn.execute(
        "UPDATE jobs SET status = 'completed', result = ?, error = NULL, "
        "last_error = NULL, locked_until = NULL, worker_id = NULL, "
        "completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ? AND worker_id = ? AND status = 'running'",
        (result, job_id, worker_id),
    )
    return bool(cur.rowcount)


def fail_job(
    conn,
    job_id: int,
    worker_id: str,
    error: str,
    max_attempts: int = MAX_JOB_ATTEMPTS,
) -> dict:
    """Retry through the DB dispatcher, or make the job terminally failed."""
    row = conn.execute(
        "SELECT attempts FROM jobs WHERE id = ? AND worker_id = ?", (job_id, worker_id)
    ).fetchone()
    attempts = int(row["attempts"] or 0) if row else max_attempts
    message = str(error)[:500]
    if attempts < max_attempts:
        delay = min(3600, 2 ** max(0, attempts - 1) * 30)
        conn.execute(
            "UPDATE jobs SET status = 'pending', error = NULL, last_error = ?, "
            "available_at = datetime('now', ?), locked_until = NULL, "
            "arq_job_id = NULL, worker_id = NULL, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND worker_id = ?",
            (message, f"+{delay} seconds", job_id, worker_id),
        )
        return {"status": "retrying", "attempts": attempts}

    conn.execute(
        "UPDATE jobs SET status = 'failed', error = ?, last_error = ?, "
        "locked_until = NULL, worker_id = NULL, completed_at = CURRENT_TIMESTAMP, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND worker_id = ?",
        (message, message, job_id, worker_id),
    )
    return {"status": "failed", "attempts": attempts}
