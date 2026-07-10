"""Tests for TurnContract and TurnPlanner."""

import pytest

from app.agents.chat.turn_contract import (
    TurnContract,
    TurnContractAction,
    plan_turn,
)


class TestTurnContractAction:
    def test_all_actions_defined(self):
        assert TurnContractAction.CLOSE_WITH_SUMMARY == "close_with_summary"
        assert TurnContractAction.ANSWER_COUNTER_QUESTION == "answer_counter_question"
        assert TurnContractAction.CLARIFY_CANDIDATE_ANSWER == "clarify_candidate_answer"
        assert TurnContractAction.ASK_SELECTED_QUESTION == "ask_selected_question"
        assert TurnContractAction.CONTINUE_NATURAL_FOLLOWUP == "continue_natural_followup"


class TestTurnContract:
    def test_valid_contract_with_selected_question(self):
        contract = TurnContract(
            action=TurnContractAction.ASK_SELECTED_QUESTION,
            priority="coverage_gap",
            payload={
                "question_id": 6370,
                "question_text": "Agent范式在项目中有没有用过？",
                "source": "draw_questions",
                "expected_focus": ["agent范式", "项目落地经验"],
            },
            validation=["non_empty", "no_internal_marker", "semantic_question_adherence"],
            reason="knowledge_probe gap with high-confidence selected question",
            source_facts={
                "answer_quality": "complete",
                "needs_new_dimension": True,
                "selected_question_id": 6370,
            },
        )
        assert contract.action == TurnContractAction.ASK_SELECTED_QUESTION
        assert contract.priority == "coverage_gap"
        assert contract.payload["question_id"] == 6370
        assert "semantic_question_adherence" in contract.validation

    def test_valid_contract_close_with_summary(self):
        contract = TurnContract(
            action=TurnContractAction.CLOSE_WITH_SUMMARY,
            priority="coverage_complete",
            payload={"closing_reason": "coverage_complete_ready_for_candidate_question"},
            validation=["non_empty", "no_unrequested_summary"],
            reason="coverage complete",
            source_facts={"message_count": 32, "all_covered": True},
        )
        assert contract.action == TurnContractAction.CLOSE_WITH_SUMMARY

    def test_valid_contract_continue_natural_followup(self):
        contract = TurnContract(
            action=TurnContractAction.CONTINUE_NATURAL_FOLLOWUP,
            priority="default",
            payload={},
            validation=["non_empty"],
            reason="answer_quality=complete, continuing",
            source_facts={"answer_quality": "complete"},
        )
        assert contract.action == TurnContractAction.CONTINUE_NATURAL_FOLLOWUP

    def test_contract_to_dict(self):
        contract = TurnContract(
            action=TurnContractAction.ASK_SELECTED_QUESTION,
            priority="coverage_gap",
            payload={"question_id": 123},
            validation=["non_empty"],
            reason="test",
            source_facts={},
        )
        d = contract.to_metadata_dict()
        assert d["action"] == "ask_selected_question"
        assert d["priority"] == "coverage_gap"
        assert d["payload"]["question_id"] == 123

    def test_contract_from_dict(self):
        data = {
            "action": "ask_selected_question",
            "priority": "coverage_gap",
            "payload": {"question_id": 456},
            "validation": ["non_empty"],
            "reason": "test",
            "source_facts": {},
        }
        contract = TurnContract.from_dict(data)
        assert contract.action == TurnContractAction.ASK_SELECTED_QUESTION
        assert contract.payload["question_id"] == 456

    def test_contract_from_dict_invalid_action_defaults_to_followup(self):
        data = {
            "action": "invalid_action",
            "priority": "default",
            "payload": {},
            "validation": [],
            "reason": "test",
            "source_facts": {},
        }
        contract = TurnContract.from_dict(data)
        assert contract.action == TurnContractAction.CONTINUE_NATURAL_FOLLOWUP

    def test_contract_from_dict_non_dict_returns_followup(self):
        contract = TurnContract.from_dict(None)
        assert contract.action == TurnContractAction.CONTINUE_NATURAL_FOLLOWUP

        contract = TurnContract.from_dict("invalid")
        assert contract.action == TurnContractAction.CONTINUE_NATURAL_FOLLOWUP


