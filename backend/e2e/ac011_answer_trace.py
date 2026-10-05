"""Return DB and real provider request evidence for AC-011."""

from __future__ import annotations

import json
import sys
import urllib.request

from app.db.connection import get_db_connection


def _provider_counts() -> dict[str, int]:
    with urllib.request.urlopen("http://llm-stub:8080/__e2e/calls", timeout=5) as response:
        return json.loads(response.read().decode("utf-8")).get("counts", {})


def main() -> None:
    if len(sys.argv) != 3 or sys.argv[1] not in {"first", "final"}:
        raise SystemExit("usage: ac011_answer_trace.py first|final IMPORT_ID")
    phase, import_id = sys.argv[1:]
    with get_db_connection() as conn:
        root = conn.execute(
            "SELECT id, requester_id, status, revision, current_attempt_no, interview_id, error_code "
            "FROM upload_imports WHERE id = ?",
            (import_id,),
        ).fetchone()
        if root is None:
            raise AssertionError(f"missing upload root {import_id}")

        answer_rows = conn.execute(
            "SELECT s.unit_key, s.status, s.error_code, s.retryable, s.result_json, "
            "s.output_hash, s.job_id, CAST(SUBSTR(s.unit_key, 8) AS INTEGER) AS question_id, "
            "q.question, q.ai_answer "
            "FROM upload_stage_results s "
            "JOIN question_bank q ON q.id = CAST(SUBSTR(s.unit_key, 8) AS INTEGER) "
            "WHERE s.import_id = ? AND s.stage = 'answer' "
            "ORDER BY CAST(SUBSTR(s.unit_key, 8) AS INTEGER)",
            (import_id,),
        ).fetchall()
        resolutions = conn.execute(
            "SELECT d.id AS detail_id, d.source_ordinal, d.question, r.id AS resolution_id, "
            "r.canonical_id, r.canonical_scope, r.status, r.invalidated_at "
            "FROM questions_detail d LEFT JOIN question_resolutions r "
            "ON r.detail_id = d.id AND r.invalidated_at IS NULL "
            "WHERE d.import_id = ? ORDER BY d.source_ordinal",
            (import_id,),
        ).fetchall()
        jobs = conn.execute(
            "SELECT j.id, j.upload_attempt_id, a.attempt_no, j.status, j.attempts, "
            "j.work_key, j.parent_job_id, json_extract(p.payload, '$.question_id') AS question_id "
            "FROM jobs j LEFT JOIN upload_attempts a ON a.id = j.upload_attempt_id "
            "LEFT JOIN job_payloads p ON p.job_id = j.id "
            "WHERE j.root_import_id = ? AND j.job_type = 'generate_answer' "
            "ORDER BY j.id",
            (import_id,),
        ).fetchall()
        aggregate_counts = conn.execute(
            "SELECT status, COUNT(*) AS count FROM upload_stage_results "
            "WHERE import_id = ? AND stage = 'answer' GROUP BY status",
            (import_id,),
        ).fetchall()

        trace = {
            "phase": phase,
            "import_id": root["id"],
            "requester_id": int(root["requester_id"]),
            "root_status": root["status"],
            "revision": int(root["revision"]),
            "current_attempt_no": int(root["current_attempt_no"]),
            "interview_id": int(root["interview_id"]),
            "error_code": root["error_code"],
            "answer_stage_counts": {row["status"]: int(row["count"]) for row in aggregate_counts},
            "answers": [dict(row) for row in answer_rows],
            "resolutions": [dict(row) for row in resolutions],
            "answer_jobs": [dict(row) for row in jobs],
            "provider_physical_request_counts": _provider_counts(),
        }

    expected_status = "partial_failed" if phase == "first" else "completed"
    if trace["root_status"] != expected_status:
        raise AssertionError(f"expected {expected_status}, got {trace['root_status']}")
    if len(trace["answers"]) != 10:
        raise AssertionError(f"expected 10 answer checkpoints, got {len(trace['answers'])}")
    expected_counts = {"succeeded": 8, "failed": 2} if phase == "first" else {"succeeded": 10}
    if trace["answer_stage_counts"] != expected_counts:
        raise AssertionError(
            f"answer stage counts mismatch: expected {expected_counts}, got {trace['answer_stage_counts']}"
        )
    failed_markers = {
        str(row["question"]).split()[0]
        for row in trace["answers"]
        if row["status"] == "failed"
    }
    if phase == "first" and failed_markers != {"AC011_QUESTION_09", "AC011_QUESTION_10"}:
        raise AssertionError(f"expected only questions 09 and 10 to fail, got {sorted(failed_markers)}")
    if phase == "final" and any(row["status"] != "succeeded" for row in trace["answers"]):
        raise AssertionError("final answer checkpoints are not all succeeded")
    successful_rows = [row for row in trace["answers"] if row["status"] == "succeeded"]
    if any(not row["output_hash"] or len(str(row["output_hash"])) != 64 for row in successful_rows):
        raise AssertionError("successful answer checkpoint is missing its content hash")
    if len(trace["resolutions"]) != 10 or any(
        row["resolution_id"] is None or row["status"] not in ("created", "matched")
        for row in trace["resolutions"]
    ):
        raise AssertionError("one or more question resolution identities are missing or failed")
    print(json.dumps(trace, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
