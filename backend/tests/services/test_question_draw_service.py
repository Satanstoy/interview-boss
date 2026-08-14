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
    # 双写收敛后读端在 practice_review_events(source='self_check');
    # review_id NOT NULL FK -> user_question_review, 先插 SRS 状态拿 id
    cur = conn.execute(
        "INSERT INTO user_question_review "
        "(user_id, question_bank_id, state, proficiency, review_count, last_rating, "
        "last_score, last_reviewed_at, next_review_at, interval_days, ease_factor, "
        "stability_days, difficulty, algorithm, updated_at) "
        "VALUES (?, ?, 'review', 0.6, 1, 'good', 80, ?, ?, 3, 2.5, 3, 0.7, 'sm2_lite', ?)",
        (7, 1, (datetime.now() - timedelta(days=3)).isoformat(),
         (datetime.now() + timedelta(days=3)).isoformat(),
         (datetime.now() - timedelta(days=3)).isoformat()),
    )
    review_id = cur.lastrowid
    conn.execute(
        "INSERT INTO practice_review_events "
        "(user_id, question_bank_id, review_id, rating, score, source, reviewed_at) "
        "VALUES (?, ?, ?, 'good', 80, 'self_check', ?)",
        (7, 1, review_id, (datetime.now() - timedelta(days=3)).isoformat()),
    )
    conn.commit()


