"""Tests for practice history endpoint reading review events with answer snapshots."""

import json


USER = {"id": 1, "username": "hist-test-user", "is_admin": 0, "bank_mode": "public"}
POSITION = "agent开发/大模型应用开发/大模型开发"


def _override_user():
    from app.asgi import app
    from app.core.auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: USER
    return app, get_current_user


def _insert_question(conn, text):
    row = conn.execute(
        """
        INSERT INTO question_bank
            (question, cat1, cat2, tags, difficulty, frequency, ai_answer, owner_id, status, job_position)
        VALUES (?, '后端', '基础', '八股', 'L1-基础', 8, '参考答案', NULL, 'approved', ?)
        RETURNING id
        """,
        (text, POSITION),
    ).fetchone()
    return row[0]


def test_evaluate_answer_stores_user_answer_snapshot(client, test_db, mock_llm):
    """evaluate-answer 应在 practice_review_events 落 user_answer 快照。"""
    qid = _insert_question(test_db, "什么是连接池？")
    test_db.commit()

    # mock LLM 返回结构化评估结果
    from unittest.mock import AsyncMock, patch

    fake_result = {
        "overall_score": 88,
        "dimensions": {"completeness": {"score": 90, "comment": "全面"}, "depth": {"score": 85, "comment": "深入"}},
        "strengths": ["结论清晰"],
        "weaknesses": ["缺少示例"],
        "suggestions": "补充示例",
    }

    app, dependency = _override_user()
    try:
        with patch(
            "app.routers.practice._call_llm_with_retry",
            new=AsyncMock(return_value=json.dumps(fake_result, ensure_ascii=False)),
        ), patch(
            "app.routers.practice.check_and_record", new=AsyncMock(return_value=True)
        ):
            resp = client.post(
                "/api/evaluate-answer",
                json={
                    "question_id": qid,
                    "question_text": "什么是连接池？",
                    "user_answer": "连接池是复用数据库连接的技术",
                    "reference_answer": "参考答案",
                },
            )
        assert resp.status_code == 200, resp.text

        # 验证 review events 里有 user_answer 快照
        row = test_db.execute(
            "SELECT user_answer, source, score FROM practice_review_events "
            "WHERE question_bank_id = ? AND user_id = 1 ORDER BY id DESC LIMIT 1",
            (qid,),
        ).fetchone()
        assert row is not None, "应写入 practice_review_events"
        assert row["user_answer"] == "连接池是复用数据库连接的技术", (
            f"user_answer 快照缺失: {row['user_answer']}"
        )
        assert row["source"] == "self_check"
    finally:
        app.dependency_overrides.pop(dependency, None)


def test_practice_history_reads_review_events(client, test_db):
    """practice-history 端点应返回 review events（含 user_answer/rating/source）。"""
    qid = _insert_question(test_db, "什么是幂等？")
    test_db.commit()

    # 直接插入一条 self_check 事件（模拟 evaluate-answer 写入）
    rev = test_db.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, "
        "last_rating, last_score, last_reviewed_at, next_review_at, interval_days, ease_factor, stability_days, difficulty, algorithm, updated_at) "
        "VALUES (1, ?, 'review', 1, 1, 'good', 88, '2026-08-18 02:00:00', NULL, 3.0, 2.3, 3.0, 0.6, 'sm2_lite', '2026-08-18 02:00:00')",
        (qid,),
    ).lastrowid
    test_db.execute(
        "INSERT INTO practice_review_events (user_id, question_bank_id, review_id, rating, score, source, reviewed_at, user_answer) "
        "VALUES (1, ?, ?, 'good', 88, 'self_check', '2026-08-18 02:00:00', '我的答案')",
        (qid, rev),
    )
    test_db.commit()

    app, dependency = _override_user()
    try:
        resp = client.get(f"/api/practice-history/{qid}")
        assert resp.status_code == 200, resp.text
        items = resp.json()
        assert len(items) == 1, f"应返回 1 条历史: {items}"
        assert items[0]["score"] == 88
        assert items[0]["user_answer"] == "我的答案"
        assert items[0]["rating"] == "good"
        assert items[0]["source"] == "self_check"
    finally:
        app.dependency_overrides.pop(dependency, None)
