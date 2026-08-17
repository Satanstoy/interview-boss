"""Tests for study_date field in practice deck responses."""

import json


USER = {"id": 1, "username": "tz-test-user", "is_admin": 0, "bank_mode": "public"}
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


def test_list_deck_questions_returns_study_date(client, test_db):
    """list_deck_questions due 队列返回 study_date 字段。"""
    _insert_question(test_db, "什么是连接池？", frequency=8)
    test_db.commit()
    app, dependency = _override_user()

    try:
        queue = client.get("/api/practice/decks/due/questions")
        assert queue.status_code == 200, queue.text
        data = queue.json()
        deck = data.get("deck", {})
        assert "study_date" in deck, f"deck 缺少 study_date 字段: {deck.keys()}"
        # study_date 格式 YYYY-MM-DD
        import re
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", deck["study_date"]), (
            f"study_date 格式错误: {deck['study_date']}"
        )
    finally:
        app.dependency_overrides.pop(dependency, None)


def test_list_decks_returns_study_date(client, test_db):
    """list_decks 返回的每个 deck 都包含 study_date 字段。"""
    _insert_question(test_db, "什么是连接池？", frequency=8)
    test_db.commit()
    app, dependency = _override_user()

    try:
        decks = client.get("/api/practice/decks")
        assert decks.status_code == 200, decks.text
        items = decks.json().get("items", [])
        assert len(items) > 0
        for deck in items:
            assert "study_date" in deck, f"deck '{deck.get('key')}' 缺少 study_date"
            import re
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", deck["study_date"]), (
                f"deck '{deck.get('key')}' study_date 格式错误: {deck['study_date']}"
            )
    finally:
        app.dependency_overrides.pop(dependency, None)


def test_study_date_matches_server_local_date(client, test_db):
    """study_date 与服务端 STUDY_TIMEZONE 的当前日期一致。"""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    _insert_question(test_db, "什么是连接池？", frequency=8)
    test_db.commit()
    app, dependency = _override_user()

    try:
        queue = client.get("/api/practice/decks/due/questions")
        assert queue.status_code == 200, queue.text
        deck = queue.json().get("deck", {})
        study_date = deck.get("study_date", "")

        # 计算期望值：当前 UTC 时间转为 Asia/Shanghai
        zone = ZoneInfo("Asia/Shanghai")
        expected = datetime.now(timezone.utc).astimezone(zone).date().isoformat()
        assert study_date == expected, (
            f"study_date={study_date} 与期望值 {expected} 不一致"
        )
    finally:
        app.dependency_overrides.pop(dependency, None)

