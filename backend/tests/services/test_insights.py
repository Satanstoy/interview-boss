"""洞察工作台的聚合口径与用户隔离测试。"""


def _insert_user(conn, user_id, position="测试岗位"):
    conn.execute(
        "INSERT INTO users (id, username, password_hash, personal_position) "
        "VALUES (?, ?, ?, ?)",
        (user_id, f"insights-user-{user_id}", "TEST_PASSWORD_PLACEHOLDER", position),
    )


def _insert_question(conn, question_id, topic, position="测试岗位", frequency=1, deleted_at=None, difficulty="简单", sources=None):
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, frequency, status, owner_id, job_position, deleted_at, difficulty, sources) "
        "VALUES (?, ?, ?, ?, ?, 'approved', NULL, ?, ?, ?, ?)",
        (
            question_id,
            f"{topic}面试题",
            "能力域",
            topic,
            frequency,
            position,
            deleted_at,
            difficulty,
            sources,
        ),
    )


def test_insights_aggregates_current_position_and_calculates_statuses(test_db):
    from app.services.insights import build_insights_snapshot

    _insert_user(test_db, 101)
    _insert_question(
        test_db, 1, "RAG系统设计", frequency=5,
        sources='[{"url": "https://a.com/1", "company": "A", "round": "一面"},'
                '{"url": "https://a.com/1", "company": "A", "round": "二面"},'
                '{"url": "https://b.com/1", "company": "B", "round": "一面"}]',
    )
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
    # 口径：独立来源数（url 去重 = 2），非问法数 frequency=5
    assert items["RAG系统设计"]["question_frequency"] == 2
    assert items["RAG系统设计"]["status"] == "needs_work"
    assert items["RAG系统设计"]["average_score"] == 50
    assert items["Agent编排"]["status"] == "stable"
    assert "前端工程" not in items
    assert "已删除主题" not in items
    assert snapshot["data_quality"]["has_practice_evidence"] is True


def test_insights_radar_excludes_fallback_topics_and_rebuilds_from_new_questions(test_db):
    from app.services.insights import build_insights_snapshot, build_practice_activity

    _insert_user(test_db, 102)
    _insert_question(
        test_db,
        10,
        "其他",
        frequency=99,
        sources='[{"url": "https://example.com/other"}]',
    )
    _insert_question(
        test_db,
        11,
        "RAG系统设计",
        frequency=2,
        sources='[{"url": "https://example.com/rag"}]',
    )
    test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, proficiency) VALUES (?, ?, ?)",
        (102, 10, 95),
    )
    test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, proficiency) VALUES (?, ?, ?)",
        (102, 11, 45),
    )
    test_db.commit()

    initial_snapshot = build_insights_snapshot({"id": 102})
    initial_activity = build_practice_activity({"id": 102})
    assert [item["name"] for item in initial_snapshot["readiness"]["items"]] == ["RAG系统设计"]
    assert initial_activity["radar"] == [{"topic": "RAG系统设计", "proficiency": 45}]

    _insert_question(
        test_db,
        12,
        "Agent编排",
        frequency=4,
        sources='[{"url": "https://example.com/agent"}]',
    )
    test_db.commit()

    refreshed_snapshot = build_insights_snapshot({"id": 102})
    assert {item["name"] for item in refreshed_snapshot["readiness"]["items"]} == {
        "RAG系统设计",
        "Agent编排",
    }
    assert "其他" not in {item["name"] for item in refreshed_snapshot["readiness"]["items"]}


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
        "high_frequency",
        "reviews",
        "data_quality",
    }


def _insert_review(conn, user_id, review_id, question_bank_id, rating, reviewed_at, score=None):
    conn.execute(
        "INSERT INTO user_question_review "
        "(id, user_id, question_bank_id, proficiency, state, last_rating) "
        "VALUES (?, ?, ?, 40, 'review', ?)",
        (review_id, user_id, question_bank_id, rating),
    )
    conn.execute(
        "INSERT INTO practice_review_events "
        "(user_id, question_bank_id, review_id, rating, score, reviewed_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, question_bank_id, review_id, rating, score, reviewed_at),
    )


