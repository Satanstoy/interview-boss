"""Assert the durable AC-007 recovery and ownership trace after real worker work."""

from __future__ import annotations

import json
import sys

from app.db.connection import get_db_connection


def main() -> None:
    import_id, checkpoint_hash = sys.argv[1:3]
    with get_db_connection() as conn:
        root_row = conn.execute(
            "SELECT id, requester_id, status, interview_id, current_attempt_no "
            "FROM upload_imports WHERE id = ?",
            (import_id,),
        ).fetchone()
        if root_row is None:
            raise AssertionError("the retried root disappeared")
        root = dict(root_row)
        if root["status"] != "completed" or not root["interview_id"]:
            raise AssertionError(f"expected a completed private result, got {root}")
        if int(root["current_attempt_no"]) != 2:
            raise AssertionError("concurrent owner clicks created an unexpected attempt number")

        attempts = conn.execute(
            "SELECT id, attempt_no, status, requested_by FROM upload_attempts "
            "WHERE import_id = ? ORDER BY attempt_no",
            (import_id,),
        ).fetchall()
        if len(attempts) != 2 or int(attempts[1]["attempt_no"]) != 2:
            raise AssertionError(f"expected exactly attempts 1 and 2, got {[dict(row) for row in attempts]}")
        if int(attempts[1]["requested_by"]) != int(root["requester_id"]):
            raise AssertionError("the recovery actor is not the owning user")
        if attempts[1]["status"] != "completed":
            raise AssertionError("the recovered attempt did not reach its terminal success state")

        checkpoint_rows = conn.execute(
            "SELECT id, status, output_hash, job_id FROM upload_stage_results "
            "WHERE import_id = ? AND stage = 'extract' AND unit_key = 'document' "
            "AND input_version = 1",
            (import_id,),
        ).fetchall()
        if len(checkpoint_rows) != 1:
            raise AssertionError("extract checkpoint was duplicated during recovery")
        checkpoint = dict(checkpoint_rows[0])
        if checkpoint["status"] != "succeeded" or checkpoint["output_hash"] != checkpoint_hash:
            raise AssertionError("successful extraction checkpoint changed during recovery")

        classify_rows = conn.execute(
            "SELECT id, status, result_json, output_hash, error_code, retryable, job_id "
            "FROM upload_stage_results WHERE import_id = ? AND stage = 'classify' "
            "AND unit_key = 'question-batch' AND input_version = 1",
            (import_id,),
        ).fetchall()
        if len(classify_rows) != 1:
            raise AssertionError("classification retry duplicated its stable checkpoint")
        classify_checkpoint = dict(classify_rows[0])
        classify_result = json.loads(classify_checkpoint["result_json"] or "{}")
        if (
            classify_checkpoint["status"] != "succeeded"
            or classify_checkpoint["error_code"] is not None
            or int(classify_checkpoint["retryable"] or 0) != 0
            or not classify_result.get("tagged_rows")
        ):
            raise AssertionError("the failed classification checkpoint was not recovered")

        jobs = conn.execute(
            "SELECT id, job_type, status, upload_attempt_id, work_key, created_by "
            "FROM jobs WHERE root_import_id = ? ORDER BY id",
            (import_id,),
        ).fetchall()
        attempt_two_jobs = [
            dict(row) for row in jobs if row["upload_attempt_id"] == attempts[1]["id"]
        ]
        incomplete_jobs = [
            row for row in attempt_two_jobs if row["status"] != "completed"
        ]
        if incomplete_jobs:
            raise AssertionError(
                f"the recovered attempt still has unfinished jobs: {incomplete_jobs}"
            )
        if sum(row["job_type"] == "credential_preflight" for row in attempt_two_jobs) != 1:
            raise AssertionError("retry must create exactly one attempt-2 credential preflight")
        if sum(row["job_type"] == "submit_import" for row in attempt_two_jobs) != 1:
            raise AssertionError("retry must create exactly one attempt-2 submit job")

        unresolved_stages = [
            dict(row) for row in conn.execute(
                "SELECT stage, unit_key, status, error_code FROM upload_stage_results "
                "WHERE import_id = ? AND status IN ('pending','running','failed','needs_action')",
                (import_id,),
            ).fetchall()
        ]
        if unresolved_stages:
            raise AssertionError(f"the completed root still has unresolved stages: {unresolved_stages}")

        interview = conn.execute(
            "SELECT id, owner_id, publish_status FROM interview WHERE id = ?",
            (root["interview_id"],),
        ).fetchone()
        if interview is None or int(interview["owner_id"]) != int(root["requester_id"]):
            raise AssertionError("owner retry wrote a result outside the owner's private scope")

        llm_calls = conn.execute(
            "SELECT stage, unit_key, status FROM upload_llm_calls "
            "WHERE root_import_id = ? ORDER BY id",
            (import_id,),
        ).fetchall()
        print(json.dumps({
            "root": root,
            "attempts": [dict(row) for row in attempts],
            "checkpoint": checkpoint,
            "classification_checkpoint": classify_checkpoint,
            "attempt_two_jobs": attempt_two_jobs,
            "private_interview": dict(interview),
            "upload_llm_calls": [dict(row) for row in llm_calls],
        }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
