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




def test_reviewed_today_flag_at_study_day_boundary(client, test_db):
    """时区边界：研究日内的复习 reviewed_today=true，研究日外（昨天）为 false。"""
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo
    import datetime as dt_mod

    qid = _insert_question(test_db, "什么是连接池？", frequency=8)
    qid2 = _insert_question(test_db, "什么是幂等？", frequency=2)
    test_db.commit()

    # 复用后端同一口径计算研究日 UTC 边界（与 practice_deck_service._study_day_utc_bounds 一致）
    zone = ZoneInfo("Asia/Shanghai")
    now = datetime.now(timezone.utc)
    local_day = now.astimezone(zone).date()
    start = dt_mod.datetime.combine(local_day, dt_mod.time.min, tzinfo=zone).astimezone(timezone.utc)
    end = start + dt_mod.timedelta(days=1)

    # 场景 1：研究日内最近记录（start + 1 分钟）→ reviewed_today 应为 true
    in_bound_ts = (start + dt_mod.timedelta(minutes=1)).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")
    # 场景 2：昨天研究日（start - 1 分钟）→ reviewed_today 应为 false
    out_bound_ts = (start - dt_mod.timedelta(minutes=1)).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M:%S")

    # 先插入 user_question_review（拿到 id），再插入 events（FK review_id 引用它）
    rev1 = test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, "
        "last_rating, last_score, last_reviewed_at, next_review_at, interval_days, ease_factor, stability_days, difficulty, algorithm, updated_at) "
        "VALUES (1, ?, 'review', 1, 1, 'good', 90, ?, NULL, 3.0, 2.3, 3.0, 0.6, 'sm2_lite', ?)",
        (qid, in_bound_ts, in_bound_ts),
    ).lastrowid
    test_db.execute(
        "INSERT INTO practice_review_events (user_id, question_bank_id, review_id, rating, score, source, reviewed_at) "
        "VALUES (1, ?, ?, 'good', 90, 'flashcard', ?)",
        (qid, rev1, in_bound_ts),
    )
    rev2 = test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, "
        "last_rating, last_score, last_reviewed_at, next_review_at, interval_days, ease_factor, stability_days, difficulty, algorithm, updated_at) "
        "VALUES (1, ?, 'review', 1, 1, 'good', 80, ?, NULL, 3.0, 2.3, 3.0, 0.6, 'sm2_lite', ?)",
        (qid2, out_bound_ts, out_bound_ts),
    ).lastrowid
    test_db.execute(
        "INSERT INTO practice_review_events (user_id, question_bank_id, review_id, rating, score, source, reviewed_at) "
        "VALUES (1, ?, ?, 'good', 80, 'flashcard', ?)",
        (qid2, rev2, out_bound_ts),
    )
    test_db.commit()

    app, dependency = _override_user()
    try:
        queue = client.get("/api/practice/decks/due/questions")
        assert queue.status_code == 200, queue.text
        items = queue.json().get("items", [])
        by_id = {i["id"]: i for i in items}
        assert qid in by_id, f"题目 {qid} 应在 due 队列"
        assert "reviewed_today" in by_id[qid], f"item 缺少 reviewed_today: {list(by_id[qid].keys())}"
        assert by_id[qid]["reviewed_today"] is True, (
            f"研究日内复习 reviewed_today 应为 true: {by_id[qid]['reviewed_today']}"
        )
        if qid2 in by_id:
            assert by_id[qid2]["reviewed_today"] is False, (
                f"非研究日复习 reviewed_today 应为 false: {by_id[qid2]['reviewed_today']}"
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