def test_practice_activity_heatmap_trend_and_streak(test_db):
    from datetime import datetime, timedelta

    from app.services.insights import build_practice_activity

    _insert_user(test_db, 401)
    _insert_question(test_db, 1, "RAG系统设计", difficulty="medium")
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")

    for i, score in enumerate((85, 90)):
        test_db.execute(
            "INSERT INTO user_practice_history "
            "(user_id, question_bank_id, score, created_at) VALUES (?, ?, ?, ?)",
            (401, 1, score, f"{today} 10:0{i}:00"),
        )
    test_db.execute(
        "INSERT INTO user_practice_history "
        "(user_id, question_bank_id, score, created_at) VALUES (?, ?, ?, ?)",
        (401, 1, 50, f"{three_days_ago} 09:00:00"),
    )
    _insert_review(test_db, 401, 1, 1, "good", f"{yesterday} 20:00:00", score=85)
    test_db.commit()

    data = build_practice_activity({"id": 401})

    assert data["streak"] == {"current": 2, "longest": 2}
    assert len(data["heatmap"]) == 365
    assert len(data["trend"]) == 30
    day_map = {d["date"]: d for d in data["heatmap"]}
    assert day_map[today]["count"] == 2
    assert day_map[today]["avg_score"] == 87.5
    assert day_map[yesterday]["count"] == 1
    assert day_map[three_days_ago]["count"] == 1
    trend_map = {d["date"]: d for d in data["trend"]}
    assert trend_map[today]["count"] == 2
    assert trend_map[today]["avg_score"] == 87.5


def test_practice_activity_streak_breaks_with_gap(test_db):
    from datetime import datetime, timedelta

    from app.services.insights import build_practice_activity

    _insert_user(test_db, 402)
    _insert_question(test_db, 2, "Agent编排")
    today = datetime.now().strftime("%Y-%m-%d")
    three_days_ago = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    test_db.execute(
        "INSERT INTO user_practice_history "
        "(user_id, question_bank_id, score, created_at) VALUES (?, ?, ?, ?)",
        (402, 2, 70, f"{today} 09:00:00"),
    )
    test_db.execute(
        "INSERT INTO user_practice_history "
        "(user_id, question_bank_id, score, created_at) VALUES (?, ?, ?, ?)",
        (402, 2, 70, f"{three_days_ago} 09:00:00"),
    )
    test_db.commit()

    data = build_practice_activity({"id": 402})

    assert data["streak"] == {"current": 1, "longest": 1}


def test_practice_activity_streak_zero_without_activity(test_db):
    from app.services.insights import build_practice_activity

    _insert_user(test_db, 403)
    _insert_question(test_db, 3, "函数调用")

    data = build_practice_activity({"id": 403})

    assert data["streak"] == {"current": 0, "longest": 0}
    assert data["heatmap"][-1]["count"] == 0


def test_practice_activity_radar_topics_are_position_scoped_and_weakest_first(test_db):
    from app.services.insights import build_practice_activity

    _insert_user(test_db, 404)
    _insert_question(test_db, 1, "RAG系统设计")
    _insert_question(test_db, 2, "Agent编排")
    _insert_question(test_db, 3, "前端工程", position="其他岗位")
    test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, proficiency) VALUES (?, ?, ?)",
        (404, 1, 80),
    )
    test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, proficiency) VALUES (?, ?, ?)",
        (404, 2, 40),
    )
    test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, proficiency) VALUES (?, ?, ?)",
        (404, 3, 90),
    )
    test_db.commit()

    data = build_practice_activity({"id": 404})

    assert data["radar"] == [
        {"topic": "Agent编排", "proficiency": 40},
        {"topic": "RAG系统设计", "proficiency": 80},
    ]


