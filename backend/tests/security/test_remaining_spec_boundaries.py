"""Expected-spec probes: real JWT/client/SQLite; failures are audit counterexamples."""
import json
import pytest
from tests.security.test_question_bank_spec_alignment import actors as _actors_fixture, question


actors = _actors_fixture

@pytest.mark.parametrize('shape', ['private_survivor', 'private_merged', 'private_snapshot'])
@pytest.mark.parametrize('endpoint', ['list', 'detail'])
def test_private_merge_history_is_not_visible_to_other_admin(client, test_db, actors, shape, endpoint):
    private = question(test_db, 8801, 'PRIVATE_HISTORY_MARKER')
    public = question(test_db, None, 'PUBLIC_HISTORY_QUESTION')
    survivor = private if shape == 'private_survivor' else public
    merged = [private] if shape == 'private_merged' else []
    hid = test_db.execute(
        'INSERT INTO merge_history(survivor_id,merged_ids,merged_questions,pre_snapshot) VALUES (?,?,?,?)',
        (survivor, json.dumps(merged),
         json.dumps(['PRIVATE_HISTORY_MARKER'] if shape == 'private_merged' else []),
         json.dumps({'owner_id': 8801, 'question': 'PRIVATE_HISTORY_MARKER'}
                    if shape == 'private_snapshot' else {'owner_id': None, 'question': 'PUBLIC_HISTORY_QUESTION'})),
    ).lastrowid
    test_db.commit()
    path = '/api/master-bank/merge-history' + (f'/{hid}' if endpoint == 'detail' else '')
    response = client.get(path, headers=actors(8802))
    print('HISTORY_OBSERVATION', json.dumps({'shape':shape,'endpoint':endpoint,'status':response.status_code,
        'private_marker_exposed':'PRIVATE_HISTORY_MARKER' in response.text}))
    assert 'PRIVATE_HISTORY_MARKER' not in response.text
    if endpoint == 'detail':
        assert response.status_code == 404


def test_admin_private_to_public_merge_requires_promotion(client, test_db, actors):
    private = question(test_db, 8802, 'PRIVATE_MERGE_MARKER')
    public = question(test_db, None, 'PUBLIC_MERGE_TARGET')
    test_db.execute('UPDATE question_bank SET original_questions=? WHERE id=?',
                    (json.dumps(['PRIVATE_MERGE_MARKER']), private))
    test_db.commit()
    before = tuple(test_db.iterdump())
    response = client.post(f'/api/master-bank/merge-question/{private}', headers=actors(8802),
        json={'original_question':'PRIVATE_MERGE_MARKER','target_id':public})
    row = test_db.execute('SELECT sources,original_questions FROM question_bank WHERE id=?',(public,)).fetchone()
    approvals = test_db.execute('SELECT COUNT(*) FROM question_promotion_requests').fetchone()[0]
    print('MERGE_OBSERVATION', json.dumps({'status':response.status_code,'public_originals':row['original_questions'],
        'public_sources':row['sources'],'promotion_requests':approvals}))
    assert tuple(test_db.iterdump()) == before
    assert response.status_code in (403,409)


def test_legacy_promotion_does_not_publish_private_model_answer(client, test_db, actors):
    private = question(test_db, 8801, 'LEGACY_ANSWER_QUESTION')
    test_db.execute("UPDATE question_bank SET ai_answer='PRIVATE_USER_MODEL_ANSWER' WHERE id=?",(private,))
    test_db.commit()
    submitted = client.post(f'/api/master-bank/{private}/share',headers=actors(8801))
    assert submitted.status_code == 200, submitted.text
    pending = submitted.json()['pending_id']
    approved = client.post(f'/api/master-bank/approve/{pending}', headers=actors(8802))
    assert approved.status_code == 200, approved.text
    response = client.get(f'/api/master-bank/{pending}/detail', headers=actors(8803))
    print('ANSWER_OBSERVATION', json.dumps({'read_status':response.status_code,
        'private_answer_exposed':'PRIVATE_USER_MODEL_ANSWER' in response.text}))
    assert 'PRIVATE_USER_MODEL_ANSWER' not in response.text


