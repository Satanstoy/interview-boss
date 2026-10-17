"""Wait for and cross-check both real AC-017 answer jobs and provider overlap."""

from __future__ import annotations

import json
import hashlib
import sys
import time
import urllib.request

from app.db.connection import get_db_connection
from e2e.seed_ac017_retry_chain import (
    ANSWER_A,
    ANSWER_B,
    IMPORT_ID,
    QUESTION_A,
    QUESTION_B,
    SUCCESS_CHECKPOINT,
)


def provider_access() -> dict:
    with urllib.request.urlopen("http://llm-stub:8080/__e2e/access", timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    timeout = int(sys.argv[1]) if len(sys.argv) > 1 else 180
    deadline = time.monotonic() + timeout
    rows = []
    while time.monotonic() < deadline:
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT j.id, j.status, j.parent_job_id, j.root_import_id, "
                "j.upload_attempt_id, j.work_key, p.payload, q.question, q.ai_answer "
                "FROM jobs j JOIN job_payloads p ON p.job_id = j.id "
                "JOIN question_bank q ON q.id = json_extract(p.payload, '$.question_id') "
                "WHERE j.root_import_id = ? AND j.job_type = 'generate_answer' "
                "ORDER BY j.work_key",
                (IMPORT_ID,),
            ).fetchall()
        if len(rows) == 2 and all(row["status"] == "completed" for row in rows):
            break
        time.sleep(0.5)
    else:
        raise AssertionError(f"parallel answer jobs did not complete: {[dict(row) for row in rows]}")

    with get_db_connection() as conn:
        root = conn.execute(
            "SELECT current_attempt_no, status FROM upload_imports WHERE id = ?", (IMPORT_ID,)
        ).fetchone()
        parent = conn.execute(
            "SELECT id FROM jobs WHERE root_import_id = ? "
            "AND idempotency_key = 'ac017:attempt-c'",
            (IMPORT_ID,),
        ).fetchone()
        attempts = conn.execute(
            "SELECT attempt_no, status FROM upload_attempts WHERE import_id = ? ORDER BY attempt_no",
            (IMPORT_ID,),
        ).fetchall()
        extract = conn.execute(
            "SELECT status, output_hash, result_json FROM upload_stage_results "
            "WHERE import_id = ? AND stage = 'extract' AND unit_key = 'document'",
            (IMPORT_ID,),
        ).fetchone()
        duplicate_work = conn.execute(
            "SELECT work_key, COUNT(*) AS count FROM jobs WHERE root_import_id = ? "
            "AND work_key IS NOT NULL GROUP BY work_key HAVING COUNT(*) > 1",
            (IMPORT_ID,),
        ).fetchall()
        duplicate_active = conn.execute(
            "SELECT work_key, COUNT(*) AS count FROM jobs WHERE root_import_id = ? "
            "AND work_key IS NOT NULL AND status IN ('pending','queued','running') "
            "GROUP BY work_key HAVING COUNT(*) > 1",
            (IMPORT_ID,),
        ).fetchall()

    expected = {QUESTION_A: ANSWER_A, QUESTION_B: ANSWER_B}
    answers = {}
    for row in rows:
        question_id = int(json.loads(row["payload"])["question_id"])
        expected_answer = expected[row["question"]]
        if row["status"] != "completed" or not row["ai_answer"] or expected_answer not in row["ai_answer"]:
            raise AssertionError(f"answer result was missing or crossed: {dict(row)}")
        if ANSWER_B in row["ai_answer"] and row["question"] != QUESTION_B:
            raise AssertionError("answer B overwrote question A")
        if ANSWER_A in row["ai_answer"] and row["question"] != QUESTION_A:
            raise AssertionError("answer A overwrote question B")
        if (
            row["root_import_id"] != IMPORT_ID
            or parent is None
            or int(row["parent_job_id"]) != int(parent["id"])
        ):
            raise AssertionError("answer job lineage is invalid")
        expected_work_key = f"answer:{question_id}:v1"
        if row["work_key"] != expected_work_key:
            raise AssertionError(f"unexpected work key for {row['question']}: {row['work_key']}")
        answers[row["question"]] = {
            "job_id": int(row["id"]),
            "status": row["status"],
            "work_key": row["work_key"],
            "answer": row["ai_answer"],
            "attempt_id": int(row["upload_attempt_id"]),
        }
    if set(answers) != {QUESTION_A, QUESTION_B}:
        raise AssertionError(f"question results crossed or missing: {answers}")
    if int(root["current_attempt_no"]) != 3 or len(attempts) != 3:
        raise AssertionError("retry history created a fourth attempt")
    if [(int(row["attempt_no"]), row["status"]) for row in attempts[:2]] != [
        (1, "failed"),
        (2, "failed"),
    ]:
        raise AssertionError("historical failed attempt A/B records changed")
    checkpoint_json = json.dumps(SUCCESS_CHECKPOINT, ensure_ascii=False, sort_keys=True)
    expected_checkpoint_hash = hashlib.sha256(checkpoint_json.encode()).hexdigest()
    if (
        not extract
        or extract["status"] != "succeeded"
        or extract["output_hash"] != expected_checkpoint_hash
        or extract["result_json"] != checkpoint_json
    ):
        raise AssertionError("the successful extraction checkpoint was lost")
    if duplicate_active:
        raise AssertionError(f"duplicate active work keys remain: {[dict(row) for row in duplicate_active]}")

    access = provider_access()
    parallel = access.get("parallel_answers", {})
    if int(parallel.get("max_active", 0)) < 2:
        raise AssertionError(f"distinct answer keys were not in-flight together: {parallel}")
    marker_counts = access.get("marker_statuses", {})
    for marker in ("AC017_PARALLEL_ANSWER_A", "AC017_PARALLEL_ANSWER_B"):
        if sum(marker_counts.get(marker, {}).values()) < 1:
            raise AssertionError(f"provider did not receive {marker}")

    trace = {
        "root": dict(root),
        "attempts": [dict(row) for row in attempts],
        "answer_jobs": answers,
        "unique_work_keys": sorted({row["work_key"] for row in rows}),
        "historical_retried_work_keys": [dict(row) for row in duplicate_work],
        "duplicate_active_work_keys": [],
        "success_checkpoint_hash": extract["output_hash"],
        "provider_parallel_answers": parallel,
        "provider_marker_statuses": {
            marker: marker_counts.get(marker, {})
            for marker in ("AC017_PARALLEL_ANSWER_A", "AC017_PARALLEL_ANSWER_B")
        },
    }
    print(json.dumps(trace, ensure_ascii=False, indent=2))
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8") as stream:
            json.dump(trace, stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
