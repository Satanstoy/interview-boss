"""Post-090 data repair migrations."""

from __future__ import annotations

import logging

logger = logging.getLogger("interview-boss")


def migration_091_repair_fk_orphans(conn) -> None:
    """Remove known asked-question orphans left by historical FK-off windows."""
    deleted = 0
    table_exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        ("interview_asked_questions",),
    ).fetchone()
    if table_exists:
        cursor = conn.execute(
            """
            DELETE FROM interview_asked_questions
            WHERE NOT EXISTS (
                SELECT 1 FROM users u
                WHERE u.id = interview_asked_questions.user_id
            )
            OR NOT EXISTS (
                SELECT 1 FROM chat_conversations c
                WHERE c.id = interview_asked_questions.conversation_id
            )
            OR NOT EXISTS (
                SELECT 1 FROM question_bank q
                WHERE q.id = interview_asked_questions.question_id
            )
            """
        )
        deleted = cursor.rowcount

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(
            "migration 091 后仍存在 FK 违规："
            f"{len(violations)} 条（前 5 条: {violations[:5]}）"
        )
    logger.info("migration 091 repaired interview_asked_questions orphans: %d", deleted)
