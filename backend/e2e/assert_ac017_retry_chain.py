"""Capture the real retry responses against the seeded A/B/C attempt family."""

from __future__ import annotations

import json
import sys

from app.db.connection import get_db_connection


def capture() -> dict:
    with get_db_connection() as conn:
        root = conn.execute(
            "SELECT id, requester_id, status, current_attempt_no, revision "
            "FROM upload_imports WHERE id = 'imp-ac017-cross-generation-retry'"
        ).fetchone()
        if root is None:
            raise AssertionError("AC-017 root is missing")
        attempts = conn.execute(
            "SELECT id, attempt_no, status, requested_by FROM upload_attempts "
            "WHERE import_id = ? ORDER BY attempt_no",
            (root["id"],),
        ).fetchall()
        jobs = conn.execute(
            "SELECT id, parent_job_id, job_type, status, upload_attempt_id, work_key "
            "FROM jobs WHERE root_import_id = ? ORDER BY id",
            (root["id"],),
        ).fetchall()
        extract = conn.execute(
            "SELECT status, result_json, output_hash, job_id FROM upload_stage_results "
            "WHERE import_id = ? AND stage = 'extract' AND unit_key = 'document'",
            (root["id"],),
        ).fetchone()
        classify = conn.execute(
            "SELECT status, error_code, retryable, job_id FROM upload_stage_results "
            "WHERE import_id = ? AND stage = 'classify' AND unit_key = 'question-batch'",
            (root["id"],),
        ).fetchone()
        duplicate_active = conn.execute(
            "SELECT work_key, COUNT(*) AS count FROM jobs WHERE root_import_id = ? "
            "AND status IN ('pending','queued','running') AND work_key IS NOT NULL "
            "GROUP BY work_key HAVING COUNT(*) > 1",
            (root["id"],),
        ).fetchall()
    if (root["status"], int(root["current_attempt_no"])) != ("partial_failed", 3):
        raise AssertionError(f"root changed during old-ID retry: {dict(root)}")
    if [(int(row["attempt_no"]), row["status"]) for row in attempts] != [
        (1, "failed"),
        (2, "failed"),
        (3, "active"),
    ]:
        raise AssertionError(f"expected failed A/B and active C: {[dict(row) for row in attempts]}")
    if len(jobs) != 3 or [row["status"] for row in jobs] != ["failed", "failed", "queued"]:
        raise AssertionError(f"unexpected A/B/C job states: {[dict(row) for row in jobs]}")
    if not extract or extract["status"] != "succeeded" or not extract["output_hash"]:
        raise AssertionError("successful extraction checkpoint is missing")
    if not classify or classify["status"] != "failed" or classify["retryable"] != 1:
        raise AssertionError("the failed classification checkpoint was not retained")
    if duplicate_active:
        raise AssertionError(f"duplicate active work keys after retries: {[dict(row) for row in duplicate_active]}")
    return {
        "root": dict(root),
        "attempts": [dict(row) for row in attempts],
        "jobs": [dict(row) for row in jobs],
        "success_checkpoint": dict(extract),
        "failed_checkpoint": dict(classify),
        "duplicate_active_work_keys": [],
    }


if __name__ == "__main__":
    trace = capture()
    print(json.dumps(trace, ensure_ascii=False, indent=2))
    if len(sys.argv) > 1:
        with open(sys.argv[1], "w", encoding="utf-8") as stream:
            json.dump(trace, stream, ensure_ascii=False, indent=2)
