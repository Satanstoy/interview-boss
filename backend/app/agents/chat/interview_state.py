"""Interview state snapshot management."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any

from app.agents.chat.coverage_config import InterviewPhase, get_coverage_thresholds
from app.agents.chat.question_plan import InterviewLedger, _big_tech_phase_counts

_SNAPSHOT_PHASES = (
    InterviewPhase.PROJECT_FOLLOWUP,
    InterviewPhase.KNOWLEDGE_PROBE,
    InterviewPhase.ALGORITHM_CODING,
    InterviewPhase.SYSTEM_DESIGN,
    InterviewPhase.BEHAVIORAL,
)
_RECENT_DECISION_LIMIT = 6


def _recent_turn_decisions(state: dict[str, Any]) -> list[dict]:
    """Restore durable turn strategies from previous assistant metadata.

    The strategy engine makes one decision per request, while the next request
    receives a newly constructed ChatState.  Assistant metadata is therefore
    the source of truth for pacing history; do not infer this from prose.
    """
    decisions: list[dict] = []
    for message in state.get("message_history") or []:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        metadata = message.get("metadata")
        if not isinstance(metadata, dict):
            continue
        intent = metadata.get("turn_intent")
        if not isinstance(intent, dict) or not isinstance(intent.get("strategy"), str):
            continue
        decisions.append({
            "strategy": intent["strategy"],
            "target_dimension": intent.get("target_dimension"),
            "assessment_goal": intent.get("assessment_goal"),
        })
    return decisions[-_RECENT_DECISION_LIMIT:]


@dataclass
class InterviewStateSnapshot:
    """Serializable interview-state snapshot for assistant metadata."""

    conversation_id: str
    job_position: str
    difficulty: str
    current_phase: str
    next_focus: str | None
    turn_count: int
    coverage: dict[str, dict[str, int | bool]]
    last_answer_evaluation: dict | None
    recent_decisions: list[dict]
    rhythm_profile: dict
    generated_at: float


def build_interview_state_snapshot(
    state: dict[str, Any],
    ledger: InterviewLedger,
    rhythm_profile: dict | None = None,
) -> dict:
    """Build a product-facing snapshot from ChatState and InterviewLedger."""

    conversation_id = str(state.get("conversation_id") or "")
    job_position = str(state.get("job_position") or "agent_llm")
    difficulty = str(state.get("difficulty") or "mid")
    rhythm = rhythm_profile or state.get("rhythm_profile") or {}

    thresholds = get_coverage_thresholds(job_position, difficulty, rhythm)
    phase_counts = _big_tech_phase_counts(ledger)
    coverage: dict[str, dict[str, int | bool]] = {}
    for phase in _SNAPSHOT_PHASES:
        current_count = int(phase_counts.get(phase.value, 0))
        threshold = int(thresholds.get(phase, 0))
        coverage[phase.value] = {
            "current_count": current_count,
            "threshold": threshold,
            "is_covered": current_count >= threshold,
        }

    current_phase = _determine_current_phase(coverage)
    next_focus = _determine_next_focus(coverage, current_phase)
    snapshot = InterviewStateSnapshot(
        conversation_id=conversation_id,
        job_position=job_position,
        difficulty=difficulty,
        current_phase=current_phase,
        next_focus=next_focus,
        turn_count=len(state.get("message_history") or []),
        coverage=coverage,
        last_answer_evaluation=state.get("last_answer_evaluation"),
        recent_decisions=_recent_turn_decisions(state),
        rhythm_profile=dict(rhythm),
        generated_at=time.time(),
    )
    return asdict(snapshot)


def _determine_current_phase(coverage: dict[str, dict]) -> str:
    """Pick the first uncovered phase, falling back to the highest-count phase."""

    for phase in _SNAPSHOT_PHASES:
        if phase.value not in coverage:
            continue
        data = coverage.get(phase.value) or {}
        if not data.get("is_covered", False):
            return phase.value

    if not coverage:
        return InterviewPhase.PROJECT_FOLLOWUP.value
    return max(
        coverage,
        key=lambda phase: int((coverage.get(phase) or {}).get("current_count", 0)),
    )


def _determine_next_focus(
    coverage: dict[str, dict],
    current_phase: str,
) -> str | None:
    """Pick the strongest uncovered phase after the current phase."""

    candidates = [
        (phase, data)
        for phase, data in coverage.items()
        if phase != current_phase and not data.get("is_covered", False)
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: int(item[1].get("threshold", 0))
        - int(item[1].get("current_count", 0)),
    )[0]
