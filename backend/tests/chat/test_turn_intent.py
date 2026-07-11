"""TDD coverage for the runtime interview rhythm strategy engine."""

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
