"""ADR-0048: real HTTP/JWT/SQLite promotion and private-reference behavior."""

import json

import pytest

from app.core.auth import create_access_token
from app.services.question_resolution import record_resolution


@pytest.fixture
def actors(test_db):
    for uid, admin in [(8801, 0), (8802, 1), (8803, 0)]:
        test_db.execute(
            "INSERT INTO users(id,username,password_hash,is_admin) VALUES (?,?,?,?)",
            (uid, f"alignment-{uid}", "TEST_HASH_PLACEHOLDER", admin),
        )
    position = test_db.execute(
        "INSERT INTO job_positions(name) VALUES ('alignment-position')"
    ).lastrowid
    test_db.execute(
        "UPDATE users SET current_position_id=? WHERE id IN (8801,8802,8803)", (position,)
    )
    test_db.commit()
    return lambda uid: {
        "Authorization": "Bearer " + create_access_token({"user_id": uid, "type": "access"}),
        "X-Requested-With": "XMLHttpRequest",
    }


def question(db, owner, text="TCP_CANONICAL", status="approved"):
    qid = db.execute(
        "INSERT INTO question_bank(question,cat1,cat2,tags,owner_id,status,job_position,"
        "sources,original_questions,original_question_sources,frequency) "
        "VALUES (?,'network','TCP','transport',?,?,'alignment-position',?,'[]','[]',1)",
        (
            text,
            owner,
            status,
            json.dumps([{"url": "private://source", "company": "PRIVATE_COMPANY"}])
            if owner
            else "[]",
        ),
    ).lastrowid
    pos = db.execute("SELECT id FROM job_positions WHERE name='alignment-position'").fetchone()[0]
    db.execute("INSERT INTO question_position(question_id,position_id) VALUES (?,?)", (qid, pos))
    db.commit()
    return qid


def promotion(db, pending_id):
    assert db.execute(
        "SELECT 1 FROM sqlite_master WHERE name='question_promotion_requests'"
    ).fetchone(), "promotion snapshot must be durable"
    return db.execute(
        "SELECT * FROM question_promotion_requests WHERE pending_question_id=?", (pending_id,)
    ).fetchone()


def share(client, headers, qid):
    return client.post(f"/api/master-bank/{qid}/share", headers=headers(8801))


def test_matching_public_question_still_requires_review(client, test_db, actors):
    public = question(test_db, None)
    private = question(test_db, 8801)
    before = dict(test_db.execute("SELECT * FROM question_bank WHERE id=?", (public,)).fetchone())
    response = share(client, actors, private)
    assert response.status_code == 200
    assert response.json()["result"] == "pending"
    assert (
        dict(test_db.execute("SELECT * FROM question_bank WHERE id=?", (public,)).fetchone())
        == before
    )
    assert (
        test_db.execute("SELECT deleted_at FROM question_bank WHERE id=?", (private,)).fetchone()[0]
        is None
    )
    assert promotion(test_db, response.json()["pending_id"])["source_question_id"] == private


def test_duplicate_share_reuses_immutable_snapshot(client, test_db, actors):
    private = question(test_db, 8801)
    first = share(client, actors, private).json()
    second = share(client, actors, private).json()
    assert second == first
    row = promotion(test_db, first["pending_id"])
    snapshot = row["snapshot_json"]
    test_db.execute(
        "UPDATE question_bank SET question=? WHERE id=?", ("EDITED_PRIVATE_VERSION", private)
    )
    test_db.commit()
    assert promotion(test_db, first["pending_id"])["snapshot_json"] == snapshot
    pending = test_db.execute(
        "SELECT question FROM question_bank WHERE id=?", (first["pending_id"],)
    ).fetchone()
    assert pending[0] == "TCP_CANONICAL"


@pytest.mark.parametrize("uid", [8802, 8803])
def test_other_owner_share_uses_non_disclosing_404(client, test_db, actors, uid):
    private = question(test_db, 8801)
    before = dict(test_db.execute("SELECT * FROM question_bank WHERE id=?", (private,)).fetchone())
    denied = client.post(f"/api/master-bank/{private}/share", headers=actors(uid))
    missing = client.post("/api/master-bank/999999/share", headers=actors(uid))
    assert denied.status_code == missing.status_code == 404
    assert denied.json() == missing.json()
    assert (
        dict(test_db.execute("SELECT * FROM question_bank WHERE id=?", (private,)).fetchone())
        == before
    )