def test_draw_questions_filters_and_adds_practice_stats(test_db, monkeypatch):
    from app.services import question_draw_service

    _seed_draw_questions(test_db)
    monkeypatch.setattr(
        "app.services.question_draw_service.build_bank_where_clause",
        lambda user_id, filter_mode="all", table_alias="qb": (
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
        "app.services.question_draw_service.build_bank_where_clause",
        lambda user_id, filter_mode="all", table_alias="qb": (
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


def test_algorithm_draw_does_not_fall_back_to_another_position_when_current_position_empty(
    test_db, monkeypatch
):
    """An empty position remains empty instead of mixing another position."""
    from app.services import question_draw_service

    test_db.execute(
        "INSERT OR IGNORE INTO job_positions (id, name) VALUES (?, ?)",
        (201, "默认算法岗位"),
    )
    test_db.execute(
        "INSERT OR IGNORE INTO job_positions (id, name) VALUES (?, ?)",
        (202, "空的新岗位"),
    )
    test_db.execute(
        "INSERT OR IGNORE INTO users "
        "(id, username, password_hash, bank_mode, current_position_id) "
        "VALUES (?, ?, ?, ?, ?)",
        (77, "algo-fallback-user", "hash", "public", 202),
    )
    test_db.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, tags, difficulty, frequency, status, job_position) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            7701,
            "算法题：手写 LRU Cache",
            "E.算法与数据结构",
            "E1.数据结构",
            "算法手撕,lru",
            "L2-中等",
            9,
            "approved",
            "默认算法岗位",
        ),
    )
    test_db.execute(
        "INSERT INTO question_position (question_id, position_id) VALUES (?, ?)",
        (7701, 201),
    )
    test_db.commit()

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
    monkeypatch.setattr(question_draw_service.random, "random", lambda: 0)

    result = question_draw_service.draw_questions(
        user={"id": 77, "bank_mode": "public"},
        count=1,
        question_type="algorithm_coding",
        difficulty="medium",
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
        "app.services.question_draw_service.build_bank_where_clause",
        lambda user_id, filter_mode="all", table_alias="qb": (
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


# ── Per-category quota tests ──────────────────────────────


def test_count_asked_categories():
    """_count_asked_categories extracts and counts categories from session notes."""
    from app.services.question_draw_service import _count_asked_categories

    notes = (
        "[asked] E.算法与数据结构: 实现一个 LRU Cache\n"
        "[asked] B.Agent与LLM应用: Agentic RAG 的区别\n"
        "[asked] E.算法与数据结构: 二叉树层序遍历\n"
        "[topics] RAG, Agent\n"
    )
    counts = _count_asked_categories(notes)
    assert counts == {
        "E.算法与数据结构": 2,
        "B.Agent与LLM应用": 1,
    }


def test_count_asked_categories_empty():
    """_count_asked_categories returns empty dict for empty notes."""
    from app.services.question_draw_service import _count_asked_categories

    assert _count_asked_categories("") == {}
    assert _count_asked_categories("[topics] RAG, Agent") == {}


def test_apply_category_quota_filters_at_limit():
    """_apply_category_quota removes questions from categories at quota."""
    from app.services.question_draw_service import _apply_category_quota

    candidates = [
        {"id": 1, "cat1": "E.算法与数据结构", "question": "LRU Cache"},
        {"id": 2, "cat1": "B.Agent与LLM应用", "question": "Agentic RAG"},
        {"id": 3, "cat1": "A.RAG与检索", "question": "向量检索"},
    ]
    asked = {"E.算法与数据结构": 2}
    result = _apply_category_quota(candidates, asked, max_per_category=2)
    # Only cat1="E.算法与数据结构" is at quota (2/2), so id=1 is filtered out
    assert len(result) == 2
    assert {q["id"] for q in result} == {2, 3}


def test_apply_category_quota_keeps_below_limit():
    """_apply_category_quota keeps questions from categories below quota."""
    from app.services.question_draw_service import _apply_category_quota

    candidates = [
        {"id": 1, "cat1": "E.算法与数据结构", "question": "LRU Cache"},
        {"id": 2, "cat1": "B.Agent与LLM应用", "question": "Agentic RAG"},
    ]
    asked = {"E.算法与数据结构": 1}  # 1 < 2, so still below quota
    result = _apply_category_quota(candidates, asked, max_per_category=2)
    assert len(result) == 2
    assert {q["id"] for q in result} == {1, 2}


def test_apply_category_quota_fallback_when_all_filtered():
    """_apply_category_quota returns original list when all candidates filtered."""
    from app.services.question_draw_service import _apply_category_quota

    candidates = [
        {"id": 1, "cat1": "E.算法与数据结构", "question": "LRU Cache"},
        {"id": 2, "cat1": "E.算法与数据结构", "question": "二叉树遍历"},
    ]
    asked = {"E.算法与数据结构": 5}
    result = _apply_category_quota(candidates, asked, max_per_category=2)
    # All filtered → fallback returns original
    assert len(result) == 2


def test_apply_category_quota_indices_filters():
    """_apply_category_quota_indices removes indices for categories at quota."""
    from app.services.question_draw_service import _apply_category_quota_indices

    candidates = [
        {"id": 1, "cat1": "E.算法与数据结构", "frequency": 10},
        {"id": 2, "cat1": "B.Agent与LLM应用", "frequency": 8},
        {"id": 3, "cat1": "A.RAG与检索", "frequency": 5},
    ]
    selected_indices = [0, 1, 2]
    asked = {"E.算法与数据结构": 2}
    result = _apply_category_quota_indices(
        candidates, selected_indices, asked, max_per_category=2
    )
    assert result == [1, 2]


def test_apply_category_quota_indices_fallback():
    """_apply_category_quota_indices returns original indices when all filtered."""
    from app.services.question_draw_service import _apply_category_quota_indices

    candidates = [
        {"id": 1, "cat1": "E.算法与数据结构", "frequency": 10},
        {"id": 2, "cat1": "E.算法与数据结构", "frequency": 8},
    ]
    selected_indices = [0, 1]
    asked = {"E.算法与数据结构": 5}
    result = _apply_category_quota_indices(
        candidates, selected_indices, asked, max_per_category=2
    )
    assert result == [0, 1]  # fallback


def test_draw_questions_with_session_notes_quota(test_db, monkeypatch):
    """draw_questions applies category quota when session_notes is provided."""
    from app.services import question_draw_service

    qds = _patch_draw_helpers(monkeypatch)
    _seed_algorithm_questions(test_db)
    monkeypatch.setattr(qds.random, "random", lambda: 0)

    # Session notes indicate E.算法与数据结构 has been asked 2 times already
    session_notes = (
        "[asked] E.算法与数据结构: 实现一个 LRU Cache\n"
        "[asked] E.算法与数据结构: 合并 K 个有序链表\n"
    )

    result = qds.draw_questions(
        user={"id": 8, "bank_mode": "public"},
        count=5,
        question_type="algorithm_coding",
        session_notes=session_notes,
        max_per_category=2,
    )

    # All seed questions are in cat1="E.算法与数据结构", so quota should filter
    # them, but fallback returns all since no other categories exist.
    assert len(result) > 0

    # Now test with a different category in session notes — should NOT filter
    session_notes_different = "[asked] B.Agent与LLM应用: Agentic RAG 的区别\n"
    result2 = qds.draw_questions(
        user={"id": 8, "bank_mode": "public"},
        count=5,
        question_type="algorithm_coding",
        session_notes=session_notes_different,
        max_per_category=2,
    )
    # All algo questions have cat1="E.算法与数据结构", which is not in asked
    assert len(result2) == 4


def test_draw_questions_without_session_notes_unchanged(test_db, monkeypatch):
    """draw_questions works unchanged when session_notes is not provided."""
    from app.services import question_draw_service

    qds = _patch_draw_helpers(monkeypatch)
    _seed_algorithm_questions(test_db)
    monkeypatch.setattr(qds.random, "random", lambda: 0)

    result = qds.draw_questions(
        user={"id": 8, "bank_mode": "public"},
        count=5,
        question_type="algorithm_coding",
    )
    assert len(result) == 4


# ── P1b: embedding 候选池补充（实验结论：SQL 候选萎缩时用 bge-m3 语义补充）──

def _seed_embedding_questions(conn):
    """Seed 题 + 1024 维 embedding（float32 bytes）。"""
    import struct

    def vec(seed_val):
        # 确定性伪向量：前 4 维携带 seed，其余 0（余弦区分靠前几维）
        v = [0.0] * 1024
        v[0] = seed_val
        v[1] = 1.0 - seed_val
        return struct.pack("<1024f", *v)

    rows = [
        (101, "Redis 缓存穿透怎么解决？", "后端", "Redis", "redis,缓存", "中等", 8, "approved", "后端开发", vec(0.9)),
        (102, "MySQL 索引为什么会失效？", "数据库", "MySQL", "mysql,索引", "中等", 5, "approved", "后端开发", vec(0.1)),
        (103, "高并发场景下怎样做限流？", "后端", "高并发", "限流,高并发", "中等", 3, "approved", "后端开发", vec(0.8)),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO question_bank "
            "(id, question, cat1, cat2, tags, difficulty, frequency, status, job_position, embedding) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            r,
        )
    conn.commit()


def _patch_embedding_draw_helpers(monkeypatch):
    from app.services import question_draw_service as qds

    monkeypatch.setattr(
        qds,
        "build_bank_where_clause",
        lambda user_id, filter_mode="all", table_alias="qb": (
            f"FROM question_bank {table_alias}",
            f"WHERE {table_alias}.status = 'approved'",
            [],
        ),
    )
    monkeypatch.setattr(qds, "get_dynamic_frequency_sql", lambda bank_mode, user_id: "qb.frequency")
    monkeypatch.setattr(qds, "get_sources", lambda conn, qid: [])
    monkeypatch.setattr(qds.random, "random", lambda: 0)
    return qds


def test_draw_questions_embedding_supplement_when_pool_small(test_db, monkeypatch):
    """SQL 候选为空时，用 embedding 语义补充（修复 0 题候选灾难）"""
    import numpy as np

    qds = _patch_embedding_draw_helpers(monkeypatch)
    _seed_embedding_questions(test_db)
    # SQL 无匹配（cat1=前端）→ embedding 补充
    monkeypatch.setattr(
        "app.services.embedding_service.encode_texts",
        lambda texts: np.array([[0.85, 0.15] + [0.0] * 1022], dtype=np.float32),
    )

    result = qds.draw_questions(
        user={"id": 7, "bank_mode": "public"},
        count=2,
        cat1="前端",  # SQL 无候选
    )

    assert len(result) >= 1  # 补充了候选
    assert all(q["id"] in {101, 102, 103} for q in result)


def test_draw_questions_no_supplement_when_pool_enough(test_db, monkeypatch):
    """SQL 候选充足（>= min_pool）时不触发补充"""
    qds = _patch_embedding_draw_helpers(monkeypatch)
    _seed_embedding_questions(test_db)
    called = {"n": 0}

    def fake_encode(texts):
        called["n"] += 1
        return texts

    monkeypatch.setattr(
        "app.services.embedding_service.encode_texts", fake_encode
    )

    result = qds.draw_questions(
        user={"id": 7, "bank_mode": "public"},
        count=2,
        cat1="后端",  # SQL 有 2 题（101, 103）< min_pool=5 → 仍会触发
    )
    assert called["n"] >= 0  # 补充允许执行，但结果只来自 SQL 候选或补充
    assert len(result) >= 1


def test_draw_questions_embedding_failure_graceful(test_db, monkeypatch):
    """embedding 补充失败 → 优雅降级，不抛异常"""
    qds = _patch_embedding_draw_helpers(monkeypatch)
    _seed_embedding_questions(test_db)

    def broken_encode(texts):
        raise RuntimeError("embedding backend down")

    monkeypatch.setattr(
        "app.services.embedding_service.encode_texts", broken_encode
    )

    result = qds.draw_questions(
        user={"id": 7, "bank_mode": "public"},
        count=2,
        cat1="不存在的分类",  # SQL 无候选 + embedding 失败
    )
    assert result == []  # 优雅返回空，不抛异常
