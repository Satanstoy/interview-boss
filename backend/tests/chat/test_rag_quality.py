"""RAG quality E2E tests for the chat agent pipeline.

Covers: RG1-RG6 from the test plan.
Tests search_questions, draw_questions, retrieval accuracy, and fallbacks.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.chat.chat_constants import PUBLIC_QUESTION_PREVIEW_LIMIT
from tests.chat.multi_turn_helpers import (
    run_single_turn,
    tool_call,
    make_question,
)

pytestmark = pytest.mark.asyncio


class TestSearchQuestionsRAG:
    """search_questions tool integration."""

    async def test_keywords_passed_to_search(self):
        """RG1: LLM 提取的 keywords 正确传给 hybrid_search"""
        search_results = [
            make_question(101, "Redis 有哪些常见数据结构？"),
            make_question(102, "Redis 分布式锁如何实现？"),
        ]
        search_mock = MagicMock(return_value=search_results)

        events, state, llm_mock = await run_single_turn(
            user_message="给我出一道 Redis 相关的题",
            classify_updates={
                "intent": "practice_request",
                "keywords": ["Redis", "缓存"],
                "search_query": "Redis 缓存",
                "answer_complete": True,
                "retrieval_intent": "find_similar",
                "search_positive_terms": ["Redis", "缓存"],
                "search_negative_terms": [],
                "question_type": "knowledge_probe",
            },
            llm_responses=[
                {
                    "content": None,
                    "tool_calls": [
                        tool_call(
                            "search_questions",
                            {"keywords": ["Redis", "缓存"], "question_type": "knowledge_probe"},
                        ),
                    ],
                    "finish_reason": "tool_calls",
                },
                {
                    "content": "说说 Redis 缓存穿透。",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ],
            stream_chunks=("说说 Redis 缓存穿透。",),
            tool_patches=[
                patch("app.mcp_server.interview_tools._hybrid_search_for_tool", search_mock),
                patch(
                    "app.services.llm.raw_llm_call",
                    new=AsyncMock(
                        return_value=json.dumps({"scores": [0.9, 0.8, 0.7, 0.6]})
                    ),
                ),
            ],
        )

        # Verify search was called with correct params
        search_mock.assert_called_once()
        call_kwargs = search_mock.call_args.kwargs
        assert call_kwargs["query_text"] == "Redis 缓存"
        assert call_kwargs["question_type"] == "knowledge_probe"

    async def test_retrieved_event_contains_public_preview_limit(self):
        """RG2: 检索结果正确存入 retrieved_questions，SSE retrieved 事件包含公开预览"""
        search_results = [
            make_question(101, "Redis 数据结构"),
            make_question(102, "Redis 分布式锁"),
            make_question(103, "Redis 缓存击穿"),
            make_question(104, "Redis 持久化"),
        ]
        search_mock = MagicMock(return_value=search_results)

        events, state, llm_mock = await run_single_turn(
            user_message="Redis 相关问题",
            classify_updates={
                "intent": "practice_request",
                "keywords": ["Redis"],
                "search_query": "Redis",
                "answer_complete": True,
                "retrieval_intent": "find_similar",
                "search_positive_terms": ["Redis"],
                "search_negative_terms": [],
                "question_type": "knowledge_probe",
            },
            llm_responses=[
                {
                    "content": None,
                    "tool_calls": [
                        tool_call("search_questions", {"keywords": ["Redis"]}),
                    ],
                    "finish_reason": "tool_calls",
                },
                {
                    "content": "说说 Redis。",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ],
            stream_chunks=("说说 Redis。",),
            tool_patches=[
                patch("app.mcp_server.interview_tools._hybrid_search_for_tool", search_mock),
                patch(
                    "app.services.llm.raw_llm_call",
                    new=AsyncMock(
                        return_value=json.dumps({"scores": [0.9, 0.8, 0.7, 0.6]})
                    ),
                ),
            ],
        )

        # Retrieved event should contain the public preview window, not every match.
        retrieved_events = [e for e in events if e["type"] == "retrieved"]
        assert len(retrieved_events) == 1
        assert len(retrieved_events[0]["questions"]) == min(
            PUBLIC_QUESTION_PREVIEW_LIMIT, len(search_results)
        )

        # First question should be the top result
        assert retrieved_events[0]["questions"][0]["id"] == 101

        # State should have all results
        assert len(state["retrieved_questions"]) == 4

    async def test_retrieved_event_has_company_and_round(self):
        """RG2: retrieved 事件包含 company 和 round 信息"""
        search_results = [
            make_question(101, "Redis 数据结构", company="字节", round_name="二面"),
        ]
        search_mock = MagicMock(return_value=search_results)

        events, state, llm_mock = await run_single_turn(
            user_message="Redis",
            classify_updates={
                "intent": "practice_request",
                "keywords": ["Redis"],
                "search_query": "Redis",
                "answer_complete": True,
                "retrieval_intent": "find_similar",
                "search_positive_terms": ["Redis"],
                "search_negative_terms": [],
                "question_type": "knowledge_probe",
            },
            llm_responses=[
                {
                    "content": None,
                    "tool_calls": [
                        tool_call("search_questions", {"keywords": ["Redis"]}),
                    ],
                    "finish_reason": "tool_calls",
                },
                {"content": "说说 Redis。", "tool_calls": None, "finish_reason": "stop"},
            ],
            stream_chunks=("说说 Redis。",),
            tool_patches=[
                patch("app.mcp_server.interview_tools._hybrid_search_for_tool", search_mock),
            ],
        )

        retrieved_events = [e for e in events if e["type"] == "retrieved"]
        q = retrieved_events[0]["questions"][0]
        assert q["company"] == "字节"
        assert q["round"] == "二面"


class TestDrawQuestionsRAG:
    """draw_questions tool integration."""

    async def test_draw_with_filters(self):
        """RG3: draw_questions 正确传递 count 和 filters"""
        draw_results = [
            make_question(201, "二分查找", cat1="算法", cat2="数组"),
        ]
        draw_mock = MagicMock(return_value=draw_results)

        events, state, llm_mock = await run_single_turn(
            user_message="出一道算法题",
            classify_updates={
                "intent": "practice_request",
                "keywords": ["算法"],
                "search_query": "算法",
                "answer_complete": True,
                "retrieval_intent": "expand_knowledge",
                "search_positive_terms": ["算法"],
                "search_negative_terms": [],
                "question_type": "new_question",
            },
            llm_responses=[
                {
                    "content": None,
                    "tool_calls": [
                        tool_call("draw_questions", {"count": 1, "cat1": "算法"}),
                    ],
                    "finish_reason": "tool_calls",
                },
                {"content": "写一个二分查找。", "tool_calls": None, "finish_reason": "stop"},
            ],
            stream_chunks=("写一个二分查找。",),
            tool_patches=[
                patch("app.mcp_server.interview_tools._draw_questions_for_tool", draw_mock),
            ],
        )

        draw_mock.assert_called_once()
        call_kwargs = draw_mock.call_args.kwargs
        assert call_kwargs["count"] == 1
        assert call_kwargs.get("cat1") == "算法"

    async def test_draw_bank_mode_passed(self):
        """RG3: bank_mode 正确传递"""
        draw_results = [make_question(201, "二分查找")]
        draw_mock = MagicMock(return_value=draw_results)

        events, state, llm_mock = await run_single_turn(
            user_message="出题",
            classify_updates={
                "intent": "practice_request",
                "keywords": [],
                "search_query": "",
                "answer_complete": True,
                "retrieval_intent": None,
                "search_positive_terms": [],
                "search_negative_terms": [],
                "question_type": None,
            },
            llm_responses=[
                {
                    "content": None,
                    "tool_calls": [tool_call("draw_questions", {"count": 1})],
                    "finish_reason": "tool_calls",
                },
                {"content": "写一个二分查找。", "tool_calls": None, "finish_reason": "stop"},
            ],
            stream_chunks=("写一个二分查找。",),
            tool_patches=[
                patch("app.mcp_server.interview_tools._draw_questions_for_tool", draw_mock),
            ],
            bank_mode="mixed",
        )

        call_kwargs = draw_mock.call_args.kwargs
        assert call_kwargs["user"]["bank_mode"] == "mixed"


class TestEmptyRetrievalFallback:
    """RG4: 检索结果为空时降级."""

    async def test_search_empty_then_draw(self):
        """RG4: search_questions 返回空 → LLM 收到空结果 → draw_questions 补充"""
        search_mock = MagicMock(return_value=[])
        draw_results = [make_question(201, "LRU Cache")]
        draw_mock = MagicMock(return_value=draw_results)

        events, state, llm_mock = await run_single_turn(
            user_message="出一道题",
            classify_updates={
                "intent": "practice_request",
                "keywords": ["未知技术"],
                "search_query": "未知技术",
                "answer_complete": True,
                "retrieval_intent": "find_similar",
                "search_positive_terms": ["未知技术"],
                "search_negative_terms": [],
                "question_type": "new_question",
            },
            llm_responses=[
                {
                    "content": None,
                    "tool_calls": [
                        tool_call("search_questions", {"keywords": ["未知技术"]}),
                    ],
                    "finish_reason": "tool_calls",
                },
                {
                    "content": None,
                    "tool_calls": [
                        tool_call("draw_questions", {"count": 1}),
                    ],
                    "finish_reason": "tool_calls",
                },
                {
                    "content": "写一个 LRU Cache。",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ],
            stream_chunks=("写一个 LRU Cache。",),
            tool_patches=[
                patch("app.mcp_server.interview_tools._hybrid_search_for_tool", search_mock),
                patch("app.mcp_server.interview_tools._draw_questions_for_tool", draw_mock),
            ],
        )

        # Both tools should have been called
        assert search_mock.call_count == 1
        assert draw_mock.call_count == 1

        # Steps should show both
        steps = [e["step"] for e in events if e["type"] == "step"]
        assert "search_questions" in steps
        assert "draw_questions" in steps


class TestNoDuplicateRetrieval:
    """RG6: has_retrieved=True 时不重复触发检索."""

    async def test_has_retrieved_no_search(self):
        """RG6: 已有检索结果 + answer_complete → LLM 直接使用，不调用工具"""
        existing_question = make_question(201, "Redis 持久化怎么做？")
        events, state, llm_mock = await run_single_turn(
            user_message="我用了 Redis 做缓存",
            classify_updates={
                "intent": "interview_question",
                "keywords": ["Redis", "缓存"],
                "search_query": "Redis 缓存",
                "answer_complete": True,
                "retrieval_intent": "find_similar",
                "search_positive_terms": ["Redis"],
                "search_negative_terms": [],
                "question_type": "knowledge_probe",
            },
            llm_responses=[
                {
                    "content": "很好，那你说说持久化。",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ],
            stream_chunks=("很好，那你说说持久化。",),
            state_overrides={
                "retrieved_questions": [existing_question],
                "candidate_questions": [existing_question],
            },
        )

        # LLM should only be called once (no tool calls)
        assert llm_mock.call_count == 1
        # No search/draw steps
        steps = [e["step"] for e in events if e["type"] == "step"]
        assert "search_questions" not in steps
        assert "draw_questions" not in steps
