"""Tests for state-machine routing functions."""

import pytest

from app.agents.chat.decision_config import DecisionConfig
from app.agents.chat.routing import (
    is_retrieval_allowed,
    route_after_classify,
    should_close_interview,
    should_record_retrieval_gap,
    should_topic_shift,
)


class TestRouteAfterClassify:
    def test_end_interview_routes_to_closing(self):
        assert route_after_classify({"intent": "end_interview"}) == "closing"

    def test_chat_routes_to_direct_response(self):
        assert route_after_classify({"intent": "chat"}) == "direct_response"

    def test_interview_question_routes_to_react_loop(self):
        assert route_after_classify({"intent": "interview_question"}) == "react_loop"

    def test_practice_request_routes_to_react_loop(self):
        assert route_after_classify({"intent": "practice_request"}) == "react_loop"


class TestShouldRecordRetrievalGap:
    def test_true_when_interview_question_complete_and_should_retrieve(self):
        state = {
            "intent": "interview_question",
            "answer_quality": "complete",
            "should_retrieve": True,
            "retrieved_questions": [],
            "candidate_questions": [],
        }
        assert should_record_retrieval_gap(state) is True

    def test_false_when_no_candidates_but_should_retrieve_false(self):
        state = {
            "intent": "interview_question",
            "answer_quality": "complete",
            "should_retrieve": False,
        }
        assert should_record_retrieval_gap(state) is False

    def test_false_when_answer_incomplete(self):
        state = {
            "intent": "interview_question",
            "answer_quality": "incomplete",
            "should_retrieve": True,
        }
        assert should_record_retrieval_gap(state) is False

    def test_false_when_already_has_candidates(self):
        state = {
            "intent": "interview_question",
            "answer_quality": "complete",
            "should_retrieve": True,
            "retrieved_questions": [{"id": 1}],
        }
        assert should_record_retrieval_gap(state) is False


class TestShouldTopicShift:
    def test_true_on_off_topic_streak(self):
        assert should_topic_shift({"off_topic_streak": 3}) is True

    def test_true_on_repetition(self):
        assert should_topic_shift({"repetition_streak": 2}) is True

    def test_true_on_escalation(self):
        assert should_topic_shift({"escalation_level": 3}) is True

    def test_false_when_low(self):
        assert should_topic_shift({"off_topic_streak": 1, "repetition_streak": 0}) is False


class TestShouldCloseInterview:
    def test_hard_stop_by_message_count(self):
        state = {"message_history": [{}] * 60}
        decision = should_close_interview(state)
        assert decision["action"] == "close"
        assert decision["reason"] == "hard_stop_by_message_count"

    def test_close_on_excessive_repetition(self):
        config = DecisionConfig(candidate_repeat_close=3)
        state = {"message_history": [], "repetition_streak": 3}
        decision = should_close_interview(state, config)
        assert decision["action"] == "close"
        assert decision["reason"] == "candidate_repeated_answers_excessive"

    def test_ask_candidate_question_on_moderate_repetition(self):
        config = DecisionConfig(candidate_repeat_degraded=2, candidate_repeat_close=5)
        state = {"message_history": [], "repetition_streak": 2}
        decision = should_close_interview(state, config)
        assert decision["action"] == "ask_candidate_question"
        assert decision["reason"] == "candidate_repeated_answers"

    def test_continue_when_nothing_triggered(self):
        state = {"message_history": [], "repetition_streak": 0}
        decision = should_close_interview(state)
        assert decision["action"] == "continue"


class TestIsRetrievalAllowed:
    def test_true_for_interview_question_complete(self):
        assert is_retrieval_allowed({"intent": "interview_question", "answer_quality": "complete"}) is True

    def test_false_for_chat(self):
        assert is_retrieval_allowed({"intent": "chat"}) is False

    def test_false_for_incomplete_answer(self):
        assert is_retrieval_allowed({"intent": "interview_question", "answer_quality": "incomplete"}) is False