def history(db, survivor, merged=(), pre=None, post=None):
    hid = db.execute(
        'INSERT INTO merge_history(survivor_id,merged_ids,merged_questions,pre_snapshot,post_snapshot) VALUES (?,?,?,?,?)',
        (survivor, json.dumps(list(merged)), '[]', json.dumps(pre or {}), json.dumps(post or {})),
    ).lastrowid
    db.commit()
    return hid


@pytest.mark.parametrize('owner', [None, 8802])
def test_authorized_history_is_visible(client, test_db, actors, owner):
    survivor = question(test_db, owner)
    hid = history(test_db, survivor, pre={'owner_id': owner})
    assert client.get(f'/api/master-bank/merge-history/{hid}', headers=actors(8802)).status_code == 200
    response = client.get('/api/master-bank/merge-history', headers=actors(8802)).json()
    assert response['total'] == 1
    assert [row['id'] for row in response['items']] == [hid]


def test_history_visibility_filters_total_before_pagination(client, test_db, actors):
    hidden = question(test_db, 8801)
    visible = question(test_db, None)
    history(test_db, hidden)
    hid = history(test_db, visible)
    response = client.get('/api/master-bank/merge-history?limit=1&offset=0', headers=actors(8802)).json()
    assert response['total'] == 1
    assert [row['id'] for row in response['items']] == [hid]
    assert client.get('/api/master-bank/merge-history?limit=1&offset=1', headers=actors(8802)).json()['items'] == []


@pytest.mark.parametrize('shape', ['missing_survivor', 'missing_merged', 'post_private', 'malformed_ids'])
def test_unproven_or_private_history_is_hidden(client, test_db, actors, shape):
    public = question(test_db, None)
    hid = history(test_db, public,
                  [999999] if shape == 'missing_merged' else [],
                  post={'owner_id': 8801} if shape == 'post_private' else {})
    if shape == 'missing_survivor':
        test_db.execute('PRAGMA foreign_keys=OFF')
        test_db.execute('UPDATE merge_history SET survivor_id=999999 WHERE id=?', (hid,))
        test_db.commit()
        test_db.execute('PRAGMA foreign_keys=ON')
    if shape == 'malformed_ids':
        test_db.execute("UPDATE merge_history SET merged_ids='invalid' WHERE id=?", (hid,))
        test_db.commit()
    before = tuple(test_db.iterdump())
    missing = client.get('/api/master-bank/merge-history/999999', headers=actors(8802))
    denied = client.get(f'/api/master-bank/merge-history/{hid}', headers=actors(8802))
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json()
    assert client.get('/api/master-bank/merge-history', headers=actors(8802)).json() == {'items': [], 'total': 0}
    assert tuple(test_db.iterdump()) == before


@pytest.mark.parametrize('owners', [(None, 8802), (8802, None)])
def test_cross_scope_merge_is_atomic(client, test_db, actors, owners):
    source = question(test_db, owners[0], 'SCOPE_SOURCE')
    target = question(test_db, owners[1], 'SCOPE_TARGET')
    before = tuple(test_db.iterdump())
    response = client.post(f'/api/master-bank/merge-question/{source}', headers=actors(8802),
                           json={'original_question': 'SCOPE_SOURCE', 'target_id': target})
    assert response.status_code == 409, response.text
    assert tuple(test_db.iterdump()) == before


