"""Basis tracking E2E tests.

Covers legacy [BASIS] parsing and the contract-owned selected-question path.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import ExitStack
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.chat.nodes import _filter_basis_ids_by_response, validate_basis
from app.agents.chat.pipeline import (
    _ensure_final_answer_quality,
    _fallback_coding_question,
    _is_bare_coding_prompt,
    _is_internal_react_marker,
)

# ── Pure Function Tests ───────────────────────────────


class TestValidateBasis:
    """validate_basis() — pure function tests."""

    def test_no_basis_type_defaults_to_conversation(self):
        """BS4: 无 basis_type → conversation, 不展示"""
        basis = {
            "basis_type": "",
            "basis_question_ids": [101],
            "basis_confidence": 0.9,
            "should_show_references": True,
        }
        result = validate_basis(basis, {101})
        assert result["basis_type"] == "conversation"
        assert result["should_show_references"] is False
        assert result["basis_confidence"] == 0.0

    def test_interview_question_with_valid_ids(self):
        """BS1: 正常 basis — 有效 ID + 高 confidence → 展示"""
        basis = {
            "basis_type": "interview_question",
            "basis_question_ids": [101, 102],
            "basis_confidence": 0.88,
            "should_show_references": False,
        }
        result = validate_basis(basis, {101, 102, 103})
        assert result["basis_question_ids"] == [101, 102]
        assert result["should_show_references"] is True
        assert result["basis_confidence"] == 0.88

    def test_non_retrieved_ids_filtered(self):
        """BS2: 非 retrieved ID 被过滤"""
        basis = {
            "basis_type": "interview_question",
            "basis_question_ids": [101, 999],
            "basis_confidence": 0.88,
            "should_show_references": False,
        }
        result = validate_basis(basis, {101, 102})
        assert result["basis_question_ids"] == [101]
        assert result["should_show_references"] is True

    def test_all_ids_filtered_drops_confidence(self):
        """BS2: 所有 ID 都不在 retrieved 中 → confidence 降至 0.3, 不展示"""
        basis = {
            "basis_type": "interview_question",
            "basis_question_ids": [999, 998],
            "basis_confidence": 0.88,
            "should_show_references": False,
        }
        result = validate_basis(basis, {101, 102})
        assert result["basis_question_ids"] == []
        assert result["basis_confidence"] == 0.3
        assert result["should_show_references"] is False

    def test_low_confidence_no_display(self):
        """BS3: confidence < 0.65 → 不展示"""
        basis = {
            "basis_type": "interview_question",
            "basis_question_ids": [101],
            "basis_confidence": 0.5,
            "should_show_references": False,
        }
        result = validate_basis(basis, {101})
        assert result["should_show_references"] is False

    def test_resume_type_clears_ids(self):
        """其他类型 (resume) → 清空 question_ids, 不展示"""
        basis = {
            "basis_type": "resume",
            "basis_question_ids": [101],
            "basis_confidence": 0.9,
            "should_show_references": True,
        }
        result = validate_basis(basis, {101})
        assert result["basis_question_ids"] == []
        assert result["should_show_references"] is False

    def test_mixed_type_with_valid_ids(self):
        """mixed 类型 → 和 interview_question 同等处理"""
        basis = {
            "basis_type": "mixed",
            "basis_question_ids": [101],
            "basis_confidence": 0.8,
            "should_show_references": False,
        }
        result = validate_basis(basis, {101})
        assert result["should_show_references"] is True


class TestFilterBasisByResponse:
    """_filter_basis_ids_by_response() — token overlap alignment."""

    def test_english_token_overlap_keeps(self):
        """英文 token 重叠 → 保留"""
        response = "Let me explain the Redis cache strategy"
        retrieved = [
            {"id": 101, "question": "Redis 有哪些常见数据结构？"},
            {"id": 102, "question": "MySQL 索引优化有哪些方法？"},
        ]
        result = _filter_basis_ids_by_response(response, [101, 102], retrieved)
        # "redis" overlaps with question 101
        assert 101 in result

    def test_cjk_overlap_keeps(self):
        """中文 token 重叠 >= 2 → 保留"""
        response = "Redis 缓存穿透的处理方法是使用布隆过滤器"
        retrieved = [
            {"id": 101, "question": "Redis 缓存穿透怎么处理？"},
        ]
        result = _filter_basis_ids_by_response(response, [101], retrieved)
        assert 101 in result

    def test_no_overlap_drops(self):
        """无 token 重叠 → 丢弃"""
        response = "今天天气不错"
        retrieved = [
            {"id": 101, "question": "Redis 有哪些常见数据结构？"},
        ]
        result = _filter_basis_ids_by_response(response, [101], retrieved)
        assert 101 not in result

    def test_empty_basis_ids(self):
        result = _filter_basis_ids_by_response("hello", [], [])
        assert result == []

    def test_empty_retrieved(self):
        result = _filter_basis_ids_by_response("hello", [101], [])
        assert result == []


class TestInternalMarkerDetection:
    """_is_internal_react_marker() — marker leakage detection."""

    def test_skill_name_detected(self):
        assert _is_internal_react_marker("project-deep-dive") is True

    def test_tool_name_detected(self):
        assert _is_internal_react_marker("search_questions") is True

    def test_normal_text_not_detected(self):
        assert _is_internal_react_marker("请介绍一下你做过的项目") is False

    def test_quoted_marker_detected(self):
        assert _is_internal_react_marker('"algorithm-coding"') is True


class TestBareCodingPrompt:
    """_is_bare_coding_prompt() + _ensure_final_answer_quality()."""

    def test_short_coding_prompt_detected(self):
        """BS7: 短 coding prompt → 替换"""
        state = {"active_skills": ["algorithm-coding"]}
        assert _is_bare_coding_prompt("来，写代码吧", state) is True

    def test_long_coding_response_not_detected(self):
        state = {"active_skills": ["algorithm-coding"]}
        assert _is_bare_coding_prompt(
            "我们来实现一个 LRU Cache，请你用哈希表加双向链表实现，要求 get 和 put 都是 O(1)。",
            state,
        ) is False

    def test_quality_check_replaces_bare_prompt(self):
        """BS7: _ensure_final_answer_quality 替换 bare coding prompt"""
        state = {"active_skills": ["algorithm-coding"]}
        result = _ensure_final_answer_quality("来，写代码吧", state)
        assert "来写一道代码题" in result
        assert len(result) > 50

    def test_quality_check_preserves_normal_text(self):
        state = {"active_skills": []}
        text = "请介绍一下你做过的最有挑战性的项目"
        result = _ensure_final_answer_quality(text, state)
        assert result == text


# ── E2E Pipeline Tests ────────────────────────────────


async def _run_basis_turn(
    *,
    llm_response_text: str,
    stream_chunks: tuple[str, ...],
    retrieved_questions: list[dict] | None = None,
) -> tuple[list[dict], dict]:
    """Run a single turn and return (events, state)."""
    from tests.chat.multi_turn_helpers import run_single_turn, make_question, tool_call

    search_results = retrieved_questions or [
        make_question(101, "Redis 有哪些常见数据结构？"),
        make_question(102, "Redis 分布式锁如何实现？"),
    ]
    search_mock = MagicMock(return_value=search_results)

    classify_updates = {
        "intent": "practice_request",
        "keywords": ["Redis"],
        "search_query": "Redis",
        "answer_complete": True,
        "answer_quality": "complete",
        "needs_new_dimension": True,
        "confidence": 0.9,
        "classify_result": {
            "intent": "practice_request",
            "answer_quality": "complete",
            "needs_new_dimension": True,
            "confidence": 0.9,
        },
        "retrieval_intent": "find_similar",
        "search_positive_terms": ["Redis"],
        "search_negative_terms": [],
        "question_type": "knowledge_probe",
    }

    llm_responses = [
        {
            "content": None,
            "tool_calls": [
                tool_call("search_questions", {"keywords": ["Redis"]}),
            ],
            "finish_reason": "tool_calls",
        },
        {
            "content": llm_response_text,
            "tool_calls": None,
            "finish_reason": "stop",
        },
    ]

    events, state, _ = await run_single_turn(
        user_message="给我出一道 Redis 相关的题",
        classify_updates=classify_updates,
        llm_responses=llm_responses,
        stream_chunks=stream_chunks,
        tool_patches=[
            patch("app.mcp_server.interview_tools._hybrid_search_for_tool", search_mock),
            patch(
                "app.agents.chat.writers.question_writer.generate_question_with_validation",
                new_callable=AsyncMock,
                return_value={
                    "status": "success",
                    "text": "请你讲讲 Redis 缓存穿透和布隆过滤器的关系。",
                    "validator_result": {"passes": True, "score": 0.91, "reason": "语义一致"},
                    "retry_count": 0,
                },
            ),
        ],
    )
    return events, state


class TestBasisE2E:
    """End-to-end basis tracking through the full pipeline."""

    async def test_selected_question_contract_sets_single_basis(self):
        """A validated selected question is the sole source of final basis."""
        events, state = await _run_basis_turn(
            llm_response_text=(
                "你先讲讲 Redis 缓存穿透和布隆过滤器的关系。"
                '[BASIS]{"type":"interview_question","question_ids":[101,102],'
                '"confidence":0.88,"show_refs":true}[/BASIS]'
            ),
            stream_chunks=(
                "你先讲讲 Redis 缓存穿透和布隆过滤器的关系。",
                '[BASIS]{"type":"interview_question","question_ids":[101,102],'
                '"confidence":0.88,"show_refs":true}[/BASIS]',
            ),
        )

        basis_event = next(e for e in events if e["type"] == "basis")
        assert basis_event["basis_type"] == "interview_question"
        assert basis_event["basis_question_ids"] == [101]
        assert basis_event["should_show_references"] is True
        assert basis_event["basis_confidence"] >= 0.65

    async def test_basis_ids_not_in_retrieved_filtered(self):
        """BS2: basis 中的 question_ids 不在 retrieved 集合内 → 被过滤掉"""
        events, state = await _run_basis_turn(
            llm_response_text=(
                "你先讲讲 Redis 缓存穿透。"
                '[BASIS]{"type":"interview_question","question_ids":[101,999],'
                '"confidence":0.88,"show_refs":true}[/BASIS]'
            ),
            stream_chunks=(
                "你先讲讲 Redis 缓存穿透。",
                '[BASIS]{"type":"interview_question","question_ids":[101,999],'
                '"confidence":0.88,"show_refs":true}[/BASIS]',
            ),
        )

        basis_event = next(e for e in events if e["type"] == "basis")
        assert 999 not in basis_event["basis_question_ids"]
        assert 101 in basis_event["basis_question_ids"]

    async def test_selected_question_contract_does_not_need_basis_marker(self):
        """The writer does not emit legacy markers, but provenance remains explicit."""
        events, state = await _run_basis_turn(
            llm_response_text="你先讲讲 Redis 缓存穿透。",
            stream_chunks=("你先讲讲 Redis 缓存穿透。",),
        )

        basis_event = next(e for e in events if e["type"] == "basis")
        assert basis_event["basis_type"] == "interview_question"
        assert basis_event["basis_question_ids"] == [101]
        assert basis_event["should_show_references"] is True

    async def test_basis_marker_stripped_from_response(self):
        """BS6: 最终 state response 中不包含 [BASIS]...[/BASIS]

        Note: SSE chunks 保留原始标记（前端 ChatView.vue 负责实时清除）。
        state["response"] 由 _build_react_metadata 清除。
        """
        events, state = await _run_basis_turn(
            llm_response_text=(
                "你先讲讲 Redis 缓存穿透。"
                '[BASIS]{"type":"interview_question","question_ids":[101],'
                '"confidence":0.9,"show_refs":true}[/BASIS]'
            ),
            stream_chunks=(
                "你先讲讲 Redis 缓存穿透。",
                '[BASIS]{"type":"interview_question","question_ids":[101],'
                '"confidence":0.9,"show_refs":true}[/BASIS]',
            ),
        )

        # state["response"] should be clean (stripped by _build_react_metadata)
        assert "[BASIS]" not in state["response"]

        # basis event should exist
        basis_event = next(e for e in events if e["type"] == "basis")
        assert basis_event["basis_type"] == "interview_question"

    async def test_selected_question_contract_overrides_legacy_marker_confidence(self):
        """Semantic validation, not a legacy marker score, proves the final basis."""
        events, state = await _run_basis_turn(
            llm_response_text=(
                "Redis 是一个内存数据库。"
                '[BASIS]{"type":"interview_question","question_ids":[101],'
                '"confidence":0.4,"show_refs":true}[/BASIS]'
            ),
            stream_chunks=(
                "Redis 是一个内存数据库。",
                '[BASIS]{"type":"interview_question","question_ids":[101],'
                '"confidence":0.4,"show_refs":true}[/BASIS]',
            ),
        )

        basis_event = next(e for e in events if e["type"] == "basis")
        assert basis_event["should_show_references"] is True
