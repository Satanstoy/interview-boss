"""Interview rhythm E2E tests.

Covers: R1-R5, FC1-FC3 from the test plan.
Tests phase transitions, question distribution, consecutive limits, forced closing.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.chat.nodes import _determine_interview_phase, _build_tool_strategy
from app.agents.chat.pipeline import _forced_closing_response
from tests.chat.multi_turn_helpers import (
    run_single_turn,
    tool_call,
    make_question,
)

pytestmark = pytest.mark.asyncio


# ── Pure Function Tests ───────────────────────────────


class TestInterviewPhase:
    """_determine_interview_phase() — rule-based phase transitions."""

    def test_opening_phase_0_messages(self):
        """R2: 0 条消息 → 开场阶段"""
        result = _determine_interview_phase(0)
        assert "开场阶段" in result
        assert "自我介绍" in result

    def test_opening_phase_2_messages(self):
        """R2: 2 条消息 → 开场阶段"""
        result = _determine_interview_phase(2)
        assert "开场阶段" in result

    def test_active_phase_3_messages(self):
        """R1: 3 条消息 → 面试进行中"""
        result = _determine_interview_phase(3)
        assert "面试进行中" in result

    def test_active_phase_32_messages(self):
        """R1: 32 条消息 → 面试进行中"""
        result = _determine_interview_phase(32)
        assert "面试进行中" in result

    def test_long_interview_33_messages(self):
        """FC3: 33 条消息 → 可以收尾"""
        result = _determine_interview_phase(33)
        assert "较长时间" in result

    def test_long_interview_44_messages(self):
        """FC3: 44 条消息 → 可以收尾"""
        result = _determine_interview_phase(44)
        assert "较长时间" in result

    def test_time_up_45_messages(self):
        """FC1: 45 条消息 → 时间已到"""
        result = _determine_interview_phase(45)
        assert "时间已到" in result

    def test_time_up_100_messages(self):
        """FC1: 100 条消息 → 时间已到"""
        result = _determine_interview_phase(100)
        assert "时间已到" in result


class TestToolStrategy:
    """_build_tool_strategy() — intent-based tool guidance."""

    def test_interview_question_complete_no_retrieved(self):
        """R1: 回答完毕 + 无检索结果 → 必须调用 search_questions"""
        state = {
            "intent": "interview_question",
            "answer_complete": True,
            "retrieved_questions": [],
            "active_skills": [],
        }
        result = _build_tool_strategy(state)
        assert "search_questions" in result
        assert "必须" in result

    def test_interview_question_complete_has_retrieved(self):
        """已有检索结果 → 直接使用，无需再次检索"""
        state = {
            "intent": "interview_question",
            "answer_complete": True,
            "retrieved_questions": [{"id": 101}],
            "active_skills": [],
        }
        result = _build_tool_strategy(state)
        assert "直接使用" in result

    def test_interview_question_incomplete(self):
        """R3: 未回答完毕 → 不调用工具"""
        state = {
            "intent": "interview_question",
            "answer_complete": False,
            "retrieved_questions": [],
            "active_skills": [],
        }
        result = _build_tool_strategy(state)
        assert "不调用工具" in result

    def test_practice_request(self):
        """练习请求 → 必须调用 search_questions"""
        state = {
            "intent": "practice_request",
            "answer_complete": True,
            "retrieved_questions": [],
            "active_skills": [],
        }
        result = _build_tool_strategy(state)
        assert "search_questions" in result

    def test_follow_up(self):
        """追问 → 基于上下文回答"""
        state = {
            "intent": "follow_up",
            "answer_complete": False,
            "retrieved_questions": [],
            "active_skills": [],
        }
        result = _build_tool_strategy(state)
        assert "上下文" in result

    def test_chat_intent(self):
        """闲聊 → 不调用工具，引导回面试"""
        state = {
            "intent": "chat",
            "answer_complete": False,
            "retrieved_questions": [],
            "active_skills": [],
        }
        result = _build_tool_strategy(state)
        assert "不调用工具" in result

    async def test_deep_dive_complete_answer_requires_search(self):
        """项目深挖 + 回答完整 + 无候选题 → 必须检索，避免直接追问掩盖工具缺失。"""
        state = {
            "intent": "interview_question",
            "answer_complete": True,
            "retrieved_questions": [],
            "active_skills": ["project-deep-dive"],
        }
        result = _build_tool_strategy(state)
        assert "项目深挖" in result
        assert "search_questions" in result
        assert "必须" in result
        assert "可以不检索" not in result


# ── E2E Pipeline Tests ────────────────────────────────


class TestOpeningPhaseE2E:
    """R2: 开场阶段行为验证."""

    async def test_first_message_uses_project_deep_dive(self):
        """R2: 第一条消息 → phase="开场阶段", 从项目深挖开始"""
        search_results = [
            make_question(101, "Redis 缓存穿透怎么处理？", cat1="中间件", cat2="缓存"),
        ]
        search_mock = MagicMock(return_value=search_results)

        events, state, llm_mock = await run_single_turn(
            user_message="你好，我是候选人",
            classify_updates={
                "intent": "interview_question",
                "keywords": ["Redis"],
                "search_query": "Redis 缓存",
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
                    "content": (
                        "好的，先从 Redis 缓存穿透开始。"
                        '[BASIS]{"type":"interview_question","question_ids":[101],'
                        '"confidence":0.9,"show_refs":true}[/BASIS]'
                    ),
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ],
            stream_chunks=(
                "好的，先从 Redis 缓存穿透开始。",
                '[BASIS]{"type":"interview_question","question_ids":[101],'
                '"confidence":0.9,"show_refs":true}[/BASIS]',
            ),
            tool_patches=[
                patch("app.agents.chat.tools._hybrid_search", search_mock),
            ],
        )

        # Should have search + generating steps
        steps = [e["step"] for e in events if e["type"] == "step"]
        assert "search_questions" in steps
        assert "generating" in steps

        # Should have retrieved event
        retrieved = [e for e in events if e["type"] == "retrieved"]
        assert len(retrieved) == 1

        # Basis should reference the question
        basis = next(e for e in events if e["type"] == "basis")
        assert basis["basis_type"] == "interview_question"
        assert 101 in basis["basis_question_ids"]


class TestAnswerCompleteness:
    """R3: 回答完整性对工具策略的影响."""

    async def test_incomplete_answer_no_tool_call(self):
        """R3: 短回答 → answer_complete=False → LLM 不调用工具"""
        events, state, llm_mock = await run_single_turn(
            user_message="嗯...",
            classify_updates={
                "intent": "interview_question",
                "keywords": [],
                "search_query": "",
                "answer_complete": False,
                "retrieval_intent": None,
                "search_positive_terms": [],
                "search_negative_terms": [],
                "question_type": None,
            },
            llm_responses=[
                {
                    "content": "能再详细说说吗？",
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ],
            stream_chunks=("能再详细说说吗？",),
        )

        # LLM should only be called once (no tool calls)
        assert llm_mock.call_count == 1
        # No search/draw steps
        steps = [e["step"] for e in events if e["type"] == "step"]
        assert "search_questions" not in steps
        assert "draw_questions" not in steps

    async def test_complete_answer_triggers_search(self):
        """R1: 完整回答 → answer_complete=True → LLM 调用 search_questions"""
        search_results = [
            make_question(102, "Redis 持久化策略有哪些？"),
        ]
        search_mock = MagicMock(return_value=search_results)

        events, state, llm_mock = await run_single_turn(
            user_message="我用了 Redis 做缓存，通过布隆过滤器解决了穿透问题",
            classify_updates={
                "intent": "interview_question",
                "keywords": ["Redis", "缓存"],
                "search_query": "Redis 缓存穿透",
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
                            {"keywords": ["Redis", "缓存"]},
                        ),
                    ],
                    "finish_reason": "tool_calls",
                },
                {
                    "content": (
                        "很好，那你说说 Redis 持久化策略。"
                        '[BASIS]{"type":"interview_question","question_ids":[102],'
                        '"confidence":0.85,"show_refs":true}[/BASIS]'
                    ),
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ],
            stream_chunks=(
                "很好，那你说说 Redis 持久化策略。",
                '[BASIS]{"type":"interview_question","question_ids":[102],'
                '"confidence":0.85,"show_refs":true}[/BASIS]',
            ),
            tool_patches=[
                patch("app.agents.chat.tools._hybrid_search", search_mock),
            ],
        )

        # LLM should be called twice (tool call + answer)
        assert llm_mock.call_count == 2
        # Should have search step
        steps = [e["step"] for e in events if e["type"] == "step"]
        assert "search_questions" in steps
        # Should have retrieved event
        retrieved = [e for e in events if e["type"] == "retrieved"]
        assert len(retrieved) == 1


class TestLoadSkillE2E:
    """R4: Skill 加载和切换."""

    async def test_load_skill_then_draw(self):
        """R4: load_skill → draw_questions → 回答"""
        mock_skill = MagicMock()
        mock_skill.get_instruction.return_value = "## Algorithm Coding\nAsk algorithm problems."

        registry = MagicMock()
        registry.get.return_value = mock_skill

        draw_results = [
            make_question(201, "实现 LRU Cache", cat1="算法", cat2="缓存", company="字节"),
        ]
        draw_mock = MagicMock(return_value=draw_results)

        events, state, llm_mock = await run_single_turn(
            user_message="开始算法面试",
            classify_updates={
                "intent": "practice_request",
                "keywords": ["算法"],
                "search_query": "算法面试",
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
                        tool_call("load_skill", {"skill_name": "algorithm-coding"}),
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
                    "content": (
                        "我们先从 LRU Cache 开始。"
                        '[BASIS]{"type":"interview_question","question_ids":[201],'
                        '"confidence":0.91,"show_refs":true}[/BASIS]'
                    ),
                    "tool_calls": None,
                    "finish_reason": "stop",
                },
            ],
            stream_chunks=(
                "我们先从 LRU Cache 开始。",
                '[BASIS]{"type":"interview_question","question_ids":[201],'
                '"confidence":0.91,"show_refs":true}[/BASIS]',
            ),
            tool_patches=[
                patch("app.agents.chat.tools._get_skill_registry", return_value=registry),
                patch("app.agents.chat.tools._draw_questions", draw_mock),
            ],
        )

        # Verify skill was loaded
        assert state["active_skills"] == ["algorithm-coding"]

        # Verify steps
        steps = [e["step"] for e in events if e["type"] == "step"]
        assert "load_skill" in steps
        assert "draw_questions" in steps
        assert "generating" in steps

        # Verify insight events
        insights = [e for e in events if e["type"] == "insight"]
        assert len(insights) >= 1
        assert any("切换" in e.get("text", "") or "算法" in e.get("text", "") for e in insights)

        # Verify basis
        basis = next(e for e in events if e["type"] == "basis")
        assert basis["basis_type"] == "interview_question"
        assert basis["should_show_references"] is True


class TestForcedClosingPhaseTransitions:
    """FC1-FC3: Phase-based forced closing."""

    def test_phase_33_messages_can_close(self):
        """FC3: 33 条消息 → 面试已进行较长时间"""
        phase = _determine_interview_phase(33)
        assert "较长时间" in phase
        assert "收尾" in phase

    def test_phase_45_messages_must_close(self):
        """FC1: 45 条消息 → 时间已到"""
        phase = _determine_interview_phase(45)
        assert "时间已到" in phase

    async def test_forced_closing_empty_under_threshold(self):
        """FC1: 44 条消息 → 不触发"""
        state = {"message_history": [{}] * 44, "user_message": ""}
        assert await _forced_closing_response(state) == ""

    async def test_forced_closing_active_over_threshold(self):
        """FC1: 45 条消息 → 触发（LLM 生成结构化总结）"""
        mock_summary_json = json.dumps({
            "overall_comment": "候选人表现中等",
            "strongest_topic": "Redis，回答较全面",
            "weakest_topic": "算法薄弱",
            "key_suggestions": ["多练算法题"],
            "score_estimate": 6,
        }, ensure_ascii=False)
        state = {
            "message_history": [{"role": "user", "content": "答"}] * 45,
            "user_message": "",
            "session_notes": "",
            "user_id": 1,
        }
        with patch(
            "app.agents.chat.pipeline._call_llm_with_retry_messages",
            new_callable=AsyncMock,
            return_value=mock_summary_json,
        ):
            result = await _forced_closing_response(state)
        assert "整体表现" in result
