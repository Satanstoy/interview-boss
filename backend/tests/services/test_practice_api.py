USER = {"id": 1, "username": "practice-user", "is_admin": 0, "bank_mode": "public"}
POSITION = "agent开发/大模型应用开发/大模型开发"


def _override_user():
    from app.asgi import app
    from app.core.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: USER
    return app, get_current_user


def _insert_question(conn, text, frequency=1):
    row = conn.execute(
        """
        INSERT INTO question_bank
            (question, cat1, cat2, tags, difficulty, frequency, ai_answer, owner_id, status, job_position)
        VALUES (?, '后端', '基础', '八股', 'L1-基础', ?, '参考答案', NULL, 'approved', ?)
        RETURNING id
        """,
        (text, frequency, POSITION),
    ).fetchone()
    return row[0]


def test_decks_link_high_frequency_bank_and_review_state(client, test_db):
    question_id = _insert_question(test_db, "什么是连接池？", frequency=8)
    second_id = _insert_question(test_db, "什么是幂等？", frequency=1)
    test_db.execute(
        "INSERT INTO user_question_view (user_id, question_bank_id, is_starred) VALUES (1, ?, 1)",
        (question_id,),
    )
    test_db.commit()
    app, dependency = _override_user()

    try:
        decks = client.get("/api/practice/decks")
        assert decks.status_code == 200
        by_key = {item["key"]: item for item in decks.json()["items"]}
        assert set(by_key) == {"due", "all", "starred"}
        assert by_key["all"]["total"] == 2
        assert by_key["starred"]["total"] == 1

        queue = client.get("/api/practice/decks/all/questions")
        assert queue.status_code == 200, queue.text
        assert queue.json()["total"] == 2
        assert queue.json()["items"][0]["id"] == question_id

        review = client.post(
            "/api/practice/review",
            json={"question_id": question_id, "rating": "good"},
        )
        assert review.status_code == 200, review.text
        assert review.json()["review"]["proficiency"] == 1
        assert review.json()["review"]["has_been_practiced"] is True

        queue = client.get("/api/practice/decks/all/questions")
        assert queue.status_code == 200, queue.text
        assert queue.json()["total"] == 2
        item = next(item for item in queue.json()["items"] if item["id"] == question_id)
        assert item["id"] == question_id
        assert item["has_been_practiced"] is True
        assert item["proficiency"] == 1
        assert item["review_state"] == "learning"

        all_questions = client.get("/api/practice/decks/all/questions")
        assert {item["id"] for item in all_questions.json()["items"]} == {
            question_id,
            second_id,
        }
    finally:
        app.dependency_overrides.pop(dependency, None)


def test_review_requires_a_question_visible_to_the_current_user(client, test_db):
    app, dependency = _override_user()
    try:
        response = client.post(
            "/api/practice/review",
            json={"question_id": 99999, "rating": "again"},
        )
        assert response.status_code == 404
    finally:
        app.dependency_overrides.pop(dependency, None)


def test_custom_deck_can_be_created_managed_and_used_as_a_review_queue(client, test_db):
    question_id = _insert_question(test_db, "什么是消息队列？", frequency=6)
    app, dependency = _override_user()

    try:
        created = client.post(
            "/api/practice/decks",
            json={
                "name": "后端高频八股",
                "description": "面试前快速过一遍",
                "visibility": "private",
            },
        )
        assert created.status_code == 200, created.text
        deck = created.json()
        assert deck["kind"] == "custom"
        deck_key = deck["key"]

        added = client.post(
            f"/api/practice/decks/{deck_key}/items",
            json={"question_id": question_id},
        )
        assert added.status_code == 200, added.text

        queue = client.get(f"/api/practice/decks/{deck_key}/questions")
        assert queue.status_code == 200, queue.text
        assert queue.json()["total"] == 1
        assert queue.json()["items"][0]["id"] == question_id

        listed = client.get("/api/practice/decks")
        custom = next(
            item for item in listed.json()["items"] if item["key"] == deck_key
        )
        assert custom["kind"] == "custom"
        assert custom["total"] == 1

        updated = client.put(
            f"/api/practice/decks/{deck_key}",
            json={"name": "后端八股冲刺", "description": "最后一轮复习"},
        )
        assert updated.status_code == 200
        assert updated.json()["name"] == "后端八股冲刺"

        removed = client.delete(
            f"/api/practice/decks/{deck_key}/items/{question_id}",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert removed.status_code == 200
        assert (
            client.get(f"/api/practice/decks/{deck_key}/questions").json()["total"] == 0
        )

        deleted = client.delete(
            f"/api/practice/decks/{deck_key}",
            headers={"X-Requested-With": "XMLHttpRequest"},
        )
        assert deleted.status_code == 200
        assert (
            client.get(f"/api/practice/decks/{deck_key}/questions").status_code == 404
        )
    finally:
        app.dependency_overrides.pop(dependency, None)


def test_migration_backfills_legacy_answer_history(test_db):
    question_id = _insert_question(test_db, "什么是缓存穿透？", frequency=4)
    test_db.execute(
        "INSERT INTO user_practice_history (user_id, question_bank_id, user_answer, score) VALUES (1, ?, '回答', 90)",
        (question_id,),
    )
    from app.db.migrations.practice import _migration_055_practice_review_system

    _migration_055_practice_review_system(test_db)
    row = test_db.execute(
        "SELECT review_count, proficiency FROM user_question_review WHERE user_id = 1 AND question_bank_id = ?",
        (question_id,),
    ).fetchone()
    assert row[0] == 1
    assert row[1] == 3


def test_practiced_questions_lists_recently_reviewed(client, test_db):
    """已刷过的题列表：按最近复习时间倒序，带熟练度与下次复习时间"""
    q1 = _insert_question(test_db, "什么是连接池？", frequency=8)
    q2 = _insert_question(test_db, "什么是幂等？", frequency=1)
    test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, last_rating, last_reviewed_at, next_review_at, updated_at) "
        "VALUES (1, ?, 'learning', 2, 1, 'good', '2026-08-05 10:00:00', '2026-08-08 10:00:00', '2026-08-05 11:00:00')",
        (q1,),
    )
    test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, last_rating, last_reviewed_at, next_review_at, updated_at) "
        "VALUES (1, ?, 'review', 4, 3, 'easy', '2026-08-06 10:00:00', '2026-08-12 10:00:00', '2026-08-06 11:00:00')",
        (q2,),
    )
    test_db.commit()
    app, dependency = _override_user()

    try:
        resp = client.get("/api/practice/practiced")
        assert resp.status_code == 200
        items = resp.json()["items"]
        assert len(items) == 2
        print("DEBUG items:", [(i["id"], i.get("last_reviewed_at")) for i in items])
        print(
            "DEBUG db:",
            [
                dict(r)
                for r in test_db.execute(
                    "SELECT question_bank_id, updated_at FROM user_question_review"
                ).fetchall()
            ],
        )
        assert items[0]["id"] == q2  # 最近复习的在前
        assert items[0]["proficiency"] == 4
        assert items[1]["id"] == q1
        assert items[1]["review_count"] == 1
        assert items[0]["next_review_at"]
    finally:
        app.dependency_overrides.pop(dependency, None)
