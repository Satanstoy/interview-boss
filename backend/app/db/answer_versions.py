"""Compatibility helpers for taxonomy-versioned reference answers."""

from __future__ import annotations

import sqlite3


def update_question_answer(
    conn,
    question_id: int,
    answer: str,
    answer_sources: str | None,
    taxonomy_version: str | None,
) -> None:
    """Persist an answer and its taxonomy version across rolling deployments.

    Migration 102 is required for production. The fallback only keeps an old
    process/test schema writable while the migration is being applied; it
    never marks an answer as current when the version column is unavailable.
    """
    try:
        conn.execute(
            "UPDATE question_bank SET ai_answer = ?, answer_sources = ?, "
            "answer_taxonomy_version = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (answer, answer_sources, taxonomy_version, question_id),
        )
    except sqlite3.OperationalError as exc:
        if "answer_taxonomy_version" not in str(exc):
            raise
        conn.execute(
            "UPDATE question_bank SET ai_answer = ?, answer_sources = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (answer, answer_sources, question_id),
        )
