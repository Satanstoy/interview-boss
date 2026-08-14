"""
复习提交幂等键（audit D14）

- `record_review` 接受可选 `idempotency_key`；同 (user_id, question_bank_id,
  idempotency_key) 已存在事件时跳过，不重复写入事件也不二次推进 SRS review_count。
- `/api/practice/review` 端点从请求体透传可选 `idempotency_key`。
- `practice_review_events.idempotency_key` 有 (user_id, question_bank_id,
  idempotency_key) 部分唯一索引（WHERE idempotency_key IS NOT NULL），DB 层兜底防重。
"""

import pytest

from app.services.practice_review_service import record_review

POSITION = "agent开发/大模型应用开发/大模型开发"


def _seed(conn):
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, tags, difficulty, ai_answer, status, owner_id, frequency, job_position) "
        "VALUES (1, 'Q1', '基础', '线程', '八股', 'L1-基础', 'A1', 'approved', NULL, 5, ?)",
        (POSITION,),
    )
    conn.commit()


def _count_events(conn, user_id, key=None):
    if key is None:
        return conn.execute(
            "SELECT COUNT(*) AS n FROM practice_review_events WHERE user_id = ?",
            (user_id,),
        ).fetchone()["n"]
    return conn.execute(
        "SELECT COUNT(*) AS n FROM practice_review_events "
        "WHERE user_id = ? AND question_bank_id = 1 AND idempotency_key = ?",
        (user_id, key),
    ).fetchone()["n"]


def _review_count(conn, user_id):
    row = conn.execute(
        "SELECT review_count FROM user_question_review WHERE user_id = ? AND question_bank_id = 1",
        (user_id,),
    ).fetchone()
    return row["review_count"] if row else 0


def test_record_review_same_key_dedupes_events_and_srs(test_db):
    """同 idempotency_key 提交两次：只写入一行事件，review_count 只 +1。"""
    _seed(test_db)
    first = record_review(
        test_db,
        user_id=1,
        question_id=1,
        rating="good",
        score=80,
        idempotency_key="review-uuid-1",
    )
    assert first["review_count"] == 1
    assert _count_events(test_db, 1) == 1
    assert _review_count(test_db, 1) == 1

    second = record_review(
        test_db,
        user_id=1,
        question_id=1,
        rating="good",
        score=80,
        idempotency_key="review-uuid-1",
    )
    test_db.commit()
    assert second["review_count"] == first["review_count"]
    assert _count_events(test_db, 1) == 1
    assert _review_count(test_db, 1) == 1


def test_record_review_no_key_still_advances(test_db):
    """不传 idempotency_key 时保持原行为：每次都正常写入并推进 SRS。"""
    _seed(test_db)
    record_review(test_db, user_id=1, question_id=1, rating="good", score=80)
    record_review(test_db, user_id=1, question_id=1, rating="good", score=80)
    test_db.commit()
    assert _count_events(test_db, 1) == 2
    assert _review_count(test_db, 1) == 2


def test_record_review_different_keys_both_apply(test_db):
    """不同 idempotency_key 视为不同提交，各自都推进 SRS。"""
    _seed(test_db)
    record_review(
        test_db, user_id=1, question_id=1, rating="good", score=80, idempotency_key="a"
    )
    record_review(
        test_db, user_id=1, question_id=1, rating="good", score=80, idempotency_key="b"
    )
    test_db.commit()
    assert _count_events(test_db, 1) == 2
    assert _review_count(test_db, 1) == 2


def test_review_endpoint_idempotency_key_wiring(client, test_db):
    """`/api/practice/review` 从请求体读取可选 idempotency_key 并透传。"""
    from app.core.auth import create_access_token

    test_db.execute(
        "INSERT INTO users (username, password_hash, email, is_admin, share_default) "
        "VALUES ('idem_user', 'test-hash', 'idem@example.com', 0, 'private')"
    )
    test_db.commit()
    user_id = test_db.execute(
        "SELECT id FROM users WHERE username = 'idem_user'"
    ).fetchone()["id"]
    token = create_access_token({"user_id": user_id, "type": "access"})
    _seed(test_db)

    payload = {"question_id": 1, "rating": "good", "score": 80, "idempotency_key": "review-uuid-1"}
    headers = {"Authorization": f"Bearer {token}"}
    r1 = client.post("/api/practice/review", json=payload, headers=headers)
    r2 = client.post("/api/practice/review", json=payload, headers=headers)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert _count_events(test_db, user_id, key="review-uuid-1") == 1
    assert _count_events(test_db, user_id) == 1
    assert _review_count(test_db, user_id) == 1
