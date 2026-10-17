"""Assert AC-016 browser/API/SQLite append, retry, and ownership invariants."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import contextmanager

from app.db.connection import get_db_connection


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


@contextmanager
def database():
    path = os.environ.get("AC016_DB_PATH")
    if path:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()
        return
    with get_db_connection() as conn:
        yield conn


def main(seed_path: str, browser_trace_path: str, boundary_trace_path: str) -> None:
    with open(seed_path, encoding="utf-8") as stream:
        seed = json.load(stream)
    with open(browser_trace_path, encoding="utf-8") as stream:
        browser = json.load(stream)
    with open(boundary_trace_path, encoding="utf-8") as stream:
        boundary = json.load(stream)

    owner_id = int(seed["owner_id"])
    source_id = int(seed["interview_id"])
    first_request_id = int(browser["first_request_id"])
    second_request_id = int(browser["second_request_id"])
    public_interview_id = int(browser["public_interview_id"])
    question_a = seed["question_a"]
    question_b = browser["question_b"]
    source_url = seed["source_url"]

    require(first_request_id != second_request_id, "contribution request IDs were reused")
    require(browser["first_item_id"] != browser["second_item_id"], "contribution item IDs were reused")
    require(browser["worker_restarted_before_admin_retry"], "worker was not restarted before admin retry")
    require("AC016_PUBLIC_ITEM_FAILURE" in browser["injected_failure_error_message"],
            "browser did not observe the injected pre-retry failure")
    require(boundary["request_id"] == second_request_id, "failure-boundary trace is for another request")
    require(boundary["failed_item_id"] == browser["second_item_id"], "failure-boundary item identity differs")
    require(boundary["b_resolution_exists_before_retry"] is False,
            "B already had a resolution at the failure boundary")
    require(boundary["public_questions_before_retry"] == [f"1. {question_a}"],
            "failure-boundary public projection differs")

    with database() as conn:
        requests = conn.execute(
            "SELECT id, source_type, source_id, requester_id, status, public_interview_id, "
            "snapshot_json, review_projection_json FROM public_contribution_requests "
            "WHERE id IN (?, ?) ORDER BY id",
            (first_request_id, second_request_id),
        ).fetchall()
        require(len(requests) == 2, "one or both contribution requests are missing")
        first, second = requests
        require(all(row["source_type"] == "interview" for row in requests), "source type changed")
        require(all(int(row["source_id"]) == source_id for row in requests), "requests do not share one source")
        require(all(int(row["requester_id"]) == owner_id for row in requests), "request owner changed")
        require(all(int(row["public_interview_id"] or 0) == public_interview_id for row in requests),
                "requests do not share one public interview")
        require(first["status"] == "published" and second["status"] == "published",
                "both contribution requests did not reach published")

        item_rows = conn.execute(
            "SELECT id, request_id, source_item_id, public_detail_id, status, error_message, "
            "snapshot_json FROM public_contribution_items WHERE request_id IN (?, ?) ORDER BY request_id, ordinal",
            (first_request_id, second_request_id),
        ).fetchall()
        require(len(item_rows) == 2, "second contribution duplicated an already published source item")
        first_item = next(row for row in item_rows if int(row["request_id"]) == first_request_id)
        second_item = next(row for row in item_rows if int(row["request_id"]) == second_request_id)
        require(int(first_item["source_item_id"]) == int(seed["source_detail_a_id"]),
                "first contribution lost source question A")
        source_b = conn.execute(
            "SELECT id FROM questions_detail WHERE interview_id = ? AND question = ? AND deleted_at IS NULL",
            (source_id, question_b),
        ).fetchone()
        require(source_b is not None and int(second_item["source_item_id"]) == int(source_b["id"]),
                "second contribution does not point to newly appended source question B")
        require(int(first_item["id"]) != int(second_item["id"]), "contribution item identity was reused")
        require(first_item["status"] == "published" and second_item["status"] == "published",
                "contribution item did not reach published")
        require(second_item["error_message"] in (None, ""),
                "successful retry did not clear the resolved item error")
        require(int(first_item["public_detail_id"]) == int(browser["first_public_detail_id"]),
                "retry changed the already published A detail")
        require(int(second_item["public_detail_id"]) == int(browser["second_public_detail_id"]),
                "retry changed the B detail identity")
        require(int(first_item["public_detail_id"]) != int(second_item["public_detail_id"]),
                "A and B share a public detail")

        snapshot_a = json.loads(first["snapshot_json"] or "{}")
        snapshot_b = json.loads(second["snapshot_json"] or "{}")
        require([item.get("question") for item in snapshot_a.get("items", [])] == [question_a],
                "first immutable snapshot was rewritten")
        require([item.get("question") for item in snapshot_b.get("items", [])] == [question_b],
                "second immutable snapshot contains an already published question")
        projection_b = json.loads(second["review_projection_json"] or "{}")
        require(
            projection_b.get("source", {}).get("source_url") == source_url,
            "second review projection lost its explicit public source URL",
        )

        public_interview = conn.execute(
            "SELECT owner_id, url, publish_status, questions_list FROM interview WHERE id = ? AND deleted_at IS NULL",
            (public_interview_id,),
        ).fetchone()
        require(public_interview is not None and public_interview["owner_id"] is None,
                "public interview is missing or has an owner")
        require(public_interview["url"] == source_url, "public interview URL differs")
        require(public_interview["publish_status"] == "published", "public interview is not published")
        public_lines = [line for line in (public_interview["questions_list"] or "").splitlines() if line]
        require(len(public_lines) == 2, "public projection contains an unexpected number of questions")
        require(sum(question_a in line for line in public_lines) == 1, "public question A is not present exactly once")
        require(sum(question_b in line for line in public_lines) == 1, "public question B is not present exactly once")
        require(public_lines[0].find(question_a) >= 0 and public_lines[1].find(question_b) >= 0,
                "public projection order is not stable")

        public_details = conn.execute(
            "SELECT id, question FROM questions_detail WHERE interview_id = ? AND deleted_at IS NULL ORDER BY id",
            (public_interview_id,),
        ).fetchall()
        require(len(public_details) == 2, "retry created duplicate public detail rows")
        require({row["question"] for row in public_details} == {question_a, question_b},
                "public detail questions differ from the published source items")

        resolution_trace = []
        source_counts = {}
        for item in item_rows:
            resolution = conn.execute(
                "SELECT r.canonical_id, r.status, r.canonical_scope, qb.question "
                "FROM question_resolutions r JOIN question_bank qb ON qb.id = r.canonical_id "
                "WHERE r.detail_id = ? AND r.occurrence_scope = 'public' "
                "AND r.occurrence_owner_id IS NULL AND r.invalidated_at IS NULL ORDER BY r.id DESC LIMIT 1",
                (int(item["public_detail_id"]),),
            ).fetchone()
            require(resolution is not None, "published public detail has no current resolution")
            require(resolution["status"] in ("matched", "created"), "resolution is not successful")
            require(resolution["canonical_scope"] == "public", "resolution escaped public scope")
            canonical_id = int(resolution["canonical_id"])
            canonical_count = conn.execute(
                "SELECT COUNT(*) FROM question_bank WHERE question = ? AND owner_id IS NULL "
                "AND status = 'approved' AND deleted_at IS NULL",
                (resolution["question"],),
            ).fetchone()[0]
            require(int(canonical_count) == 1, "question canonical was duplicated")
            source_count = conn.execute(
                "SELECT COUNT(*) FROM question_sources WHERE question_bank_id = ? AND url = ? "
                "AND deleted_at IS NULL",
                (canonical_id, source_url),
            ).fetchone()[0]
            require(int(source_count) == 1, "canonical source was duplicated or lost")
            source_counts[canonical_id] = int(source_count)
            resolution_trace.append(
                {
                    "public_detail_id": int(item["public_detail_id"]),
                    "canonical_id": canonical_id,
                    "question": resolution["question"],
                    "resolution_status": resolution["status"],
                    "source_count": int(source_count),
                }
            )
        require(len(source_counts) == 2, "A and B were collapsed into an unexpected canonical")

        private_interview = conn.execute(
            "SELECT owner_id, url, company, round FROM interview WHERE id = ? AND deleted_at IS NULL",
            (source_id,),
        ).fetchone()
        require(private_interview is not None, "same-URL private interview was deleted")
        require(int(private_interview["owner_id"]) == owner_id, "private interview ownership changed")
        require(private_interview["url"] == source_url, "private interview URL was rewritten")
        require(private_interview["company"] == "AC016 private company sentinel",
                "private interview company was overwritten")
        require(private_interview["round"] == "AC016 private round sentinel",
                "private interview round was overwritten")
        private_questions = conn.execute(
            "SELECT question, status FROM questions_detail WHERE interview_id = ? AND deleted_at IS NULL ORDER BY source_ordinal",
            (source_id,),
        ).fetchall()
        require([row["question"] for row in private_questions] == [question_a, question_b],
                "private interview questions were deleted or rewritten")
        require(all(row["status"] == "approved" for row in private_questions),
                "private interview source status changed")

        queues = conn.execute(
            "SELECT id, question_detail_id, status FROM analysis_queue "
            "WHERE contribution_request_id = ? ORDER BY id",
            (second_request_id,),
        ).fetchall()
        require(len(queues) == 1, "retry duplicated the second contribution queue row")
        require(queues[0]["status"] == "done", "retry queue row did not complete")
        require(int(queues[0]["question_detail_id"]) == int(second_item["public_detail_id"]),
                "retry queue row changed the public detail identity")

        trace = {
            "requests": [
                {"id": int(row["id"]), "source_id": int(row["source_id"]), "status": row["status"]}
                for row in requests
            ],
            "items": [
                {
                    "id": int(row["id"]),
                    "request_id": int(row["request_id"]),
                    "source_item_id": int(row["source_item_id"]),
                    "public_detail_id": int(row["public_detail_id"]),
                    "status": row["status"],
                    "error_message": row["error_message"],
                }
                for row in item_rows
            ],
            "public_interview_id": public_interview_id,
            "public_url": public_interview["url"],
            "public_questions": public_lines,
            "public_detail_ids": [int(row["id"]) for row in public_details],
            "resolutions": resolution_trace,
            "private_interview_id": source_id,
            "private_owner_id": owner_id,
            "private_questions": [row["question"] for row in private_questions],
            "second_request_queue": [
                {
                    "id": int(row["id"]),
                    "question_detail_id": int(row["question_detail_id"]),
                    "status": row["status"],
                }
                for row in queues
            ],
            "failure_boundary": boundary,
        }

    print(json.dumps(trace, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3])
