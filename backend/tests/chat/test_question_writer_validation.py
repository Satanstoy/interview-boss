"""Tests for question_writer + semantic validator integration.

When contract.action == "ask_selected_question", the pipeline should:
1. Use question_writer to generate natural question text
2. Validate with semantic_question_adherence
3. Retry once with feedback on failure
4. Raise GenerationError if still failing
"""

import pytest

from app.agents.chat.writers.question_writer import (
    generate_question_with_validation,
    _build_question_writer_prompt,
)


class TestBuildQuestionWriterPrompt:
    def test_includes_selected_question(self):
        prompt = _build_question_writer_prompt(
            selected_question={"id": 100, "question": "Agent范式用过吗？"},
            context_anchor="上一题的回答内容",
            question_type="knowledge_probe",
        )
        assert "Agent范式" in prompt
        assert "knowledge_probe" in prompt

    def test_includes_context_anchor(self):
        prompt = _build_question_writer_prompt(
            selected_question={"id": 1, "question": "test"},
            context_anchor="候选人说了关于项目的经验",
            question_type="project_followup",
        )
        assert "候选人说了关于项目的经验" in prompt


class TestGenerateQuestionWithValidation:
    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        """正常情况：第一次生成就通过验证。"""

        async def mock_llm(messages):
            return "你在项目中有实际用过 Agent 范式吗？能具体说说是怎么落地的？"

        async def mock_validator(*, generated_text, selected_question, llm_call):
            return {
                "passes": True,
                "score": 0.91,
                "reason": "语义一致",
                "detected_question": generated_text,
                "issues": [],
            }

        result = await generate_question_with_validation(
            selected_question={"id": 6370, "question": "Agent范式在项目中有没有用过？"},
            context_anchor="候选人回答了工具调用相关内容",
            question_type="knowledge_probe",
            llm_call=mock_llm,
            validator=mock_validator,
        )
        assert result["status"] == "success"
        assert "Agent" in result["text"]

    @pytest.mark.asyncio
    async def test_retry_on_validation_failure(self):
        """验证失败后应重试一次。"""
        call_count = 0

        async def mock_llm(messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return "你们怎么保证工具调用稳定？"  # 偏离主题
            return "你在项目中有实际用过 Agent 范式吗？"  # 重试后正确

        validation_count = 0

        async def mock_validator(*, generated_text, selected_question, llm_call):
            nonlocal validation_count
            validation_count += 1
            if validation_count == 1:
                return {
                    "passes": False,
                    "score": 0.38,
                    "reason": "话题偏离",
                    "detected_question": generated_text,
                    "issues": ["topic_drift"],
                }
            return {
                "passes": True,
                "score": 0.88,
                "reason": "重试后通过",
                "detected_question": generated_text,
                "issues": [],
            }

        result = await generate_question_with_validation(
            selected_question={"id": 6370, "question": "Agent范式在项目中有没有用过？"},
            context_anchor="test",
            question_type="knowledge_probe",
            llm_call=mock_llm,
            validator=mock_validator,
        )
        assert result["status"] == "success"
        assert call_count == 2  # 重试了一次
        assert validation_count == 2

    @pytest.mark.asyncio
    async def test_generation_error_after_retry_fails(self):
        """重试仍失败时应返回 GenerationError。"""

        async def mock_llm(messages):
            return "你们怎么保证工具调用稳定？"  # 始终偏离

        async def mock_validator(*, generated_text, selected_question, llm_call):
            return {
                "passes": False,
                "score": 0.38,
                "reason": "话题偏离",
                "detected_question": generated_text,
                "issues": ["topic_drift"],
            }

        result = await generate_question_with_validation(
            selected_question={"id": 6370, "question": "Agent范式在项目中有没有用过？"},
            context_anchor="test",
            question_type="knowledge_probe",
            llm_call=mock_llm,
            validator=mock_validator,
        )
        assert result["status"] == "error"
        assert "validation_failed" in result.get("error_code", "")

    @pytest.mark.asyncio
    async def test_llm_failure_returns_error(self):
        """LLM 调用失败时应返回 error。"""

        async def mock_llm(messages):
            raise Exception("LLM timeout")

        async def mock_validator(*, generated_text, selected_question, llm_call):
            return {"passes": True, "score": 1.0, "reason": "", "detected_question": "", "issues": []}

        result = await generate_question_with_validation(
            selected_question={"id": 1, "question": "test"},
            context_anchor="test",
            question_type="knowledge_probe",
            llm_call=mock_llm,
            validator=mock_validator,
        )
        assert result["status"] == "error"

    @pytest.mark.asyncio
    async def test_rejects_mechanical_output(self):
        """机械复述应被拒绝。"""

        async def mock_llm(messages):
            return "好，Agent范式在项目中有没有用过？"

        async def mock_validator(*, generated_text, selected_question, llm_call):
            return {"passes": True, "score": 0.9, "reason": "", "detected_question": "", "issues": []}

        result = await generate_question_with_validation(
            selected_question={"id": 1, "question": "Agent范式在项目中有没有用过？"},
            context_anchor="test",
            question_type="knowledge_probe",
            llm_call=mock_llm,
            validator=mock_validator,
        )
        # 机械复述应被检测并拒绝
        assert result["status"] == "error"