class TestPlanTurn:
    """Test the deterministic TurnPlanner priority logic."""

    def _make_state(self, **overrides) -> dict:
        """Create a minimal state dict for testing."""
        base = {
            "classify_result": {
                "intent": "interview_question",
                "answer_quality": "complete",
                "should_retrieve": False,
            },
            "closing_stage": "technical",
            "counter_question": False,
            "counter_question_topic": None,
            "message_count": 10,
            "selected_question": None,
            "candidate_questions": [],
            "retrieved_questions": [],
            "user_message": "我的回答是这样的...",
            "repetition_streak": 0,
            "decision_config": None,
        }
        base.update(overrides)
        return base

    def test_close_with_summary_when_stop_policy_says_close(self):
        """Priority 1: close_with_summary when stop policy returns close."""
        state = self._make_state(closing_stage="candidate_question_asked")
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CLOSE_WITH_SUMMARY

    def test_close_with_summary_when_final_summary(self):
        state = self._make_state(closing_stage="final_summary")
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CLOSE_WITH_SUMMARY

    def test_answer_counter_question(self):
        """Priority 2: answer_counter_question when candidate asks a question."""
        state = self._make_state(
            counter_question=True,
            counter_question_topic="团队规模",
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.ANSWER_COUNTER_QUESTION
        assert contract.payload.get("counter_question_topic") == "团队规模"

    def test_answer_counter_question_during_closing(self):
        """Counter question during closing should still be answered."""
        state = self._make_state(
            closing_stage="candidate_question_asked",
            counter_question=True,
            counter_question_topic="技术栈",
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.ANSWER_COUNTER_QUESTION

    def test_clarify_when_answer_vague(self):
        """Priority 3: clarify when answer_quality is vague."""
        state = self._make_state(
            classify_result={
                "intent": "interview_question",
                "answer_quality": "vague",
                "should_retrieve": False,
            },
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CLARIFY_CANDIDATE_ANSWER

    def test_clarify_when_answer_incomplete(self):
        state = self._make_state(
            classify_result={
                "intent": "interview_question",
                "answer_quality": "incomplete",
                "should_retrieve": False,
            },
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CLARIFY_CANDIDATE_ANSWER

    def test_ask_selected_question_when_available(self):
        """Priority 4: ask_selected_question when selected question exists."""
        state = self._make_state(
            selected_question={
                "id": 6370,
                "question": "Agent范式在项目中有没有用过？",
            },
            classify_result={
                "intent": "interview_question",
                "answer_quality": "complete",
                "should_retrieve": True,
                "needs_new_dimension": True,
            },
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.ASK_SELECTED_QUESTION
        assert contract.payload.get("question_id") == 6370

    def test_continue_natural_followup_as_default(self):
        """Priority 5: continue_natural_followup as default path."""
        state = self._make_state()
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CONTINUE_NATURAL_FOLLOWUP

    def test_priority_close_over_counter(self):
        """close_with_summary should take priority over counter question."""
        state = self._make_state(
            closing_stage="final_summary",
            counter_question=True,
            counter_question_topic="薪资",
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CLOSE_WITH_SUMMARY

    def test_priority_counter_over_clarify(self):
        """counter question should take priority over clarify."""
        state = self._make_state(
            counter_question=True,
            counter_question_topic="团队",
            classify_result={
                "intent": "interview_question",
                "answer_quality": "vague",
            },
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.ANSWER_COUNTER_QUESTION

    def test_priority_clarify_over_ask_selected(self):
        """clarify should take priority over ask_selected_question."""
        state = self._make_state(
            classify_result={
                "intent": "interview_question",
                "answer_quality": "vague",
            },
            selected_question={"id": 123, "question": "test"},
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CLARIFY_CANDIDATE_ANSWER

    def test_no_selected_question_falls_to_followup(self):
        """Without selected_question, should fall to natural followup."""
        state = self._make_state(
            selected_question=None,
            classify_result={
                "intent": "interview_question",
                "answer_quality": "complete",
                "should_retrieve": False,
            },
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CONTINUE_NATURAL_FOLLOWUP

    def test_contract_source_facts_populated(self):
        """source_facts should contain key decision inputs."""
        state = self._make_state(
            selected_question={"id": 100, "question": "test"},
            classify_result={
                "intent": "interview_question",
                "answer_quality": "complete",
                "should_retrieve": True,
            },
        )
        contract = plan_turn(state)
        assert "answer_quality" in contract.source_facts
        assert "selected_question_id" in contract.source_facts

    def test_contract_validation_list_non_empty(self):
        """Every contract should have at least one validation rule."""
        state = self._make_state()
        contract = plan_turn(state)
        assert len(contract.validation) > 0

    def test_ask_selected_question_includes_validation_rules(self):
        """ask_selected_question should include semantic_question_adherence."""
        state = self._make_state(
            selected_question={"id": 100, "question": "test"},
            classify_result={
                "intent": "interview_question",
                "answer_quality": "complete",
                "should_retrieve": True,
            },
        )
        contract = plan_turn(state)
        assert "semantic_question_adherence" in contract.validation

    def test_close_with_summary_includes_validation_rules(self):
        """close_with_summary should include summary validation."""
        state = self._make_state(closing_stage="final_summary")
        contract = plan_turn(state)
        assert "non_empty" in contract.validation
