"""Error recovery E2E tests for the chat agent pipeline.

Covers: ER1-ER6 from the test plan.
Tests fallback mechanisms when tools fail, LLM fails, loops detected, etc.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.chat.pipeline import (
    _fallback_react_answer,
    _is_internal_react_marker,
    _forced_closing_response,
    _last_assistant_message,
    validate_tool_call,
    StopRun,
)
from tests.chat.multi_turn_helpers import (
    run_single_turn,
    tool_call,
    make_question,
    routerize_events,
)

pytestmark = pytest.mark.asyncio


# ── Pure Function Tests ───────────────────────────────


class TestValidateToolCall:
    """validate_tool_call() — pure function tests."""

    def test_valid_tool_call_passes(self):
        """ER5: 有效工具调用 → 通过验证"""
        tc = tool_call("search_questions", {"keywords": ["Redis"]})
        result = validate_tool_call(tc)
        assert result == tc

    def test_missing_function_denied(self):
        """ER5: 无 function 字段 → invalid_tool_call"""
        with pytest.raises(StopRun, match="invalid_tool_call"):
            validate_tool_call({"id": "bad"})

    def test_unknown_tool_denied(self):
        """ER5: 不在 allowlist 的工具 → tool_denied"""
        tc = tool_call("unknown_tool", {})
        with pytest.raises(StopRun, match="tool_denied"):
            validate_tool_call(tc)

    def test_invalid_json_args_denied(self):
        """无效 JSON 参数 → invalid_args"""
        tc = {
            "id": "bad",
            "function": {"name": "search_questions", "arguments": "not-json"},
        }
        with pytest.raises(StopRun, match="invalid_args"):
            validate_tool_call(tc)

    def test_all_allowed_tools_pass(self):
        """所有允许的工具名都通过验证"""
        for name in ["load_skill", "search_questions", "draw_questions"]:
            tc = tool_call(name, {"test": True})
            result = validate_tool_call(tc)
            assert result["function"]["name"] == name


class TestFallbackReactAnswer:
    """_fallback_react_answer() — fallback generation."""

    def test_fallback_with_candidates(self):
        """ER2: 有候选题时 → 使用第一道候选题"""
        state = {
            "candidate_questions": [
                make_question(101, "Redis 缓存穿透怎么处理？"),
            ],
            "retrieved_questions": [],
            "keywords": ["Redis"],
        }
        result = _fallback_react_answer(state, "test_reason")
        assert "Redis 缓存穿透怎么处理" in result
        assert state["question_source_reason"] == "fallback_after_test_reason"

    def test_fallback_with_retrieved(self):
        """ER2: 无 candidate 但有 retrieved → 使用 retrieved"""
        state = {
            "candidate_questions": [],
            "retrieved_questions": [
                make_question(101, "Redis 分布式锁"),
            ],
            "keywords": ["Redis"],
        }
        result = _fallback_react_answer(state, "test_reason")
        assert "Redis 分布式锁" in result

    def test_fallback_without_candidates(self):
        """ER2: 无候选题 → 使用关键词生成追问"""
        state = {
            "candidate_questions": [],
            "retrieved_questions": [],
            "keywords": ["Redis", "缓存"],
        }
        result = _fallback_react_answer(state, "test_reason")
        assert "Redis" in result or "缓存" in result

    def test_fallback_without_keywords(self):
        """ER2: 无关键词 → 通用追问"""
        state = {
            "candidate_questions": [],
            "retrieved_questions": [],
            "keywords": [],
        }
        result = _fallback_react_answer(state, "test_reason")
        assert "你刚才提到的项目" in result


class TestForcedClosing:
    """_forced_closing_response() — hard stop at 44+ messages."""

    async def test_under_44_messages_no_closing(self):
        """消息数 <= 44 → 不触发强制关闭"""
        state = {"message_history": [{}] * 44, "user_message": ""}
        assert await _forced_closing_response(state) == ""

    @pytest.mark.asyncio
    async def test_over_44_messages_first_closing(self):
        """FC1: 消息数 > 44 且未问过反问 → LLM 生成结构化总结"""
        state = {
            "message_history": [{"role": "user", "content": "答"}] * 45,
            "user_message": "我还想继续",
            "session_notes": "[asked] Redis 持久化",
            "user_id": 1,
        }
        mock_summary_json = json.dumps({
            "overall_comment": "候选人基础知识扎实",
            "strongest_topic": "Redis，回答全面",
            "weakest_topic": "算法，答得浅",
            "key_suggestions": ["建议复习排序算法"],
            "score_estimate": 7,
        }, ensure_ascii=False)
        with patch(
            "app.agents.chat.pipeline._call_llm_with_retry_messages",
            new_callable=AsyncMock,
            return_value=mock_summary_json,
        ):
            result = await _forced_closing_response(state)
        assert "整体表现" in result
        assert "候选人基础知识扎实" in result

    @pytest.mark.asyncio
    async def test_over_44_messages_after_question(self):
        """FC2: 已问过"你有什么想问"且用户提了反问 → LLM 总结 + 反问回应"""
        state = {
            "message_history": [{"role": "user", "content": "答"}] * 45,
            "user_message": "请问团队的技术栈是什么？",
            "session_notes": "",
            "user_id": 1,
        }
        mock_summary_json = json.dumps({
            "overall_comment": "整体一般",
            "strongest_topic": "项目经验",
            "weakest_topic": "算法基础薄弱",
            "key_suggestions": ["多练习"],
            "score_estimate": 6,
        }, ensure_ascii=False)
        with patch(
            "app.agents.chat.pipeline._last_assistant_message",
            return_value="你有什么想问我们的吗？",
        ), patch(
            "app.agents.chat.pipeline._call_llm_with_retry_messages",
            new_callable=AsyncMock,
            return_value=mock_summary_json,
        ):
            result = await _forced_closing_response(state)
        assert "模拟面试就到这里" in result
        assert "整体一般" in result

    @pytest.mark.asyncio
    async def test_closing_updates_state(self):
        """强制关闭更新 question_source"""
        state = {
            "message_history": [{"role": "user", "content": "答"}] * 45,
            "user_message": "",
            "session_notes": "",
            "user_id": 1,
        }
        mock_summary_json = json.dumps({
            "overall_comment": "test",
            "strongest_topic": "t",
            "weakest_topic": "w",
            "key_suggestions": ["s"],
            "score_estimate": 5,
        }, ensure_ascii=False)
        with patch(
            "app.agents.chat.pipeline._call_llm_with_retry_messages",
            new_callable=AsyncMock,
            return_value=mock_summary_json,
        ):
            await _forced_closing_response(state)
        assert state["question_source"] == "conversation"
        assert state["question_source_reason"] == "forced_closing_by_message_count"


class TestInternalMarkerDetection:
    """_is_internal_react_marker() — marker leakage."""

    def test_skill_names_detected(self):
        for name in [
            "project-deep-dive",
            "algorithm-coding",
            "theory-qa",
            "interview-rhythm",
            "adaptive-difficulty",
            "hr-soft-skills",
        ]:
            assert _is_internal_react_marker(name) is True, f"Failed for {name}"

    def test_tool_names_detected(self):
        for name in ["load_skill", "search_questions", "draw_questions"]:
            assert _is_internal_react_marker(name) is True, f"Failed for {name}"

    def test_normal_text_not_detected(self):
        assert _is_internal_react_marker("请介绍一下你的项目经验") is False


# ── E2E Pipeline Tests ────────────────────────────────


class TestToolFailureRecovery:
    """Tool execution failure → LLM recovers."""

    async def test_search_failure_recovers_to_direct_answer(self):
        """ER1: search_questions 抛异常 → LLM 收到错误 → 直接回答"""
        search_mock = MagicMock(side_effect=RuntimeError("search service unavailable"))

        events, state, llm_mock = await run_single_turn(
            user_message="给我出一道 Redis 相关的题",
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
                    "content": "搜索出错了，我直接给你一道基础题。",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ],
            stream_chunks=("搜索出错了，我直接给你一道基础题。",),
            tool_patches=[
                patch("app.agents.chat.tools._hybrid_search", search_mock),
            ],
        )

        assert search_mock.call_count == 1
        # Should still get a done event (not crash)
        assert any(e["type"] == "done" for e in events)
        assert "搜索出错了" in state["response"]

    async def test_draw_failure_recovers(self):
        """ER1: draw_questions 抛异常 → LLM 收到错误 → 直接回答"""
        draw_mock = MagicMock(side_effect=RuntimeError("draw service unavailable"))

        events, state, llm_mock = await run_single_turn(
            user_message="开始算法面试",
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
                        tool_call("draw_questions", {"count": 2}),
                    ],
                    "finish_reason": "tool_calls",
                },
                {
                    "content": "抽题服务暂时不可用，我来手动出一道。",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ],
            stream_chunks=("抽题服务暂时不可用，我来手动出一道。",),
            tool_patches=[
                patch("app.agents.chat.tools._draw_questions", draw_mock),
            ],
        )

        assert any(e["type"] == "done" for e in events)


class TestLoopDetection:
    """ER4: Identical tool calls → loop_detected → stop."""

    async def test_repeated_tool_call_detected(self):
        """完全相同的 tool call 重复 → loop_detected"""
        mock_skill = MagicMock()
        mock_skill.get_instruction.return_value = "Theory QA instruction."

        registry = MagicMock()
        registry.get.return_value = mock_skill

        # LLM keeps calling load_skill with the same args
        same_tc = tool_call("load_skill", {"skill_name": "theory-qa"})
        llm_responses = [
            {"content": None, "tool_calls": [same_tc], "finish_reason": "tool_calls"},
            {"content": None, "tool_calls": [same_tc], "finish_reason": "tool_calls"},
        ]

        events, state, llm_mock = await run_single_turn(
            user_message="继续",
            classify_updates={
                "intent": "interview_question",
                "keywords": [],
                "search_query": "",
                "answer_complete": True,
                "retrieval_intent": None,
                "search_positive_terms": [],
                "search_negative_terms": [],
                "question_type": None,
            },
            llm_responses=llm_responses,
            stream_chunks=("好的，我们继续。",),
            tool_patches=[
                patch(
                    "app.agents.chat.tools._get_skill_registry",
                    return_value=registry,
                ),
            ],
        )

        # Should have stopped after loop detection (not infinite loop)
        assert llm_mock.call_count == 2
        assert any(e["type"] == "done" for e in events)


class TestLLMFailureFallback:
    """ER2: LLM call failure → fallback answer."""

    async def test_llm_exception_produces_fallback(self):
        """ReAct 步骤中 LLM 抛异常 → break → stream fallback"""
        # When LLM fails, _react_loop breaks, then tries _stream_final_answer.
        # The stream mock returns a fallback message.
        events, state, llm_mock = await run_single_turn(
            user_message="给我出一道题",
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
            llm_responses=[Exception("LLM service unavailable")],
            stream_chunks=("让我们围绕 Redis 继续讨论。",),
        )

        # Should get a done event (not crash)
        assert any(e["type"] == "done" for e in events)
        # LLM was called once (and failed)
        assert llm_mock.call_count == 1


class TestForcedClosingE2E:
    """FC1-FC3: Forced closing through the pipeline."""

    async def test_forced_closing_skips_react_loop(self):
        """FC1: 44+ 消息 → 强制关闭，不进入 ReAct 循环"""
        from app.agents.chat.pipeline import run_chat

        async def mock_load_context(state):
            state.update(
                {
                    "message_history": [{}] * 45,
                    "recent_messages": [],
                    "compressed_context": None,
                    "session_notes": "",
                    "interview_context": "目标岗位：后端开发",
                    "job_position": "后端开发",
                    "memory_summaries": [],
                    "retrieved_questions": [],
                }
            )
            return state

        async def mock_classify(state):
            state.update(
                {
                    "intent": "interview_question",
                    "keywords": [],
                    "search_query": "",
                    "answer_complete": True,
                    "retrieval_intent": None,
                    "search_positive_terms": [],
                    "search_negative_terms": [],
                    "question_type": None,
                }
            )
            return state

        async def mock_extract_memory(snapshot):
            pass

        llm_mock = AsyncMock()  # Should NOT be called (ReAct loop skipped)

        mock_summary_json = json.dumps({
            "overall_comment": "候选人整体表现出色",
            "strongest_topic": "项目经验丰富",
            "weakest_topic": "算法基础薄弱",
            "key_suggestions": ["多练算法题"],
            "score_estimate": 7,
        }, ensure_ascii=False)

        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "app.agents.chat.pipeline.build_react_system_prompt",
                    return_value="Test prompt.",
                )
            )
            stack.enter_context(
                patch(
                    "app.agents.chat.pipeline._step_load_context",
                    new_callable=AsyncMock,
                    side_effect=mock_load_context,
                )
            )
            stack.enter_context(
                patch(
                    "app.agents.chat.pipeline._step_classify",
                    new_callable=AsyncMock,
                    side_effect=mock_classify,
                )
            )
            stack.enter_context(
                patch(
                    "app.agents.chat.pipeline._step_extract_memory",
                    new_callable=AsyncMock,
                    side_effect=mock_extract_memory,
                )
            )
            stack.enter_context(
                patch("app.agents.chat.pipeline.llm_with_tools", new=llm_mock)
            )
            stack.enter_context(
                patch(
                    "app.agents.chat.pipeline._call_llm_with_retry_messages",
                    new_callable=AsyncMock,
                    return_value=mock_summary_json,
                )
            )

            events = []
            async for event in run_chat(
                conversation_id="conv-forced-close",
                user_id=1,
                user_message="我还想继续",
                mode="free_practice",
                bank_mode="public",
            ):
                events.append(event)

        # ReAct LLM (llm_with_tools) should NOT have been called
        assert llm_mock.call_count == 0

        # Should have chunk + done events with structured summary
        chunk_text = "".join(
            e.get("content", "") for e in events if e["type"] == "chunk"
        )
        assert "整体表现" in chunk_text
        assert "候选人整体表现出色" in chunk_text
        assert any(e["type"] == "done" for e in events)
