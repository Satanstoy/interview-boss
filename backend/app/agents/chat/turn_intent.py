"""Single-turn interview strategy, independent from ReAct prompt activation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class TurnStrategy(str, Enum):
    DEEP_DIVE = "deep_dive"
    CLARIFICATION = "clarification"
    TOPIC_SHIFT = "topic_shift"
    COUNTER_RESPONSE = "counter_response"
    CLOSE = "close"


@dataclass(frozen=True)
class ToolIntent:
    requires_question_bank: bool = False


@dataclass(frozen=True)
class WriterBrief:
    assessment_goal: str
    anchor: str = ""


@dataclass(frozen=True)
class TurnIntent:
    strategy: TurnStrategy
    assessment_goal: str
    target_dimension: str | None
    drill_layer: str | None
    tool_intent: ToolIntent
    writer_brief: WriterBrief
    source_facts: dict[str, Any] = field(default_factory=dict)
    reason: str = ""

    def to_metadata_dict(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "assessment_goal": self.assessment_goal,
            "target_dimension": self.target_dimension,
            "drill_layer": self.drill_layer,
            "tool_intent": {
                "requires_question_bank": self.tool_intent.requires_question_bank,
            },
            "writer_brief": {
                "assessment_goal": self.writer_brief.assessment_goal,
                "anchor": self.writer_brief.anchor,
            },
            "source_facts": self.source_facts,
            "reason": self.reason,
        }


def _missing_dimension(interview_state: dict[str, Any]) -> str | None:
    coverage = interview_state.get("coverage") or {}
    next_focus = interview_state.get("next_focus")
    if isinstance(next_focus, str) and next_focus:
        return next_focus
    for dimension, values in coverage.items():
        if not isinstance(values, dict):
            continue
        if not values.get("is_covered", False):
            return str(dimension)
    return None


def _consecutive_deep_dives(interview_state: dict[str, Any]) -> int:
    count = 0
    for decision in reversed(interview_state.get("recent_decisions") or []):
        if not isinstance(decision, dict) or decision.get("strategy") != TurnStrategy.DEEP_DIVE.value:
            break
        count += 1
    return count


def build_turn_intent(state: dict[str, Any]) -> TurnIntent:
    """Build the pacing decision from semantic and ledger facts.

    `interview-rhythm` is applied here every turn; it never depends on a
    ReAct `load_skill` call or prompt-injection metadata.
    """
    semantic = state.get("classify_result") or {}
    interview_state = state.get("interview_state") or {}
    active_skills = set(state.get("active_skills") or [])
    answer_quality = semantic.get("answer_quality", "complete")
    source_facts = {
        "rhythm_policy_applied": True,
        "answer_quality": answer_quality,
        "consecutive_deep_dives": _consecutive_deep_dives(interview_state),
    }

    if semantic.get("requested_end") or state.get("intent") == "end_interview":
        return TurnIntent(
            strategy=TurnStrategy.CLOSE,
            assessment_goal="practice_feedback",
            target_dimension=None,
            drill_layer=None,
            tool_intent=ToolIntent(),
            writer_brief=WriterBrief("practice_feedback"),
            source_facts=source_facts,
            reason="candidate_requested_end",
        )

    if semantic.get("asked_counter_question"):
        return TurnIntent(
            strategy=TurnStrategy.COUNTER_RESPONSE,
            assessment_goal="counter_question_grounding",
            target_dimension=None,
            drill_layer=None,
            tool_intent=ToolIntent(),
            writer_brief=WriterBrief("counter_question_grounding"),
            source_facts=source_facts,
            reason="candidate_asked_counter_question",
        )

    if answer_quality in {"vague", "incomplete", "off_topic"} or semantic.get("needs_clarification"):
        return TurnIntent(
            strategy=TurnStrategy.CLARIFICATION,
            assessment_goal="missing_answer_evidence",
            target_dimension=None,
            drill_layer=None,
            tool_intent=ToolIntent(),
            writer_brief=WriterBrief("missing_answer_evidence", str(state.get("user_message") or "")),
            source_facts=source_facts,
            reason="answer_needs_clarification",
        )

    missing_dimension = _missing_dimension(interview_state)
    deep_dives = source_facts["consecutive_deep_dives"]
    if deep_dives >= 2 and missing_dimension:
        source_facts["missing_dimension"] = missing_dimension
        return TurnIntent(
            strategy=TurnStrategy.TOPIC_SHIFT,
            assessment_goal="new_dimension_coverage",
            target_dimension=missing_dimension,
            drill_layer=None,
            tool_intent=ToolIntent(requires_question_bank=True),
            writer_brief=WriterBrief("new_dimension_coverage"),
            source_facts=source_facts,
            reason="interview_rhythm_deep_dive_limit",
        )

    if "project-deep-dive" in active_skills:
        return TurnIntent(
            strategy=TurnStrategy.DEEP_DIVE,
            assessment_goal="decision_rationale",
            target_dimension="project_followup",
            drill_layer="decision_rationale",
            tool_intent=ToolIntent(),
            writer_brief=WriterBrief("decision_rationale", str(state.get("user_message") or "")),
            source_facts=source_facts,
            reason="project_deep_dive_tactic",
        )

    return TurnIntent(
        strategy=TurnStrategy.DEEP_DIVE,
        assessment_goal="project_detail",
        target_dimension="project_followup",
        drill_layer="architecture",
        tool_intent=ToolIntent(),
        writer_brief=WriterBrief("project_detail", str(state.get("user_message") or "")),
        source_facts=source_facts,
        reason="default_interview_rhythm_opening",
    )
