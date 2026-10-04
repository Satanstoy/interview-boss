"""Assert the durable AC-007 recovery and ownership trace after real worker work."""

from __future__ import annotations

import json
import sys
import time

from app.db.connection import get_db_connection


def main() -> None:
    import_id, checkpoint_hash = sys.argv[1:3]
    rootless_queue_id = int(sys.argv[3]) if len(sys.argv) > 3 else None
    rootless_interview_id = int(sys.argv[4]) if len(sys.argv) > 4 else None
    public_contribution_queue_id = int(sys.argv[5]) if len(sys.argv) > 5 else None
    if (rootless_queue_id is None) != (rootless_interview_id is None):
        raise SystemExit("rootless queue and interview IDs must be supplied together")
    if rootless_queue_id is not None:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            with get_db_connection() as conn:
                state = conn.execute(
                    "SELECT status FROM analysis_queue WHERE id = ?",
                    (rootless_queue_id,),
                ).fetchone()
            if state and state["status"] == "done":
                break
            time.sleep(1)

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
        rootless_trace = None
        public_contribution_trace = None
        if rootless_queue_id is not None:
            queue_rows = conn.execute(
                "SELECT aq.id, aq.status, aq.owner_id, aq.root_import_id, aq.interview_id, "
                "aq.question_detail_id, i.owner_id AS interview_owner_id, "
                "i.job_position AS interview_job_position, "
                "qd.import_id AS detail_import_id, qd.question "
                "FROM analysis_queue aq "
                "JOIN interview i ON i.id = aq.interview_id "
                "JOIN questions_detail qd ON qd.id = aq.question_detail_id "
                "WHERE aq.id = ?",
                (rootless_queue_id,),
            ).fetchall()
            if len(queue_rows) != 1:
                raise AssertionError("rootless retry must preserve exactly the original queue row")
            rootless = dict(queue_rows[0])
            if (
                rootless["status"] != "done"
                or int(rootless["interview_id"]) != rootless_interview_id
                or int(rootless["owner_id"]) != int(root_row["requester_id"])
                or int(rootless["interview_owner_id"]) != int(root_row["requester_id"])
                or rootless["root_import_id"] is not None
                or rootless["detail_import_id"] is not None
            ):
                raise AssertionError(f"rootless retry changed identity or scope: {rootless}")
            queue_for_interview = conn.execute(
                "SELECT id FROM analysis_queue WHERE interview_id = ?",
                (rootless_interview_id,),
            ).fetchall()
            if [int(row["id"]) for row in queue_for_interview] != [rootless_queue_id]:
                raise AssertionError("rootless retry created a duplicate queue row")
            linked_roots = conn.execute(
                "SELECT COUNT(*) FROM upload_imports WHERE interview_id = ?",
                (rootless_interview_id,),
            ).fetchone()[0]
            if linked_roots:
                raise AssertionError("rootless retry unexpectedly created an upload root")
            attempts_total = conn.execute("SELECT COUNT(*) FROM upload_attempts").fetchone()[0]
            if attempts_total != 2:
                raise AssertionError("rootless retry unexpectedly created an upload attempt")
            rootless_jobs = conn.execute(
                "SELECT id, status, root_import_id, upload_attempt_id, created_by "
                "FROM jobs WHERE job_type = 'cluster_batch' AND root_import_id IS NULL "
                "AND created_by = ? ORDER BY id",
                (int(root_row["requester_id"]),),
            ).fetchall()
            if len(rootless_jobs) != 1 or rootless_jobs[0]["status"] != "completed":
                raise AssertionError(
                    f"expected exactly one completed rootless worker job, got {[dict(row) for row in rootless_jobs]}"
                )
            if rootless_jobs[0]["upload_attempt_id"] is not None:
                raise AssertionError("rootless worker job must not reference an upload attempt")
            personal_clusters = conn.execute(
                "SELECT id, question, original_questions, original_question_sources, sources, "
                "owner_id, job_position FROM question_bank WHERE owner_id = ? "
                "AND job_position = ? ORDER BY id",
                (int(root_row["requester_id"]), rootless["interview_job_position"]),
            ).fetchall()
            matching_clusters = []
            for cluster_row in personal_clusters:
                cluster = dict(cluster_row)
                try:
                    original_questions = json.loads(cluster["original_questions"] or "[]")
                except (TypeError, json.JSONDecodeError):
                    original_questions = []
                if rootless["question"] == cluster["question"] or rootless["question"] in original_questions:
                    matching_clusters.append(cluster)
            if not matching_clusters:
                raise AssertionError(
                    "rootless retry did not preserve the question in the owner's private bank"
                )
            rootless_trace = {
                "queue_row": rootless,
                "worker_jobs": [dict(row) for row in rootless_jobs],
                "private_bank_clusters": matching_clusters,
                "upload_roots_linked": linked_roots,
                "upload_attempts_total": attempts_total,
            }

        if public_contribution_queue_id is not None:
            contribution_rows = conn.execute(
                "SELECT aq.id, aq.status AS queue_status, aq.owner_id, aq.root_import_id, "
                "aq.contribution_request_id, i.owner_id AS interview_owner_id, "
                "pcr.status AS request_status, pci.status AS item_status "
                "FROM analysis_queue aq "
                "JOIN interview i ON i.id = aq.interview_id "
                "JOIN public_contribution_requests pcr "
                "ON pcr.id = aq.contribution_request_id "
                "JOIN public_contribution_items pci ON pci.request_id = pcr.id "
                "WHERE aq.id = ?",
                (public_contribution_queue_id,),
            ).fetchall()
            if len(contribution_rows) != 1:
                raise AssertionError("expected one seeded public contribution queue row")
            contribution = dict(contribution_rows[0])
            if (
                contribution["queue_status"] != "failed"
                or contribution["owner_id"] is not None
                or contribution["interview_owner_id"] is not None
                or contribution["root_import_id"] is not None
                or contribution["request_status"] != "failed"
                or contribution["item_status"] != "failed"
            ):
                raise AssertionError(
                    f"personal retry changed the public contribution state: {contribution}"
                )
            public_contribution_trace = contribution

        print(json.dumps({
            "root": root,
            "attempts": [dict(row) for row in attempts],
            "checkpoint": checkpoint,
            "classification_checkpoint": classify_checkpoint,
            "attempt_two_jobs": attempt_two_jobs,
            "private_interview": dict(interview),
            "upload_llm_calls": [dict(row) for row in llm_calls],
            "rootless_retry": rootless_trace,
            "public_contribution_exclusion": public_contribution_trace,
        }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
