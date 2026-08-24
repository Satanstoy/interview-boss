"""Database-level invariants for question-bank scope and legacy details."""

from __future__ import annotations

import sqlite3

import pytest


def test_question_bank_exposes_scope_and_rejects_unknown_review_state(test_db):
    columns = {row[1] for row in test_db.execute("PRAGMA table_xinfo('question_bank')").fetchall()}
    assert {"visibility", "review_state"} <= columns

    test_db.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) "
        "VALUES (7, 'scope-owner', 'x', 0)"
    )
    test_db.execute(
        "INSERT INTO question_bank (id, question, owner_id, status) "
        "VALUES (1001, '公共题', NULL, 'approved'), "
        "(1002, '个人待审题', 7, 'pending')"
    )
    rows = test_db.execute(
        "SELECT id, visibility, review_state FROM question_bank WHERE id IN (1001, 1002) "
        "ORDER BY id"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (1001, "public", "approved"),
        (1002, "private", "pending"),
    ]

    with pytest.raises(sqlite3.IntegrityError):
        test_db.execute(
            "INSERT INTO question_bank (question, owner_id, status) "
            "VALUES ('非法状态题', 7, 'rejected')"
        )

    with pytest.raises(sqlite3.IntegrityError):
        test_db.execute(
            "UPDATE question_bank SET status = 'rejected' WHERE id = 1002"
        )


def test_legacy_unlinked_details_are_linked_or_quarantined(test_db):
    from app.db.migrations.question_bank_scope import (
        _migration_109_question_detail_scope_guard,
    )

    test_db.execute(
        "INSERT INTO users (id, username, password_hash, is_admin) "
        "VALUES (8, 'legacy-owner', 'x', 0)"
    )
    test_db.execute(
        "INSERT INTO interview (id, url, owner_id, status) VALUES "
        "(1101, 'https://unique.example', NULL, 'approved'), "
        "(1102, 'https://ambiguous.example', NULL, 'approved'), "
        "(1103, 'https://ambiguous.example', 8, 'approved')"
    )
    test_db.execute(
        "INSERT INTO questions_detail (id, interview_id, url, question, deleted_at) "
        "VALUES (1201, NULL, 'https://unique.example', '可唯一补链', NULL), "
        "(1202, NULL, 'https://ambiguous.example', '多候选隔离', NULL), "
        "(1203, NULL, 'https://missing.example', '无候选隔离', NULL)"
    )
    test_db.commit()

    _migration_109_question_detail_scope_guard(test_db)
    test_db.commit()

    linked = test_db.execute("SELECT interview_id FROM questions_detail WHERE id = 1201").fetchone()
    assert linked["interview_id"] == 1101

    quarantined = test_db.execute(
        "SELECT detail_id, reason FROM question_detail_scope_quarantine ORDER BY detail_id"
    ).fetchall()
    assert [tuple(row) for row in quarantined] == [
        (1202, "ambiguous_interview"),
        (1203, "missing_interview"),
    ]
