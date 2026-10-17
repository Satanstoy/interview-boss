"""Push review regressions through real HTTP, JWT and isolated SQLite."""

import json

import pytest

from tests.security.test_question_bank_spec_alignment import actors as _actors_fixture

actors = _actors_fixture


def seed_source(db, table, owner, *, deleted=False, suffix="one"):
    url = f"https://boundary.example/{suffix}"
    iid = db.execute(
        "INSERT INTO interview(url,owner_id,status,job_position,deleted_at) "
        "VALUES (?,?,'approved','review-position',?)",
        (url, owner, "2020-01-01" if deleted else None),
    ).lastrowid
    detail = db.execute(
        "INSERT INTO questions_detail(interview_id,question,url,owner_id,deleted_at) "
        "VALUES (?,'PRIVATE_QUESTION',?,?,?)",
        (iid, url, owner, "2020-01-01" if deleted else None),
    ).lastrowid
    sources = [{"url": url, "company": "PRIVATE_COMPANY", "round": "PRIVATE_ROUND"}]
    canonical = db.execute(
        "INSERT INTO question_bank(question,owner_id,status,sources,original_questions,"
        "original_question_sources,job_position,deleted_at) "
        "VALUES ('PRIVATE_QUESTION',?,'approved',?,'[\"PRIVATE_QUESTION\"]',?,'review-position',?)",
        (owner, json.dumps([] if deleted else sources),
         json.dumps([{"question": "PRIVATE_QUESTION", "sources": sources}]),
         "2020-01-01" if deleted else None),
    ).lastrowid
    source_id = iid
    if table == "jd":
        source_id = db.execute(
            "INSERT INTO jd(url,owner_id,status,job_position,deleted_at) "
            "VALUES (?,?,'approved','review-position',?)",
            (url, owner, "2020-01-01" if deleted else None),
        ).lastrowid
    elif table == "tagged":
        source_id = detail
    db.commit()
    return source_id, canonical


@pytest.mark.parametrize("table", ("interview", "jd", "tagged"))
@pytest.mark.parametrize("operation", ("delete", "restore"))
def test_admin_source_mutation_hides_foreign_private_state(
    client, test_db, actors, table, operation
):
    source, _ = seed_source(test_db, table, 8801, deleted=operation == "restore")
    before = tuple(test_db.iterdump())
    if operation == "delete":
        denied = client.delete(f"/api/data/{table}/{source}", headers=actors(8802))
        missing = client.delete(f"/api/data/{table}/999999", headers=actors(8802))
    else:
        denied = client.post(f"/api/data/restore/{table}/{source}", headers=actors(8802))
        missing = client.post(f"/api/data/restore/{table}/999999", headers=actors(8802))
    assert denied.status_code == missing.status_code == 404, denied.text
    assert denied.json() == missing.json()
    assert tuple(test_db.iterdump()) == before


@pytest.mark.parametrize("table", ("interview", "jd", "questions_detail"))
def test_admin_generic_update_cannot_change_foreign_private_source(client, test_db, actors, table):
    source, _ = seed_source(test_db, "tagged" if table == "questions_detail" else table, 8801)
    field = "question" if table == "questions_detail" else "company"
    before = tuple(test_db.iterdump())
    denied = client.put("/api/data/update", headers=actors(8802), json={
        "table_name": table, "record_id": source, "update_data": {field: "CHANGED"}})
    missing = client.put("/api/data/update", headers=actors(8802), json={
        "table_name": table, "record_id": 999999, "update_data": {field: "CHANGED"}})
    assert denied.status_code == missing.status_code == 404, denied.text
    assert denied.json() == missing.json()
    assert tuple(test_db.iterdump()) == before


@pytest.mark.parametrize("table", ("interview", "jd", "questions_detail"))
@pytest.mark.parametrize("owner", (None, 8802))
def test_admin_generic_update_preserves_own_and_public_behavior(client, test_db, actors, table, owner):
    source, _ = seed_source(test_db, "tagged" if table == "questions_detail" else table, owner)
    field = "question" if table == "questions_detail" else "company"
    result = client.put("/api/data/update", headers=actors(8802), json={
        "table_name": table, "record_id": source, "update_data": {field: "CHANGED"}})
    assert result.status_code == 200, result.text


@pytest.mark.parametrize("table", ("interview", "jd"))
@pytest.mark.parametrize("foreign_first", (False, True))
@pytest.mark.parametrize("foreign_deleted", (False, True))
def test_admin_mixed_source_delete_is_atomic(client, test_db, actors, table, foreign_first, foreign_deleted):
    allowed, _ = seed_source(test_db, table, None, suffix="public")
    foreign, _ = seed_source(test_db, table, 8801, suffix="private", deleted=foreign_deleted)
    before = tuple(test_db.iterdump())
    ids = [foreign, allowed] if foreign_first else [allowed, foreign]
    denied = client.post("/api/data/batch-delete", headers=actors(8802),
                         json={"file_type": table, "ids": ids})
    missing = client.post("/api/data/batch-delete", headers=actors(8802),
                          json={"file_type": table, "ids": [999999]})
    assert denied.status_code == missing.status_code == 404, denied.text
    assert denied.json() == missing.json()
    assert tuple(test_db.iterdump()) == before


@pytest.mark.parametrize("table", ("interview", "jd"))
@pytest.mark.parametrize("owner", (None, 8802))
def test_admin_can_batch_delete_own_and_public_sources(client, test_db, actors, table, owner):
    source, _ = seed_source(test_db, table, owner)
    result = client.post("/api/data/batch-delete", headers=actors(8802),
                         json={"file_type": table, "ids": [source]})
    assert result.status_code == 200, result.text
    assert result.json()["deleted"] == 1


