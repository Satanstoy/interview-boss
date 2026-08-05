"""
review 端点接入 urgency/deadline 的接线测试

- `_user_urgency` 助手：从用户招聘偏好计算 urgency 与下一个 window_close 截止时间
  （测试固定 today，避免依赖真实日期）
- `/api/practice/review` 端点：记录复习并返回排期（smoke）
"""

from datetime import date, datetime

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


def test_user_urgency_returns_zero_without_prefs(test_db):
    from app.routers.practice import _user_urgency

    token, user_id = _make_user(None, test_db)
    assert token
    urgency, deadline = _user_urgency(user_id, today=date(2026, 8, 10))
    assert urgency == 0.0
    assert deadline is None


def test_user_urgency_returns_zero_for_daily_batch(test_db):
    from app.routers.practice import _user_urgency

    _, user_id = _make_user(None, test_db)
    test_db.execute(
        "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity) "
        "VALUES (?, ?, 'daily', 30)",
        (user_id, 2027),
    )
    test_db.commit()
    urgency, deadline = _user_urgency(user_id, today=date(2026, 8, 10))
    assert urgency == 0.0
    assert deadline is None


def test_user_urgency_computes_urgency_and_deadline(test_db):
    from app.routers.practice import _user_urgency

    _, user_id = _make_user(None, test_db)
    test_db.execute(
        "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity) "
        "VALUES (?, ?, 'autumn', 30)",
        (user_id, 2027),
    )
    test_db.commit()
    # autumn 2027：提前批窗口关闭 2026-08-31 → days_left 21 → urgency 0.65
    urgency, deadline = _user_urgency(user_id, today=date(2026, 8, 10))
    assert urgency > 0.0
    assert deadline == datetime(2026, 8, 31, 0, 0)


def test_user_urgency_skips_past_window_close_for_deadline(test_db):
    from app.routers.practice import _user_urgency

    _, user_id = _make_user(None, test_db)
    test_db.execute(
        "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity) "
        "VALUES (?, ?, 'autumn', 30)",
        (user_id, 2027),
    )
    test_db.commit()
    # 2026-09-10：最近的里程碑是正式批高峰（peak），窗口关闭已过期 → deadline None
    urgency, deadline = _user_urgency(user_id, today=date(2026, 9, 10))
    assert urgency > 0.0
    assert deadline is None


def test_user_urgency_no_window_close_means_no_deadline(test_db):
    from app.routers.practice import _user_urgency

    _, user_id = _make_user(None, test_db)
    test_db.execute(
        "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity) "
        "VALUES (?, ?, 'spring', 30)",
        (user_id, 2027),
    )
    test_db.commit()
    urgency, deadline = _user_urgency(user_id, today=date(2026, 8, 10))
    assert urgency == 0.0  # 主批高峰 2027-04-15 距离 > 60 天
    assert deadline is None  # spring 无 window_close 里程碑


def test_review_endpoint_records_review(client, test_db):
    token, user_id = _make_user(client, test_db)
    with get_db_connection() as conn:
        _seed(conn)
        conn.commit()
    resp = client.post(
        "/api/practice/review",
        json={"question_id": 1, "rating": "good", "score": 80},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    review = resp.json()["review"]
    assert review["review_count"] == 1
    assert review["next_review_at"]
    assert review["interval_days"] == 3.0  # 无偏好 → 基线间隔


def test_review_endpoint_applies_urgency_when_prefs_active(client, test_db):
    token, user_id = _make_user(client, test_db)
    test_db.execute(
        "INSERT INTO user_recruitment_pref (user_id, graduation_year, batch, daily_capacity) "
        "VALUES (?, 2027, 'autumn', 30)",
        (user_id,),
    )
    test_db.commit()
    with get_db_connection() as conn:
        _seed(conn)
        conn.commit()
    resp = client.post(
        "/api/practice/review",
        json={"question_id": 1, "rating": "good", "score": 80},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    review = resp.json()["review"]
    assert review["review_count"] == 1
    assert review["next_review_at"]
    # 有偏好的间隔必须 <= 无偏好基线 3.0（urgency=0 时相等，>0 时更短）
    assert review["interval_days"] <= 3.0
