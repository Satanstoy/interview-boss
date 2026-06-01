"""
TDD 测试 — LLM 语义记忆召回

红灯阶段：memory_recall_service 尚不存在，测试应 FAIL
"""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
import json


class TestClassifyAndRecall:
    """classify_and_recall 核心测试"""

    @pytest.mark.asyncio
    async def test_returns_valid_intent_and_ids(self):
        """M-001: 正常输入应返回有效 intent 和 memory IDs 子集"""
        from app.services.memory_recall_service import classify_and_recall

        summaries = [
            {"id": 5, "memory_type": "weakness", "summary": "Redis 缓存策略不熟悉"},
            {"id": 7, "memory_type": "strength", "summary": "Java 多线程理解深入"},
            {"id": 12, "memory_type": "preference", "summary": "喜欢代码示例"},
        ]

        mock_response = json.dumps({
            "intent": "interview_question",
            "relevant_memory_ids": [5, 12],
            "keywords": ["Redis", "缓存"],
            "search_query": "Redis 缓存策略",
            "answer_complete": True,
        })

        with patch("app.services.memory_recall_service._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response

            intent, memory_ids, keywords, search_query, answer_complete = await classify_and_recall(
                user_message="请介绍一下 Redis 的缓存策略",
                recent_context="面试官: 我们来聊聊中间件",
                memory_summaries=summaries,
                user_id=1,
            )

        valid_intents = {"interview_question", "practice_request", "chat", "follow_up"}
        assert intent in valid_intents
        assert all(mid in {5, 7, 12} for mid in memory_ids)
        assert len(memory_ids) <= 3
        assert isinstance(keywords, list)
        assert isinstance(search_query, str)
        assert answer_complete is True

    @pytest.mark.asyncio
    async def test_falls_back_on_llm_failure(self):
        """M-002: LLM 调用失败应降级到规则分类，空 memory_ids"""
        from app.services.memory_recall_service import classify_and_recall

        summaries = [
            {"id": 1, "memory_type": "weakness", "summary": "测试"},
        ]

        with patch("app.services.memory_recall_service._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = Exception("API 超时")

            intent, memory_ids, keywords, search_query, answer_complete = await classify_and_recall(
                user_message="请介绍一下 Redis",
                recent_context="",
                memory_summaries=summaries,
                user_id=1,
            )

        valid_intents = {"interview_question", "practice_request", "chat", "follow_up"}
        assert intent in valid_intents
        assert memory_ids == []

    @pytest.mark.asyncio
    async def test_filters_invalid_memory_ids(self):
        """M-003: LLM 返回不存在的 ID 应被过滤"""
        from app.services.memory_recall_service import classify_and_recall

        summaries = [
            {"id": 5, "memory_type": "weakness", "summary": "测试"},
        ]

        mock_response = json.dumps({
            "intent": "interview_question",
            "relevant_memory_ids": [999, 5, 42],
            "keywords": ["测试"],
            "search_query": "测试消息",
            "answer_complete": False,
        })

        with patch("app.services.memory_recall_service._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response

            intent, memory_ids, keywords, search_query, answer_complete = await classify_and_recall(
                user_message="测试消息",
                recent_context="",
                memory_summaries=summaries,
                user_id=1,
            )

        assert 999 not in memory_ids
        assert 42 not in memory_ids
        assert 5 in memory_ids

    @pytest.mark.asyncio
    async def test_empty_summaries_skips_recall(self):
        """M-004: 无记忆时应跳过召回，仅返回 intent"""
        from app.services.memory_recall_service import classify_and_recall

        # Use rule-based shortcut for greeting
        intent, memory_ids, keywords, search_query, answer_complete = await classify_and_recall(
            user_message="你好",
            recent_context="",
            memory_summaries=[],
            user_id=1,
        )

        assert intent == "chat"
        assert memory_ids == []

    @pytest.mark.asyncio
    async def test_combined_prompt_extracts_keywords(self):
        """M-005: 合并 prompt 应同时提取关键词"""
        from app.services.memory_recall_service import classify_and_recall

        summaries = [
            {"id": 1, "memory_type": "weakness", "summary": "Redis 不熟"},
        ]

        mock_response = json.dumps({
            "intent": "interview_question",
            "relevant_memory_ids": [1],
            "keywords": ["Redis", "缓存策略", "数据结构"],
            "search_query": "Redis 缓存策略 数据结构",
            "answer_complete": True,
        })

        with patch("app.services.memory_recall_service._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response

            intent, memory_ids, keywords, search_query, answer_complete = await classify_and_recall(
                user_message="Redis 的缓存策略有哪些？",
                recent_context="",
                memory_summaries=summaries,
                user_id=1,
            )

        assert "Redis" in keywords
        assert len(keywords) > 0

    @pytest.mark.asyncio
    async def test_chat_intent_returns_empty(self):
        """M-006: 闲聊消息应返回 intent=chat, 空 keywords 和 ids"""
        from app.services.memory_recall_service import classify_and_recall

        summaries = [
            {"id": 1, "memory_type": "weakness", "summary": "测试"},
        ]

        # "谢谢" matches rule-based keyword exactly, returns early without LLM
        # Keywords are empty because the rule returns before _extract_keywords_fallback
        intent, memory_ids, keywords, search_query, answer_complete = await classify_and_recall(
            user_message="谢谢",
            recent_context="面试官: ...",
            memory_summaries=summaries,
            user_id=1,
        )

        assert intent == "chat"
        assert memory_ids == []
        assert keywords == []


class TestMemoryResolution:
    """记忆解析集成测试"""

    def test_get_memories_by_ids_fetches_correct_content(self, test_db):
        """M-007: get_memories_by_ids 应正确获取指定 ID 的记忆"""
        from app.services import chat_service

        # Create test user
        conn = test_db
        conn.execute("INSERT INTO users (username, password_hash, is_admin) VALUES ('test_user', 'hash', 0)")
        conn.commit()
        user_id = conn.execute("SELECT id FROM users WHERE username = 'test_user'").fetchone()[0]

        # Create test memories
        id1 = chat_service.save_memory(user_id, "weakness", "Redis 不熟悉", "auto_extract")
        id2 = chat_service.save_memory(user_id, "strength", "Java 精通", "auto_extract")
        id3 = chat_service.save_memory(user_id, "preference", "喜欢代码示例", "auto_extract")

        # Fetch by IDs
        results = chat_service.get_memories_by_ids([id1, id3], user_id)

        assert len(results) == 2
        result_ids = {r["id"] for r in results}
        assert id1 in result_ids
        assert id3 in result_ids
        assert id2 not in result_ids


class TestPipelineIntegration:
    """Pipeline 集成测试"""

    @pytest.mark.asyncio
    async def test_interview_path_uses_one_llm_call(self):
        """M-008: 面试路径在 generate_response 前应仅 1 次 LLM 调用"""
        from app.services.memory_recall_service import classify_and_recall

        summaries = [
            {"id": 1, "memory_type": "weakness", "summary": "Redis 不熟"},
        ]

        mock_response = json.dumps({
            "intent": "interview_question",
            "relevant_memory_ids": [1],
            "keywords": ["Redis"],
            "search_query": "Redis 数据结构",
            "answer_complete": True,
        })

        with patch("app.services.memory_recall_service._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = mock_response

            await classify_and_recall(
                user_message="Redis 的五种数据结构",
                recent_context="",
                memory_summaries=summaries,
                user_id=1,
            )

            # Only 1 LLM call for the combined classify + recall + keywords
            assert mock_llm.call_count == 1
