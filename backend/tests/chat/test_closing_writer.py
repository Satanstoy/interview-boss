"""Tests for closing_writer — 自然收尾语生成。"""

import pytest

from app.agents.chat.writers.closing_writer import (
    generate_closing_utterance,
    _is_bare_goodbye,
    _contains_summary_content,
)


class TestIsBareGoodbye:
    def test_bare_goodbye_patterns(self):
        assert _is_bare_goodbye("今天先到这里，再见！") is True
        assert _is_bare_goodbye("面试结束，感谢参加") is True
        assert _is_bare_goodbye("就到这里吧") is True

    def test_not_bare_goodbye(self):
        assert _is_bare_goodbye("好的，我们今天的面试就到这里。") is False
        assert _is_bare_goodbye("") is False


class TestContainsSummaryContent:
    def test_summary_signals(self):
        assert _contains_summary_content("整体表现不错") is True
        assert _contains_summary_content("综合评分 7/10") is True

    def test_no_summary_content(self):
        assert _contains_summary_content("感谢你的时间") is False
        assert _contains_summary_content("") is False


class TestGenerateClosingUtterance:
    @pytest.mark.asyncio
    async def test_success_returns_natural_text(self):
        async def mock_llm(messages):
            return "好的，今天的面试就到这里。感谢你的时间，后续可以根据面试中暴露的问题继续针对性复盘。祝顺利！"

        result = await generate_closing_utterance(
            closing_reason="coverage_complete",
            recent_context="候选人回答了系统设计题",
            llm_call=mock_llm,
        )
        assert result["status"] == "success"
        assert len(result["text"]) > 10

    @pytest.mark.asyncio
    async def test_rejects_summary_content(self):
        """closing_utterance 不应包含结构化总结。"""

        async def mock_llm(messages):
            return "整体表现不错，综合评分 7/10，建议继续学习。"

        result = await generate_closing_utterance(
            closing_reason="coverage_complete",
            recent_context="test",
            llm_call=mock_llm,
        )
        assert result["status"] == "error"
        assert "summary" in result.get("error_code", "").lower() or "summary" in result.get("message", "").lower()

    @pytest.mark.asyncio
    async def test_rejects_empty_output(self):
        async def mock_llm(messages):
            return ""

        result = await generate_closing_utterance(
            closing_reason="coverage_complete",
            recent_context="test",
            llm_call=mock_llm,
        )
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self):
        async def mock_llm(messages):
            raise Exception("LLM timeout")

        result = await generate_closing_utterance(
            closing_reason="coverage_complete",
            recent_context="test",
            llm_call=mock_llm,
        )
        assert result["status"] == "error"
        assert "LLM" in result.get("message", "")

    @pytest.mark.asyncio
    async def test_closing_reason_in_prompt(self):
        """closing_reason 应该被传入 prompt。"""
        captured_messages = []

        async def mock_llm(messages):
            captured_messages.extend(messages)
            return "好的，感谢你的时间。"

        await generate_closing_utterance(
            closing_reason="hard_stop_by_message_count",
            recent_context="test context",
            llm_call=mock_llm,
        )
        user_content = captured_messages[1]["content"]
        assert "hard_stop_by_message_count" in user_content
