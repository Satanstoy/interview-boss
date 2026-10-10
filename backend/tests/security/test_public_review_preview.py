"""Review preview through real authenticated HTTP and isolated SQLite."""
import json

import pytest
from tests.security.test_question_bank_spec_alignment import actors as _actors_fixture

actors = _actors_fixture


@pytest.fixture
def contribution(test_db, actors):
    source = {'company': 'PRIVATE_COMPANY', 'round': 'PRIVATE_ROUND', 'source_url': 'https://private.example/source', 'focus': 'network'}
    items = [{'question': 'FIRST_QUESTION', 'cat1': 'network', 'cat2': 'TCP', 'tags': ['tcp'], 'difficulty': '中等'},
             {'question': 'EXCLUDED_QUESTION', 'cat1': 'network', 'cat2': 'TCP'}]
    rid = test_db.execute("INSERT INTO public_contribution_requests(source_type,source_id,requester_id,status,snapshot_json,revision) VALUES ('interview',1,8801,'pending_review',?,7)", (json.dumps({'source': source, 'items': items}),)).lastrowid
    ids = []
    for ordinal, item in enumerate(items):
        ids.append(test_db.execute("INSERT INTO public_contribution_items(request_id,source_item_type,source_item_id,ordinal,status,snapshot_json) VALUES (?,'question',?,?,'pending_review',?)", (rid, ordinal + 1, ordinal, json.dumps(item))).lastrowid)
    test_db.commit()
    return rid, ids


def test_review_detail_exposes_revision(client, actors, contribution):
    rid, _ = contribution
    response = client.get(f'/api/admin/public-contributions/{rid}', headers=actors(8802))
    assert response.status_code == 200
    assert response.json()['revision'] == 7


@pytest.mark.parametrize("delete_metadata", [False, True])
def test_preview_preserves_or_explicitly_deletes_metadata_without_writing(client, test_db, actors, contribution, delete_metadata):
    rid, ids = contribution
    before = tuple(test_db.iterdump())
    response = client.post(f'/api/admin/public-contributions/{rid}/preview', headers=actors(8802), json={
        'expected_revision': 7, 'excluded_item_ids': [ids[1]],
        'review_fields': {'source': {'company': None, 'round': None} if delete_metadata else {}, 'items': [{'item_id': ids[0], 'question': 'PUBLIC_EDIT', 'tags': ['http']}]} })
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['revision'] == 7
    assert result['projection']['source']['company'] == (None if delete_metadata else 'PRIVATE_COMPANY')
    assert result['projection']['source']['round'] == (None if delete_metadata else 'PRIVATE_ROUND')
    assert result['projection']['source']['source_url'] is None
    assert [row['question'] for row in result['projection']['items']] == ['PUBLIC_EDIT']
    assert result['projection']['items'][0]['tags'] == 'http'
    assert ('PRIVATE_COMPANY' in response.text) is not delete_metadata
    assert 'source_snapshot_unchanged' not in result['projection']
    assert tuple(test_db.iterdump()) == before


@pytest.mark.parametrize('payload,status', [({'expected_revision': 6}, 409),
    ({'expected_revision': 7, 'excluded_item_ids': [99999]}, 400),
    ({'expected_revision': 7, 'review_fields': {'source': {'owner_id': None}}}, 422),
    ({}, 422)])
def test_invalid_preview_is_rejected_atomically(client, test_db, actors, contribution, payload, status):
    rid, _ = contribution
    before = tuple(test_db.iterdump())
    response = client.post(f'/api/admin/public-contributions/{rid}/preview', headers=actors(8802), json=payload)
    assert response.status_code == status, response.text
    assert tuple(test_db.iterdump()) == before


def test_preview_requires_admin(client, actors, contribution):
    rid, _ = contribution
    response = client.post(f'/api/admin/public-contributions/{rid}/preview', headers=actors(8801), json={'expected_revision': 7})
    assert response.status_code == 403


def test_legacy_preview_uses_submitted_snapshot_and_redacts_answer(client, test_db, actors):
    from tests.security.test_question_bank_spec_alignment import question

    private = question(test_db, 8801, 'IMMUTABLE_SUBMITTED_QUESTION')
    test_db.execute("UPDATE question_bank SET ai_answer='PRIVATE_MODEL_ANSWER' WHERE id=?", (private,))
    test_db.commit()
    pending = client.post(f'/api/master-bank/{private}/share', headers=actors(8801)).json()['pending_id']
    test_db.execute("UPDATE question_bank SET question='CHANGED_PRIVATE_QUESTION' WHERE id=?", (private,))
    test_db.commit()
    before = tuple(test_db.iterdump())
    response = client.get(f'/api/master-bank/pending/{pending}/preview', headers=actors(8802))
    assert response.status_code == 200, response.text
    assert response.json()['projection']['question'] == 'IMMUTABLE_SUBMITTED_QUESTION'
    assert response.json()['projection']['ai_answer'] is None
    assert response.json()['projection']['sources'] == '[]'
    assert 'PRIVATE_MODEL_ANSWER' not in response.text
    assert 'CHANGED_PRIVATE_QUESTION' not in response.text
    assert tuple(test_db.iterdump()) == before
    denied = client.get(f'/api/master-bank/pending/{private}/preview', headers=actors(8802))
    missing = client.get('/api/master-bank/pending/999999/preview', headers=actors(8802))
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json()


