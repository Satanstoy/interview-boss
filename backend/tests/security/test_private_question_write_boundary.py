"""Real HTTP routes, JWT authentication and isolated SQLite ownership checks."""

import json

import pytest

from app.core.auth import create_access_token


OPERATIONS = ("delete", "batch-delete", "restore", "batch-restore")


@pytest.fixture
def actors(client, test_db):
    for uid, admin in ((801, 1), (802, 0), (803, 0)):
        test_db.execute(
            "INSERT INTO users (id, username, password_hash, is_admin) VALUES (?, ?, ?, ?)",
            (uid, f"boundary-{uid}", "TEST_HASH_PLACEHOLDER", admin),
        )
    test_db.commit()

    def headers(uid):
        token = create_access_token({"user_id": uid, "type": "access"})
        return {"Authorization": f"Bearer {token}", "X-Requested-With": "XMLHttpRequest"}

    # Authentication initializes each user's default position; finish that setup
    # before taking snapshots of the state protected by the write boundary.
    for uid in (801, 802, 803):
        assert client.get("/api/auth/me", headers=headers(uid)).status_code == 200

    return headers


def seed_question(db, owner, deleted=False, variant="原题"):
    qid = db.execute(
        "INSERT INTO question_bank (question, owner_id, status, deleted_at, updated_at, "
        "original_questions, original_question_sources, sources, job_position, question_manually_edited) "
        "VALUES (?, ?, 'approved', ?, '2020-01-01', ?, '[]', '[]', 'boundary-unconfigured', 1)",
        (variant, owner, "2020-01-01" if deleted else None, json.dumps([variant])),
    ).lastrowid
    db.commit()
    return qid


def snapshot(db):
    # Include normalized projections, review jobs, details and audit rows as well.
    return tuple(db.iterdump())


def request(client, headers, operation, ids):
    if operation == "delete":
        return client.delete(f"/api/master-bank/{ids[0]}", headers=headers)
    if operation == "restore":
        return client.post(f"/api/master-bank/restore/{ids[0]}", headers=headers)
    return client.post(f"/api/master-bank/{operation}", json={"ids": ids}, headers=headers)


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("actor", (801, 803))
def test_foreign_private_write_is_hidden_and_unchanged(client, test_db, actors, operation, actor):
    qid = seed_question(test_db, 802, deleted="restore" in operation)
    before = snapshot(test_db)
    denied = request(client, actors(actor), operation, [qid])
    assert snapshot(test_db) == before
    missing = request(client, actors(actor), operation, [999999])
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json()


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("actor,owner", ((802, 802), (801, None), (801, 801)))
def test_owner_and_public_admin_writes_succeed(client, test_db, actors, operation, actor, owner):
    qids = [seed_question(test_db, owner, deleted="restore" in operation)]
    if operation.startswith("batch"):
        qids.append(seed_question(test_db, owner, deleted="restore" in operation, variant="第二题"))
    response = request(client, actors(actor), operation, qids)
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "success"
    if operation.startswith("batch"):
        key = "restored" if "restore" in operation else "deleted"
        assert response.json()[key] == len(qids)
    for qid in qids:
        row = test_db.execute("SELECT deleted_at FROM question_bank WHERE id = ?", (qid,)).fetchone()
        assert (row["deleted_at"] is None) == ("restore" in operation)


@pytest.mark.parametrize("operation", OPERATIONS)
def test_regular_user_cannot_write_public_question(client, test_db, actors, operation):
    qid = seed_question(test_db, None, deleted="restore" in operation)
    before = snapshot(test_db)
    response = request(client, actors(802), operation, [qid])
    assert response.status_code == 403
    assert snapshot(test_db) == before


@pytest.mark.parametrize("operation", ("batch-delete", "batch-restore"))
@pytest.mark.parametrize("actor", (801, 803))
@pytest.mark.parametrize("foreign_in_target_state", (True, False))
@pytest.mark.parametrize("foreign_first", (True, False))
def test_mixed_batch_is_atomic_even_with_inactive_foreign_id(
    client, test_db, actors, operation, actor, foreign_in_target_state, foreign_first
):
    restoring = "restore" in operation
    allowed = seed_question(test_db, None if actor == 801 else actor, deleted=restoring)
    foreign = seed_question(
        test_db, 802, deleted=restoring if foreign_in_target_state else not restoring
    )
    ids = [foreign, allowed] if foreign_first else [allowed, foreign]
    before = snapshot(test_db)
    response = request(client, actors(actor), operation, ids)
    assert snapshot(test_db) == before
    assert response.status_code == 404
    missing = request(client, actors(actor), operation, [999999])
    assert response.json() == missing.json()


