"""Tests for answer.py transition rewrite logic.

Covers:
- _rewrite_transition_with_llm: LLM-based natural transition generation
- GenerationError: raised instead of mechanical fallback
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


# ── GenerationError (replaces mechanical fallback) ────────────


class TestGenerationError:
    """Verify GenerationError is available and has expected attributes."""

    def test_generation_error_importable(self):
        from app.agents.chat.answer import GenerationError

        err = GenerationError(code="test_code", message="test message", guard="test")
        assert err.code == "test_code"
        assert err.message == "test message"
        assert err.guard == "test"
        assert str(err) == "test message"


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
