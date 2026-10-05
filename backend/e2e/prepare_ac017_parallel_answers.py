"""Create two real, distinct answer work keys after AC-017 retry assertions."""

from __future__ import annotations

import json

from app.db.connection import get_db_connection
from app.services.job_lifecycle import create_answer_generation_jobs
from e2e.seed_ac017_retry_chain import (
    IMPORT_ID,
    OWNER,
    QUESTION_A,
    QUESTION_B,
)


def main() -> None:
    with get_db_connection() as conn:
        root = conn.execute(
            "SELECT requester_id, current_attempt_no FROM upload_imports WHERE id = ?",
            (IMPORT_ID,),
        ).fetchone()
        if root is None or int(root["current_attempt_no"]) != 3:
            raise AssertionError("A/B/C retry checks did not preserve attempt C")
        owner = conn.execute("SELECT id FROM users WHERE username = ?", (OWNER,)).fetchone()
        if owner is None or int(owner["id"]) != int(root["requester_id"]):
            raise AssertionError("AC-017 source owner changed")
        attempt = conn.execute(
            "SELECT id, status FROM upload_attempts WHERE import_id = ? AND attempt_no = 3",
            (IMPORT_ID,),
        ).fetchone()
        if attempt is None or attempt["status"] != "active":
            raise AssertionError("attempt C must be active when parallel answer work is planned")
        parent = conn.execute(
            "SELECT id, status FROM jobs WHERE idempotency_key = 'ac017:attempt-c' "
            "AND root_import_id = ?",
            (IMPORT_ID,),
        ).fetchone()
        if parent is None or parent["status"] != "queued":
            raise AssertionError("active C job is not available to parent its answer jobs")

        question_ids = [
            int(row["id"])
            for row in conn.execute(
                "SELECT id FROM question_bank WHERE owner_id = ? AND question IN (?, ?) "
                "ORDER BY id",
                (int(owner["id"]), QUESTION_A, QUESTION_B),
            ).fetchall()
        ]
        if len(question_ids) != 2:
            raise AssertionError("both AC-017 parallel answer fixtures are required")

        conn.execute(
            "UPDATE jobs SET status = 'completed', completed_at = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status = 'queued'",
            (int(parent["id"]),),
        )
        answer_tasks = list(zip(question_ids, (QUESTION_A, QUESTION_B), strict=True))
        first_ids = create_answer_generation_jobs(
            conn,
            int(parent["id"]),
            answer_tasks,
            int(owner["id"]),
            skip_search=True,
            llm_scope="user",
            search_scope="user",
        )
        second_ids = create_answer_generation_jobs(
            conn,
            int(parent["id"]),
            answer_tasks,
            int(owner["id"]),
            skip_search=True,
            llm_scope="user",
            search_scope="user",
        )
        if first_ids != second_ids:
            raise AssertionError("replanning the same answer work keys created duplicate jobs")
        conn.commit()

        jobs = conn.execute(
            "SELECT id, status, upload_attempt_id, work_key, idempotency_key "
            "FROM jobs WHERE id IN (?, ?) ORDER BY work_key",
            first_ids,
        ).fetchall()
        if len(jobs) != 2 or any(row["status"] != "pending" for row in jobs):
            raise AssertionError(f"expected two pending distinct answer jobs: {[dict(row) for row in jobs]}")
        if len({row["work_key"] for row in jobs}) != 2:
            raise AssertionError("the two questions did not receive distinct work keys")
        if any(int(row["upload_attempt_id"]) != int(attempt["id"]) for row in jobs):
            raise AssertionError("answer work escaped active attempt C")

    print(
        json.dumps(
            {
                "import_id": IMPORT_ID,
                "attempt_c_id": int(attempt["id"]),
                "parent_job_id": int(parent["id"]),
                "answer_jobs": [dict(row) for row in jobs],
                "duplicate_replan_same_job_ids": first_ids,
                "different_work_keys_created": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
