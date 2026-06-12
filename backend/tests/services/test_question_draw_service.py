"""Tests for weighted question drawing service."""

from datetime import datetime, timedelta


def _seed_draw_questions(conn):
    conn.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, bank_mode) "
        "VALUES (?, ?, ?, ?)",
        (7, "draw-test-user", "hash", "public"),
    )
    rows = [
        (1, "Redis 缓存穿透怎么解决？", "后端", "Redis", "redis,缓存", "中等", 8, "approved", "后端开发"),
        (2, "MySQL 索引为什么会失效？", "数据库", "MySQL", "mysql,索引", "中等", 5, "approved", "后端开发"),
        (3, "React Hooks 的闭包问题？", "前端", "React", "react", "中等", 3, "approved", "前端开发"),
        (4, "TCP 三次握手的目的是什么？", "网络", "TCP", "tcp", "简单", 6, "approved", "后端开发"),
    ]
    for row in rows:
        conn.execute(
            "INSERT INTO question_bank "
            "(id, question, cat1, cat2, tags, difficulty, frequency, status, job_position) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )
    conn.execute(
        "INSERT INTO user_practice_history "
        "(user_id, question_bank_id, user_answer, score, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (7, 1, "答过", 80, (datetime.now() - timedelta(days=3)).isoformat()),
    )
    conn.commit()


def test_draw_questions_filters_and_adds_practice_stats(test_db, monkeypatch):
    from app.services import question_draw_service

    _seed_draw_questions(test_db)
    monkeypatch.setattr(
        question_draw_service,
        "_build_bank_where_clause",
        lambda user, table_alias="qb": (
            f"FROM question_bank {table_alias}",
            f"WHERE {table_alias}.status = 'approved'",
            [],
        ),
    )
    monkeypatch.setattr(
        question_draw_service,
        "get_dynamic_frequency_sql",
        lambda bank_mode, user_id: "qb.frequency",
    )
    monkeypatch.setattr(
        question_draw_service,
        "get_sources",
        lambda conn, qid: [{"company": "测试公司", "round": "一面"}],
    )
    monkeypatch.setattr(question_draw_service.random, "random", lambda: 0)

    result = question_draw_service.draw_questions(
        user={"id": 7, "bank_mode": "public"},
        count=3,
        cat1="后端",
        exclude_ids={4},
    )

    result_ids = {q["id"] for q in result}
    assert result_ids <= {1}
    assert 4 not in result_ids
    assert result[0]["attempt_count"] == 1
    assert result[0]["last_practiced_at"]
    assert result[0]["sources"] == [{"company": "测试公司", "round": "一面"}]


def test_draw_questions_returns_empty_when_no_candidates(test_db, monkeypatch):
    from app.services import question_draw_service

    _seed_draw_questions(test_db)
    monkeypatch.setattr(
        question_draw_service,
        "_build_bank_where_clause",
        lambda user, table_alias="qb": (
            f"FROM question_bank {table_alias}",
            f"WHERE {table_alias}.status = 'approved'",
            [],
        ),
    )
    monkeypatch.setattr(
        question_draw_service,
        "get_dynamic_frequency_sql",
        lambda bank_mode, user_id: "qb.frequency",
    )

    result = question_draw_service.draw_questions(
        user={"id": 7, "bank_mode": "public"},
        count=5,
        cat1="不存在的分类",
    )

    assert result == []


def test_weighted_sampling_prefers_high_frequency(monkeypatch):
    from app.services import question_draw_service

    candidates = [
        {"id": 1, "frequency": 1},
        {"id": 2, "frequency": 100},
    ]

    monkeypatch.setattr(question_draw_service.random, "random", lambda: 0.95)

    selected = question_draw_service._weighted_sample_without_replacement(
        candidates, practice_map={}, count=1
    )

    assert selected == [1]
