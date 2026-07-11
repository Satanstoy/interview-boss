"""TDD coverage for the runtime interview rhythm strategy engine."""

import pytest

from app.agents.chat.turn_contract import (
    TurnContractAction,
    plan_turn,
)
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

    strategy = compute_tool_strategy(_state(turn_intent=intent.to_metadata_dict()))
    assert strategy.requires_retrieval is True
    assert strategy.allow_draw is True
    assert strategy.allow_search is False
    assert strategy.next_phase_hint == "knowledge_probe"


def test_runtime_rhythm_pivots_after_two_persisted_deep_dives():
    """The third project answer must change dimension using durable decisions."""
    state = _state(
        interview_state={
            **_state()["interview_state"],
            "recent_decisions": [
                {"strategy": "deep_dive"},
                {"strategy": "deep_dive"},
            ],
        }
    )

    intent = build_turn_intent(state)

    assert intent.strategy == TurnStrategy.TOPIC_SHIFT
    assert intent.target_dimension == "knowledge_probe"


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

    from app.agents.chat.tool_strategy import compute_tool_strategy

    tool_strategy = compute_tool_strategy(
        _state(
            active_skills=["project-deep-dive"],
            should_retrieve=True,
            turn_intent=intent.to_metadata_dict(),
            interview_state=state["interview_state"],
        )
    )
    assert tool_strategy.requires_retrieval is False
    assert tool_strategy.allow_search is False


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
            "writer_brief": {
                "anchor": "RRF 融合",
                "assessment_goal": "decision_rationale",
            },
        },
        llm_call=llm_call,
    )

    assert result["status"] == "success"
    assert "decision_rationale" in captured[1]["content"]
    assert "RRF 融合" in captured[1]["content"]


# ──────────────────────────────────────────────────────────────────────────
# Invariant: build_turn_intent strategy and plan_turn contract action must
# stay semantically aligned for the same state. Without this guard, future
# edits to either module can silently split pacing (writer_brief says deep
# dive, contract asks a selected question) and no test catches it.
# ──────────────────────────────────────────────────────────────────────────

_STRATEGY_TO_ALLOWED_ACTIONS = {
    TurnStrategy.CLOSE: {TurnContractAction.CLOSE_WITH_SUMMARY},
    TurnStrategy.COUNTER_RESPONSE: {TurnContractAction.ANSWER_COUNTER_QUESTION},
    TurnStrategy.CLARIFICATION: {TurnContractAction.CLARIFY_CANDIDATE_ANSWER},
    TurnStrategy.TOPIC_SHIFT: {
        TurnContractAction.ASK_SELECTED_QUESTION,
        TurnContractAction.CONTINUE_NATURAL_FOLLOWUP,
    },
    TurnStrategy.DEEP_DIVE: {
        TurnContractAction.CONTINUE_NATURAL_FOLLOWUP,
        TurnContractAction.ASK_SELECTED_QUESTION,
    },
}


def _intent_to_planner_state(state: dict) -> dict:
    """Promote turn_intent metadata into the state shape plan_turn reads.

    plan_turn consumes ``state["turn_intent"]`` only for tracing; it reads
    counter evidence from classify_result / counter_question_evidence, and
    requested_end from classify_result. The intent builder already set
    those, so we only need to ensure turn_intent is present as metadata.
    """
    intent = build_turn_intent(state)
    return {**state, "turn_intent": intent.to_metadata_dict()}


@pytest.mark.parametrize(
    "label, overrides",
    [
        (
            "end_interview",
            {"classify_result": {**_state()["classify_result"], "requested_end": True}},
        ),
        (
            "counter_question",
            {
                "classify_result": {
                    **_state()["classify_result"],
                    "counter_question": {"text": "你们团队多大", "topic": "团队规模"},
                }
            },
        ),
        (
            "vague_answer",
            {
                "classify_result": {
                    **_state()["classify_result"],
                    "answer_quality": "vague",
                }
            },
        ),
        (
            "incomplete_answer",
            {
                "classify_result": {
                    **_state()["classify_result"],
                    "answer_quality": "incomplete",
                }
            },
        ),
        ("topic_shift_after_two_deep_dives", {}),
        (
            "project_deep_dive_active",
            {
                "active_skills": ["project-deep-dive"],
                "interview_state": {
                    **_state()["interview_state"],
                    "recent_decisions": [{"strategy": "deep_dive"}],
                },
            },
        ),
        (
            "default_opening",
            {
                "interview_state": {
                    **_state()["interview_state"],
                    "recent_decisions": [],
                }
            },
        ),
    ],
)
def test_turn_intent_strategy_aligns_with_plan_turn_action(label, overrides):
    """For every reachable (intent, contract) pair, the contract action must
    be in the allow-list for the intent's strategy."""
    state = _state(**overrides)
    intent = build_turn_intent(state)
    planner_state = _intent_to_planner_state(state)
    contract = plan_turn(planner_state)

    allowed = _STRATEGY_TO_ALLOWED_ACTIONS[intent.strategy]
    assert contract.action in allowed, (
        f"{label}: intent.strategy={intent.strategy.value} but "
        f"contract.action={contract.action.value}; "
        f"allowed={sorted(a.value for a in allowed)}"
    )


def test_strategy_action_mapping_covers_all_strategies():
    """If a new TurnStrategy is added without updating the invariant map,
    fail loudly here so the alignment test stays meaningful."""
    from app.agents.chat.turn_intent import TurnStrategy as AllStrategies

    missing = set(AllStrategies) - set(_STRATEGY_TO_ALLOWED_ACTIONS)
    assert not missing, (
        f"_STRATEGY_TO_ALLOWED_ACTIONS missing: {sorted(s.value for s in missing)}"
    )
