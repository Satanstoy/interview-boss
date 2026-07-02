"""Tests for answer.py transition rewrite logic.

Covers:
- _rewrite_transition_with_llm: LLM-based natural transition generation
- _format_bank_question_fallback: deterministic last-resort fallback
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


# ── _format_bank_question_fallback (deterministic last resort) ──


class TestFormatBankQuestionFallback:
    """Deterministic fallback when LLM rewrite is not available."""

    def test_plan_style_no_mechanical_prefix(self):
        from app.agents.chat.answer import _format_bank_question_fallback

        result = _format_bank_question_fallback("MySQL 索引原理", style="plan")
        assert "换个具体点的问题：" not in result
        assert "MySQL" in result

    def test_plan_style_starts_with_natural_prefix(self):
        from app.agents.chat.answer import _format_bank_question_fallback

        result = _format_bank_question_fallback("Redis 跳表结构", style="plan")
        assert result.startswith("好，")

    def test_candidate_style_no_mechanical_prefix(self):
        from app.agents.chat.answer import _format_bank_question_fallback

        result = _format_bank_question_fallback("说说 Redis 跳表", style="candidate")
        assert "换个具体点的问题" not in result
        assert "顺着你刚才的回答" not in result
        assert "Redis" in result

    def test_empty_question_returns_generic(self):
        from app.agents.chat.answer import _format_bank_question_fallback

        result = _format_bank_question_fallback("", style="plan")
        assert len(result) > 10

    def test_no_last_user_answer_parameter(self):
        """_format_bank_question_fallback should NOT accept last_user_answer —
        natural transitions are handled by _rewrite_transition_with_llm."""
        import inspect
        from app.agents.chat.answer import _format_bank_question_fallback

        sig = inspect.signature(_format_bank_question_fallback)
        assert "last_user_answer" not in sig.parameters


# ── _rewrite_transition_with_llm ────────────────────────────────


class TestRewriteTransitionWithLlm:
    """LLM-based natural transition from candidate answer to next question."""

    @pytest.mark.asyncio
    async def test_returns_llm_text_on_success(self):
        from app.agents.chat.answer import _rewrite_transition_with_llm

        mock_events = [
            {"type": "chunk", "content": "你刚才提到了 Redis 做缓存，"},
            {"type": "chunk", "content": "那 MySQL 的索引原理你了解吗？"},
        ]

        async def mock_stream(*args, **kwargs):
            for e in mock_events:
                yield e

        with patch("app.agents.chat.answer.llm_service") as mock_llm:
            mock_llm.stream_llm_messages = mock_stream
            result = await _rewrite_transition_with_llm(
                "MySQL 索引原理",
                "我用 Redis 做缓存，TTL 设了 300 秒。",
            )

        assert result is not None
        assert "Redis" in result
        assert "MySQL" in result or "索引" in result

    @pytest.mark.asyncio
    async def test_returns_none_on_llm_failure(self):
        from app.agents.chat.answer import _rewrite_transition_with_llm

        async def mock_stream(*args, **kwargs):
            raise RuntimeError("LLM API error")
            yield  # make it a generator

        with patch("app.agents.chat.answer.llm_service") as mock_llm:
            mock_llm.stream_llm_messages = mock_stream
            result = await _rewrite_transition_with_llm(
                "MySQL 索引原理",
                "我用 Redis 做缓存。",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_llm_outputs_mechanical_prefix(self):
        """If LLM still outputs mechanical prefix despite instructions, reject it."""
        from app.agents.chat.answer import _rewrite_transition_with_llm

        async def mock_stream(*args, **kwargs):
            yield {"type": "chunk", "content": "换个具体点的问题：MySQL 索引原理"}

        with patch("app.agents.chat.answer.llm_service") as mock_llm:
            mock_llm.stream_llm_messages = mock_stream
            result = await _rewrite_transition_with_llm(
                "MySQL 索引原理",
                "我用 Redis 做缓存。",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_for_empty_question(self):
        from app.agents.chat.answer import _rewrite_transition_with_llm

        result = await _rewrite_transition_with_llm("", "我用 Redis 做缓存。")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_llm_returns_empty(self):
        from app.agents.chat.answer import _rewrite_transition_with_llm

        async def mock_stream(*args, **kwargs):
            yield {"type": "chunk", "content": ""}

        with patch("app.agents.chat.answer.llm_service") as mock_llm:
            mock_llm.stream_llm_messages = mock_stream
            result = await _rewrite_transition_with_llm(
                "MySQL 索引原理",
                "我用 Redis 做缓存。",
            )

        assert result is None
