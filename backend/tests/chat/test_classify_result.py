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
