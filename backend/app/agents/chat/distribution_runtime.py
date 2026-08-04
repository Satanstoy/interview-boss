"""Runtime bridge from an immutable distribution plan to one controlled turn."""

from __future__ import annotations

import re
from typing import Any

from app.agents.chat.distribution_controller import decide_next_question_type
from app.agents.chat.distribution_execution import distribution_execution_from_events


_CANONICAL_TYPES = {
    "project_followup",
    "knowledge_probe",
    "algorithm_coding",
    "system_design",
    "behavioral",
}
_NON_PRIMARY_ANSWER_QUALITIES = {"vague", "incomplete", "off_topic", "repeated"}
_MIN_MESSAGES_BEFORE_CONTROLLED_PRIMARY = 4
_EXPLICIT_NEXT_QUESTION_RE = re.compile(
    r"(?:继续|进入|选择|抽取|出).{0,12}(?:下一(?:道)?.{0,8}题|题库.{0,12}题)"
    r"|(?:下一(?:道)?.{0,8}题|题库.{0,12}题).{0,12}(?:继续|出|考察)",
    re.I,
)
_NEGATED_NEXT_QUESTION_RE = re.compile(
    r"(?:不要|不想|不用|不必|不再|不|别|无需)\s*(?:再\s*)?(?:继续|进入|选择|抽取|出)"
    r"\s*(?:下一(?:道)?.{0,8}题|题库.{0,12}题)",
    re.I,
)


def distribution_events_from_history(state: dict[str, Any], plan_id: str) -> list[dict]:
    """Read append-only distribution events belonging to *plan_id*."""

    conversation_id = state.get("conversation_id")
    if conversation_id:
        try:
            from app.services import chat_service

            return [
                event
                for event in chat_service.get_distribution_events(conversation_id)
                if isinstance(event, dict) and event.get("plan_id") == plan_id
            ]
        except Exception:
            # Conversation context may be synthetic in unit tests or unavailable
            # during a transient persistence failure; retain the in-memory facts.
            pass
    events: list[dict] = []
    for message in state.get("message_history") or []:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        metadata = message.get("metadata") or {}
        for event in metadata.get("coverage_events") or []:
            if isinstance(event, dict) and event.get("plan_id") == plan_id:
                events.append(event)
    return events


def _is_primary_turn_eligible(state: dict[str, Any]) -> bool:
    """Keep opening, clarification, explicit exit, and counter answers natural."""

    if len(state.get("message_history") or []) < _MIN_MESSAGES_BEFORE_CONTROLLED_PRIMARY:
        return False
    semantic = state.get("classify_result") or {}
    if state.get("intent") == "end_interview" or semantic.get("requested_end"):
        return False
    if state.get("counter_question") or isinstance(semantic.get("counter_question"), dict):
        return False
    # A direct request for another practice question is not an incomplete
    # answer. It should advance the frozen plan even when the classifier has
    # no candidate-answer evidence to score.
    if state.get("intent") == "practice_request":
        return True
    answer_quality = semantic.get("answer_quality") or state.get("answer_quality") or "complete"
    return answer_quality not in _NON_PRIMARY_ANSWER_QUALITIES and not semantic.get("needs_clarification")


def _has_explicit_next_question_request(state: dict[str, Any]) -> bool:
    """Recognize the candidate's unambiguous request to keep asking questions."""

    user_message = str(state.get("user_message") or "")
    return bool(
        not _NEGATED_NEXT_QUESTION_RE.search(user_message)
        and _EXPLICIT_NEXT_QUESTION_RE.search(user_message)
    )


def distribution_plan_is_incomplete(state: dict[str, Any]) -> bool:
    """Whether a frozen plan still needs a bank-bound primary question."""

    plan = state.get("distribution_plan")
    if not isinstance(plan, dict) or not plan.get("plan_id"):
        return False
    target_question_count = int(plan.get("target_question_count") or 0)
    if target_question_count <= 0:
        return False
    events = distribution_events_from_history(state, str(plan["plan_id"]))
    execution = distribution_execution_from_events(plan, events)
    return execution["actual_primary_count"] < target_question_count


def apply_distribution_control(state: dict[str, Any]) -> dict[str, Any]:
    """Write the controller decision into state when a primary question is due.

    The returned dict is persisted only as turn-local observability.  The
    immutable plan and append-only coverage events remain the source of truth.
    """

    plan = state.get("distribution_plan")
    if not isinstance(plan, dict) or not plan.get("plan_id"):
        state["distribution_primary_required"] = False
        return {"enforce_primary_question": False, "reason": "no_distribution_plan"}

    events = distribution_events_from_history(state, str(plan["plan_id"]))
    execution = distribution_execution_from_events(plan, events)
    control: dict[str, Any] = {
        "plan_id": plan["plan_id"],
        "actual_primary_count": execution["actual_primary_count"],
        "target_question_count": int(plan.get("target_question_count") or 0),
        "enforce_primary_question": False,
        "reason": "plan_complete",
    }
    if execution["actual_primary_count"] >= control["target_question_count"]:
        state["distribution_primary_required"] = False
        state["distribution_control"] = control
        return control
    if _has_explicit_next_question_request(state):
        # The candidate has explicitly requested another question. Do not let
        # false semantic end/counter classifications pre-empt the unfinished
        # plan. This only applies to an unambiguous new-question request.
        state["intent"] = "practice_request"
        semantic = state.setdefault("classify_result", {})
        if isinstance(semantic, dict):
            semantic["requested_end"] = False
            semantic["counter_question"] = None
        state["requested_end"] = False
        state["counter_question"] = False
        state["asked_counter_question"] = False
        state["counter_question_evidence"] = None
        state["counter_question_topic"] = None
    if not _is_primary_turn_eligible(state):
        control["reason"] = "turn_not_eligible_for_primary_question"
        state["distribution_primary_required"] = False
        state["distribution_control"] = control
        return control

    decision = decide_next_question_type(plan, events, {})
    preferred_type = decision.preferred_type
    if preferred_type not in _CANONICAL_TYPES:
        control["reason"] = "no_feasible_question_type"
        control["allowed_types"] = decision.allowed_types
        state["distribution_primary_required"] = False
        state["distribution_control"] = control
        return control

    control.update(
        {
            "enforce_primary_question": True,
            "preferred_type": preferred_type,
            "allowed_types": decision.allowed_types,
            "selection_reason": decision.selection_reason,
            "constraint_exception": decision.constraint_exception,
            "reason": "distribution_plan_target_deficit",
        }
    )
    state["distribution_primary_required"] = True
    state["distribution_control"] = control
    state["strategy_preferred_question_type"] = preferred_type
    state["question_type"] = preferred_type
    state["requires_bank_question"] = True
    state["should_retrieve"] = True
    state["needs_new_dimension"] = True
    state["selection_confidence"] = 1.0
    semantic = state.setdefault("classify_result", {})
    if isinstance(semantic, dict):
        semantic["needs_new_dimension"] = True
        semantic["should_retrieve"] = True
        semantic["confidence"] = max(float(semantic.get("confidence") or 0.0), 0.75)
    return control
