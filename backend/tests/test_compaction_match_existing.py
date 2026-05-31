"""
测试 compact_singletons_in_db 的"孤岛→已有聚类"匹配步骤

验证：
1. frequency=1 的题能匹配到 frequency>1 的题并正确合并
2. 匹配上的题被从 singletons 中排除，不再互相比
3. 未匹配的题走原有互相比流程
"""
import json
import sqlite3
import asyncio
from unittest.mock import patch, AsyncMock, Mock

import pytest


# ── helpers ────────────────────────────────────────────────────────

def _insert_qb(conn, *, id, question, cat2='C1', frequency=1,
               sources=None, original_questions=None,
               original_question_sources=None, ai_answer=None,
               status='approved', deleted_at=None):
    conn.execute(
        "INSERT INTO question_bank "
        "(id, question, cat1, cat2, frequency, sources, original_questions, "
        "original_question_sources, ai_answer, status, deleted_at) "
        "VALUES (?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?)",
        (id, question, cat2, frequency,
         json.dumps(sources or []),
         json.dumps(original_questions or []),
         json.dumps(original_question_sources or []),
         ai_answer, status, deleted_at)
    )


# ── fixtures ───────────────────────────────────────────────────────

@pytest.fixture
def seed_db(test_db):
    """在 test_db 里插入测试数据"""
    conn = test_db

    # 频率>1 的已有聚类
    _insert_qb(conn, id=1, question='TCP三次握手原理',
               cat2='C4.操作系统与网络', frequency=5,
               sources=[{'url': 'https://a.com', 'company': 'A', 'round': '技术面'}],
               original_questions=['TCP三次握手', 'TCP三次握手原理'],
               original_question_sources=[
                   {'question': 'TCP三次握手', 'sources': [{'url': 'https://a.com'}]},
                   {'question': 'TCP三次握手原理', 'sources': [{'url': 'https://b.com'}]},
               ])

    _insert_qb(conn, id=2, question='Redis持久化方式有哪些',
               cat2='D1.缓存设计与优化', frequency=3,
               sources=[{'url': 'https://c.com', 'company': 'B', 'round': '一面'}],
               original_questions=['Redis持久化方式'],
               original_question_sources=[
                   {'question': 'Redis持久化方式', 'sources': [{'url': 'https://c.com'}]},
               ])

    # 频率=1 的孤岛（带 sources 以便验证合并）
    _insert_qb(conn, id=10, question='TCP为什么是三次握手而不是两次',
               cat2='C4.操作系统与网络', frequency=1, ai_answer='因为...',
               sources=[{'url': 'https://d.com', 'company': 'X', 'round': '二面'}],
               original_questions=['TCP为什么是三次握手而不是两次'],
               original_question_sources=[
                   {'question': 'TCP为什么是三次握手而不是两次',
                    'sources': [{'url': 'https://d.com'}]},
               ])

    _insert_qb(conn, id=11, question='Redis的RDB和AOF持久化有什么区别',
               cat2='D1.缓存设计与优化', frequency=1,
               sources=[{'url': 'https://e.com', 'company': 'Y', 'round': '三面'}],
               original_questions=['Redis的RDB和AOF持久化有什么区别'],
               original_question_sources=[
                   {'question': 'Redis的RDB和AOF持久化有什么区别',
                    'sources': [{'url': 'https://e.com'}]},
               ])

    _insert_qb(conn, id=12, question='volatile关键字的作用',
               cat2='C1.编程语言基础', frequency=1, ai_answer='保证可见性...')

    _insert_qb(conn, id=13, question='Java synchronized原理',
               cat2='C1.编程语言基础', frequency=1)

    conn.commit()
    return conn


# ── 测试 ──────────────────────────────────────────────────────────