@pytest.mark.parametrize("operation", ("delete-original-question", "split-question", "merge-source", "merge-target", "re-tag"))
def test_equivalent_admin_write_entries_reject_foreign_private_rows(
    client, test_db, actors, operation
):
    foreign = seed_question(test_db, 802)
    public = seed_question(test_db, None, variant="公共原题")
    before = snapshot(test_db)
    headers = actors(801)
    if operation.startswith("merge"):
        source, target = (foreign, public) if operation == "merge-source" else (public, foreign)
        response = client.post(
            f"/api/master-bank/merge-question/{source}",
            json={"original_question": "原题" if source == foreign else "公共原题", "target_id": target},
            headers=headers,
        )
    else:
        response = client.post(
            f"/api/master-bank/{operation}/{foreign}",
            json={"original_question": "原题"}, headers=headers,
        )
    assert snapshot(test_db) == before
    assert response.status_code == 404, response.text


@pytest.mark.parametrize("foreign_role", ("survivor", "merged"))
@pytest.mark.parametrize("already_rolled_back", (False, True))
def test_merge_rollback_cannot_write_foreign_private_question(
    client, test_db, actors, foreign_role, already_rolled_back
):
    foreign = seed_question(test_db, 802)
    public = seed_question(test_db, None, variant="公共原题")
    survivor, merged = (foreign, public) if foreign_role == "survivor" else (public, foreign)
    history = test_db.execute(
        "INSERT INTO merge_history (survivor_id, merged_ids, merged_questions, pre_snapshot, is_rolled_back) "
        "VALUES (?, ?, ?, ?, ?)",
        (survivor, json.dumps([merged]), json.dumps(["原题"]),
         json.dumps({"question": "回滚题"}), already_rolled_back),
    ).lastrowid
    test_db.commit()
    before = snapshot(test_db)
    response = client.post(f"/api/master-bank/merge-rollback/{history}", headers=actors(801))
    assert snapshot(test_db) == before
    assert response.status_code == 404


def test_rollback_rejects_foreign_private_snapshot_of_current_public_question(client, test_db, actors):
    public = seed_question(test_db, None)
    history = test_db.execute(
        "INSERT INTO merge_history (survivor_id, merged_ids, merged_questions, pre_snapshot) "
        "VALUES (?, '[]', '[]', ?)",
        (public, json.dumps({"question": "私人快照", "owner_id": 802})),
    ).lastrowid
    test_db.commit()
    before = snapshot(test_db)
    response = client.post(f"/api/master-bank/merge-rollback/{history}", headers=actors(801))
    assert snapshot(test_db) == before
    assert response.status_code == 404


@pytest.mark.parametrize("endpoint", ("clustering-maintenance", "fix-lone-islands"))
@pytest.mark.parametrize("dry_run", (True, False))
def test_admin_maintenance_only_reads_and_writes_public_questions(
    client, test_db, actors, endpoint, dry_run
):
    foreign = seed_question(test_db, 802, variant="重复题")
    foreign_marker = seed_question(test_db, 802, variant="PRIVATE_MAINTENANCE_MARKER")
    public = seed_question(test_db, None, variant="重复题")
    test_db.execute("UPDATE question_bank SET frequency = 99")
    test_db.commit()
    private_before = [tuple(row) for row in test_db.execute(
        "SELECT * FROM question_bank WHERE owner_id = 802 ORDER BY id"
    )]
    response = client.post(
        f"/api/master-bank/{endpoint}",
        params={"dry_run": str(dry_run).lower()}, headers=actors(801),
    )
    assert response.status_code == 200, response.text
    assert [tuple(row) for row in test_db.execute(
        "SELECT * FROM question_bank WHERE owner_id = 802 ORDER BY id"
    )] == private_before
    for table in ("question_sources", "question_original_items", "cluster_review_state", "cluster_review_tasks"):
        column = "cluster_id" if table.startswith("cluster_review") else "question_bank_id"
        assert test_db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE {column} IN (?, ?)", (foreign, foreign_marker)
        ).fetchone()[0] == 0
    assert "PRIVATE_MAINTENANCE_MARKER" not in response.text
    if not dry_run:
        assert test_db.execute(
            "SELECT frequency FROM question_bank WHERE id = ?", (public,)
        ).fetchone()[0] == 1


def test_admin_category_normalization_does_not_write_foreign_private_question(client, test_db, actors):
    foreign = seed_question(test_db, 802)
    public = seed_question(test_db, None)
    test_db.execute("UPDATE question_bank SET cat1 = 'C. 计算机基础', cat2 = 'C1. 编程语言基础'")
    test_db.commit()
    before = tuple(test_db.execute("SELECT * FROM question_bank WHERE id = ?", (foreign,)).fetchone())
    response = client.post("/api/normalize-categories", headers=actors(801))
    assert response.status_code == 200, response.text
    assert tuple(test_db.execute("SELECT * FROM question_bank WHERE id = ?", (foreign,)).fetchone()) == before
    assert test_db.execute("SELECT cat1 FROM question_bank WHERE id = ?", (public,)).fetchone()[0] == "C.计算机基础"
