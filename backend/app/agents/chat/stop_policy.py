"""Interview stop-policy decisions.

This module keeps product-level wrap-up decisions out of prompt prose.  The
LLM can still choose natural wording, but the backend owns the stop gates.
"""

from __future__ import annotations

from typing import Any

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
    """

    config = state.get("decision_config") or DecisionConfig()
    message_count = len(state.get("message_history") or [])
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
    }

    # Candidate repetition detection — hard guard before any other logic.
    # The repetition streak is computed in pipeline._step_classify and written
    # to state; stop policy reads it instead of counting text again.
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
