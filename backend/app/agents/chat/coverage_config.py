"""Coverage thresholds for interview phases."""

from __future__ import annotations

from enum import Enum


class InterviewPhase(str, Enum):
    """Interview phase names aligned with chat question types."""

    WARMUP = "warmup"
    PROJECT_FOLLOWUP = "project_followup"
    KNOWLEDGE_PROBE = "knowledge_probe"
    ALGORITHM_CODING = "algorithm_coding"
    SYSTEM_DESIGN = "system_design"
    BEHAVIORAL = "behavioral"
    WRAP_UP = "wrap_up"


DEFAULT_COVERAGE_THRESHOLDS: dict[tuple[str, str], dict[InterviewPhase, int]] = {
    ("agent_llm", "junior"): {
        InterviewPhase.PROJECT_FOLLOWUP: 3,
        InterviewPhase.KNOWLEDGE_PROBE: 3,
        InterviewPhase.ALGORITHM_CODING: 1,
        InterviewPhase.SYSTEM_DESIGN: 0,
        InterviewPhase.BEHAVIORAL: 1,
    },
    ("agent_llm", "mid"): {
        InterviewPhase.PROJECT_FOLLOWUP: 5,
        InterviewPhase.KNOWLEDGE_PROBE: 3,
        InterviewPhase.ALGORITHM_CODING: 1,
        InterviewPhase.SYSTEM_DESIGN: 1,
        InterviewPhase.BEHAVIORAL: 1,
    },
    ("agent_llm", "senior"): {
        InterviewPhase.PROJECT_FOLLOWUP: 6,
        InterviewPhase.KNOWLEDGE_PROBE: 3,
        InterviewPhase.ALGORITHM_CODING: 1,
        InterviewPhase.SYSTEM_DESIGN: 1,
        InterviewPhase.BEHAVIORAL: 1,
    },
    ("agent_llm", "staff_plus"): {
        InterviewPhase.PROJECT_FOLLOWUP: 6,
        InterviewPhase.KNOWLEDGE_PROBE: 2,
        InterviewPhase.ALGORITHM_CODING: 1,
        InterviewPhase.SYSTEM_DESIGN: 2,
        InterviewPhase.BEHAVIORAL: 1,
    },
    ("backend", "mid"): {
        InterviewPhase.PROJECT_FOLLOWUP: 3,
        InterviewPhase.KNOWLEDGE_PROBE: 5,
        InterviewPhase.ALGORITHM_CODING: 2,
        InterviewPhase.SYSTEM_DESIGN: 1,
        InterviewPhase.BEHAVIORAL: 1,
    },
}


def get_coverage_thresholds(
    job_position: str,
    difficulty: str,
    rhythm_profile: dict | None = None,
) -> dict[InterviewPhase, int]:
    """Return coverage thresholds, optionally adjusted by a rhythm profile."""

    key = ((job_position or "agent_llm").strip(), (difficulty or "mid").strip())
    thresholds = DEFAULT_COVERAGE_THRESHOLDS.get(
        key,
        DEFAULT_COVERAGE_THRESHOLDS[("agent_llm", "mid")],
    ).copy()

    if not rhythm_profile or rhythm_profile.get("confidence", 0) < 0.5:
        return thresholds

    distribution = rhythm_profile.get("distribution") or {}
    for phase_name, count in distribution.items():
        try:
            phase = InterviewPhase(phase_name)
        except ValueError:
            continue
        if phase not in thresholds:
            continue
        try:
            count_int = int(count)
        except (TypeError, ValueError):
            continue
        thresholds[phase] = max(1, min(count_int * 2, thresholds[phase] * 2))

    return thresholds
