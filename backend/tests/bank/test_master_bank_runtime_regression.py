"""题库运行时 SQL 回归测试。"""

USER = {"id": 1, "username": "sj", "is_admin": 1, "bank_mode": "all"}
POSITION = "agent开发/大模型应用开发/大模型开发"


def _ensure_practice_tables(conn):
    """Make the regression independent from the optional practice migration."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS user_question_review (
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            state TEXT NOT NULL DEFAULT 'new',
            proficiency INTEGER NOT NULL DEFAULT 0,
            review_count INTEGER NOT NULL DEFAULT 0,
            lapse_count INTEGER NOT NULL DEFAULT 0,
            last_rating TEXT DEFAULT '',
            last_reviewed_at TIMESTAMP,
            next_review_at TIMESTAMP,
            interval_days REAL NOT NULL DEFAULT 0,
            ease_factor REAL NOT NULL DEFAULT 2.3
        );
        CREATE TABLE IF NOT EXISTS practice_review_events (
            user_id INTEGER NOT NULL,
            question_bank_id INTEGER NOT NULL,
            score INTEGER,
            reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
    )


def _insert_question(conn):
    _ensure_practice_tables(conn)
    row = conn.execute(
        "INSERT INTO question_bank "
        "(question, cat1, cat2, tags, difficulty, frequency, ai_answer, owner_id, status, job_position) "
        "VALUES (?, '后端', '基础', 'SQL', '中等', 3, '参考答案', NULL, 'approved', ?)",
        ("题库运行时 SQL 回归题", POSITION),
    ).fetchone()
    conn.commit()
    return row[0] if row else conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def test_master_bank_works_with_practice_review_schema(client, test_db):
    """user_question_review.state 应映射为 API 的 review_state。"""
    from app.asgi import app
    from app.core.auth import get_current_user

    question_id = _insert_question(test_db)
    app.dependency_overrides[get_current_user] = lambda: USER

    try:
        response = client.get(
            "/api/master-bank?filter=all&compact=true&page=1&page_size=50"
        )
        assert response.status_code == 200, response.text
        item = next(item for item in response.json()["items"] if item["id"] == question_id)
        assert item["review_state"] == "new"
        assert item["review_count"] == 0
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_practice_stats_works_without_position_join(client, test_db):
    """没有 question_position 关联时，统计 SQL 也不能拼出重复 FROM。"""
    from app.asgi import app
    from app.core.auth import get_current_user

    _insert_question(test_db)
    app.dependency_overrides[get_current_user] = lambda: USER

    try:
        response = client.get("/api/practice-stats")
        assert response.status_code == 200, response.text
        assert response.json()["total_questions"] >= 1
    finally:
        app.dependency_overrides.pop(get_current_user, None)
