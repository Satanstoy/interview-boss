"""The AC-029 preseeded canonical must obey the question-bank dual-write contract."""

from __future__ import annotations

import json

import pytest


@pytest.fixture(autouse=True)
def _isolate_seed_database(app_db_isolation):
    return app_db_isolation


def test_preseeded_public_canonical_keeps_its_source_after_normalization(
    test_db, monkeypatch
):
    from app.services.question_variant_reconciliation import _sync_normalized_tables
    from e2e import seed_ac029_public_canonical as seed

    test_db.execute(
        "INSERT INTO users (id, username, password_hash, is_admin, email) "
        "VALUES (201, 'real_stack_admin', 'hash', 1, 'admin@example.test')"
    )
    monkeypatch.setattr(seed, "get_db_connection", lambda: test_db)

    seed.main()

    row = test_db.execute(
        "SELECT id, sources, original_questions, original_question_sources "
        "FROM question_bank WHERE question = ? AND owner_id IS NULL",
        (seed.QUESTION,),
    ).fetchone()
    _sync_normalized_tables(test_db, int(row["id"]))

    active_sources = test_db.execute(
        "SELECT url, company, round FROM question_sources "
        "WHERE question_bank_id = ? AND deleted_at IS NULL",
        (int(row["id"]),),
    ).fetchall()
    assert [tuple(source) for source in active_sources] == [
        (seed.SOURCE["url"], seed.SOURCE["company"], seed.SOURCE["round"])
    ]
    assert json.loads(row["sources"]) == [seed.SOURCE]
    assert json.loads(row["original_questions"]) == [seed.QUESTION]
    assert json.loads(row["original_question_sources"]) == [
        {"question": seed.QUESTION, "sources": [seed.SOURCE]}
    ]