def test_jd_preview_matches_approved_projection(client, test_db, actors):
    jd = test_db.execute("INSERT INTO jd(url,owner_id,status,company,job_title,tech_stack) VALUES ('https://private.example/jd',8801,'approved','PRIVATE_COMPANY','PRIVATE_JOB','Python')").lastrowid
    test_db.commit()
    created = client.post('/api/public-contributions', headers=actors(8801), json={'source_type': 'jd', 'source_id': jd})
    assert created.status_code == 200, created.text
    rid = created.json()['id']
    detail = client.get(f'/api/admin/public-contributions/{rid}', headers=actors(8802)).json()
    payload = {'expected_revision': detail['revision'], 'review_fields': {'source': {'company': None, 'job_title': 'PUBLIC_JOB', 'source_url': None}}}
    preview = client.post(f'/api/admin/public-contributions/{rid}/preview', headers=actors(8802), json=payload)
    assert preview.status_code == 200, preview.text
    approved = client.post(f'/api/admin/public-contributions/{rid}/approve', headers=actors(8802), json=payload)
    assert approved.status_code == 200, approved.text
    stored = json.loads(test_db.execute('SELECT review_projection_json FROM public_contribution_requests WHERE id=?', (rid,)).fetchone()[0])
    assert stored['hash'] == preview.json()['projection']['hash']
    assert stored['source'] == preview.json()['projection']['source']
    public = test_db.execute('SELECT company,job_title FROM jd WHERE id=?', (approved.json()['public_jd_id'],)).fetchone()
    assert public['company'] in (None, '')
    assert public['job_title'] == 'PUBLIC_JOB'


@pytest.mark.parametrize('source_fields,expected', [({}, None), ({'salary': 'PUBLIC_SALARY'}, 'PUBLIC_SALARY'), ({'salary': None}, None)])
def test_jd_salary_requires_explicit_confirmation(client, test_db, actors, source_fields, expected):
    jd = test_db.execute("INSERT INTO jd(url,owner_id,status,company,job_title,salary) VALUES ('https://private.example/salary',8801,'approved','PRIVATE_COMPANY','ROLE','PRIVATE_SALARY')").lastrowid
    test_db.commit()
    response = client.post('/api/public-contributions', headers=actors(8801), json={'source_type': 'jd', 'source_id': jd})
    assert response.status_code == 200, response.text
    rid = response.json()['id']
    detail = client.get(f'/api/admin/public-contributions/{rid}', headers=actors(8802)).json()
    payload = {'expected_revision': detail['revision'], 'review_fields': {'source': source_fields}}
    preview = client.post(f'/api/admin/public-contributions/{rid}/preview', headers=actors(8802), json=payload)
    assert preview.status_code == 200, preview.text
    assert preview.json()['projection']['source']['salary'] == expected
    assert 'PRIVATE_SALARY' not in preview.text
    approved = client.post(f'/api/admin/public-contributions/{rid}/approve', headers=actors(8802), json=payload)
    assert approved.status_code == 200, approved.text
    row = test_db.execute('SELECT salary FROM jd WHERE id=?', (approved.json()['public_jd_id'],)).fetchone()
    assert row['salary'] == expected or (expected is None and row['salary'] == '')
    assert test_db.execute('SELECT salary FROM jd WHERE id=?', (jd,)).fetchone()[0] == 'PRIVATE_SALARY'


@pytest.mark.parametrize('reuse_public', [False, True])
def test_interview_array_tags_preview_equals_materialized_tags(client, test_db, actors, reuse_public):
    source = test_db.execute("INSERT INTO interview(url,owner_id,status,job_position,questions_list) VALUES ('https://private.example/tags',8801,'approved','alignment-position','TAG_QUESTION')").lastrowid
    test_db.execute("INSERT INTO questions_detail(interview_id,question,cat1,cat2,tags,owner_id,job_position) VALUES (?,'TAG_QUESTION','network','TCP','private-tag',8801,'alignment-position')", (source,))
    if reuse_public:
        test_db.execute("INSERT INTO interview(url,owner_id,status,job_position) VALUES ('https://review.example/public',NULL,'approved','alignment-position')")
    test_db.commit()
    created = client.post('/api/public-contributions', headers=actors(8801), json={'source_type': 'interview', 'source_id': source})
    assert created.status_code == 200, created.text
    rid = created.json()['id']
    detail = client.get(f'/api/admin/public-contributions/{rid}', headers=actors(8802)).json()
    item = detail['items'][0]['id']
    payload = {'expected_revision': detail['revision'], 'review_fields': {
        'source': {'source_url': 'https://review.example/public'},
        'items': [{'item_id': item, 'tags': ['tcp', 'http']}]}}
    preview = client.post(f'/api/admin/public-contributions/{rid}/preview', headers=actors(8802), json=payload)
    assert preview.status_code == 200, preview.text
    approved = client.post(f'/api/admin/public-contributions/{rid}/approve', headers=actors(8802), json=payload)
    assert approved.status_code == 200, approved.text
    result = test_db.execute('SELECT public_detail_id FROM public_contribution_items WHERE id=?', (item,)).fetchone()[0]
    tags = test_db.execute('SELECT tags FROM questions_detail WHERE id=?', (result,)).fetchone()[0]
    assert tags == preview.json()['projection']['items'][0]['tags'] == 'tcp, http'
    stored = json.loads(test_db.execute('SELECT review_projection_json FROM public_contribution_requests WHERE id=?', (rid,)).fetchone()[0])
    assert stored['hash'] == preview.json()['projection']['hash']
    assert test_db.execute('SELECT tags FROM questions_detail WHERE interview_id=?', (source,)).fetchone()[0] == 'private-tag'
