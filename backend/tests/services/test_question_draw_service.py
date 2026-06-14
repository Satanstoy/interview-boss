"""Tests for weighted question drawing service."""

from datetime import datetime, timedelta


def _seed_draw_questions(conn):
    conn.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, bank_mode) "
        "VALUES (?, ?, ?, ?)",
        (7, "draw-test-user", "hash", "public"),
    )
    rows = [
        (
            1,
            "Redis 缓存穿透怎么解决？",
            "后端",
            "Redis",
            "redis,缓存",
            "中等",
            8,
            "approved",
            "后端开发",
        ),
        (
            2,
            "MySQL 索引为什么会失效？",
            "数据库",
            "MySQL",
            "mysql,索引",
            "中等",
            5,
            "approved",
            "后端开发",
        ),
        (
            3,
            "React Hooks 的闭包问题？",
            "前端",
            "React",
            "react",
            "中等",
            3,
            "approved",
            "前端开发",
        ),
        (
            4,
            "TCP 三次握手的目的是什么？",
            "网络",
            "TCP",
            "tcp",
            "简单",
            6,
            "approved",
            "后端开发",
        ),
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


# ── Difficulty mapping tests ──────────────────────────────


def _seed_algorithm_questions(conn):
    """Seed algorithm coding questions with Chinese difficulty labels."""
    conn.execute(
        "INSERT OR IGNORE INTO users (id, username, password_hash, bank_mode) "
        "VALUES (?, ?, ?, ?)",
        (8, "algo-test-user", "hash", "public"),
    )
    rows = [
        (
            101,
            "实现 LRU Cache",
            "E.算法与数据结构",
            "E2.算法手撕",
            "lru,缓存",
            "L2-中等",
            10,
            "approved",
            "后端开发",
        ),
        (
            102,
            "二叉树的层序遍历",
            "E.算法与数据结构",
            "E1.数据结构",
            "二叉树,bfs",
            "L1-基础",
            8,
            "approved",
            "后端开发",
        ),
        (
            103,
            "合并 K 个有序链表",
            "E.算法与数据结构",
            "E2.算法手撕",
            "链表,堆",
            "L3-困难",
            6,
            "approved",
            "后端开发",
        ),
        (
            104,
            "最长递增子序列",
            "E.算法与数据结构",
            "E2.算法手撕",
            "动态规划",
            "L2-中等",
            7,
            "approved",
            "后端开发",
        ),
    ]
    for row in rows:
        conn.execute(
            "INSERT INTO question_bank "
            "(id, question, cat1, cat2, tags, difficulty, frequency, status, job_position) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            row,
        )
    conn.commit()


def _patch_draw_helpers(monkeypatch):
    """Common monkeypatches for draw_questions tests."""
    from app.services import question_draw_service

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
        lambda conn, qid: [],
    )
    return question_draw_service


def test_difficulty_mapping_medium_matches_l2(test_db, monkeypatch):
    """difficulty='medium' should match Chinese 'L2-中等' questions."""
    qds = _patch_draw_helpers(monkeypatch)
    _seed_algorithm_questions(test_db)
    monkeypatch.setattr(qds.random, "random", lambda: 0)

    result = qds.draw_questions(
        user={"id": 8, "bank_mode": "public"},
        count=5,
        question_type="algorithm_coding",
        difficulty="medium",
    )

    result_ids = {q["id"] for q in result}
    # L2-中等 questions: 101 (LRU Cache), 104 (最长递增子序列)
    assert 101 in result_ids
    assert 104 in result_ids
    # L1-基础 and L3-困难 should NOT be included
    assert 102 not in result_ids
    assert 103 not in result_ids


def test_difficulty_mapping_easy_matches_l1(test_db, monkeypatch):
    """difficulty='easy' should match Chinese 'L1-基础' questions."""
    qds = _patch_draw_helpers(monkeypatch)
    _seed_algorithm_questions(test_db)
    monkeypatch.setattr(qds.random, "random", lambda: 0)

    result = qds.draw_questions(
        user={"id": 8, "bank_mode": "public"},
        count=5,
        question_type="algorithm_coding",
        difficulty="easy",
    )

    result_ids = {q["id"] for q in result}
    assert 102 in result_ids
    assert 101 not in result_ids


def test_difficulty_mapping_hard_matches_l3(test_db, monkeypatch):
    """difficulty='hard' should match Chinese 'L3-困难' questions."""
    qds = _patch_draw_helpers(monkeypatch)
    _seed_algorithm_questions(test_db)
    monkeypatch.setattr(qds.random, "random", lambda: 0)

    result = qds.draw_questions(
        user={"id": 8, "bank_mode": "public"},
        count=5,
        question_type="algorithm_coding",
        difficulty="hard",
    )

    result_ids = {q["id"] for q in result}
    assert 103 in result_ids
    assert 101 not in result_ids


def test_difficulty_fallback_when_no_match(test_db, monkeypatch):
    """When difficulty filter yields 0 results, retry without difficulty."""
    qds = _patch_draw_helpers(monkeypatch)
    _seed_algorithm_questions(test_db)
    monkeypatch.setattr(qds.random, "random", lambda: 0)

    # Use a difficulty that doesn't exist in seed data
    result = qds.draw_questions(
        user={"id": 8, "bank_mode": "public"},
        count=5,
        question_type="algorithm_coding",
        difficulty="impossible_level",
    )

    # Should fall back and return questions without difficulty filter
    assert len(result) > 0
    result_ids = {q["id"] for q in result}
    assert result_ids & {101, 102, 103, 104}


def test_difficulty_mapping_chinese_input_still_works(test_db, monkeypatch):
    """Chinese difficulty input like '中等' should still work via LIKE match."""
    qds = _patch_draw_helpers(monkeypatch)
    _seed_algorithm_questions(test_db)
    monkeypatch.setattr(qds.random, "random", lambda: 0)

    result = qds.draw_questions(
        user={"id": 8, "bank_mode": "public"},
        count=5,
        difficulty="中等",
    )

    result_ids = {q["id"] for q in result}
    # "中等" matches "L2-中等"
    assert 101 in result_ids or 104 in result_ids
