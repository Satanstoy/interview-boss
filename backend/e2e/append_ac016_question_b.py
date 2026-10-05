"""Append question B to the private source after its first contribution publishes."""

from __future__ import annotations

import json
import sys

from app.db.connection import get_db_connection


QUESTION_B = "AC016_FAIL_PUBLIC_B: how should a queue consumer enforce idempotency?"


def main(interview_id: int) -> None:
    with get_db_connection() as conn:
        interview = conn.execute(
            "SELECT id, url, company, round, owner_id, job_position "
            "FROM interview WHERE id = ? AND owner_id IS NOT NULL AND deleted_at IS NULL",
            (interview_id,),
        ).fetchone()
        if interview is None:
            raise RuntimeError("AC-016 private source is missing")
        question_a = conn.execute(
            "SELECT question FROM questions_detail WHERE interview_id = ? "
            "AND deleted_at IS NULL ORDER BY source_ordinal, id LIMIT 1",
            (interview_id,),
        ).fetchone()
        if question_a is None:
            raise RuntimeError("AC-016 original private question A is missing")
        if conn.execute(
            "SELECT 1 FROM questions_detail WHERE interview_id = ? AND question = ? "
            "AND deleted_at IS NULL",
            (interview_id, QUESTION_B),
        ).fetchone():
            raise RuntimeError("AC-016 question B unexpectedly already exists")
        detail_id = int(
            conn.execute(
                "INSERT INTO questions_detail (interview_id, url, company, round, question, "
                "cat1, cat2, tags, diff_tag, owner_id, status, job_position, source_ordinal) "
                "VALUES (?, ?, ?, ?, ?, '', '', '', '', ?, 'approved', ?, 20) RETURNING id",
                (
                    interview_id,
                    interview["url"],
                    interview["company"],
                    interview["round"],
                    QUESTION_B,
                    interview["owner_id"],
                    interview["job_position"],
                ),
            ).fetchone()["id"]
        )
        conn.execute(
            "UPDATE interview SET questions_list = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (f"1. {question_a['question']}\n2. {QUESTION_B}", interview_id),
        )
        conn.commit()
    print(json.dumps({"interview_id": interview_id, "question_b_detail_id": detail_id}))


if __name__ == "__main__":
    main(int(sys.argv[1]))
