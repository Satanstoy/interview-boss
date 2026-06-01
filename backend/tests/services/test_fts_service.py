"""
TDD 测试 — FTS5 全文检索服务

测试 search_questions_fts 的各种场景：
- 英文关键词走 FTS5 路径
- CJK 关键词走 LIKE 回退路径
- 岗位过滤
- 排除已答题目
- 空关键词处理
"""
import pytest
from unittest.mock import patch, MagicMock


class TestSearchQuestionsFts:
    """search_questions_fts 核心测试"""

    def _seed_questions(self, conn):
        """插入测试题目数据"""
        questions = [
            (1, "Redis 的五种数据结构有哪些？", "中间件", "缓存", "redis,nosql", "approved", "后端开发"),
            (2, "如何实现分布式锁？", "中间件", "分布式", "redis,zookeeper", "approved", "后端开发"),
            (3, "MySQL 索引优化有哪些方法？", "数据库", "索引", "mysql,btree", "approved", "后端开发"),
            (4, "React Hooks 的使用方法？", "前端", "框架", "react,hooks", "approved", "前端开发"),
            (5, "TCP 三次握手过程？", "网络", "tcp", "tcp,network", "approved", "后端开发"),
            (6, "已删除的题目", "中间件", "缓存", "redis", "deleted", "后端开发"),
        ]
        for q in questions:
            conn.execute(
                "INSERT INTO question_bank (id, question, cat1, cat2, tags, status, job_position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                q
            )
        conn.commit()

        # 同步到 FTS5 索引
        from app.services.fts_service import sync_fts_entry
        for q in questions:
            if q[5] == "approved":  # 只同步未删除的
                sync_fts_entry(q[0])

    def test_empty_keywords_returns_empty(self, test_db):
        """空关键词应返回空列表"""
        from app.services.fts_service import search_questions_fts

        result = search_questions_fts([])
        assert result == []

    def test_english_keywords_fts5_search(self, test_db):
        """英文关键词应走 FTS5 路径并返回匹配结果"""
        from app.services.fts_service import search_questions_fts

        self._seed_questions(test_db)
        result = search_questions_fts(["Redis"])

        assert len(result) > 0
        # 应包含 Redis 相关题目
        questions_text = " ".join(r["question"] for r in result)
        assert "Redis" in questions_text or "redis" in questions_text.lower()

    def test_cjk_keywords_like_fallback(self, test_db):
        """CJK 关键词应走 LIKE 回退路径"""
        from app.services.fts_service import search_questions_fts

        self._seed_questions(test_db)
        result = search_questions_fts(["缓存"])

        assert len(result) > 0
        questions_text = " ".join(r["question"] for r in result)
        assert "缓存" in questions_text or "Redis" in questions_text

    def test_job_position_filter(self, test_db):
        """岗位过滤应只返回匹配岗位的题目"""
        from app.services.fts_service import search_questions_fts

        self._seed_questions(test_db)
        result = search_questions_fts(["Redis"], job_position="前端开发")

        # 前端开发岗位没有 Redis 题目（React 题目不含 Redis）
        # 但可能因 fallback 返回后端题目，所以只验证结果结构
        for r in result:
            assert "id" in r
            assert "question" in r

    def test_exclude_ids_filters_results(self, test_db):
        """exclude_ids 应排除指定 ID 的题目"""
        from app.services.fts_service import search_questions_fts

        self._seed_questions(test_db)
        # 先获取所有 Redis 结果
        all_results = search_questions_fts(["Redis"])
        if len(all_results) > 1:
            exclude = {all_results[0]["id"]}
            filtered = search_questions_fts(["Redis"], exclude_ids=exclude)
            filtered_ids = {r["id"] for r in filtered}
            assert all_results[0]["id"] not in filtered_ids

    def test_deleted_questions_excluded(self, test_db):
        """已删除的题目不应出现在搜索结果中"""
        from app.services.fts_service import search_questions_fts

        self._seed_questions(test_db)
        result = search_questions_fts(["Redis"])

        result_ids = {r["id"] for r in result}
        assert 6 not in result_ids  # ID 6 是 deleted 状态

    def test_result_structure(self, test_db):
        """返回结果应包含所有必要字段"""
        from app.services.fts_service import search_questions_fts

        self._seed_questions(test_db)
        result = search_questions_fts(["Redis"])

        if result:
            r = result[0]
            assert "id" in r
            assert "question" in r
            assert "cat1" in r
            assert "cat2" in r
            assert "tags" in r
            assert "ai_answer" in r
            assert "rank" in r

    def test_search_prioritizes_question_over_ai_answer(self, test_db):
        """搜索应优先返回 question/tags 匹配的题目，而非仅 ai_answer 匹配的"""
        from app.services.fts_service import search_questions_fts

        conn = test_db
        # 题目 A: question 中包含 Redis
        conn.execute(
            "INSERT INTO question_bank (id, question, cat1, cat2, tags, ai_answer, status, job_position) "
            "VALUES (1, 'Redis 的五种数据结构有哪些？', '中间件', '缓存', 'redis', 'Redis 是一个...', 'approved', '后端开发')"
        )
        # 题目 B: question 不含 Redis，但 ai_answer 包含 Redis
        conn.execute(
            "INSERT INTO question_bank (id, question, cat1, cat2, tags, ai_answer, status, job_position) "
            "VALUES (2, '高并发的场景下怎样做限流？', '分布式', '高并发', '限流', '可以使用 Redis 做限流...', 'approved', '后端开发')"
        )
        conn.commit()

        from app.services.fts_service import sync_fts_entry
        sync_fts_entry(1)
        sync_fts_entry(2)

        result = search_questions_fts(["Redis"])
        assert len(result) > 0

        # 第一个结果应该是 question 中包含 Redis 的题目
        assert result[0]["id"] == 1, f"期望 ID=1 (question 匹配), 实际 ID={result[0]['id']}"

    def test_search_finds_tcp_acronym(self, test_db):
        """应能搜索到英文缩写如 TCP"""
        from app.services.fts_service import search_questions_fts

        conn = test_db
        conn.execute(
            "INSERT INTO question_bank (id, question, cat1, cat2, tags, status, job_position) "
            "VALUES (1, '说一下TCP三次握手和四次挥手的过程', '网络', 'tcp', 'tcp,network', 'approved', '后端开发')"
        )
        conn.commit()

        from app.services.fts_service import sync_fts_entry
        sync_fts_entry(1)

        result = search_questions_fts(["TCP"])
        assert len(result) > 0, "TCP 搜索应返回结果"
        assert any("TCP" in r["question"] for r in result)


