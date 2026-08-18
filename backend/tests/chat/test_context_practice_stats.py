"""Tests for chat context builder practice summary (read from review events)."""


def _insert_review_event(conn, user_id, question_id, score, reviewed_at):
    """Insert a self_check review event + question + review state."""
    rev = conn.execute(
        "INSERT INTO user_question_review (user_id, question_bank_id, state, proficiency, review_count, "
        "last_rating, last_score, last_reviewed_at, next_review_at, interval_days, ease_factor, stability_days, difficulty, algorithm, updated_at) "
        "VALUES (?, ?, 'review', 1, 1, 'good', ?, ?, NULL, 3.0, 2.3, 3.0, 0.6, 'sm2_lite', ?)",
        (user_id, question_id, score, reviewed_at, reviewed_at),
    ).lastrowid
    conn.execute(
        "INSERT INTO practice_review_events (user_id, question_bank_id, review_id, rating, score, source, reviewed_at) "
        "VALUES (?, ?, ?, 'good', ?, 'self_check', ?)",
        (user_id, question_id, rev, score, reviewed_at),
    )


def test_practice_summary_reads_review_events(test_db):
    """练习摘要的「最近练习」应来自 practice_review_events（自评事件）。"""
    from app.agents.chat.context_builder import _get_user_practice_summary

    # 准备题目
    q = test_db.execute(
        "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, ai_answer, owner_id, status, job_position) "
        "VALUES ('什么是连接池？', '后端', '基础', '八股', 'L1-基础', 8, '参考答案', NULL, 'approved', 'agent开发/大模型应用开发/大模型开发') "
        "RETURNING id"
    ).fetchone()[0]

    # 插入一条最近的自评事件（source='self_check'）
    _insert_review_event(test_db, 1, q, 92, "2026-08-18 02:00:00")
    test_db.commit()

    summary = _get_user_practice_summary(1)
    assert "已练习 1 题" in summary, f"应包含总练习数: {summary}"
    assert "92分" in summary, f"最近练习应包含该题评分: {summary}"
    assert "连接池" in summary, f"最近练习应包含该题题目: {summary}"
