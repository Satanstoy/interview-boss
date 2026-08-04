"""洞察工作台的聚合口径与用户隔离测试。"""


def _insert_user(conn, user_id, position="测试岗位"):
    conn.execute(
        "INSERT INTO users (id, username, password_hash, personal_position) "
        "VALUES (?, ?, ?, ?)",
        (user_id, f"insights-user-{user_id}", "TEST_PASSWORD_PLACEHOLDER", position),
    )


def _insert_question(conn, question_id, topic, position="测试岗位", frequency=1, deleted_at=None):
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, frequency, status, owner_id, job_position, deleted_at) "
        "VALUES (?, ?, ?, ?, ?, 'approved', NULL, ?, ?)",
        (
            question_id,
            f"{topic}面试题",
            "能力域",
            topic,
            frequency,
            position,
            deleted_at,
        ),
    )


def test_insights_aggregates_current_position_and_calculates_statuses(test_db):
    from app.services.insights import build_insights_snapshot

    _insert_user(test_db, 101)
    _insert_question(test_db, 1, "RAG系统设计", frequency=5)
    _insert_question(test_db, 2, "Agent编排", frequency=3)
    _insert_question(test_db, 3, "前端工程", position="其他岗位", frequency=99)
    _insert_question(test_db, 4, "已删除主题", frequency=99, deleted_at="2026-08-01")
    test_db.execute(
        "INSERT INTO user_practice_history (user_id, question_bank_id, score) VALUES (?, ?, ?)",
        (101, 1, 50),
    )
    test_db.execute(
        "INSERT INTO user_practice_history (user_id, question_bank_id, score) VALUES (?, ?, ?)",
        (101, 2, 85),
    )
    test_db.commit()

    snapshot = build_insights_snapshot({"id": 101})

    assert snapshot["target_position"] == {"name": "测试岗位", "source": "user_position"}
    assert snapshot["summary"] == {
        "question_count": 2,
        "jd_count": 0,
        "interview_count": 0,
        "practiced_question_count": 2,
        "evaluated_answer_count": 2,
        "evidence_state": "available",
    }
    items = {item["name"]: item for item in snapshot["readiness"]["items"]}
    assert items["RAG系统设计"]["question_frequency"] == 5
    assert items["RAG系统设计"]["status"] == "needs_work"
    assert items["RAG系统设计"]["average_score"] == 50
    assert items["Agent编排"]["status"] == "stable"
    assert "前端工程" not in items
    assert "已删除主题" not in items
    assert snapshot["data_quality"]["has_practice_evidence"] is True


def test_insights_practice_and_reviews_are_user_scoped(test_db):
    from app.services.insights import build_insights_snapshot

    _insert_user(test_db, 201)
    _insert_user(test_db, 202)
    _insert_question(test_db, 11, "检索增强")
    test_db.execute(
        "INSERT INTO user_practice_history (user_id, question_bank_id, score) VALUES (?, ?, ?)",
        (202, 11, 95),
    )
    test_db.execute(
        "INSERT INTO chat_conversations (id, user_id, mode, title, job_position) "
        "VALUES (?, ?, ?, ?, ?)",
        ("mine", 201, "mock", "我的面试", "测试岗位"),
    )
    test_db.execute(
        "INSERT INTO chat_conversations (id, user_id, mode, title, job_position) "
        "VALUES (?, ?, ?, ?, ?)",
        ("other", 202, "mock", "其他人的面试", "测试岗位"),
    )
    test_db.execute(
        "INSERT INTO chat_messages (conversation_id, role, content) VALUES (?, ?, ?)",
        ("mine", "user", "请开始"),
    )
    test_db.commit()

    snapshot = build_insights_snapshot({"id": 201})

    assert snapshot["summary"]["practiced_question_count"] == 0
    assert snapshot["summary"]["evaluated_answer_count"] == 0
    assert snapshot["reviews"]["total"] == 1
    assert snapshot["reviews"]["items"] == [
        {
            "id": "mine",
            "title": "我的面试",
            "mode": "mock",
            "job_position": "测试岗位",
            "message_count": 1,
            "created_at": snapshot["reviews"]["items"][0]["created_at"],
            "updated_at": snapshot["reviews"]["items"][0]["updated_at"],
        }
    ]


def test_insights_endpoint_requires_auth_and_returns_contract(client, test_db):
    from app.asgi import app
    from app.core.auth import get_current_user

    _insert_user(test_db, 301)
    _insert_question(test_db, 31, "函数调用")
    app.dependency_overrides[get_current_user] = lambda: {"id": 301}
    try:
        response = client.get("/api/insights")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    assert set(body) == {
        "version",
        "target_position",
        "summary",
        "actions",
        "readiness",
        "reviews",
        "data_quality",
    }
