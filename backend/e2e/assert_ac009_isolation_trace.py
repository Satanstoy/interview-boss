"""Assert database ownership, lineage, and worker separation for AC-009."""

from __future__ import annotations

import json
import sys

from app.db.connection import get_db_connection


CASES = (
    {
        "marker": "AC009_USER_A_REAL_STACK",
        "other_marker": "AC009_USER_B_REAL_STACK",
        "other_question": "AC009_USER_B 专属问题：解释消息幂等。",
        "answer_marker": "AC009_USER_A_ANSWER",
        "other_answer_marker": "AC009_USER_B_ANSWER",
        "question": "AC009_USER_A 专属问题：解释事务隔离。",
        "company": "AC009_USER_A 公司",
    },
    {
        "marker": "AC009_USER_B_REAL_STACK",
        "other_marker": "AC009_USER_A_REAL_STACK",
        "other_question": "AC009_USER_A 专属问题：解释事务隔离。",
        "answer_marker": "AC009_USER_B_ANSWER",
        "other_answer_marker": "AC009_USER_A_ANSWER",
        "question": "AC009_USER_B 专属问题：解释消息幂等。",
        "company": "AC009_USER_B 公司",
    },
)


def main() -> None:
    import_a, import_b, username_a, username_b = sys.argv[1:5]
    if import_a == import_b or username_a == username_b:
        raise AssertionError("the owners and roots must be distinct")

    evidence = []
    preflight_worker_ids = set()
    submit_start_seconds = []
    with get_db_connection() as conn:
        for import_id, username, case in zip(
            (import_a, import_b), (username_a, username_b), CASES
        ):
            owner = conn.execute(
                "SELECT id FROM users WHERE username = ?", (username,)
            ).fetchone()
            if owner is None:
                raise AssertionError(f"missing owner {username}")
            owner_id = int(owner["id"])
            root_row = conn.execute(
                "SELECT id, requester_id, status, current_attempt_no, created_at, interview_id, "
                "payload_json "
                "FROM upload_imports WHERE id = ?",
                (import_id,),
            ).fetchone()
            if root_row is None:
                raise AssertionError(f"missing root {import_id}")
            root = dict(root_row)
            if (
                int(root["requester_id"]) != owner_id
                or root["status"] != "completed"
                or int(root["current_attempt_no"]) != 1
                or root["created_at"] != "2026-10-04 12:00:00"
                or not root["interview_id"]
                or case["marker"] not in (root["payload_json"] or "")
                or case["other_marker"] in (root["payload_json"] or "")
            ):
                raise AssertionError(f"root ownership/status/timestamp mismatch: {root}")

            attempt_rows = conn.execute(
                "SELECT id, attempt_no, status, requested_by FROM upload_attempts "
                "WHERE import_id = ? ORDER BY attempt_no",
                (import_id,),
            ).fetchall()
            if (
                len(attempt_rows) != 1
                or int(attempt_rows[0]["attempt_no"]) != 1
                or attempt_rows[0]["status"] != "completed"
                or int(attempt_rows[0]["requested_by"]) != owner_id
            ):
                raise AssertionError(f"unexpected attempt lineage for {import_id}")

            interview_row = conn.execute(
                "SELECT id, url, company, round, questions_list, owner_id, status, publish_status "
                "FROM interview WHERE id = ?",
                (root["interview_id"],),
            ).fetchone()
            if interview_row is None:
                raise AssertionError(f"result interview missing for {import_id}")
            interview = dict(interview_row)
            if (
                int(interview["owner_id"]) != owner_id
                or interview["company"] != case["company"]
                or case["question"] not in (interview["questions_list"] or "")
                or interview["publish_status"] != "published"
            ):
                raise AssertionError(f"interview content/scope mismatch: {interview}")

            detail_rows = conn.execute(
                "SELECT d.id, d.interview_id, d.import_id, d.source_ordinal, d.url, d.company, "
                "d.round, d.question, d.answer, i.owner_id AS interview_owner_id "
                "FROM questions_detail d JOIN interview i ON i.id = d.interview_id "
                "WHERE d.import_id = ? ORDER BY d.source_ordinal",
                (import_id,),
            ).fetchall()
            if len(detail_rows) != 1:
                raise AssertionError(f"expected one source detail for {import_id}")
            detail = dict(detail_rows[0])
            if (
                int(detail["interview_id"]) != int(root["interview_id"])
                or int(detail["interview_owner_id"]) != owner_id
                or int(detail["source_ordinal"] or 0) != (101 if case["marker"].endswith("A_REAL_STACK") else 202)
                or detail["company"] != case["company"]
                or detail["question"] != case["question"]
                or case["other_question"] in (detail["question"] or "")
            ):
                raise AssertionError(f"detail lineage/content mismatch: {detail}")

            resolution_rows = conn.execute(
                "SELECT r.id, r.detail_id, r.occurrence_scope, r.occurrence_owner_id, "
                "r.canonical_id, r.canonical_scope, r.status, q.owner_id AS canonical_owner_id, "
                "q.question AS canonical_question, q.ai_answer, q.sources "
                "FROM question_resolutions r LEFT JOIN question_bank q ON q.id = r.canonical_id "
                "WHERE r.detail_id = ? AND r.invalidated_at IS NULL",
                (detail["id"],),
            ).fetchall()
            if len(resolution_rows) != 1:
                raise AssertionError(f"expected one current resolution for detail {detail['id']}")
            resolution = dict(resolution_rows[0])
            if (
                resolution["occurrence_scope"] != "private"
                or int(resolution["occurrence_owner_id"]) != owner_id
                or resolution["canonical_id"] is None
                or resolution["canonical_scope"] != "private"
                or resolution["status"] not in {"created", "matched"}
                or int(resolution["canonical_owner_id"]) != owner_id
                or resolution["canonical_question"] != case["question"]
                or case["answer_marker"] not in (resolution["ai_answer"] or "")
                or case["other_answer_marker"] in (resolution["ai_answer"] or "")
            ):
                raise AssertionError(f"resolution/canonical/answer scope mismatch: {resolution}")
            sources = json.loads(resolution["sources"] or "[]")
            if not any(
                source.get("company") == case["company"]
                and source.get("round") == interview["round"]
                for source in sources
                if isinstance(source, dict)
            ):
                raise AssertionError(f"canonical source does not point to this interview: {sources}")

            jobs = [
                dict(row)
                for row in conn.execute(
                    "SELECT id, job_type, status, worker_id, upload_attempt_id, work_key, "
                    "created_by, started_at "
                    "FROM jobs WHERE root_import_id = ? ORDER BY id",
                    (import_id,),
                ).fetchall()
            ]
            submit_jobs = [
                job for job in jobs
                if job["job_type"] == "submit_import" and job["status"] == "completed"
            ]
            if len(submit_jobs) != 1:
                raise AssertionError(f"expected one completed submit job: {jobs}")
            if int(submit_jobs[0]["upload_attempt_id"]) != int(attempt_rows[0]["id"]):
                raise AssertionError("submit job was attached to another attempt")
            if not submit_jobs[0]["started_at"]:
                raise AssertionError("submit job has no durable worker start time")
            submit_start_seconds.append(submit_jobs[0]["started_at"][:19])
            preflight_jobs = [
                job for job in jobs
                if job["job_type"] == "credential_preflight" and job["status"] == "completed"
            ]
            if len(preflight_jobs) != 1 or not preflight_jobs[0]["worker_id"]:
                raise AssertionError(f"expected one completed preflight with a durable worker id: {jobs}")
            preflight_worker_ids.add(preflight_jobs[0]["worker_id"])
            answer_jobs = [
                job for job in jobs
                if job["job_type"] == "generate_answer" and job["status"] == "completed"
            ]
            if len(answer_jobs) != 1 or int(answer_jobs[0]["created_by"]) != owner_id:
                raise AssertionError(f"answer work is not owned by the upload owner: {jobs}")
            if int(answer_jobs[0]["upload_attempt_id"]) != int(attempt_rows[0]["id"]):
                raise AssertionError("answer job was attached to another attempt")

            stage_rows = [
                dict(row)
                for row in conn.execute(
                    "SELECT stage, unit_key, status, job_id FROM upload_stage_results "
                    "WHERE import_id = ? ORDER BY stage, unit_key",
                    (import_id,),
                ).fetchall()
            ]
            failed_stages = [
                row for row in stage_rows
                if row["status"] in {"failed", "needs_action", "running", "pending"}
            ]
            if failed_stages:
                raise AssertionError(f"completed root has unfinished stages: {failed_stages}")
            evidence.append({
                "root": root,
                "owner": {"username": username, "id": owner_id},
                "attempt": dict(attempt_rows[0]),
                "interview": interview,
                "detail": detail,
                "resolution": resolution,
                "jobs": jobs,
                "stages": stage_rows,
            })

        if len(preflight_worker_ids) != 2:
            raise AssertionError(
                f"both independent workers must claim one root each: {sorted(preflight_worker_ids)}"
            )
        overlap = json.load(sys.stdin)
        if overlap != {"markers": sorted(case["marker"] for case in CASES),
                       "passes": 2, "failures": 0}:
            raise AssertionError(f"both real worker extraction calls must overlap: {overlap}")

        print(json.dumps({
            "same_second": evidence[0]["root"]["created_at"] == evidence[1]["root"]["created_at"],
            "submit_start_seconds": submit_start_seconds,
            "provider_overlap": overlap,
            "distinct_preflight_workers": sorted(preflight_worker_ids),
            "owners_roots_and_results": evidence,
        }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
