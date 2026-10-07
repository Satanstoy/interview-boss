import json
from app.core.auth import create_access_token


def seed(client, db):
    db.execute(
        "INSERT INTO users(id, username, password_hash, is_admin) VALUES (8801,'spec-probe-user','TEST_HASH_PLACEHOLDER',0)"
    )
    db.execute(
        "INSERT INTO users(id, username, password_hash, is_admin) VALUES (8802,'spec-probe-admin','TEST_HASH_PLACEHOLDER',1)"
    )
    db.commit()

    def headers(uid):
        return {
            "Authorization": "Bearer " + create_access_token({"user_id": uid, "type": "access"}),
            "X-Requested-With": "XMLHttpRequest",
        }

    assert client.get("/api/auth/me", headers=headers(8801)).status_code == 200
    assert client.get("/api/auth/me", headers=headers(8802)).status_code == 200
    return headers


def test_share_match_directly_changes_public_without_review(client, test_db):
    headers = seed(client, test_db)
    public = test_db.execute(
        "INSERT INTO question_bank(question, cat2, owner_id, status, job_position, sources, original_questions, original_question_sources, frequency) VALUES ('Redis持久化','Redis',NULL,'approved','后端开发','[]','[]','[]',1)"
    ).lastrowid
    private = test_db.execute(
        "INSERT INTO question_bank(question, cat2, owner_id, status, job_position, sources, original_questions, original_question_sources) VALUES ('Redis持久化','Redis',8801,'approved','后端开发',?,'[]','[]')",
        (
            json.dumps(
                [{"url": "private://8801/sensitive-interview", "company": "PRIVATE_COMPANY"}]
            ),
        ),
    ).lastrowid
    test_db.commit()
    before = dict(test_db.execute("SELECT * FROM question_bank WHERE id=?", (public,)).fetchone())
    request_before = test_db.execute(
        "SELECT count(*) FROM public_contribution_requests"
    ).fetchone()[0]
    response = client.post(f"/api/master-bank/{private}/share", headers=headers(8801))
    after = dict(test_db.execute("SELECT * FROM question_bank WHERE id=?", (public,)).fetchone())
    deleted = test_db.execute(
        "SELECT deleted_at FROM question_bank WHERE id=?", (private,)
    ).fetchone()[0]
    request_after = test_db.execute("SELECT count(*) FROM public_contribution_requests").fetchone()[
        0
    ]
    assert response.status_code == 200, response.text
    assert response.json() == {"result": "merged", "target_id": public}
    assert after["sources"] != before["sources"]
    assert "private://8801/sensitive-interview" in after["sources"]
    assert deleted is not None
    assert request_after == request_before
    print(
        "CONFIRMED direct-share: HTTP200 merged; public sources changed; private URL added; private row soft-deleted; contribution request count unchanged"
    )


def test_legacy_pending_is_counted_but_not_listed(client, test_db):
    headers = seed(client, test_db)
    private = test_db.execute(
        "INSERT INTO question_bank(question,cat2,owner_id,status,job_position) VALUES ('UniquePrivateQuestion','UniqueCat',8801,'approved','后端开发')"
    ).lastrowid
    test_db.commit()
    response = client.post(f"/api/master-bank/{private}/share", headers=headers(8801))
    assert response.status_code == 200, response.text
    assert response.json()["result"] == "pending"
    admin_list = client.get("/api/admin/public-contributions", headers=headers(8802))
    assert admin_list.status_code == 200, admin_list.text
    assert admin_list.json()["total"] == 1
    assert admin_list.json()["items"] == []
    print("CONFIRMED legacy pending: HTTP200 pending; admin unified list total=1 and items=[]")


def test_mine_route_omits_owned_private_reference_to_public_canonical(client, test_db):
    from app.services.question_resolution import record_resolution, list_mine_canonical_ids

    headers = seed(client, test_db)
    pos = test_db.execute(
        "INSERT INTO job_positions(name) VALUES ('mine-probe-position')"
    ).lastrowid
    test_db.execute("UPDATE users SET current_position_id=? WHERE id=8801", (pos,))
    test_db.commit()
    user = test_db.execute("SELECT current_position_id FROM users WHERE id=8801").fetchone()
    pos_id = user["current_position_id"]
    assert pos_id is not None
    pos_name = test_db.execute("SELECT name FROM job_positions WHERE id=?", (pos_id,)).fetchone()[
        "name"
    ]
    public = test_db.execute(
        "INSERT INTO question_bank(question, cat1, cat2, owner_id, status, job_position, sources, original_questions, original_question_sources, frequency) VALUES ('TCP_PUBLIC_CANONICAL','network','TCP',NULL,'approved',?,'[]','[]','[]',1)",
        (pos_name,),
    ).lastrowid
    test_db.execute(
        "INSERT INTO question_position(question_id,position_id) VALUES (?,?)", (public, pos_id)
    )
    interview = test_db.execute(
        "INSERT INTO interview(url, owner_id, status, job_position, questions_list) VALUES ('private://8801/mine-canonical',8801,'approved',?,'[]')",
        (pos_name,),
    ).lastrowid
    detail = test_db.execute(
        "INSERT INTO questions_detail(interview_id, question, cat1, cat2, owner_id, status, url, job_position) VALUES (?, 'TCP_PUBLIC_CANONICAL', 'network', 'TCP', 8801, 'approved','private://8801/mine-canonical',?)",
        (interview, pos_name),
    ).lastrowid
    resolution = record_resolution(
        test_db,
        detail_id=detail,
        occurrence_scope="private",
        occurrence_owner_id=8801,
        canonical_id=public,
        canonical_scope="public",
        status="matched",
        pipeline_version="probe-v1",
    )
    test_db.commit()
    assert resolution["canonical_id"] == public
    assert public in list_mine_canonical_ids(test_db, user_id=8801)
    responses = {
        mode: client.get("/api/master-bank", params={"filter": mode}, headers=headers(8801))
        for mode in ("mine", "public", "all")
    }
    for mode, response in responses.items():
        assert response.status_code == 200, (mode, response.text)

    def ids(response):
        payload = response.json()
        if isinstance(payload, list):
            return [item["id"] for item in payload]
        return [item["id"] for item in payload.get("items", payload.get("data", []))]

    result = {mode: ids(response) for mode, response in responses.items()}
    assert public in result["public"], responses["public"].text
    assert public in result["all"], responses["all"].text
    assert public not in result["mine"], responses["mine"].text
    print(
        f"CONFIRMED mine omission: owner=8801 position_id={pos_id} canonical={public} detail={detail} current_resolution={dict(resolution)}; HTTP route IDs={result}"
    )
