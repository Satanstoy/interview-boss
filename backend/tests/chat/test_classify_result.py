"""Tests for ClassifyResult Pydantic model."""

import pytest

from app.agents.chat.classify_result import ClassifyResult


class TestClassifyResult:
    def test_default_values(self):
        result = ClassifyResult()
        assert result.intent == "interview_question"
        assert result.answer_quality == "complete"
        assert result.should_retrieve is False
        assert result.transition_style == "natural"
        assert result.escalation_level == 0
        assert result.off_topic_streak == 0
        assert result.repetition_streak == 0
        assert result.requires_bank_question is False

    def test_to_state_spreads_into_chat_state(self):
        result = ClassifyResult(
            intent="practice_request",
            answer_quality="complete",
            should_retrieve=True,
            requires_bank_question=True,
        )
        state_update = result.to_state()
        assert state_update["intent"] == "practice_request"
        assert state_update["should_retrieve"] is True
        assert state_update["requires_bank_question"] is True
        # Optional None fields are omitted.
        assert "question_type" not in state_update

    def test_from_dict_parses_valid_json(self):
        data = {
            "intent": "interview_question",
            "answer_quality": "off_topic",
            "should_retrieve": False,
            "transition_style": "pivot",
            "escalation_level": 2,
        }
        result = ClassifyResult.from_dict(data)
        assert result.intent == "interview_question"
        assert result.answer_quality == "off_topic"
        assert result.transition_style == "pivot"
        assert result.escalation_level == 2

    def test_from_dict_returns_default_on_invalid_input(self):
        result = ClassifyResult.from_dict({"intent": "not_a_valid_intent"})
        assert result.intent == "interview_question"  # default

    def test_from_dict_returns_default_on_non_dict(self):
        assert ClassifyResult.from_dict(None).intent == "interview_question"
        assert ClassifyResult.from_dict("invalid").intent == "interview_question"

    def test_escalation_level_clamped(self):
        result = ClassifyResult(escalation_level=10)
        assert result.escalation_level == 3

        result = ClassifyResult(escalation_level=-1)
        assert result.escalation_level == 0

    def test_empty_strings_normalized_to_none(self):
        result = ClassifyResult(transition_style="", question_type="")
        assert result.transition_style is None
        assert result.question_type is None


class TestClassifyResultPhase1Signals:
    """Phase 1: 测试新增的语义信号字段。"""

    def test_default_semantic_signals(self):
        result = ClassifyResult()
        assert result.candidate_act is None
        assert result.asked_counter_question is False
        assert result.asked_for_summary is False
        assert result.requested_end is False
        assert result.needs_clarification is False
        assert result.needs_new_dimension is False
        assert result.suggested_question_type is None
        assert result.confidence == 0.0
        assert result.evidence is None

    def test_semantic_signals_with_values(self):
        result = ClassifyResult(
            candidate_act="answered_question",
            asked_counter_question=False,
            needs_new_dimension=True,
            suggested_question_type="system_design",
            confidence=0.86,
            evidence="候选人完整回答了 Agent 工具调用落地",
        )
        assert result.candidate_act == "answered_question"
        assert result.needs_new_dimension is True
        assert result.suggested_question_type == "system_design"
        assert result.confidence == 0.86
        assert "Agent" in result.evidence

    def test_confidence_clamped(self):
        result = ClassifyResult(confidence=1.5)
        assert result.confidence == 1.0

        result = ClassifyResult(confidence=-0.5)
        assert result.confidence == 0.0

    def test_counter_question_signal(self):
        result = ClassifyResult(
            candidate_act="asked_counter_question",
            counter_question={"text": "团队如何评估 RAG 效果？", "topic": "评估方式"},
        )
        assert result.asked_counter_question is True
        assert result.candidate_act == "asked_counter_question"

    def test_requested_end_signal(self):
        result = ClassifyResult(
            candidate_act="requested_end",
            requested_end=True,
        )
        assert result.requested_end is True

    def test_asked_for_summary_signal(self):
        result = ClassifyResult(
            candidate_act="asked_for_summary",
            asked_for_summary=True,
        )
        assert result.asked_for_summary is True

    def test_to_state_includes_new_fields(self):
        result = ClassifyResult(
            candidate_act="answered_question",
            asked_counter_question=False,
            needs_new_dimension=True,
            confidence=0.9,
        )
        state = result.to_state()
        assert state["candidate_act"] == "answered_question"
        assert state["needs_new_dimension"] is True
        assert state["confidence"] == 0.9

    def test_from_dict_with_new_fields(self):
        data = {
            "intent": "interview_question",
            "answer_quality": "complete",
            "candidate_act": "answered_question",
            "counter_question": {"text": "团队如何评估 RAG 效果？", "topic": "评估方式"},
            "needs_clarification": False,
            "confidence": 0.75,
            "evidence": "test evidence",
        }
        result = ClassifyResult.from_dict(data)
        assert result.candidate_act == "answered_question"
        assert result.asked_counter_question is True
        assert result.confidence == 0.75

    def test_default_method_includes_new_fields(self):
        result = ClassifyResult.default()
        assert result.candidate_act is None
        assert result.asked_counter_question is False
        assert result.needs_clarification is False
        assert result.needs_new_dimension is False
        assert result.confidence == 0.0