def test_unified_review_lists_legacy_pending_and_respects_type(client, test_db, actors):
    pending = share(client, actors, question(test_db, 8801)).json()["pending_id"]
    response = client.get("/api/admin/public-contributions", headers=actors(8802)).json()
    assert response["total"] == len(response["items"]) == 1
    item = response["items"][0]
    assert item["id"] == pending and item["legacy"] is True
    assert item["source_type"] == "interview"
    assert item["summary"]["question_previews"][0]["question"] == "TCP_CANONICAL"
    jd = client.get("/api/admin/public-contributions?source_type=jd", headers=actors(8802)).json()
    assert jd["total"] == 0 and jd["items"] == []
    assert client.get("/api/admin/public-contributions", headers=actors(8801)).status_code == 403


def test_approval_only_retires_exact_submitted_source_and_hides_private_metadata(
    client, test_db, actors
):
    public = question(test_db, None)
    private = question(test_db, 8801)
    unrelated = question(test_db, 8801)
    pending = share(client, actors, private).json().get("pending_id")
    assert pending, "share must create a pending review even on public match"
    result = client.post(f"/api/master-bank/approve/{pending}", headers=actors(8802))
    assert result.status_code == 200, result.text
    p = promotion(test_db, pending)
    assert p["status"] == "approved" and p["target_question_id"] == public
    assert p["reviewer_id"] == 8802
    assert test_db.execute(
        "SELECT deleted_at FROM question_bank WHERE id=?", (private,)
    ).fetchone()[0]
    assert (
        test_db.execute("SELECT deleted_at FROM question_bank WHERE id=?", (unrelated,)).fetchone()[
            0
        ]
        is None
    )
    source = test_db.execute("SELECT sources FROM question_bank WHERE id=?", (public,)).fetchone()[
        0
    ]
    assert "PRIVATE_COMPANY" not in source and "private://source" not in source
    before = dict(test_db.execute("SELECT * FROM question_bank WHERE id=?", (public,)).fetchone())
    assert (
        client.post(f"/api/master-bank/approve/{pending}", headers=actors(8802)).status_code == 200
    )
    assert (
        dict(test_db.execute("SELECT * FROM question_bank WHERE id=?", (public,)).fetchone())
        == before
    )


def test_changed_private_version_is_not_retired_by_old_snapshot_approval(client, test_db, actors):
    private = question(test_db, 8801)
    pending = share(client, actors, private).json()["pending_id"]
    test_db.execute(
        "UPDATE question_bank SET question=? WHERE id=?", ("EDITED_PRIVATE_VERSION", private)
    )
    test_db.commit()
    assert (
        client.post(f"/api/master-bank/approve/{pending}", headers=actors(8802)).status_code == 200
    )
    assert (
        test_db.execute("SELECT deleted_at FROM question_bank WHERE id=?", (private,)).fetchone()[0]
        is None
    )
    assert promotion(test_db, pending)["snapshot_json"]


def test_reject_keeps_private_and_rejected_cannot_be_approved(client, test_db, actors):
    private = question(test_db, 8801)
    pending = share(client, actors, private).json()["pending_id"]
    assert (
        client.post(f"/api/master-bank/reject/{pending}", headers=actors(8802)).status_code == 200
    )
    assert promotion(test_db, pending)["status"] == "rejected"
    assert (
        client.post(f"/api/master-bank/approve/{pending}", headers=actors(8802)).status_code == 409
    )
    assert (
        test_db.execute("SELECT deleted_at FROM question_bank WHERE id=?", (private,)).fetchone()[0]
        is None
    )