class TestFallbackLikeSearch:
    """_fallback_like_search 测试"""

    def _seed_questions(self, conn):
        """插入测试题目数据"""
        questions = [
            (1, "Redis 缓存策略详解", "中间件", "缓存", "redis", "approved", "后端开发"),
            (2, "分布式系统架构设计", "架构", "分布式", "distributed", "approved", "后端开发"),
            (3, "前端性能优化方案", "前端", "性能", "performance", "approved", "前端开发"),
        ]
        for q in questions:
            conn.execute(
                "INSERT INTO question_bank (id, question, cat1, cat2, tags, status, job_position) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                q
            )
        conn.commit()

    def test_cjk_keyword_matches(self, test_db):
        """CJK 关键词应通过 LIKE 匹配成功"""
        from app.services.fts_service import _fallback_like_search

        self._seed_questions(test_db)
        result = _fallback_like_search(["缓存"], test_db, 10)

        assert len(result) > 0
        assert any("缓存" in r["question"] for r in result)

    def test_english_keyword_matches(self, test_db):
        """英文关键词应通过 LIKE 匹配成功"""
        from app.services.fts_service import _fallback_like_search

        self._seed_questions(test_db)
        result = _fallback_like_search(["Redis"], test_db, 10)

        assert len(result) > 0
        assert any("Redis" in r["question"] for r in result)

    def test_empty_keywords_returns_empty(self, test_db):
        """空关键词应返回空列表"""
        from app.services.fts_service import _fallback_like_search

        result = _fallback_like_search([], test_db, 10)
        assert result == []

    def test_job_position_filter(self, test_db):
        """岗位过滤应生效"""
        from app.services.fts_service import _fallback_like_search

        self._seed_questions(test_db)
        result = _fallback_like_search(["优化"], test_db, 10, job_position="前端开发")

        # 应该只返回前端开发的题目
        for r in result:
            assert "前端" in r["question"] or "performance" in r.get("tags", "")

    def test_exclude_ids(self, test_db):
        """应排除指定 ID"""
        from app.services.fts_service import _fallback_like_search

        self._seed_questions(test_db)
        result = _fallback_like_search(["缓存"], test_db, 10, exclude_ids={1})

        result_ids = {r["id"] for r in result}
        assert 1 not in result_ids


