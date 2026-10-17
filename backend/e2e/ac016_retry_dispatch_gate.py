"""Classify durable public-contribution retry work for the AC-016 runner."""

import sqlite3
import sys


def retry_dispatch_state(conn: sqlite3.Connection, request_id: int) -> str:
    """Return the retry job state, including work completed before polling."""
    retry_job = conn.execute(
        "SELECT status FROM jobs WHERE job_type = 'cluster_batch' "
        "AND idempotency_key LIKE ? ORDER BY id DESC LIMIT 1",
        (f"retry:{request_id}:%",),
    ).fetchone()
    if retry_job is not None:
        if retry_job["status"] == "pending":
            return "pending"
        if retry_job["status"] in ("queued", "processing"):
            return "dispatched"
        if retry_job["status"] == "completed":
            return "completed"
        return "missing"

    # If an active rootless cluster window already owns the public queue, the
    # retry endpoint intentionally reuses it instead of inserting retry:<id>.
    # The queue row ties that shared job to this contribution request.
    active_job = conn.execute(
        "SELECT j.status FROM jobs j "
        "JOIN job_payloads p ON p.job_id = j.id "
        "WHERE j.job_type = 'cluster_batch' AND j.status IN ('pending', 'queued', 'processing') "
        "AND json_extract(p.payload, '$.queue_scope') = 'public_contribution' "
        "AND EXISTS (SELECT 1 FROM analysis_queue aq "
        "            WHERE aq.contribution_request_id = ? AND aq.status = 'pending') "
        "ORDER BY j.id DESC LIMIT 1",
        (request_id,),
    ).fetchone()
    if active_job is None:
        request = conn.execute(
            "SELECT status FROM public_contribution_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        return "completed" if request and request["status"] == "published" else "missing"
    return "pending" if active_job["status"] == "pending" else "dispatched"


if __name__ == "__main__":
    with sqlite3.connect("/app/backend/data/interview-boss.db") as connection:
        connection.row_factory = sqlite3.Row
        print(retry_dispatch_state(connection, int(sys.argv[1])))