@pytest.mark.parametrize("invalid", [None, "resolution", "detail", "interview", "other_owner"])
def test_mine_references_public_canonical_only_through_live_owned_occurrences(
    client, test_db, actors, invalid
):
    public = question(test_db, None)
    interview = test_db.execute(
        "INSERT INTO interview(url,owner_id,status,job_position) VALUES ('private://mine',8801,'approved','alignment-position')"
    ).lastrowid
    detail = test_db.execute(
        "INSERT INTO questions_detail(interview_id,question,owner_id,status,job_position) VALUES (?,'TCP_CANONICAL',8801,'approved','alignment-position')",
        (interview,),
    ).lastrowid
    record_resolution(
        test_db,
        detail_id=detail,
        occurrence_scope="private",
        occurrence_owner_id=8801,
        canonical_id=public,
        canonical_scope="public",
        status="matched",
        pipeline_version="alignment-v1",
    )
    if invalid == "resolution":
        test_db.execute(
            "UPDATE question_resolutions SET invalidated_at=CURRENT_TIMESTAMP WHERE detail_id=?",
            (detail,),
        )
    elif invalid in ("detail", "interview"):
        table = "questions_detail" if invalid == "detail" else "interview"
        test_db.execute(
            f"UPDATE {table} SET deleted_at=CURRENT_TIMESTAMP WHERE id=?",
            (detail if invalid == "detail" else interview,),
        )
    elif invalid == "other_owner":
        test_db.execute("UPDATE questions_detail SET owner_id=8803 WHERE id=?", (detail,))
    test_db.commit()
    response = client.get(
        "/api/master-bank?filter=mine&compact=true&page=1&page_size=20", headers=actors(8801)
    )
    assert response.status_code == 200
    payload = response.json()
    ids = [r["id"] for r in (payload if isinstance(payload, list) else payload["items"])]
    assert (public in ids) is (invalid is None)
    outsider = client.get(
        "/api/master-bank?filter=mine&compact=true&page=1&page_size=20", headers=actors(8802)
    ).json()
    assert public not in [
        r["id"] for r in (outsider if isinstance(outsider, list) else outsider["items"])
    ]


def test_historical_pending_does_not_guess_a_private_source_by_text(client, test_db, actors):
    private = question(test_db, 8801)
    pending = question(test_db, None, status="pending")
    test_db.execute(
        "UPDATE question_bank SET submitted_by=8801,sources=? WHERE id=?",
        (json.dumps([{"url": "private://historic", "company": "SECRET"}]), pending),
    )
    test_db.commit()
    assert (
        client.post(f"/api/master-bank/approve/{pending}", headers=actors(8802)).status_code == 200
    )
    assert (
        test_db.execute("SELECT deleted_at FROM question_bank WHERE id=?", (private,)).fetchone()[0]
        is None
    )
    assert promotion(test_db, pending)["source_question_id"] is None
    assert (
        test_db.execute("SELECT sources FROM question_bank WHERE id=?", (pending,)).fetchone()[0]
        == "[]"
    )


def test_promotion_migration_is_repeatable_without_guessing_old_source_links(test_db, actors):
    from app.db.migrations.question_promotions import _migration_126_question_promotions

    private = question(test_db, 8801)
    pending = question(test_db, None, status="pending")
    before = [dict(r) for r in test_db.execute("SELECT * FROM question_bank ORDER BY id")]
    _migration_126_question_promotions(test_db)
    _migration_126_question_promotions(test_db)
    assert [dict(r) for r in test_db.execute("SELECT * FROM question_bank ORDER BY id")] == before
    assert test_db.execute("SELECT count(*) FROM question_promotion_requests").fetchone()[0] == 0
    assert pending != private


def test_owner_can_withdraw_pending_snapshot_and_resubmit_new_version(client, test_db, actors):
    private = question(test_db, 8801)
    pending = share(client, actors, private).json()["pending_id"]
    response = client.post(f"/api/master-bank/{pending}/withdraw-share", headers=actors(8801))
    assert response.status_code == 200
    assert promotion(test_db, pending)["status"] == "withdrawn"
    assert (
        client.post(f"/api/master-bank/approve/{pending}", headers=actors(8802)).status_code == 409
    )
    assert (
        test_db.execute("SELECT deleted_at FROM question_bank WHERE id=?", (private,)).fetchone()[0]
        is None
    )
    test_db.execute(
        "UPDATE question_bank SET question=? WHERE id=?", ("NEW_PRIVATE_VERSION", private)
    )
    test_db.commit()
    replacement = share(client, actors, private).json()["pending_id"]
    assert replacement != pending
    assert (
        json.loads(promotion(test_db, replacement)["snapshot_json"])["question"]
        == "NEW_PRIVATE_VERSION"
    )


