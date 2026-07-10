"""Tests for semantic_question_adherence validator."""

import pytest

from app.agents.chat.validators.semantic_question_adherence import (
    validate_question_adherence,
    _extract_detected_question,
)


class TestExtractDetectedQuestion:
    def test_extracts_question_from_text(self):
        text = "你在那个项目里有实际用过 Agent 范式吗？"
        result = _extract_detected_question(text)
        assert "Agent" in result or "项目" in result

    def test_returns_full_text_if_no_question_mark(self):
        text = "请介绍一下你的项目经验"
        result = _extract_detected_question(text)
        assert len(result) > 0


class TestValidateQuestionAdherence:
    @pytest.mark.asyncio
    async def test_pass_when_semantic_match(self):
        """生成的问题与 selected_question 语义一致时应通过。"""

        async def mock_llm(messages):
            return '{"passes": true, "score": 0.91, "reason": "最终问题询问候选人是否在项目中使用过 Agent 范式，与计划题语义一致。", "detected_question": "你在那个项目里有实际用过 Agent 范式吗？", "issues": []}'

        result = await validate_question_adherence(
            generated_text="你在那个项目里有实际用过 Agent 范式吗？",
            selected_question={
                "id": 6370,
                "question": "Agent范式在项目中有没有用过？",
            },
            llm_call=mock_llm,
        )
        assert result["passes"] is True
        assert result["score"] >= 0.75

    @pytest.mark.asyncio
    async def test_fail_when_topic_drift(self):
        """生成的问题偏离 selected_question 时应失败。"""

        async def mock_llm(messages):
            return '{"passes": false, "score": 0.38, "reason": "最终问题转向工具调用稳定性，没有询问是否实际使用过 Agent 范式。", "detected_question": "你们怎么保证工具调用稳定？", "issues": ["topic_drift"]}'

        result = await validate_question_adherence(
            generated_text="你们怎么保证工具调用稳定？",
            selected_question={
                "id": 6370,
                "question": "Agent范式在项目中有没有用过？",
            },
            llm_call=mock_llm,
        )
        assert result["passes"] is False
        assert result["score"] < 0.75
        assert "topic_drift" in result.get("issues", [])

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self):
        """LLM 调用失败时应返回 error。"""

        async def mock_llm(messages):
            raise Exception("LLM timeout")

        result = await validate_question_adherence(
            generated_text="test",
            selected_question={"id": 1, "question": "test"},
            llm_call=mock_llm,
        )
        assert result["passes"] is False
        assert "llm_call_error" in result.get("issues", [])

    @pytest.mark.asyncio
    async def test_handles_invalid_json(self):
        """LLM 返回无效 JSON 时应返回 error。"""

        async def mock_llm(messages):
            return "I cannot generate JSON"

        result = await validate_question_adherence(
            generated_text="test",
            selected_question={"id": 1, "question": "test"},
            llm_call=mock_llm,
        )
        assert result["passes"] is False

    @pytest.mark.asyncio
    async def test_threshold_boundary(self):
        """score 刚好 0.75 时应通过。"""

        async def mock_llm(messages):
            return '{"passes": true, "score": 0.75, "reason": "边界情况", "detected_question": "test?", "issues": []}'

        result = await validate_question_adherence(
            generated_text="test?",
            selected_question={"id": 1, "question": "test"},
            llm_call=mock_llm,
        )
        assert result["passes"] is True

    @pytest.mark.asyncio
    async def test_score_below_threshold_fails(self):
        """score 低于 0.75 时应失败。"""

        async def mock_llm(messages):
            return '{"passes": true, "score": 0.74, "reason": "接近但不够", "detected_question": "test?", "issues": []}'

        result = await validate_question_adherence(
            generated_text="test?",
            selected_question={"id": 1, "question": "test"},
            llm_call=mock_llm,
        )
        assert result["passes"] is False
