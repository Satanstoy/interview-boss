"""Tests for turn_planner — unified deterministic planner.

TurnPlanner consumes semantic classification and stop-policy facts in a single
deterministic policy that outputs TurnContract.
"""

import pytest

from app.agents.chat.turn_contract import TurnContractAction, plan_turn


class TestTurnPlannerIntegration:
    """Integration tests verifying turn_planner produces correct contracts
    for all 5 action paths."""

    def _make_state(self, **overrides) -> dict:
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
            "message_history": [{"role": "user", "content": "test"}] * 10,
        }
        base.update(overrides)
        return base

    def test_close_with_summary_final_summary(self):
        state = self._make_state(closing_stage="final_summary")
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CLOSE_WITH_SUMMARY
        assert contract.payload.get("closing_reason") is not None

    def test_close_with_summary_candidate_question_answered(self):
        state = self._make_state(closing_stage="candidate_question_answered")
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CLOSE_WITH_SUMMARY

    def test_close_with_summary_closed(self):
        state = self._make_state(closing_stage="closed")
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CLOSE_WITH_SUMMARY

    def test_answer_counter_question(self):
        state = self._make_state(
            counter_question=True,
            counter_question_topic="团队规模",
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.ANSWER_COUNTER_QUESTION
        assert contract.payload.get("counter_question_topic") == "团队规模"

    def test_classifier_counter_question_signal_has_priority(self):
        """Planner must consume the LLM semantic signal, not a regex-derived flag."""
        state = self._make_state(
            classify_result={
                "intent": "interview_question",
                "answer_quality": "complete",
                "asked_counter_question": True,
                "candidate_act": "asked_counter_question",
            },
            selected_question={"id": 100, "question": "不应抢走反问的题"},
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.ANSWER_COUNTER_QUESTION
        assert contract.source_facts["asked_counter_question"] is True

    def test_answer_counter_question_during_closing(self):
        state = self._make_state(
            closing_stage="candidate_question_asked",
            counter_question=True,
            counter_question_topic="技术栈",
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.ANSWER_COUNTER_QUESTION

    def test_clarify_vague_answer(self):
        state = self._make_state(
            classify_result={
                "intent": "interview_question",
                "answer_quality": "vague",
            },
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CLARIFY_CANDIDATE_ANSWER

    def test_clarify_incomplete_answer(self):
        state = self._make_state(
            classify_result={
                "intent": "interview_question",
                "answer_quality": "incomplete",
            },
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CLARIFY_CANDIDATE_ANSWER

    def test_ask_selected_question(self):
        state = self._make_state(
            selected_question={"id": 100, "question": "test question", "selection_confidence": 0.9},
            classify_result={
                "intent": "interview_question",
                "answer_quality": "complete",
                "should_retrieve": True,
                "needs_new_dimension": True,
                "confidence": 0.9,
            },
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.ASK_SELECTED_QUESTION
        assert contract.payload.get("question_id") == 100

    def test_selected_question_without_new_dimension_stays_followup(self):
        """A stale selected question cannot force a topic switch by itself."""
        state = self._make_state(
            selected_question={"id": 100, "question": "stale candidate"},
            classify_result={
                "intent": "interview_question",
                "answer_quality": "complete",
                "needs_new_dimension": False,
                "confidence": 0.95,
            },
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CONTINUE_NATURAL_FOLLOWUP

    def test_low_confidence_selected_question_stays_followup(self):
        """Selection confidence is an explicit planner fact, not decorative metadata."""
        state = self._make_state(
            selected_question={"id": 100, "question": "uncertain candidate"},
            classify_result={
                "intent": "interview_question",
                "answer_quality": "complete",
                "needs_new_dimension": True,
                "confidence": 0.4,
            },
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CONTINUE_NATURAL_FOLLOWUP

    def test_continue_natural_followup(self):
        state = self._make_state()
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CONTINUE_NATURAL_FOLLOWUP

    def test_priority_ordering(self):
        """Verify priority: close > counter > clarify > ask_selected > followup"""
        # close > counter
        state = self._make_state(
            closing_stage="final_summary",
            counter_question=True,
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CLOSE_WITH_SUMMARY

        # counter > clarify
        state = self._make_state(
            counter_question=True,
            classify_result={"answer_quality": "vague"},
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.ANSWER_COUNTER_QUESTION

        # clarify > ask_selected
        state = self._make_state(
            classify_result={"answer_quality": "vague"},
            selected_question={"id": 1, "question": "test"},
        )
        contract = plan_turn(state)
        assert contract.action == TurnContractAction.CLARIFY_CANDIDATE_ANSWER

    def test_contract_has_source_facts(self):
        state = self._make_state(
            selected_question={"id": 100, "question": "test", "selection_confidence": 0.9},
            classify_result={
                "intent": "interview_question",
                "answer_quality": "complete",
                "should_retrieve": True,
                "needs_new_dimension": True,
                "confidence": 0.9,
            },
        )
        contract = plan_turn(state)
        assert "answer_quality" in contract.source_facts
        assert "selected_question_id" in contract.source_facts

    def test_contract_has_validation_rules(self):
        state = self._make_state()
        contract = plan_turn(state)
        assert len(contract.validation) > 0

    def test_ask_selected_question_validation_includes_semantic(self):
        state = self._make_state(
            selected_question={"id": 100, "question": "test", "selection_confidence": 0.9},
            classify_result={
                "intent": "interview_question",
                "answer_quality": "complete",
                "should_retrieve": True,
                "needs_new_dimension": True,
                "confidence": 0.9,
            },
        )
        contract = plan_turn(state)
        assert "semantic_question_adherence" in contract.validation

    def test_close_with_summary_validation(self):
        state = self._make_state(closing_stage="final_summary")
        contract = plan_turn(state)
        assert "non_empty" in contract.validation
        assert "no_unrequested_summary" in contract.validation
