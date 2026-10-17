"""Real compaction and rollback routes retain historical canonical references."""
import json

import pytest

from tests.security.test_question_bank_spec_alignment import actors as _actors_fixture, question

actors = _actors_fixture


@pytest.mark.parametrize('scope', ['private', 'public'])
@pytest.mark.parametrize('historical', [False, True])
def test_compaction_retains_references_and_rollback_restores_source(
    client, test_db, actors, monkeypatch, scope, historical,
):
    import app.services.pipeline.compact as compact
    import app.services.clustering.matcher as matcher

    source = question(test_db, None, 'SOURCE_ORIGINAL')
    target = question(test_db, None, 'TARGET_ORIGINAL')
    test_db.execute("UPDATE question_bank SET original_questions='[\"SOURCE_ORIGINAL\"]' WHERE id=?", (source,))
    test_db.execute("UPDATE question_bank SET frequency=2,original_questions='[\"T1\",\"T2\"]' WHERE id=?", (target,))
    from app.services.question_bank_integrity import (
        claim_public_original_questions,
        sync_question_bank_projections,
    )

    for qid, originals in ((source, ['SOURCE_ORIGINAL']), (target, ['T1', 'T2'])):
        sync_question_bank_projections(test_db.cursor(), qid, [], originals, [])
        claim_public_original_questions(test_db, qid, None, 'approved', originals)

    def lineage():
        return {
            'normalized': [tuple(row) for row in test_db.execute(
                'SELECT question_bank_id,question_text FROM question_original_items '
                'WHERE question_bank_id IN (?,?) AND deleted_at IS NULL '
                'ORDER BY question_bank_id,question_text', (source, target),
            )],
            'claims': [tuple(row) for row in test_db.execute(
                'SELECT question_bank_id,question_text FROM question_variant_owners '
                'WHERE question_bank_id IN (?,?) ORDER BY question_bank_id,question_text',
                (source, target),
            )],
        }

    lineage_before = lineage()
    source_normalized_before = [tuple(row) for row in test_db.execute(
        'SELECT * FROM question_original_items WHERE question_bank_id=? ORDER BY id', (source,),
    )]
    position = test_db.execute("INSERT INTO job_positions(name) VALUES ('retained-position')").lastrowid
    test_db.execute('INSERT INTO question_position(question_id,position_id) VALUES (?,?)', (source, position))
    owner = 8801 if scope == 'private' else None
    iid = test_db.execute("INSERT INTO interview(owner_id,status) VALUES (?,'approved')", (owner,)).lastrowid
    did = test_db.execute("INSERT INTO questions_detail(interview_id,owner_id,question) VALUES (?,?,'SOURCE_ORIGINAL')", (iid, owner)).lastrowid
    rid = test_db.execute(
        "INSERT INTO question_resolutions(detail_id,occurrence_scope,occurrence_owner_id,canonical_id,canonical_scope,status,pipeline_version,invalidated_at) "
        "VALUES (?,?,?,?,'public','matched','review',?)", (did, scope, owner, source, '2020-01-01' if historical else None),
    ).lastrowid
    test_db.execute("INSERT INTO user_question_view(user_id,question_bank_id,user_answer) VALUES (8801,?,'PRIVATE_NOTE')", (source,))
    test_db.execute("INSERT INTO user_question_review(user_id,question_bank_id,review_count) VALUES (8801,?,3)", (source,))
    test_db.commit()
    details_before = dict(test_db.execute('SELECT * FROM questions_detail WHERE id=?', (did,)).fetchone())
    calls = []

    async def model_response(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            return json.dumps({'matches': [{'new_id': source, 'cluster_id': target, 'confidence': 0.99}]})
        return json.dumps({'validations': [{'new_id': source, 'cluster_id': target, 'valid': True, 'confidence': 0.99}]})

    monkeypatch.setattr(compact, '_call_llm_with_retry', model_response)
    monkeypatch.setattr(matcher, '_call_llm_with_retry', model_response)
    response = client.post('/api/master-bank/compact?match_existing=true', headers=actors(8802))
    assert response.status_code == 200, response.text
    events = [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith('data: ')]
    final = next((event for event in events if event.get('type') == 'done'), None)
    assert final is not None, response.text
    assert final['matched_to_existing'] == 1
    tombstone = test_db.execute('SELECT * FROM question_bank WHERE id=?', (source,)).fetchone()
    assert tombstone is not None and tombstone['deleted_at'] is not None
    assert test_db.execute('SELECT COUNT(*) FROM question_position WHERE question_id=? AND position_id=?', (source, position)).fetchone()[0] == 1
    assert test_db.execute('SELECT invalidated_at FROM question_resolutions WHERE id=?', (rid,)).fetchone()[0] is not None
    assert dict(test_db.execute('SELECT * FROM questions_detail WHERE id=?', (did,)).fetchone()) == details_before
    assert test_db.execute('SELECT user_answer FROM user_question_view WHERE question_bank_id=?', (source,)).fetchone()[0] == 'PRIVATE_NOTE'
    assert test_db.execute('SELECT review_count FROM user_question_review WHERE question_bank_id=?', (source,)).fetchone()[0] == 3
    hid = test_db.execute('SELECT id FROM merge_history WHERE survivor_id=?', (target,)).fetchone()[0]
    assert client.post(f'/api/master-bank/merge-rollback/{hid}', headers=actors(8802)).status_code == 200
    assert test_db.execute('SELECT deleted_at FROM question_bank WHERE id=?', (source,)).fetchone()[0] is None
    assert lineage() == lineage_before
    assert [tuple(row) for row in test_db.execute(
        'SELECT * FROM question_original_items WHERE question_bank_id=? ORDER BY id', (source,),
    )] == source_normalized_before
    assert test_db.execute('SELECT COUNT(*) FROM question_position WHERE question_id=? AND position_id=?', (source, position)).fetchone()[0] == 1
    assert test_db.execute('PRAGMA foreign_key_check').fetchall() == []
