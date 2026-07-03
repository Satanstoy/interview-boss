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

        intent, memory_ids, keywords, search_query, answer_complete, _structured_rewrite, _classify_result = await classify_and_recall_fast(
            user_message="请介绍一下 Redis 的五种数据结构",
            memory_summaries=[],
        )

        assert intent in ("interview_question", "practice_request", "chat", "follow_up")
        assert isinstance(keywords, list)
        assert len(keywords) > 0
        assert isinstance(search_query, str)
        assert answer_complete is False  # short question (< 30 chars), not a complete answer

    @pytest.mark.asyncio
    async def test_fast_path_chat_message(self):
        """问候消息应快速返回 chat 意图"""
        from app.services.memory_recall_service import classify_and_recall_fast

        intent, memory_ids, keywords, search_query, answer_complete, _structured_rewrite, _classify_result = await classify_and_recall_fast(
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

        intent, memory_ids, keywords, search_query, answer_complete, _structured_rewrite, _classify_result = await classify_and_recall_fast(
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

        intent, memory_ids, keywords, search_query, answer_complete, _structured_rewrite, _classify_result = await classify_and_recall_fast(
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

    @pytest.mark.asyncio
    async def test_fast_path_lifecycle_wording_is_not_end_interview(self):
        """描述业务流程里的'面试结束'不代表用户要结束当前面试。"""
        from app.services.memory_recall_service import classify_and_recall_fast

        intent, *_ = await classify_and_recall_fast(
            user_message=(
                "整体数据流是候选人进入系统后先加载上下文，"
                "从候选人进来到面试结束，RAG 检索、工具调用和题目选择策略会串起来。"
            ),
            memory_summaries=[],
            recent_context="面试官: 这套系统整体的数据流是怎样的？",
        )

        assert intent == "interview_question"

    @pytest.mark.asyncio
    async def test_llm_path_lifecycle_wording_is_not_end_interview(self):
        """即使文本包含'面试结束'，上下文是回答架构问题时仍应继续面试。"""
        import json
        from unittest.mock import AsyncMock, patch

        from app.services.memory_recall_service import classify_and_recall

        with patch(
            "app.services.memory_recall_service._call_llm_with_retry",
            new_callable=AsyncMock,
            return_value=json.dumps(
                {
                    "intent": "end_interview",
                    "relevant_memory_ids": [],
                    "keywords": ["RAG", "工具调用"],
                    "search_query": "RAG 工具调用",
                    "rewrite": {
                        "retrieval_intent": "find_similar",
                        "main_topic": "RAG 工具调用",
                        "positive_terms": ["RAG", "工具调用"],
                        "negative_terms": [],
                    },
                    "answer_complete": True,
                },
                ensure_ascii=False,
            ),
        ):
            intent, *_ = await classify_and_recall(
                user_message=(
                    "整体数据流是创建会话后写入 metadata，"
                    "从候选人进来到面试结束都会保留 reasoning trace 和 interview_state。"
                ),
                recent_context="面试官: RAG 检索、工具调用、题目选择策略这三块是怎么串起来的？",
                memory_summaries=[],
                user_id=1,
            )

        assert intent == "interview_question"