@pytest.mark.parametrize("uid", [8802, 8803])
def test_withdraw_pending_snapshot_is_owner_only(client, test_db, actors, uid):
    pending = share(client, actors, question(test_db, 8801)).json()["pending_id"]
    response = client.post(f"/api/master-bank/{pending}/withdraw-share", headers=actors(uid))
    missing = client.post("/api/master-bank/999999/withdraw-share", headers=actors(uid))
    assert response.status_code == missing.status_code == 404
    assert response.json() == missing.json()
    assert promotion(test_db, pending)["status"] == "pending"


def test_owner_can_delete_submitted_private_source_without_losing_snapshot(client, test_db, actors):
    import sqlite3

    private = question(test_db, 8801)
    test_db.execute(
        "UPDATE question_bank SET original_questions=? WHERE id=?",
        (json.dumps(["TCP_CANONICAL"]), private),
    )
    test_db.commit()
    pending = share(client, actors, private).json()["pending_id"]
    snapshot = promotion(test_db, pending)["snapshot_json"]
    try:
        response = client.post(
            f"/api/master-bank/delete-original-question/{private}",
            json={"original_question": "TCP_CANONICAL"},
            headers=actors(8801),
        )
    except sqlite3.IntegrityError:
        pytest.fail("a promotion snapshot must not block lawful source deletion")
    assert response.status_code == 200, response.text
    assert promotion(test_db, pending)["snapshot_json"] == snapshot
    assert promotion(test_db, pending)["source_question_id"] is None
    assert (
        client.post(f"/api/master-bank/approve/{pending}", headers=actors(8802)).status_code == 409
    )


def test_admin_can_delete_promoted_target_without_losing_review_history(client, test_db, actors):
    import sqlite3

    public = question(test_db, None)
    private = question(test_db, 8801)
    pending = share(client, actors, private).json()["pending_id"]
    assert (
        client.post(f"/api/master-bank/approve/{pending}", headers=actors(8802)).status_code == 200
    )
    snapshot = promotion(test_db, pending)["snapshot_json"]
    try:
        response = client.post(
            f"/api/master-bank/delete-original-question/{public}",
            json={"original_question": "TCP_CANONICAL"},
            headers=actors(8802),
        )
    except sqlite3.IntegrityError:
        pytest.fail("a promotion audit must not block lawful public canonical deletion")
    assert response.status_code == 200, response.text
    assert promotion(test_db, pending)["target_question_id"] is None
    assert promotion(test_db, pending)["snapshot_json"] == snapshot


@pytest.mark.parametrize("operation", ["delete", "batch_delete"])
def test_canonical_delete_cannot_delete_a_pending_request(client, test_db, actors, operation):
    private = question(test_db, 8801)
    pending = share(client, actors, private).json()["pending_id"]
    public = question(test_db, None, text="OTHER_PUBLIC")
    response = (
        client.delete(f"/api/master-bank/{pending}", headers=actors(8802))
        if operation == "delete"
        else client.post(
            "/api/master-bank/batch-delete", json={"ids": [public, pending]}, headers=actors(8802)
        )
    )
    assert response.status_code == 409
    assert share(client, actors, private).json()["pending_id"] == pending
    assert (
        test_db.execute("SELECT deleted_at FROM question_bank WHERE id=?", (public,)).fetchone()[0]
        is None
    )


@pytest.mark.parametrize("terminal", ["withdrawn", "rejected"])
def test_canonical_restore_cannot_revive_terminal_request(client, test_db, actors, terminal):
    pending = share(client, actors, question(test_db, 8801)).json()["pending_id"]
    if terminal == "withdrawn":
        assert (
            client.post(
                f"/api/master-bank/{pending}/withdraw-share", headers=actors(8801)
            ).status_code
            == 200
        )
    else:
        assert (
            client.post(f"/api/master-bank/reject/{pending}", headers=actors(8802)).status_code
            == 200
        )
    response = client.post(f"/api/master-bank/restore/{pending}", headers=actors(8802))
    assert response.status_code == 409
    assert promotion(test_db, pending)["status"] == terminal
    assert test_db.execute(
        "SELECT deleted_at FROM question_bank WHERE id=?", (pending,)
    ).fetchone()[0]