class TestMatchSingletonsToExisting:
    """测试 _match_singletons_to_existing 函数"""

    @pytest.mark.asyncio
    async def test_match_and_merge(self, test_db, seed_db):
        """frequency=1 的题匹配到 frequency>1 的题后正确合并"""
        import app.db.connection as db_module

        # 强制 run_db 同步执行
        async def _sync_run_db(func):
            return func()
        db_module.run_db = _sync_run_db

        from app.services.pipeline.batch import (
            _match_singletons_to_existing,
            _load_existing_clusters_for_compact,
        )

        singletons = [
            {'id': 10, 'question': 'TCP为什么是三次握手而不是两次',
             'cat2': 'C4.操作系统与网络', 'ai_answer': '因为...',
             'sources': '[{"url": "https://d.com", "company": "X", "round": "二面"}]',
             'original_questions': '["TCP为什么是三次握手而不是两次"]',
             'original_question_sources': '[{"question": "TCP为什么是三次握手而不是两次", "sources": [{"url": "https://d.com"}]}]'},
            {'id': 12, 'question': 'volatile关键字的作用',
             'cat2': 'C1.编程语言基础', 'ai_answer': '保证可见性...',
             'sources': '[]', 'original_questions': '[]',
             'original_question_sources': '[]'},
        ]

        existing = {
            'C4.操作系统与网络': [{'id': 1, 'question': 'TCP三次握手原理'}],
            'C1.编程语言基础': [],
        }

        # Mock LLM：让 id=10 匹配到 cluster_id=1
        mock_result = json.dumps({"matches": [
            {"new_id": "10", "cluster_id": 1}
        ]})

        mock_llm_obj = AsyncMock(side_effect=[mock_result, 'validate_raw'])
        mock_extract_obj = Mock(side_effect=[
            {"matches": [{"new_id": "10", "cluster_id": 1}]},
            {"validations": [{"new_id": "10", "cluster_id": "1", "valid": True, "confidence": 0.95}]},
        ])
        with patch("app.services.pipeline.batch._call_llm_with_retry", mock_llm_obj):
            with patch("app.services.clustering._call_llm_with_retry", mock_llm_obj):
                with patch("app.services.pipeline.batch._extract_json", mock_extract_obj):
                    with patch("app.services.clustering._extract_json", mock_extract_obj):
                        matched_ids = await _match_singletons_to_existing(
                            singletons, existing, user_id=None
                        )

        # 验证：id=10 被匹配
        assert 10 in matched_ids
        # id=12 没有匹配（C1 无 existing clusters）
        assert 12 not in matched_ids

        # 验证 DB：id=10 被删除
        row = test_db.execute(
            "SELECT * FROM question_bank WHERE id = 10"
        ).fetchone()
        assert row is None

        # 验证 DB：id=1 被正确更新（frequency 增加，sources 合并）
        row = test_db.execute(
            "SELECT frequency, sources, original_questions, ai_answer "
            "FROM question_bank WHERE id = 1"
        ).fetchone()
        assert row is not None
        sources = json.loads(row['sources'])
        oqs = json.loads(row['original_questions'])
        # sources 应包含原有 + 新合并的
        assert len(sources) >= 2
        # original_questions 应包含原有 + 新合并的
        assert 'TCP为什么是三次握手而不是两次' in oqs
        # ai_answer 被转移到 survivor（原来 id=1 没有 ai_answer，从 id=10 获得）
        assert row['ai_answer'] == '因为...'

    @pytest.mark.asyncio
    async def test_ai_answer_forwarded(self, test_db, seed_db):
        """被合并题的 ai_answer 应转移到 survivor"""
        import app.db.connection as db_module

        async def _sync_run_db(func):
            return func()
        db_module.run_db = _sync_run_db

        from app.services.pipeline.batch import _match_singletons_to_existing

        # id=10 有 ai_answer='因为...'，id=1 没有
        singletons = [
            {'id': 10, 'question': 'TCP为什么是三次握手而不是两次',
             'cat2': 'C4.操作系统与网络', 'ai_answer': '因为...',
             'sources': '[{"url": "https://d.com", "company": "X", "round": "二面"}]',
             'original_questions': '["TCP为什么是三次握手而不是两次"]',
             'original_question_sources': '[{"question": "TCP为什么是三次握手而不是两次", "sources": [{"url": "https://d.com"}]}]'},
        ]
        existing = {
            'C4.操作系统与网络': [{'id': 1, 'question': 'TCP三次握手原理'}],
        }

        mock_result = json.dumps({"matches": [
            {"new_id": "10", "cluster_id": 1}
        ]})

        mock_llm_obj = AsyncMock(side_effect=[mock_result, 'validate_raw'])
        mock_extract_obj = Mock(side_effect=[
            {"matches": [{"new_id": "10", "cluster_id": 1}]},
            {"validations": [{"new_id": "10", "cluster_id": "1", "valid": True, "confidence": 0.95}]},
        ])
        with patch("app.services.pipeline.batch._call_llm_with_retry", mock_llm_obj):
            with patch("app.services.clustering._call_llm_with_retry", mock_llm_obj):
                with patch("app.services.pipeline.batch._extract_json", mock_extract_obj):
                    with patch("app.services.clustering._extract_json", mock_extract_obj):
                        await _match_singletons_to_existing(
                            singletons, existing, user_id=None
                        )

        row = test_db.execute(
            "SELECT ai_answer FROM question_bank WHERE id = 1"
        ).fetchone()
        assert row['ai_answer'] == '因为...'

    @pytest.mark.asyncio
    async def test_no_match_returns_empty(self, test_db, seed_db):
        """LLM 无匹配时返回空集，不删除任何题"""
        import app.db.connection as db_module

        async def _sync_run_db(func):
            return func()
        db_module.run_db = _sync_run_db

        from app.services.pipeline.batch import _match_singletons_to_existing

        singletons = [
            {'id': 12, 'question': 'volatile关键字的作用',
             'cat2': 'C1.编程语言基础', 'ai_answer': '保证可见性...',
             'sources': '[]', 'original_questions': '[]',
             'original_question_sources': '[]'},
        ]
        existing = {
            'C1.编程语言基础': [],
        }

        # C1 没有 existing clusters，不会调用 LLM
        matched_ids = await _match_singletons_to_existing(
            singletons, existing, user_id=None
        )

        assert matched_ids == set()
        # id=12 仍然存在
        row = test_db.execute(
            "SELECT * FROM question_bank WHERE id = 12"
        ).fetchone()
        assert row is not None

    @pytest.mark.asyncio
    async def test_excludes_from_singleton_group(self, test_db, seed_db):
        """匹配上的题被排除，不在后续互相比中出现"""
        import app.db.connection as db_module

        async def _sync_run_db(func):
            return func()
        db_module.run_db = _sync_run_db

        from app.services.pipeline.batch import compact_singletons_in_db

        # Mock _call_llm_with_retry：第一次（匹配已有聚类）返回匹配，后续调用返回空结果
        call_count = 0

        async def mock_llm(prompt, **kwargs):
            nonlocal call_count
            call_count += 1
            if '待验证的题目对' in prompt:
                # 验证调用
                return json.dumps({"validations": [
                    {"new_id": "10", "cluster_id": "1", "valid": True, "confidence": 0.95}
                ]})
            if '已有标准题库' in prompt:
                # 匹配已有聚类
                return json.dumps({"matches": [
                    {"new_id": "10", "cluster_id": 1}
                ]})
            return json.dumps({"clusters": []})

        extract_count = 0
        def mock_extract(content):
            nonlocal extract_count
            extract_count += 1
            if extract_count == 1:
                return {"matches": [{"new_id": "10", "cluster_id": 1}]}
            if extract_count == 2:
                return {"validations": [{"new_id": "10", "cluster_id": "1", "valid": True, "confidence": 0.95}]}
            # Phase 2 内部聚类
            return {"clusters": []}

        mock_llm_obj = AsyncMock(side_effect=mock_llm)
        mock_extract_obj = Mock(side_effect=mock_extract)
        with patch("app.services.pipeline.batch._call_llm_with_retry", mock_llm_obj):
            with patch("app.services.clustering._call_llm_with_retry", mock_llm_obj):
                with patch("app.services.pipeline.batch._extract_json", mock_extract_obj):
                    with patch("app.services.clustering._extract_json", mock_extract_obj):
                        result = await compact_singletons_in_db(user_id=None)

        # id=10 应该被匹配到已有聚类
        assert result['matched_to_existing'] >= 1
        # 互相比处理的剩余孤岛数应排除 id=10
        assert result['total_singletons'] == 4  # id=10,11,12,13
        assert result['remaining'] < result['total_singletons']

    @pytest.mark.asyncio
    async def test_frequency_updated_after_merge(self, test_db, seed_db):
        """合并后 survivor 的 frequency 正确更新"""
        import app.db.connection as db_module

        async def _sync_run_db(func):
            return func()
        db_module.run_db = _sync_run_db

        from app.services.pipeline.batch import _match_singletons_to_existing

        # id=2 有 frequency=3，原始问题 1 个
        # 合并 id=11 后，original_questions 应有 2 个，frequency=2
        singletons = [
            {'id': 11, 'question': 'Redis的RDB和AOF持久化有什么区别',
             'cat2': 'D1.缓存设计与优化',
             'sources': '[{"url": "https://e.com", "company": "Y", "round": "三面"}]',
             'original_questions': '["Redis的RDB和AOF持久化有什么区别"]',
             'original_question_sources': '[{"question": "Redis的RDB和AOF持久化有什么区别", "sources": [{"url": "https://e.com"}]}]'},
        ]
        existing = {
            'D1.缓存设计与优化': [{'id': 2, 'question': 'Redis持久化方式有哪些'}],
        }

        mock_result = json.dumps({"matches": [
            {"new_id": "11", "cluster_id": 2}
        ]})

        mock_llm_obj = AsyncMock(side_effect=[mock_result, 'validate_raw'])
        mock_extract_obj = Mock(side_effect=[
            {"matches": [{"new_id": "11", "cluster_id": 2}]},
            {"validations": [{"new_id": "11", "cluster_id": "2", "valid": True, "confidence": 0.95}]},
        ])
        with patch("app.services.pipeline.batch._call_llm_with_retry", mock_llm_obj):
            with patch("app.services.clustering._call_llm_with_retry", mock_llm_obj):
                with patch("app.services.pipeline.batch._extract_json", mock_extract_obj):
                    with patch("app.services.clustering._extract_json", mock_extract_obj):
                        await _match_singletons_to_existing(
                            singletons, existing, user_id=None
                        )

        row = test_db.execute(
            "SELECT frequency, original_questions FROM question_bank WHERE id = 2"
        ).fetchone()
        oqs = json.loads(row['original_questions'])
        assert 'Redis的RDB和AOF持久化有什么区别' in oqs
        assert row['frequency'] == len(oqs)


