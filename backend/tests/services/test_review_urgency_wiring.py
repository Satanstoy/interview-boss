"""
review 端点接入 urgency 的接线测试

- `_user_urgency` 助手：从用户招聘偏好（届次 + pace）计算机会窗口 urgency
  （无偏好 → base 0.2；测试固定 today，避免依赖真实日期），无 deadline 概念
- `/api/practice/review` 端点：mastered 抽查打卡 30 天重置 / again 降级、
  按 pace 应用 urgency 调制（smoke）
"""

from datetime import date

import pytest

from app.db.connection import get_db_connection

POSITION = "agent开发/大模型应用开发/大模型开发"


def _make_user(client, test_db):
    """创建测试用户并返回 (Bearer token, user_id)"""
    from app.core.auth import create_access_token

    cursor = test_db.execute(
        "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
        "VALUES (?, ?, ?, 0, 'private')",
        ("test_review_user", "test-hash", "test_review_user@example.com"),
    )
    test_db.commit()
    user_id = cursor.lastrowid
    token = create_access_token({"user_id": user_id, "type": "access"})
    return token, user_id


def _seed(conn):
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, tags, difficulty, ai_answer, status, owner_id, frequency, job_position) "
        "VALUES (1, 'Q1', '基础', '线程', '八股', 'L1-基础', 'A1', 'approved', NULL, 5, ?)",
        (POSITION,),
    )
    conn.commit()


def _seed_mastered(conn, user_id):
    conn.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, "
        "interval_days, ease_factor, next_review_at, updated_at) "
        "VALUES (?, 1, 'mastered', 5, 9, 30.0, 2.6, datetime('now', '-1 days'), CURRENT_TIMESTAMP)",
        (user_id,),
    )
    conn.commit()


def test_user_urgency_returns_base_without_prefs(test_db):
    from app.routers.practice import _user_urgency

    _, user_id = _make_user(None, test_db)
    assert _user_urgency(user_id, today=date(2026, 8, 10)) == pytest.approx(0.2)


def test_user_urgency_computes_from_windows_and_pace(test_db):
    from app.routers.practice import _user_urgency

    _, hard_id = _make_user(None, test_db)
    _, easy_id = _make_user(None, test_db)
    test_db.execute(
        "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity, pace) "
        "VALUES (?, 2027, 'autumn', 30, 'hard')",
        (hard_id,),
    )
    test_db.execute(
        "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity, pace) "
        "VALUES (?, 2027, 'autumn', 30, 'easy')",
        (easy_id,),
    )
    test_db.commit()
    # 提前批窗口内（peak 2026-08-15，today 2026-08-20）：hard 紧迫度 > easy
    assert _user_urgency(hard_id, today=date(2026, 8, 20)) > _user_urgency(
        easy_id, today=date(2026, 8, 20)
    )
    # 窗口间歇期（2026-06-01 无任何脉冲）：只剩 base 0.2 ± pace 偏移
    # hard = 0.2 + 0.3 = 0.5；easy = 0.2 − 0.3 → 截断到 0.0
    assert _user_urgency(hard_id, today=date(2026, 6, 1)) == pytest.approx(0.5)
    assert _user_urgency(easy_id, today=date(2026, 6, 1)) == pytest.approx(0.0)


def test_review_mastered_card_resets_to_30_days(client, test_db):
    token, user_id = _make_user(client, test_db)
    with get_db_connection() as conn:
        _seed(conn)
        _seed_mastered(conn, user_id)
    resp = client.post(
        "/api/practice/review",
        json={"question_id": 1, "rating": "good", "score": 80},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    review = resp.json()["review"]
    assert review["state"] == "mastered"
    assert review["interval_days"] == 30.0


def test_review_mastered_again_degrades(client, test_db):
    token, user_id = _make_user(client, test_db)
    with get_db_connection() as conn:
        _seed(conn)
        _seed_mastered(conn, user_id)
    resp = client.post(
        "/api/practice/review",
        json={"question_id": 1, "rating": "again", "score": 40},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    review = resp.json()["review"]
    assert review["state"] == "relearning"
    assert review["proficiency"] == 4


def test_review_applies_urgency_from_pace(client, test_db):
    """pace=hard + 窗口内 → 间隔明显短于 pace=easy 的对照"""
    token_hard, uid_hard = _make_user(client, test_db)
    token_easy, uid_easy = _make_user(client, test_db)
    with get_db_connection() as conn:
        _seed(conn)
        conn.execute(
            "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity, pace) "
            "VALUES (?, 2027, 'autumn', 30, 'hard')",
            (uid_hard,),
        )
        conn.execute(
            "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity, pace) "
            "VALUES (?, 2027, 'autumn', 30, 'easy')",
            (uid_easy,),
        )
        conn.commit()
    # 窗口内日期：无论真实今天在哪个窗口/间歇，hard 偏移 +0.3 ≥ easy −0.3，
    # 同一评分下 hard 用户的间隔 <= easy 用户（clamp 到 1.0 时相等）
    iv_hard = client.post(
        "/api/practice/review",
        json={"question_id": 1, "rating": "good", "score": 80},
        headers={"Authorization": f"Bearer {token_hard}"},
    ).json()["review"]["interval_days"]
    iv_easy = client.post(
        "/api/practice/review",
        json={"question_id": 1, "rating": "good", "score": 80},
        headers={"Authorization": f"Bearer {token_easy}"},
    ).json()["review"]["interval_days"]
    assert iv_hard <= iv_easy
