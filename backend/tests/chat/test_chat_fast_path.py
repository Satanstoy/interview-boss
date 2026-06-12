"""
TDD 测试 — classify_and_recall_fast 快速路径

验证第一条消息时的零 LLM 成本分类路径
"""
import pytest


class TestClassifyAndRecallFast:
    """快速分类路径测试"""

    @pytest.mark.asyncio
    async def test_fast_path_returns_valid_intent(self):
        """第一条消息应通过规则快速分类"""
        from app.services.memory_recall_service import classify_and_recall_fast

        intent, memory_ids, keywords, search_query, answer_complete, _structured_rewrite = await classify_and_recall_fast(
            user_message="请介绍一下 Redis 的五种数据结构",
            memory_summaries=[],
        )

        assert intent in ("interview_question", "practice_request", "chat", "follow_up")
        assert isinstance(keywords, list)
        assert len(keywords) > 0
        assert isinstance(search_query, str)
        assert answer_complete is True

    @pytest.mark.asyncio
    async def test_fast_path_chat_message(self):
        """问候消息应快速返回 chat 意图"""
        from app.services.memory_recall_service import classify_and_recall_fast

        intent, memory_ids, keywords, search_query, answer_complete, _structured_rewrite = await classify_and_recall_fast(
            user_message="你好",
            memory_summaries=[],
        )

        assert intent == "chat"
        assert memory_ids == []

    @pytest.mark.asyncio
    async def test_fast_path_uses_recent_memories(self):
        """有记忆时应返回最近 3 条记忆 ID"""
        from app.services.memory_recall_service import classify_and_recall_fast

        summaries = [
            {"id": 1, "memory_type": "weakness", "summary": "Redis 不熟"},
            {"id": 2, "memory_type": "strength", "summary": "Java 精通"},
            {"id": 3, "memory_type": "preference", "summary": "喜欢代码"},
            {"id": 4, "memory_type": "weakness", "summary": "SQL 不熟"},
        ]

        intent, memory_ids, keywords, search_query, answer_complete, _structured_rewrite = await classify_and_recall_fast(
            user_message="请介绍一下 Redis",
            memory_summaries=summaries,
        )

        # 应返回前 3 条记忆 ID
        assert memory_ids == [1, 2, 3]
        assert intent == "interview_question"

    @pytest.mark.asyncio
    async def test_fast_path_extracts_keywords(self):
        """应从消息中提取技术关键词"""
        from app.services.memory_recall_service import classify_and_recall_fast

        intent, memory_ids, keywords, search_query, answer_complete, _structured_rewrite = await classify_and_recall_fast(
            user_message="Redis 的缓存策略和分布式锁怎么实现",
            memory_summaries=[],
        )

        assert len(keywords) > 0
        # 应包含 Redis 相关关键词
        keyword_text = " ".join(keywords).lower()
        assert "redis" in keyword_text or "缓存" in keyword_text

    @pytest.mark.asyncio
    async def test_fast_path_no_llm_call(self):
        """快速路径不应调用 LLM"""
        from unittest.mock import patch, AsyncMock
        from app.services.memory_recall_service import classify_and_recall_fast

        with patch("app.services.memory_recall_service._call_llm_with_retry", new_callable=AsyncMock) as mock_llm:
            await classify_and_recall_fast(
                user_message="请介绍一下 Redis",
                memory_summaries=[],
            )
            mock_llm.assert_not_called()
