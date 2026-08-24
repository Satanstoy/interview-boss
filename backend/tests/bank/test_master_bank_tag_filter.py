"""题库分类 + 标签筛选的一致性回归测试。"""

POSITION = "标签筛选测试岗位"
CATEGORY = "E.语言与编程工具"


def _insert_question(test_db, question, tags, frequency, category=CATEGORY):
    position_id = test_db.execute(
        "SELECT id FROM job_positions WHERE name = ?", (POSITION,)
    ).fetchone()
    position_id = position_id[0] if position_id else None
    if position_id is None:
        position_id = test_db.execute(
            "INSERT INTO job_positions (name) VALUES (?)", (POSITION,)
        ).lastrowid
    test_db.execute(
        "UPDATE users SET current_position_id = ? WHERE id = 1", (position_id,)
    )
    question_id = test_db.execute(
        "INSERT INTO question_bank "
        "(question, cat1, cat2, tags, difficulty, frequency, owner_id, status, job_position) "
        "VALUES (?, ?, ?, ?, 'L2', ?, NULL, 'approved', ?)",
        (question, category, "E1.Python", tags, frequency, POSITION),
    ).lastrowid
    test_db.execute(
        "INSERT INTO question_position (question_id, position_id) VALUES (?, ?)",
        (question_id, position_id),
    )
    test_db.commit()
    return question_id


def test_master_bank_tag_filter_keeps_count_and_items_in_same_scope(client, test_db):
    """Python 只有 1 题时，服务端筛选结果也必须是 total=1 且返回该题。"""
    from app.asgi import app
    from app.core.auth import get_current_user

    python_id = _insert_question(test_db, "Python 依赖管理", "Python", frequency=1)
    _insert_question(test_db, "其他工程题", "Redis", frequency=10)
    _insert_question(test_db, "Python 前缀题", "Pythonista", frequency=5)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1,
        "username": "tag-filter-test",
        "is_admin": True,
        "bank_mode": "public",
        "current_position_id": 1,
    }

    try:
        response = client.get(
            "/api/master-bank",
            params={
                "filter": "all",
                "compact": "true",
                "page": 1,
                "page_size": 1,
                "cat1": CATEGORY,
                "tag": "Python",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total"] == 1
        assert [item["id"] for item in payload["items"]] == [python_id]
        filtered_tag_counts = {
            item["tag"]: item["count"] for item in payload["filtered_tag_counts"]
        }
        assert filtered_tag_counts == {"Redis": 1, "Pythonista": 1, "Python": 1}
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_master_bank_tag_filter_accepts_spaces_around_delimiters(client, test_db):
    """标签分隔符两侧存在多余空格时，点击标签仍能召回题目。"""
    from app.asgi import app
    from app.core.auth import get_current_user

    category = "E.标签空格兼容"
    first_id = _insert_question(
        test_db, "Python 与 Redis", "Python ,Redis", frequency=1, category=category
    )
    second_id = _insert_question(
        test_db, "Python 与消息队列", "Python,  Kafka", frequency=1, category=category
    )
    app.dependency_overrides[get_current_user] = lambda: {
        "id": 1,
        "username": "tag-spacing-test",
        "is_admin": True,
        "bank_mode": "public",
        "current_position_id": 1,
    }

    try:
        response = client.get(
            "/api/master-bank",
            params={
                "filter": "all",
                "compact": "true",
                "cat1": category,
                "tag": "Python",
            },
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total"] == 2
        assert {item["id"] for item in payload["items"]} == {first_id, second_id}
    finally:
        app.dependency_overrides.pop(get_current_user, None)
