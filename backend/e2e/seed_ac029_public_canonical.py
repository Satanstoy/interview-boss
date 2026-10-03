"""Seed one published public canonical for the disposable AC-029 journey."""

from __future__ import annotations

import json
import os

from app.core.prompts import DEFAULT_TAXONOMY
from app.db.connection import get_db_connection
from app.db.question_bank_sources import insert_original_item, insert_source


QUESTION = "多智能体系统如何设计任务协作？"
SOURCE = {
    "url": "https://ac029.example/preexisting-public-source",
    "company": "AC029 保留来源",
    "round": "历史一面",
}


def main() -> None:
    with get_db_connection() as conn:
        admin_username = os.environ.get("ADMIN_USERNAME", "sj")
        admin = conn.execute(
            "SELECT id, email FROM users WHERE username = ? AND is_admin = 1",
            (admin_username,),
        ).fetchone()
        if admin is None:
            raise RuntimeError("AC-029 disposable administrator is missing")
        if not admin["email"]:
            conn.execute(
                "UPDATE users SET email = ? WHERE id = ?",
                ("real_stack_admin@example.test", int(admin["id"])),
            )

        existing = conn.execute(
            "SELECT id FROM question_bank WHERE question = ? AND owner_id IS NULL "
            "AND status = 'approved' AND deleted_at IS NULL",
            (QUESTION,),
        ).fetchone()
        if existing:
            raise RuntimeError("AC-029 disposable canonical unexpectedly already exists")

        cursor = conn.execute(
            "INSERT INTO question_bank "
            "(question, cat1, cat2, tags, difficulty, frequency, sources, original_questions, "
            "original_question_sources, owner_id, status, job_position) "
            "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, NULL, 'approved', ?)",
            (
                QUESTION,
                "B.Agent与LLM应用",
                "B1.Agent架构与范式",
                "Agent架构设计",
                "L2-中等",
                json.dumps([SOURCE], ensure_ascii=False),
                json.dumps([QUESTION], ensure_ascii=False),
                json.dumps(
                    [{"question": QUESTION, "sources": [SOURCE]}],
                    ensure_ascii=False,
                ),
                DEFAULT_TAXONOMY["job_position"],
            ),
        )
        canonical_id = int(cursor.lastrowid)
        insert_source(conn, canonical_id, SOURCE["url"], SOURCE["company"], SOURCE["round"])
        insert_original_item(conn, canonical_id, QUESTION, [SOURCE])
        position = conn.execute(
            "SELECT id FROM job_positions WHERE name = ? "
            "AND (is_deleted = 0 OR is_deleted IS NULL) LIMIT 1",
            (DEFAULT_TAXONOMY["job_position"],),
        ).fetchone()
        if position:
            conn.execute(
                "INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, ?)",
                (canonical_id, int(position["id"])),
            )
        conn.commit()
        print(json.dumps({"canonical_id": canonical_id, "question": QUESTION}, ensure_ascii=False))


if __name__ == "__main__":
    main()
