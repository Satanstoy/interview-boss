"""Standalone clusters retain the authenticated same-scope merge path."""

import json

import pytest

from tests.security.test_question_bank_spec_alignment import actors as _actors_fixture, question


actors = _actors_fixture


@pytest.mark.parametrize("owner", [None, 8802])
def test_standalone_question_merges_into_same_scope_cluster(client, test_db, actors, owner):
    source = question(test_db, owner, "STANDALONE_SOURCE")
    target = question(test_db, owner, "STANDALONE_TARGET")
    response = client.post(
        f"/api/master-bank/merge-question/{source}",
        headers=actors(8802),
        json={"original_question": "STANDALONE_SOURCE", "target_id": target},
    )
    assert response.status_code == 200, response.text
    merged = test_db.execute("SELECT * FROM question_bank WHERE id=?", (target,)).fetchone()
    assert merged["owner_id"] == owner
    assert json.loads(merged["original_questions"]) == ["STANDALONE_SOURCE"]
    assert merged["frequency"] == 1
    remaining = test_db.execute("SELECT deleted_at FROM question_bank WHERE id=?", (source,)).fetchone()
    assert remaining is None or remaining["deleted_at"] is not None