def test_practice_activity_difficulty_correct_rate(test_db):
    from app.services.insights import build_practice_activity

    _insert_user(test_db, 405)
    _insert_question(test_db, 1, "RAG系统设计", difficulty="简单")
    _insert_question(test_db, 2, "Agent编排", difficulty="中等")
    _insert_question(test_db, 3, "前端工程", difficulty="hard")
    _insert_question(test_db, 4, "未标注难度", difficulty="")
    for qid, score in ((1, 70), (1, 50), (2, 90), (3, 45), (4, 66)):
        test_db.execute(
            "INSERT INTO user_practice_history "
            "(user_id, question_bank_id, score, created_at) VALUES (?, ?, ?, datetime('now'))",
            (405, qid, score),
        )
    test_db.commit()

    data = build_practice_activity({"id": 405})

    stats = {item["difficulty"]: item for item in data["difficulty"]}
    assert stats["简单"] == {
        "difficulty": "简单", "count": 2,
        "correct_count": 1, "needs_work_count": 1, "correct_rate": 50,
    }
    assert stats["中等"] == {
        "difficulty": "中等", "count": 1,
        "correct_count": 1, "needs_work_count": 0, "correct_rate": 100,
    }
    assert stats["困难"] == {
        "difficulty": "困难", "count": 1,
        "correct_count": 0, "needs_work_count": 1, "correct_rate": 0,
    }
    assert stats["未标注"] == {
        "difficulty": "未标注", "count": 1,
        "correct_count": 1, "needs_work_count": 0, "correct_rate": 100,
    }


def test_practice_activity_recent_merges_and_limits(test_db):
    from datetime import datetime

    from app.services.insights import build_practice_activity

    _insert_user(test_db, 406)
    _insert_question(test_db, 1, "RAG系统设计")
    for i in range(12):
        test_db.execute(
            "INSERT INTO user_practice_history "
            "(user_id, question_bank_id, score, created_at) VALUES (?, ?, ?, ?)",
            (406, 1, 60 + i, f"2026-08-01 {i:02d}:00:00"),
        )
    _insert_review(test_db, 406, 1, 1, "easy", "2026-08-05 09:00:00")
    test_db.commit()

    data = build_practice_activity({"id": 406})

    assert len(data["recent"]) == 10
    first = data["recent"][0]
    assert first["type"] == "review"
    assert first["rating"] == "easy"
    assert first["question"] == "RAG系统设计面试题"
    assert first["score"] is None
    answers = [item for item in data["recent"] if item["type"] == "answer"]
    assert len(answers) == 9
    assert all(item["score"] is not None and item["created_at"] for item in answers)


def test_practice_activity_is_user_scoped(test_db):
    from app.services.insights import build_practice_activity

    _insert_user(test_db, 407)
    _insert_user(test_db, 408)
    _insert_question(test_db, 1, "RAG系统设计")
    test_db.execute(
        "INSERT INTO user_practice_history "
        "(user_id, question_bank_id, score, created_at) VALUES (?, ?, ?, datetime('now'))",
        (407, 1, 88),
    )
    test_db.commit()

    data = build_practice_activity({"id": 408})

    assert data["heatmap"][-1]["count"] == 0
    assert data["streak"] == {"current": 0, "longest": 0}
    assert data["radar"] == []
    assert data["difficulty"] == []
    assert data["recent"] == []


def test_practice_activity_endpoint_contract(client, test_db):
    from app.asgi import app
    from app.core.auth import get_current_user

    _insert_user(test_db, 501)
    app.dependency_overrides[get_current_user] = lambda: {"id": 501}
    try:
        response = client.get("/api/insights/practice-activity")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "version",
        "heatmap",
        "streak",
        "trend",
        "radar",
        "difficulty",
        "recent",
    }
    assert len(body["heatmap"]) == 365
    assert len(body["trend"]) == 30
    assert body["streak"] == {"current": 0, "longest": 0}


