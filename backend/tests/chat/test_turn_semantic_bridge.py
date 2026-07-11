"""Tests for carrying LLM semantic classification facts into the chat state."""

from unittest.mock import AsyncMock, patch

import pytest

from app.agents.chat.pipeline import _step_classify


@pytest.mark.asyncio
async def test_classifier_semantic_signals_are_available_to_turn_planner():
    state = {
        "user_message": "我想问一下团队怎么评估 Agent 效果？",
        "message_history": [],
        "memory_summaries": [],
        "recent_messages": [],
        "user_id": 1,
    }
    classify_result = {
        "intent": "interview_question",
        "answer_quality": "complete",
        "should_retrieve": False,
        "counter_question": {"text": "团队怎么评估 Agent 效果？", "topic": "团队评估方式"},
        "candidate_act": "asked_counter_question",
        "needs_clarification": False,
        "needs_new_dimension": False,
        "suggested_question_type": None,
        "confidence": 0.91,
        "evidence": "候选人在询问团队的评估方式",
    }

    with patch(
        "app.agents.chat.pipeline.classify_and_recall",
        new=AsyncMock(
            return_value=(
                "interview_question",
                [],
                [],
                "",
                True,
                {},
                classify_result,
            )
        ),
    ):
        await _step_classify(state)

    assert state["asked_counter_question"] is True
    assert state["counter_question"] is True
    assert state["counter_question_evidence"]["text"] == "团队怎么评估 Agent 效果？"
    assert state["candidate_act"] == "asked_counter_question"
    assert state["confidence"] == 0.91
    assert state["classify_result"]["evidence"] == "候选人在询问团队的评估方式"