@pytest.mark.parametrize("table", ("interview", "jd", "tagged"))
@pytest.mark.parametrize("owner,expected", ((8801, 200), (8803, 404)))
def test_regular_source_delete_obeys_ownership(client, test_db, actors, table, owner, expected):
    source, _ = seed_source(test_db, table, owner)
    before = tuple(test_db.iterdump())
    result = client.delete(f"/api/data/{table}/{source}", headers=actors(8801))
    assert result.status_code == expected, result.text
    if expected == 404:
        assert tuple(test_db.iterdump()) == before


@pytest.mark.parametrize("table", ("interview", "jd", "tagged"))
@pytest.mark.parametrize("owner", (None, 8802))
@pytest.mark.parametrize("operation", ("delete", "restore"))
def test_admin_own_and_public_source_mutations_remain_available(
    client, test_db, actors, table, owner, operation
):
    source, _ = seed_source(test_db, table, owner, deleted=operation == "restore")
    if operation == "delete":
        result = client.delete(f"/api/data/{table}/{source}", headers=actors(8802))
    else:
        result = client.post(f"/api/data/restore/{table}/{source}", headers=actors(8802))
    assert result.status_code == 200, result.text


@pytest.mark.parametrize("operation", ("delete", "batch-delete"))
def test_public_canonical_delete_invalidates_resolutions_in_same_transaction(
    client, test_db, actors, operation
):
    _, qid = seed_source(test_db, "interview", None)
    private_interview = test_db.execute(
        "INSERT INTO interview(owner_id,status) VALUES (8801,'approved')"
    ).lastrowid
    detail = test_db.execute(
        "INSERT INTO questions_detail(interview_id,owner_id,question) VALUES (?,8801,'Q')",
        (private_interview,),
    ).lastrowid
    test_db.execute(
        "INSERT INTO question_resolutions(detail_id,occurrence_scope,occurrence_owner_id,"
        "canonical_id,canonical_scope,status,pipeline_version) "
        "VALUES (?,'private',8801,?,'public','matched','review')", (detail, qid),
    )
    test_db.commit()
    if operation == "delete":
        result = client.delete(f"/api/master-bank/{qid}", headers=actors(8802))
    else:
        result = client.post("/api/master-bank/batch-delete", headers=actors(8802),
                             json={"ids": [qid]})
    assert result.status_code == 200, result.text
    resolution = test_db.execute(
        "SELECT invalidated_at FROM question_resolutions WHERE detail_id=?", (detail,)
    ).fetchone()
    assert resolution["invalidated_at"] is not None
    assert test_db.execute("SELECT deleted_at FROM questions_detail WHERE id=?", (detail,)).fetchone()[0] is None


@pytest.mark.parametrize("operation", ("delete", "batch-delete"))
def test_canonical_delete_rolls_back_when_resolution_write_fails(client, test_db, actors, operation):
    _, qid = seed_source(test_db, "interview", None)
    test_db.execute(
        "CREATE TRIGGER fail_resolution_invalidation BEFORE UPDATE ON question_resolutions "
        "BEGIN SELECT RAISE(ABORT,'TEST_RESOLUTION_FAILURE'); END"
    )
    detail = test_db.execute("SELECT id FROM questions_detail ORDER BY id LIMIT 1").fetchone()[0]
    test_db.execute(
        "INSERT INTO question_resolutions(detail_id,occurrence_scope,canonical_id,"
        "canonical_scope,status,pipeline_version) VALUES (?,'public',?,'public','matched','review')",
        (detail, qid),
    )
    test_db.commit()
    before = tuple(test_db.iterdump())
    if operation == "delete":
        result = client.delete(f"/api/master-bank/{qid}", headers=actors(8802))
    else:
        result = client.post("/api/master-bank/batch-delete", headers=actors(8802), json={"ids": [qid]})
    assert result.status_code == 500, result.text
    assert tuple(test_db.iterdump()) == before


def test_redacted_jds_have_distinct_public_results_and_frozen_positions(client, test_db, actors):
    public_ids = []
    for index in (1, 2):
        position = f"FROZEN_POSITION_{index}"
        source = test_db.execute(
            "INSERT INTO jd(url,owner_id,status,job_title,tech_stack,job_position) "
            "VALUES (?,8801,'approved',?,?,?)",
            (f"https://private.example/jd/{index}", f"ROLE_{index}", f"STACK_{index}", position),
        ).lastrowid
        test_db.commit()
        created = client.post("/api/public-contributions", headers=actors(8801),
                              json={"source_type": "jd", "source_id": source})
        assert created.status_code == 200, created.text
        rid = created.json()["id"]
        payload = {"expected_revision": 1, "review_fields": {"source": {
            "source_url": None, "position": f"REVIEWED_PUBLIC_ROLE_{index}"}}}
        preview = client.post(f"/api/admin/public-contributions/{rid}/preview",
                              headers=actors(8802), json=payload)
        assert preview.status_code == 200, preview.text
        result = client.post(f"/api/admin/public-contributions/{rid}/approve",
                             headers=actors(8802), json=payload)
        assert result.status_code == 200, result.text
        public_id = result.json()["public_jd_id"]
        public_ids.append(public_id)
        public = test_db.execute("SELECT * FROM jd WHERE id=?", (public_id,)).fetchone()
        assert public["job_position"] == position
        assert public["position"] == f"REVIEWED_PUBLIC_ROLE_{index}"
        assert public["job_title"] == preview.json()["projection"]["source"]["job_title"]
        assert public["url"] == ""
    assert public_ids[0] != public_ids[1]