def _insert_questions_detail(conn, detail_id, cat2, position="测试岗位", owner_id=601):
    """插入一条面经及其 questions_detail 行（url 关联，owner_id 拥有该面经）。

    高频待练按 用户可见作用域 JOIN interview 聚合，因此必须同时提供
    interview 父行（owner_id + status='approved'）才能进入聚合。
    """
    url = f"https://insights.example/detail-{detail_id}"
    conn.execute(
        "INSERT INTO interview (url, company, round, questions_list, owner_id, "
        "status, job_position) VALUES (?, ?, '一面', '[]', ?, 'approved', ?)",
        (url, f"{cat2}公司", owner_id, position),
    )
    conn.execute(
        "INSERT INTO questions_detail (id, url, question, cat2, job_position, deleted_at) "
        "VALUES (?, ?, ?, ?, ?, NULL)",
        (detail_id, url, f"{cat2}面经题", cat2, position),
    )


def test_insights_high_frequency_topics_aggregates_questions_detail(test_db):
    """高频待练 = 面经 questions_detail 按 cat2 聚合频次降序（不含空/已删/其他）。"""
    from app.services.insights import build_insights_snapshot

    _insert_user(test_db, 601)
    # 面经题目：Agent架构 3 次、RAG 2 次、其他岗位 RAG 1 次（应排除）、已删 1 次（应排除）、其他 4 次（应排除）
    _insert_questions_detail(test_db, 1, "Agent架构与范式")
    _insert_questions_detail(test_db, 2, "Agent架构与范式")
    _insert_questions_detail(test_db, 3, "Agent架构与范式")
    _insert_questions_detail(test_db, 4, "RAG系统设计")
    _insert_questions_detail(test_db, 5, "RAG系统设计")
    _insert_questions_detail(test_db, 6, "RAG系统设计", position="其他岗位")
    _insert_questions_detail(test_db, 7, "其他")
    _insert_questions_detail(test_db, 8, "其他")
    _insert_questions_detail(test_db, 9, "其他")
    _insert_questions_detail(test_db, 10, "其他")
    test_db.execute(
        "INSERT INTO questions_detail (id, question, cat2, job_position, deleted_at) "
        "VALUES (11, '已删', '已删主题', '测试岗位', '2026-08-01')"
    )
    test_db.commit()

    snapshot = build_insights_snapshot({"id": 601})

    assert "high_frequency" in snapshot
    assert snapshot["high_frequency"] == [
        {"topic": "Agent架构与范式", "frequency": 3},
        {"topic": "RAG系统设计", "frequency": 2},
    ]


def test_insights_high_frequency_empty_without_details(client, test_db):
    """无面经题目时 high_frequency 为空数组。"""
    from app.asgi import app
    from app.core.auth import get_current_user

    _insert_user(test_db, 602)
    app.dependency_overrides[get_current_user] = lambda: {"id": 602}
    try:
        response = client.get("/api/insights")
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    body = response.json()
    assert "high_frequency" in body
    assert body["high_frequency"] == []


def test_insights_readiness_items_include_srs_proficiency(test_db):
    """readiness.items 必须带 proficiency（SRS 熟练度聚合，练过才有值，未练为 None）。"""
    from app.services.insights import build_insights_snapshot

    _insert_user(test_db, 701)
    _insert_question(test_db, 21, "RAG系统设计")
    _insert_question(test_db, 22, "Agent编排")
    _insert_question(test_db, 23, "未练主题")
    test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, proficiency, review_count) "
        "VALUES (?, ?, ?, ?)",
        (701, 21, 85, 3),
    )
    test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, proficiency, review_count) "
        "VALUES (?, ?, ?, ?)",
        (701, 22, 60, 1),
    )
    test_db.commit()

    snapshot = build_insights_snapshot({"id": 701})
    items = {item["name"]: item for item in snapshot["readiness"]["items"]}

    assert items["RAG系统设计"]["proficiency"] == 85
    assert items["Agent编排"]["proficiency"] == 60
    assert items["未练主题"]["proficiency"] is None
