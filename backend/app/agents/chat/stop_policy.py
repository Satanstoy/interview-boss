"""Interview stop-policy decisions.

This module keeps product-level wrap-up decisions out of prompt prose.  The
LLM can still choose natural wording, but the backend owns the stop gates.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("interview-boss")

from app.agents.chat.chat_constants import (
    CANDIDATE_QUESTION_MARKER,
    CANDIDATE_QUESTION_PROMPT,
)
from app.agents.chat.coverage_config import (
    InterviewPhase,
    get_coverage_thresholds,
)
from app.agents.chat.decision_config import DecisionConfig
from app.agents.chat.question_plan import (
    _big_tech_phase_counts,
    _build_interview_ledger,
)

_STOP_PHASES = (
    InterviewPhase.PROJECT_FOLLOWUP,
    InterviewPhase.KNOWLEDGE_PROBE,
    InterviewPhase.ALGORITHM_CODING,
    InterviewPhase.SYSTEM_DESIGN,
    InterviewPhase.BEHAVIORAL,
)


def evaluate_interview_stop(state: dict[str, Any]) -> dict[str, Any]:
    """Return the next stop-policy action for the current turn.

    Actions:
    - ``continue``: keep interviewing.
    - ``ask_candidate_question``: coverage is complete; ask the candidate's
      reverse-question prompt before final closing.
    - ``close``: generate the final structured summary.

    The primary signal is ``state["closing_stage"]`` (persisted across turns).
    Text-based heuristics are only used as fallback for legacy sessions.
    """

    config = state.get("decision_config") or DecisionConfig()
    message_count = len(state.get("message_history") or [])
    closing_stage = state.get("closing_stage", "technical")
    logger.info(
        "Stop policy evaluate: closing_stage=%s message_count=%s counter_question=%s",
        closing_stage,
        message_count,
        state.get("counter_question"),
    )
    coverage = _coverage_status(state)
    missing_phases = [
        phase
        for phase, data in coverage.items()
        if int(data["threshold"]) > 0 and not data["is_covered"]
    ]
    all_covered = not missing_phases

    base = {
        "message_count": message_count,
        "coverage": coverage,
        "missing_phases": missing_phases,
        "closing_stage": closing_stage,
    }

    # ── closing_stage state machine (primary path) ──

    # If we already asked the candidate question, this turn should close.
    if closing_stage == "candidate_question_asked":
        # But if candidate asks a counter question, let them answer first.
        if state.get("counter_question"):
            return {
                **base,
                "action": "continue",
                "mode": "wrap_up",
                "reason": "counter_question_during_closing",
            }
        return {
            **base,
            "action": "close",
            "mode": "wrap_up",
            "reason": "candidate_question_already_asked",
        }

    # If we're in final_summary, force close.
    if closing_stage == "final_summary":
        return {
            **base,
            "action": "close",
            "mode": "wrap_up",
            "reason": "closing_stage_final_summary",
        }

    # If already closed, keep closed (shouldn't normally reach here).
    if closing_stage == "closed":
        return {
            **base,
            "action": "close",
            "mode": "wrap_up",
            "reason": "already_closed",
        }

    # ── Legacy/fallback path for sessions without closing_stage ──

    # Candidate repetition detection — hard guard before any other logic.
    user_repeat_count = state.get("repetition_streak", 0)
    if user_repeat_count >= config.candidate_repeat_close:
        return {
            **base,
            "action": "close",
            "mode": "forced_by_repetition",
            "reason": "candidate_repeated_answers_excessive",
        }
    if (
        user_repeat_count >= config.candidate_repeat_degraded
        and not _last_assistant_asked_candidate_question(state)
    ):
        return {
            **base,
            "action": "ask_candidate_question",
            "mode": "degraded",
            "reason": "candidate_repeated_answers",
        }

    if message_count > config.hard_stop_message_count:
        return {
            **base,
            "action": "close",
            "mode": "hard_stop",
            "reason": "hard_stop_by_message_count",
        }

    if all_covered and message_count >= config.soft_close_message_count:
        # Use closing_stage if available, else fall back to text detection
        if closing_stage == "candidate_question_answered":
            return {
                **base,
                "action": "close",
                "mode": "wrap_up",
                "reason": "candidate_question_answered",
            }
        if _last_assistant_asked_candidate_question(state):
            return {
                **base,
                "action": "close",
                "mode": "wrap_up",
                "reason": "coverage_complete_after_candidate_question",
            }
        return {
            **base,
            "action": "ask_candidate_question",
            "mode": "wrap_up",
            "reason": "coverage_complete_ready_for_candidate_question",
            "message": CANDIDATE_QUESTION_PROMPT,
        }

    mode = (
        "strong_close"
        if message_count >= config.strong_close_message_count
        else "active"
    )
    return {
        **base,
        "action": "continue",
        "mode": mode,
        "reason": "coverage_incomplete",
    }


def _coverage_status(state: dict[str, Any]) -> dict[str, dict[str, int | bool]]:
    ledger = _build_interview_ledger(state)
    phase_counts = _big_tech_phase_counts(ledger)
    thresholds = get_coverage_thresholds(
        str(state.get("job_position") or "agent_llm"),
        str(state.get("difficulty") or "mid"),
        state.get("rhythm_profile") or {},
    )
    coverage: dict[str, dict[str, int | bool]] = {}
    for phase in _STOP_PHASES:
        current_count = int(phase_counts.get(phase.value, 0))
        threshold = int(thresholds.get(phase, 0))
        coverage[phase.value] = {
            "current_count": current_count,
            "threshold": threshold,
            "is_covered": current_count >= threshold,
        }
    return coverage


def _last_assistant_asked_candidate_question(state: dict[str, Any]) -> bool:
    for msg in reversed(state.get("message_history") or []):
        if not isinstance(msg, dict) or msg.get("role") != "assistant":
            continue
        content = str(msg.get("content") or "")
        return CANDIDATE_QUESTION_MARKER in content
    return False