class TestCompactSingletonsEndToEnd:
    """端到端测试 compact_singletons_in_db 完整流程"""

    @pytest.mark.asyncio
    async def test_full_flow_with_existing_match(self, test_db, seed_db):
        """完整流程：先匹配已有聚类，剩余再互相比"""
        import app.db.connection as db_module

        async def _sync_run_db(func):
            return func()
        db_module.run_db = _sync_run_db

        from app.services.pipeline.batch import compact_singletons_in_db

        call_prompts = []

        async def mock_llm(prompt, **kwargs):
            call_prompts.append(prompt)
            if '待验证的题目对' in prompt:
                return json.dumps({"validations": [
                    {"new_id": "10", "cluster_id": "1", "valid": True, "confidence": 0.95}
                ]})
            if '已有标准题库' in prompt:
                return json.dumps({"matches": [
                    {"new_id": "10", "cluster_id": 1}
                ]})
            return json.dumps({"clusters": []})

        call_count = 0
        def mock_extract(content):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"matches": [{"new_id": "10", "cluster_id": 1}]}
            if call_count == 2:
                return {"validations": [{"new_id": "10", "cluster_id": "1", "valid": True, "confidence": 0.95}]}
            # Phase 2 内部聚类（C1 组 id=12, 13）
            return {"clusters": []}

        mock_llm_obj = AsyncMock(side_effect=mock_llm)
        mock_extract_obj = Mock(side_effect=mock_extract)
        with patch("app.services.pipeline.batch._call_llm_with_retry", mock_llm_obj):
            with patch("app.services.clustering._call_llm_with_retry", mock_llm_obj):
                with patch("app.services.pipeline.batch._extract_json", mock_extract_obj):
                    with patch("app.services.clustering._extract_json", mock_extract_obj):
                        result = await compact_singletons_in_db(user_id=None)

        assert result['total_singletons'] == 4
        assert result['matched_to_existing'] == 1

        # 第一次调用应该包含"已有标准题库"（匹配已有聚类）
        assert any('已有标准题库' in p for p in call_prompts)


