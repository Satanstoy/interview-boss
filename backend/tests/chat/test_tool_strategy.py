"""Tests for compute_tool_strategy."""

import pytest

from app.agents.chat.tool_policy import ToolPolicy, build_tool_policy
from app.agents.chat.tool_strategy import ToolStrategy, compute_tool_strategy


class TestToolStrategy:
    def test_to_prompt_text_includes_instruction(self):
        strategy = ToolStrategy(instruction="测试指令", requires_retrieval=True)
        text = strategy.to_prompt_text()
        assert "<tool_strategy>" in text
        assert "测试指令" in text
        assert "search_questions" in text or "draw_questions" in text
        assert "不能直接输出自然语言问题" in text

    def test_to_prompt_text_blocks_disallowed_tools(self):
        strategy = ToolStrategy(allow_search=False, allow_draw=False)
        text = strategy.to_prompt_text()
        assert "禁止：search_questions" in text
        assert "禁止：draw_questions" in text


class TestComputeToolStrategy:
    def test_end_interview_blocks_all_tools(self):
        state = {"intent": "end_interview"}
        strategy = compute_tool_strategy(state)
        assert strategy.requires_retrieval is False
        assert strategy.allow_search is False
        assert strategy.allow_draw is False
        assert strategy.allow_load_skill is False

    def test_practice_request_allows_retrieval(self):
        state = {"intent": "practice_request"}
        strategy = compute_tool_strategy(state)
        assert strategy.requires_retrieval is True
        assert strategy.allow_search is True
        assert strategy.allow_draw is True

    def test_practice_request_overrides_default_deep_dive_turn_intent(self):
        state = {
            "intent": "practice_request",
            "turn_intent": {
                "strategy": "deep_dive",
                "tool_intent": {"requires_question_bank": False},
            },
        }

        strategy = compute_tool_strategy(state)

        assert strategy.requires_retrieval is True
        assert strategy.allow_search is True
        assert strategy.allow_draw is True
        assert strategy.allow_load_skill is True

    def test_incomplete_answer_no_retrieval(self):
        state = {
            "intent": "interview_question",
            "answer_quality": "incomplete",
            "should_retrieve": True,
        }
        strategy = compute_tool_strategy(state)
        assert strategy.requires_retrieval is False
        assert strategy.allow_search is False
        assert strategy.allow_draw is False

    def test_off_topic_no_retrieval(self):
        state = {
            "intent": "interview_question",
            "answer_quality": "off_topic",
        }
        strategy = compute_tool_strategy(state)
        assert strategy.requires_retrieval is False

    def test_complete_interview_question_with_should_retrieve(self):
        state = {
            "intent": "interview_question",
            "answer_quality": "complete",
            "should_retrieve": True,
            "retrieved_questions": [],
            "candidate_questions": [],
        }
        strategy = compute_tool_strategy(state)
        assert strategy.requires_retrieval is True
        assert strategy.allow_search is True

    def test_existing_candidates_no_retrieval(self):
        state = {
            "intent": "interview_question",
            "answer_quality": "complete",
            "should_retrieve": True,
            "retrieved_questions": [{"id": 1}],
        }
        strategy = compute_tool_strategy(state)
        assert strategy.requires_retrieval is False

    def test_high_escalation_forces_draw(self):
        state = {
            "intent": "interview_question",
            "answer_quality": "complete",
            "escalation_level": 3,
        }
        strategy = compute_tool_strategy(state)
        assert strategy.requires_retrieval is True
        assert strategy.allow_search is False
        assert strategy.allow_draw is True

    def test_repetition_forces_topic_shift(self):
        state = {
            "intent": "interview_question",
            "answer_quality": "complete",
            "repetition_streak": 2,
        }
        strategy = compute_tool_strategy(state)
        assert strategy.requires_retrieval is True
        assert strategy.allow_draw is True

    def test_algorithm_coding_uses_draw(self):
        state = {
            "intent": "interview_question",
            "answer_quality": "complete",
            "should_retrieve": True,
            "question_type": "algorithm_coding",
        }
        strategy = compute_tool_strategy(state)
        assert strategy.requires_retrieval is True
        assert strategy.allow_search is False
        assert strategy.allow_draw is True
        assert "algorithm_coding" in strategy.instruction

    def test_chat_does_not_retrieve(self):
        state = {"intent": "chat"}
        strategy = compute_tool_strategy(state)
        assert strategy.requires_retrieval is False
        assert strategy.allow_search is False
        assert strategy.allow_draw is False


class TestToolPolicy:
    def test_end_interview_policy_denies_all_tools(self):
        state = {"user_id": 7, "conversation_id": "c1", "intent": "end_interview"}

        policy = build_tool_policy(state)

        assert policy.allowed_tools == frozenset()

    def test_retrieval_policy_allows_draw_but_not_search(self):
        state = {
            "user_id": 7,
            "conversation_id": "c1",
            "intent": "interview_question",
            "requires_bank_question": True,
            "distribution_primary_required": True,
            "distribution_control": {"preferred_type": "knowledge_probe"},
        }

        policy = build_tool_policy(state)

        assert "draw_questions" in policy.allowed_tools
        assert "search_questions" not in policy.allowed_tools

    def test_select_question_is_not_allowed_without_server_candidates(self):
        state = {"user_id": 7, "conversation_id": "c1", "intent": "chat"}

        assert "select_question" not in build_tool_policy(state).allowed_tools

    def test_policy_constructor_is_immutable(self):
        policy = ToolPolicy(
            user_id=7,
            conversation_id="c1",
            bank_mode="public",
            allowed_tools=frozenset({"select_question"}),
            allowed_skills=None,
            policy_version="test",
        )

        with pytest.raises(AttributeError):
            policy.user_id = 8
