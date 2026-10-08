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
