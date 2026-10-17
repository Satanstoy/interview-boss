"""Capture sanitized SQLite + real-stub HTTP evidence for AC-013."""

from __future__ import annotations

import json
import sys
import urllib.request

from app.db.connection import get_db_connection


def _stub_json(path: str) -> dict:
    with urllib.request.urlopen(f"http://llm-stub:8080{path}", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def capture(import_id: str, marker: str) -> dict:
    with get_db_connection() as conn:
        root = conn.execute(
            "SELECT id, status, revision, current_attempt_no, error_code, error_message, interview_id "
            "FROM upload_imports WHERE id = ?",
            (import_id,),
        ).fetchone()
        if root is None:
            raise AssertionError(f"missing upload root {import_id}")

        attempts = conn.execute(
            "SELECT attempt_no, status FROM upload_attempts WHERE import_id = ? ORDER BY attempt_no",
            (import_id,),
        ).fetchall()
        jobs = conn.execute(
            "SELECT j.id, j.job_type, j.status, j.attempts, a.attempt_no "
            "FROM jobs j LEFT JOIN upload_attempts a ON a.id = j.upload_attempt_id "
            "WHERE j.root_import_id = ? AND j.job_type IN ('credential_preflight','submit_import') "
            "ORDER BY j.id",
            (import_id,),
        ).fetchall()
        stages = conn.execute(
            "SELECT stage, unit_key, status, error_code, retryable, job_id "
            "FROM upload_stage_results WHERE import_id = ? "
            "AND stage IN ('credential_preflight','extract') ORDER BY id",
            (import_id,),
        ).fetchall()
        calls = conn.execute(
            "SELECT stage, status, error_code, COUNT(*) AS count "
            "FROM upload_llm_calls WHERE root_import_id = ? GROUP BY stage, status, error_code "
            "ORDER BY stage, status, error_code",
            (import_id,),
        ).fetchall()
        extract_calls = conn.execute(
            "SELECT status, COUNT(*) AS count FROM upload_llm_calls "
            "WHERE root_import_id = ? AND stage = 'extract' GROUP BY status ORDER BY status",
            (import_id,),
        ).fetchall()
        submit_job_count = conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE root_import_id = ? AND job_type = 'submit_import'",
            (import_id,),
        ).fetchone()[0]
        detail_count = conn.execute(
            "SELECT COUNT(*) FROM questions_detail WHERE import_id = ?", (import_id,)
        ).fetchone()[0]
        interview_count = conn.execute(
            "SELECT COUNT(*) FROM interview WHERE id = ?", (root["interview_id"],)
        ).fetchone()[0] if root["interview_id"] is not None else 0

    provider_calls = _stub_json("/__e2e/calls").get("counts", {})
    provider_access = _stub_json("/__e2e/access")
    return {
        "import_id": root["id"],
        "marker": marker,
        "root": {
            "status": root["status"],
            "revision": int(root["revision"]),
            "current_attempt_no": int(root["current_attempt_no"]),
            "error_code": root["error_code"],
            "error_message": root["error_message"],
            "interview_id": root["interview_id"],
        },
        "attempts": [dict(row) for row in attempts],
        "jobs": [dict(row) for row in jobs],
        "submit_job_count": int(submit_job_count),
        "stages": [dict(row) for row in stages],
        "llm_calls": [dict(row) for row in calls],
        "extract_call_statuses": {
            row["status"]: int(row["count"]) for row in extract_calls
        },
        "details_count": int(detail_count),
        "interview_count": int(interview_count),
        "provider_marker_count": int(provider_calls.get(marker, 0)),
        "provider_access": provider_access,
    }


def assert_trace(trace: dict) -> None:
    marker = trace["marker"]
    root = trace["root"]
    extract_statuses = trace["extract_call_statuses"]
    marker_statuses = trace["provider_access"].get("marker_statuses", {}).get(marker, {})

    expected = {
        "AC013_AUTH_401": ("needs_action", "MODEL_AUTH_INVALID", {"failed": 1}, {"401": 1}),
        "AC013_PERMISSION_403": ("needs_action", "PERMISSION_REVOKED", {"failed": 1}, {"403": 1}),
        "AC013_RATE_429": ("completed", None, {"failed": 3, "succeeded": 1}, {"200": 1, "429": 3}),
        "AC013_FORMAT_INVALID": (
            "partial_failed",
            "MODEL_OUTPUT_INVALID",
            {"succeeded": 3},
            {"200": 3},
        ),
        "AC013_TIMEOUT_ONCE": ("completed", None, {"succeeded": 1, "unknown": 1}, {"200": 2}),
    }
    if marker not in expected:
        raise AssertionError(f"unexpected AC-013 marker: {marker}")
    expected_status, expected_code, expected_extract, expected_http = expected[marker]
    if root["status"] != expected_status or root["error_code"] != expected_code:
        raise AssertionError(
            f"{marker}: expected root {expected_status}/{expected_code}, "
            f"got {root['status']}/{root['error_code']}"
        )
    if extract_statuses != expected_extract:
        raise AssertionError(f"{marker}: extract ledger mismatch: {extract_statuses}")
    if trace["provider_marker_count"] != sum(expected_http.values()):
        raise AssertionError(
            f"{marker}: HTTP marker calls mismatch: {trace['provider_marker_count']}"
        )
    if marker_statuses != expected_http:
        raise AssertionError(f"{marker}: HTTP access status mismatch: {marker_statuses}")
    if marker in ("AC013_AUTH_401", "AC013_PERMISSION_403"):
        extract_stages = [stage for stage in trace["stages"] if stage["stage"] == "extract"]
        if not any(
            stage["status"] == "needs_action" and stage["error_code"] == expected_code
            for stage in extract_stages
        ):
            raise AssertionError(f"{marker}: credential stage was not needs_action")
        if trace["submit_job_count"] != 1 or trace["attempts"][-1]["attempt_no"] != 1:
            raise AssertionError(f"{marker}: non-retryable auth failure created another attempt")
    elif marker == "AC013_RATE_429":
        if root["current_attempt_no"] != 2 or len(trace["attempts"]) != 2:
            raise AssertionError("legacy retry did not resume the same root as attempt 2")
        if trace["submit_job_count"] != 2:
            raise AssertionError("legacy SSE enqueued a duplicate submit job")
        if [row["status"] for row in trace["attempts"]] != ["failed", "completed"]:
            raise AssertionError(f"rate retry attempt history mismatch: {trace['attempts']}")
    elif marker == "AC013_TIMEOUT_ONCE":
        if trace["details_count"] != 1 or trace["interview_count"] != 1:
            raise AssertionError("unknown timeout caused duplicate or missing business writes")
    elif marker == "AC013_FORMAT_INVALID" and trace["submit_job_count"] != 1:
        raise AssertionError("format repair failure redelivered the same job after budget exhaustion")


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: ac013_error_trace.py IMPORT_ID MARKER")
    trace = capture(sys.argv[1], sys.argv[2])
    assert_trace(trace)
    print(json.dumps(trace, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
