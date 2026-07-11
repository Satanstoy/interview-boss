"""TDD coverage for the runtime interview rhythm strategy engine."""

import pytest

from app.agents.chat.turn_intent import TurnStrategy, build_turn_intent


def _state(**overrides):
    state = {
        "active_skills": [],
        "classify_result": {
            "intent": "interview_question",
            "answer_quality": "complete",
            "needs_new_dimension": False,
            "confidence": 0.9,
            "evidence": "候选人已说明项目架构，但尚未解释技术取舍。",
        },
        "interview_state": {
            "coverage": {
                "project_followup": {
                    "current_count": 3,
                    "threshold": 5,
                    "is_covered": False,
                },
                "knowledge_probe": {
                    "current_count": 0,
                    "threshold": 3,
                    "is_covered": False,
                },
                "algorithm_coding": {
                    "current_count": 0,
                    "threshold": 1,
                    "is_covered": False,
                },
            },
            "current_phase": "project_followup",
            "next_focus": "knowledge_probe",
            "recent_decisions": [
                {"strategy": "deep_dive"},
                {"strategy": "deep_dive"},
                {"strategy": "deep_dive"},
            ],
        },
        "user_message": "我们用 RRF 融合 BM25 和向量召回，再交给 reranker 精排。",
    }
    state.update(overrides)
    return state


def test_runtime_rhythm_applies_without_active_skill_or_load_tool():
    """A fresh session must pivot after the deep-dive limit without ReAct activation."""
    intent = build_turn_intent(_state())

    assert intent.strategy == TurnStrategy.TOPIC_SHIFT
    assert intent.target_dimension == "knowledge_probe"
    assert intent.tool_intent.requires_question_bank is True
    assert intent.source_facts["rhythm_policy_applied"] is True

    from app.agents.chat.tool_strategy import compute_tool_strategy

    strategy = compute_tool_strategy(
        _state(turn_intent=intent.to_metadata_dict())
    )
    assert strategy.requires_retrieval is True
    assert strategy.allow_draw is True
    assert strategy.allow_search is False
    assert strategy.next_phase_hint == "knowledge_probe"


def test_project_tactic_keeps_unresolved_tradeoff_in_deep_dive():
    """A missing decision rationale takes precedence over a generic coverage shift."""
    state = _state(
        interview_state={
            **_state()["interview_state"],
            "recent_decisions": [{"strategy": "deep_dive"}],
        },
        active_skills=["project-deep-dive"],
    )

    intent = build_turn_intent(state)

    assert intent.strategy == TurnStrategy.DEEP_DIVE
    assert intent.drill_layer == "decision_rationale"
    assert intent.tool_intent.requires_question_bank is False
    assert intent.writer_brief.assessment_goal == "decision_rationale"


def test_done_metadata_records_executed_turn_intent():
    """The final trace must expose the decision that owned pacing this turn."""
    from app.agents.chat.pipeline import _attach_executed_contract_metadata

    state = {
        "turn_intent": {
            "strategy": "deep_dive",
            "assessment_goal": "decision_rationale",
        }
    }
    metadata = {}

    _attach_executed_contract_metadata(state, metadata)

    assert metadata["turn_intent"]["strategy"] == "deep_dive"


@pytest.mark.asyncio
async def test_followup_writer_receives_turn_intent_brief():
    """The final writer must receive the strategy, not only a generic focus."""
    from app.agents.chat.writers.followup_writer import generate_followup

    captured = []

    async def llm_call(messages):
        captured.extend(messages)
        return "你当时为什么选择 RRF 融合？"

    result = await generate_followup(
        candidate_answer="我们使用 RRF 融合 BM25 和向量检索。",
        next_focus="project_followup",
        recent_context="候选人介绍了 RAG 项目。",
        turn_intent={
            "strategy": "deep_dive",
            "assessment_goal": "decision_rationale",
            "drill_layer": "decision_rationale",
            "writer_brief": {"anchor": "RRF 融合", "assessment_goal": "decision_rationale"},
        },
        llm_call=llm_call,
    )

    assert result["status"] == "success"
    assert "decision_rationale" in captured[1]["content"]
    assert "RRF 融合" in captured[1]["content"]