def test_terminal_snapshot_is_not_listed_if_legacy_projection_was_restored(client, test_db, actors):
    pending = share(client, actors, question(test_db, 8801)).json()["pending_id"]
    assert (
        client.post(f"/api/master-bank/{pending}/withdraw-share", headers=actors(8801)).status_code
        == 200
    )
    # A stale legacy projection must not override the authoritative request state.
    test_db.execute("UPDATE question_bank SET deleted_at=NULL WHERE id=?", (pending,))
    test_db.commit()
    assert all(
        item["id"] != pending
        for item in client.get("/api/master-bank/pending/mine", headers=actors(8801)).json()[
            "items"
        ]
    )
    response = client.get("/api/admin/public-contributions", headers=actors(8802)).json()
    assert all(item["id"] != pending for item in response["items"] if item.get("legacy"))


@pytest.mark.parametrize("state", ["pending", "withdrawn", "rejected", "historical"])
@pytest.mark.parametrize("operation", ["split", "merge_source", "merge_target", "delete_original"])
def test_request_projection_cannot_bypass_review_through_cluster_mutations(
    client, test_db, actors, state, operation
):
    private = question(test_db, 8801)
    test_db.execute(
        "UPDATE question_bank SET original_questions=? WHERE id=?",
        (json.dumps(["TCP_CANONICAL", "OTHER_VARIANT"]), private),
    )
    test_db.commit()
    pending = share(client, actors, private).json()["pending_id"]
    public = question(test_db, None, text="SAFE_PUBLIC")
    if state == "historical":
        test_db.execute(
            "DELETE FROM question_promotion_requests WHERE pending_question_id=?", (pending,)
        )
        test_db.commit()
    elif state == "withdrawn":
        assert (
            client.post(
                f"/api/master-bank/{pending}/withdraw-share", headers=actors(8801)
            ).status_code
            == 200
        )
    elif state == "rejected":
        assert (
            client.post(f"/api/master-bank/reject/{pending}", headers=actors(8802)).status_code
            == 200
        )
    before = [tuple(row) for row in test_db.execute("SELECT * FROM question_bank ORDER BY id")]
    if operation == "split":
        path = f"/api/master-bank/split-question/{pending}"
        body = {"original_question": "TCP_CANONICAL"}
    elif operation == "delete_original":
        path = f"/api/master-bank/delete-original-question/{pending}"
        body = {"original_question": "TCP_CANONICAL"}
    else:
        source, target = (pending, public) if operation == "merge_source" else (public, pending)
        path = f"/api/master-bank/merge-question/{source}"
        body = {
            "original_question": "TCP_CANONICAL" if source == pending else "SAFE_PUBLIC",
            "target_id": target,
        }
    response = client.post(path, json=body, headers=actors(8802))
    assert response.status_code == 409, response.text
    assert [
        tuple(row) for row in test_db.execute("SELECT * FROM question_bank ORDER BY id")
    ] == before


@pytest.mark.parametrize("endpoint", ["clustering-maintenance", "fix-lone-islands"])
def test_public_maintenance_cannot_publish_pending_snapshot(client, test_db, actors, endpoint):
    public = question(test_db, None)
    private = question(test_db, 8801)
    pending = share(client, actors, private).json()["pending_id"]
    test_db.execute("UPDATE question_bank SET frequency=99 WHERE id=?", (pending,))
    test_db.commit()
    before = tuple(test_db.execute("SELECT * FROM question_bank WHERE id=?", (pending,)).fetchone())
    public_sources = test_db.execute(
        "SELECT sources FROM question_bank WHERE id=?", (public,)
    ).fetchone()[0]
    response = client.post(
        f"/api/master-bank/{endpoint}", params={"dry_run": "false"}, headers=actors(8802)
    )
    assert response.status_code == 200, response.text
    after = test_db.execute("SELECT * FROM question_bank WHERE id=?", (pending,)).fetchone()
    assert after is not None, "maintenance must not merge or delete a pending request"
    assert tuple(after) == before
    assert (
        test_db.execute("SELECT sources FROM question_bank WHERE id=?", (public,)).fetchone()[0]
        == public_sources
    )
    assert "PRIVATE_COMPANY" not in response.text
