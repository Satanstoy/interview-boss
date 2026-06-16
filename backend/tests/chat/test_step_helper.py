"""Tests for the _step() helper with reason and insight fields."""

from unittest.mock import MagicMock
import pytest

from app.agents.chat.pipeline import _step
from app.agents.shared.events import _event_queue_var


class TestStepHelper:
    def test_step_basic_event_format(self):
        """_step() with only step + message produces minimal event."""
        emitted = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            _step("loading", "正在加载对话历史...")
        finally:
            _event_queue_var.reset(token)

        assert len(emitted) == 1
        event = emitted[0]
        assert event["type"] == "step"
        assert event["step"] == "loading"
        assert event["message"] == "正在加载对话历史..."
        assert "reason" not in event
        assert "insight" not in event

    def test_step_with_reason(self):
        """_step() includes reason when provided."""
        emitted = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            _step("loading", "正在加载对话历史...", reason="加载最近20条对话历史")
        finally:
            _event_queue_var.reset(token)

        assert emitted[0]["reason"] == "加载最近20条对话历史"

    def test_step_with_reason_and_insight(self):
        """_step() includes both reason and insight when provided."""
        emitted = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            _step(
                "search_questions",
                "正在检索面试题...",
                reason="从题库检索Redis相关题目",
                insight="从题库检索到关于「Redis」的题目",
            )
        finally:
            _event_queue_var.reset(token)

        event = emitted[0]
        assert event["reason"] == "从题库检索Redis相关题目"
        assert event["insight"] == "从题库检索到关于「Redis」的题目"

    def test_step_empty_reason_not_included(self):
        """_step() omits reason when empty string."""
        emitted = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)
        token = _event_queue_var.set(mock_queue)
        try:
            _step("loading", "正在加载对话历史...", reason="")
        finally:
            _event_queue_var.reset(token)

        assert "reason" not in emitted[0]
