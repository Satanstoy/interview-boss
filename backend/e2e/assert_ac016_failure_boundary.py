"""Capture AC-016 SQLite state after worker failure and before admin retry."""

from __future__ import annotations

import json
import os
import sqlite3
import sys
from contextlib import contextmanager

from app.db.connection import get_db_connection


QUESTION_A = "AC016 question A: how does a distributed lock prevent stale writes?"
QUESTION_B = "AC016_FAIL_PUBLIC_B: how should a queue consumer enforce idempotency?"


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


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main(request_id: int) -> None:
    with database() as conn:
        request = conn.execute(
            "SELECT id, source_id, status, public_interview_id FROM public_contribution_requests WHERE id = ?",
            (request_id,),
        ).fetchone()
        require(request is not None, "second AC-016 contribution is missing")
        failed_item = conn.execute(
            "SELECT id, source_item_id, public_detail_id, status, error_message "
            "FROM public_contribution_items WHERE request_id = ? ORDER BY ordinal",
            (request_id,),
        ).fetchall()
        require(len(failed_item) == 1, "second contribution does not contain exactly new question B")
        item = failed_item[0]
        require(item["status"] == "failed", "B is not failed at the recovery boundary")
        require("AC016_PUBLIC_ITEM_FAILURE" in (item["error_message"] or ""),
                "failure boundary lacks the injected worker error")
        require(item["public_detail_id"] is not None, "failed B lost its pre-created public detail")
        resolution = conn.execute(
            "SELECT id FROM question_resolutions WHERE detail_id = ? "
            "AND occurrence_scope = 'public' AND occurrence_owner_id IS NULL "
            "AND invalidated_at IS NULL LIMIT 1",
            (int(item["public_detail_id"]),),
        ).fetchone()
        require(resolution is None, "B received a public resolution before admin retry")

        public_interview = conn.execute(
            "SELECT questions_list FROM interview WHERE id = ? AND owner_id IS NULL",
            (int(request["public_interview_id"]),),
        ).fetchone()
        require(public_interview is not None, "public interview projection is missing")
        public_lines = [line for line in (public_interview["questions_list"] or "").splitlines() if line]
        require(len(public_lines) == 1 and QUESTION_A in public_lines[0],
                "public projection exposed failed B or lost already published A")
        require(QUESTION_B not in public_interview["questions_list"], "failed B leaked into public list")
        require(
            conn.execute(
                "SELECT COUNT(*) FROM question_bank WHERE question = ? AND owner_id IS NULL "
                "AND deleted_at IS NULL",
                (QUESTION_B,),
            ).fetchone()[0] == 0,
            "failed B created a public canonical before its resolution",
        )
        first_item = conn.execute(
            "SELECT i.id, i.public_detail_id, i.status FROM public_contribution_items i "
            "JOIN public_contribution_requests r ON r.id = i.request_id "
            "WHERE r.source_id = ? AND r.id != ? AND i.status = 'published' "
            "ORDER BY r.id DESC, i.ordinal LIMIT 1",
            (int(request["source_id"]), request_id),
        ).fetchone()
        require(first_item is not None, "already published A contribution is missing")
        detail_a = conn.execute(
            "SELECT question FROM questions_detail WHERE id = ? AND interview_id = ?",
            (int(first_item["public_detail_id"]), int(request["public_interview_id"])),
        ).fetchone()
        require(detail_a is not None and detail_a["question"] == QUESTION_A,
                "already published A detail changed before retry")

        print(json.dumps({
            "request_id": int(request_id),
            "request_status_before_retry": request["status"],
            "failed_item_id": int(item["id"]),
            "failed_source_item_id": int(item["source_item_id"]),
            "failed_public_detail_id": int(item["public_detail_id"]),
            "failure_error_message": item["error_message"],
            "b_resolution_exists_before_retry": False,
            "b_canonical_exists_before_retry": False,
            "public_interview_id": int(request["public_interview_id"]),
            "public_questions_before_retry": public_lines,
            "published_a_item_id": int(first_item["id"]),
            "published_a_detail_id": int(first_item["public_detail_id"]),
            "published_a_question_before_retry": detail_a["question"],
        }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main(int(sys.argv[1]))