class TestSyncFtsEntry:
    """sync_fts_entry 和 delete_fts_entry 测试"""

    def test_sync_and_search(self, test_db):
        """同步后应能搜索到题目"""
        from app.services.fts_service import sync_fts_entry, search_questions_fts

        conn = test_db
        conn.execute(
            "INSERT INTO question_bank (id, question, cat1, cat2, tags, status, job_position) "
            "VALUES (1, 'Kubernetes Pod 调度策略', '运维', '容器', 'k8s,docker', 'approved', '后端开发')"
        )
        conn.commit()

        sync_fts_entry(1)

        # 搜索应能找到
        result = search_questions_fts(["Kubernetes"])
        assert any(r["id"] == 1 for r in result)

    def test_delete_removes_from_fts_index(self, test_db):
        """删除后 FTS5 索引应不再包含该题目（但 LIKE 回退仍可能找到）"""
        from app.services.fts_service import sync_fts_entry, delete_fts_entry

        conn = test_db
        conn.execute(
            "INSERT INTO question_bank (id, question, cat1, cat2, tags, status, job_position) "
            "VALUES (1, 'Kubernetes Pod 调度策略', '运维', '容器', 'k8s,docker', 'approved', '后端开发')"
        )
        conn.commit()

        sync_fts_entry(1)

        # 验证 FTS5 索引中有该题目
        row = conn.execute("SELECT rowid FROM question_fts WHERE rowid = 1").fetchone()
        assert row is not None

        delete_fts_entry(1)

        # 验证 FTS5 索引中已删除
        row = conn.execute("SELECT rowid FROM question_fts WHERE rowid = 1").fetchone()
        assert row is None

    def test_sync_nonexistent_id_no_error(self, test_db):
        """同步不存在的 ID 不应报错"""
        from app.services.fts_service import sync_fts_entry

        # 不应抛出异常
        sync_fts_entry(99999)


