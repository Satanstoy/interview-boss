"""Seed one private AC-016 source; browser/API performs both contributions."""

from __future__ import annotations

import json
import os

from app.core.auth import hash_password
from app.core.prompts import DEFAULT_TAXONOMY
from app.db.connection import get_db_connection


USERNAME = "ac016_owner"
PASSWORD = "Ac016-append-projection-real-stack-123!"
SOURCE_URL = "https://ac016.example/interview/shared"
QUESTION_A = "AC016 question A: how does a distributed lock prevent stale writes?"


def main() -> None:
    with get_db_connection() as conn:
        admin_username = os.environ.get("ADMIN_USERNAME", "real_stack_admin")
        admin = conn.execute(
            "SELECT id FROM users WHERE username = ? AND is_admin = 1",
            (admin_username,),
        ).fetchone()
        if admin is None:
            raise RuntimeError("AC-016 disposable administrator is missing")
        admin_email = conn.execute(
            "SELECT email FROM users WHERE id = ?", (int(admin["id"]),)
        ).fetchone()["email"]
        if not admin_email:
            conn.execute(
                "UPDATE users SET email = ? WHERE id = ?",
                ("real_stack_admin@example.test", int(admin["id"])),
            )

        existing = conn.execute(
            "SELECT id FROM users WHERE username = ?", (USERNAME,)
        ).fetchone()
        if existing is not None:
            raise RuntimeError("AC-016 disposable owner unexpectedly already exists")
        owner_id = int(
            conn.execute(
                "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
                "VALUES (?, ?, ?, 0, 'private') RETURNING id",
                (USERNAME, hash_password(PASSWORD), f"{USERNAME}@example.test"),
            ).fetchone()["id"]
        )
        interview_id = int(
            conn.execute(
                "INSERT INTO interview (url, company, round, focus, questions_list, difficulty, "
                "owner_id, status, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, 'approved', ?) "
                "RETURNING id",
                (
                    SOURCE_URL,
                    "AC016 private company sentinel",
                    "AC016 private round sentinel",
                    "AC016 append projection",
                    QUESTION_A,
                    "中等",
                    owner_id,
                    DEFAULT_TAXONOMY["job_position"],
                ),
            ).fetchone()["id"]
        )
        detail_id = int(
            conn.execute(
                "INSERT INTO questions_detail (interview_id, url, company, round, question, "
                "cat1, cat2, tags, diff_tag, owner_id, status, job_position, source_ordinal) "
                "VALUES (?, ?, ?, ?, ?, '', '', '', '', ?, 'approved', ?, 10) RETURNING id",
                (
                    interview_id,
                    SOURCE_URL,
                    "AC016 private company sentinel",
                    "AC016 private round sentinel",
                    QUESTION_A,
                    owner_id,
                    DEFAULT_TAXONOMY["job_position"],
                ),
            ).fetchone()["id"]
        )
        conn.commit()

    print(
        json.dumps(
            {
                "owner_id": owner_id,
                "interview_id": interview_id,
                "source_detail_a_id": detail_id,
                "source_url": SOURCE_URL,
                "question_a": QUESTION_A,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