@pytest.mark.parametrize('owner', [None, 8802, 8801])
def test_same_scope_merge_obeys_ownership(client, test_db, actors, owner):
    source = question(test_db, owner, 'SAME_SCOPE_SOURCE')
    target = question(test_db, owner, 'SAME_SCOPE_TARGET')
    test_db.execute('UPDATE question_bank SET original_questions=? WHERE id=?', (json.dumps(['SAME_SCOPE_SOURCE']), source))
    test_db.commit()
    before = tuple(test_db.iterdump())
    response = client.post(f'/api/master-bank/merge-question/{source}', headers=actors(8802),
                           json={'original_question': 'SAME_SCOPE_SOURCE', 'target_id': target})
    assert response.status_code == (404 if owner == 8801 else 200), response.text
    if owner == 8801:
        assert tuple(test_db.iterdump()) == before


def test_deleted_participant_requires_durable_ownership_proof(client, test_db, actors):
    public = question(test_db, None)
    merged = question(test_db, None, 'DELETED_PUBLIC')
    hid = history(test_db, public, [merged], pre={'owner_id': None,
        'participant_owners': {str(public): None, str(merged): None}})
    test_db.execute('DELETE FROM question_bank WHERE id=?', (merged,))
    test_db.commit()
    assert client.get(f'/api/master-bank/merge-history/{hid}', headers=actors(8802)).status_code == 200
    test_db.execute('UPDATE merge_history SET pre_snapshot=? WHERE id=?',
                    (json.dumps({'owner_id': None, 'participant_owners': {str(public): None, str(merged): 8801}}), hid))
    test_db.commit()
    assert client.get(f'/api/master-bank/merge-history/{hid}', headers=actors(8802)).status_code == 404


def test_promotion_preserves_private_answer_and_existing_global_answer(client, test_db, actors):
    public = question(test_db, None, 'ANSWER_MATCH')
    private = question(test_db, 8801, 'ANSWER_MATCH')
    test_db.execute("UPDATE question_bank SET ai_answer='GLOBAL_REFERENCE' WHERE id=?", (public,))
    test_db.execute("UPDATE question_bank SET ai_answer='PRIVATE_REFERENCE' WHERE id=?", (private,))
    test_db.commit()
    pending = client.post(f'/api/master-bank/{private}/share', headers=actors(8801)).json()['pending_id']
    snapshot = test_db.execute('SELECT snapshot_json FROM question_promotion_requests WHERE pending_question_id=?', (pending,)).fetchone()[0]
    assert client.post(f'/api/master-bank/approve/{pending}', headers=actors(8802)).status_code == 200
    assert test_db.execute('SELECT ai_answer FROM question_bank WHERE id=?', (public,)).fetchone()[0] == 'GLOBAL_REFERENCE'
    assert test_db.execute('SELECT ai_answer FROM question_bank WHERE id=?', (private,)).fetchone()[0] == 'PRIVATE_REFERENCE'
    assert test_db.execute('SELECT snapshot_json FROM question_promotion_requests WHERE pending_question_id=?', (pending,)).fetchone()[0] == snapshot
    assert json.loads(snapshot)['ai_answer'] == 'PRIVATE_REFERENCE'


def test_compaction_records_ownership_before_deleting_participant(client, test_db, actors):
    from app.services.pipeline.compact import _do_merge_to_existing

    survivor = question(test_db, None, 'COMPACT_SURVIVOR')
    merged = question(test_db, None, 'COMPACT_MERGED')
    entry = dict(test_db.execute('SELECT * FROM question_bank WHERE id=?', (merged,)).fetchone())
    _do_merge_to_existing(survivor, entry, confidence=0.95)
    test_db.commit()
    assert test_db.execute('SELECT id FROM question_bank WHERE id=?', (merged,)).fetchone() is None
    row = test_db.execute('SELECT id,pre_snapshot FROM merge_history WHERE survivor_id=?', (survivor,)).fetchone()
    assert json.loads(row['pre_snapshot'])['participant_owners'] == {str(survivor): None, str(merged): None}
    assert client.get(f"/api/master-bank/merge-history/{row['id']}", headers=actors(8802)).status_code == 200