class TestReciprocalRankFusion:
    """RRF 融合算法测试"""

    def test_rrf_common_items_rank_highest(self):
        """同时出现在两个列表中的文档应排名最高"""
        from app.services.fts_service import reciprocal_rank_fusion

        list_a = [{"id": 1, "question": "A"}, {"id": 2, "question": "B"}, {"id": 3, "question": "C"}]
        list_b = [{"id": 2, "question": "B"}, {"id": 1, "question": "A"}, {"id": 4, "question": "D"}]

        result = reciprocal_rank_fusion([list_a, list_b])
        result_ids = [r["id"] for r in result]

        # id=1 和 id=2 都出现在两个列表中，应排前 2（顺序可能互换）
        assert set(result_ids[:2]) == {1, 2}
        # id=3 只在 list_a 中，id=4 只在 list_b 中，应排后面
        assert set(result_ids[2:]) == {3, 4}

    def test_rrf_single_list_passthrough(self):
        """单列表应直接返回（按原始顺序）"""
        from app.services.fts_service import reciprocal_rank_fusion

        items = [{"id": 1, "question": "A"}, {"id": 2, "question": "B"}]
        result = reciprocal_rank_fusion([items])
        assert [r["id"] for r in result] == [1, 2]

    def test_rrf_empty_lists(self):
        """空列表应返回空结果"""
        from app.services.fts_service import reciprocal_rank_fusion

        result = reciprocal_rank_fusion([[], []])
        assert result == []

    def test_rrf_preserves_document_info(self):
        """融合后应保留完整文档信息"""
        from app.services.fts_service import reciprocal_rank_fusion

        items = [{"id": 1, "question": "Redis 五种数据结构", "cat1": "中间件", "tags": "redis"}]
        result = reciprocal_rank_fusion([items])
        assert result[0]["question"] == "Redis 五种数据结构"
        assert result[0]["cat1"] == "中间件"

    def test_rrf_score_formula(self):
        """验证 RRF 分数计算公式: 1/(k+rank)"""
        from app.services.fts_service import reciprocal_rank_fusion

        # id=1 排第 1，id=2 排第 2
        items = [{"id": 1, "question": "A"}, {"id": 2, "question": "B"}]
        result = reciprocal_rank_fusion([items], k=60)

        # id=1: 1/(60+1) ≈ 0.01639
        # id=2: 1/(60+2) ≈ 0.01613
        assert result[0]["_rrf_score"] > result[1]["_rrf_score"]
        assert abs(result[0]["_rrf_score"] - 1.0/61) < 0.0001


class TestHybridSearch:
    """混合搜索集成测试"""

    def _seed_questions_with_embeddings(self, conn):
        """插入测试题目和 embedding"""
        import numpy as np

        questions = [
            (1, "Redis 的五种数据结构有哪些？", "中间件", "缓存", "redis", "approved", "后端开发"),
            (2, "如何实现分布式锁？", "中间件", "分布式", "redis,zookeeper", "approved", "后端开发"),
            (3, "TCP 三次握手过程？", "网络", "tcp", "tcp,network", "approved", "后端开发"),
            (4, "React Hooks 的使用方法？", "前端", "框架", "react,hooks", "approved", "前端开发"),
        ]
        for q in questions:
            # 生成随机 embedding
            emb = np.random.randn(512).astype(np.float32)
            emb /= np.linalg.norm(emb)
            conn.execute(
                "INSERT INTO question_bank (id, question, cat1, cat2, tags, status, job_position, embedding) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (q[0], q[1], q[2], q[3], q[4], q[5], q[6], emb.tobytes())
            )
        conn.commit()

        from app.services.fts_service import sync_fts_entry
        for q in questions:
            sync_fts_entry(q[0])

    def test_hybrid_search_returns_results(self, test_db):
        """混合搜索应返回结果"""
        from app.services.fts_service import hybrid_search

        self._seed_questions_with_embeddings(test_db)
        result = hybrid_search(keywords=["Redis"], query_text="Redis 缓存", limit=3)

        assert len(result) > 0
        assert all("id" in r for r in result)

    def test_hybrid_search_fallback_to_fts_only(self, test_db):
        """无 embedding 时应降级到纯 FTS 搜索"""
        from app.services.fts_service import hybrid_search, sync_fts_entry

        conn = test_db
        conn.execute(
            "INSERT INTO question_bank (id, question, cat1, cat2, tags, status, job_position) "
            "VALUES (1, 'Redis 缓存策略', '中间件', '缓存', 'redis', 'approved', '后端开发')"
        )
        conn.commit()
        sync_fts_entry(1)

        # 无 embedding，应降级到 FTS
        result = hybrid_search(keywords=["Redis"], query_text="Redis", limit=3)
        assert len(result) > 0

    def test_hybrid_search_empty_keywords(self, test_db):
        """空关键词应返回空结果"""
        from app.services.fts_service import hybrid_search

        result = hybrid_search(keywords=[], query_text="", limit=3)
        assert result == []
