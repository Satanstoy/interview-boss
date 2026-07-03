"""Interview decision thresholds — frozen, configurable, per-conversation overridable.

All interview rhythm thresholds (message counts, overlap coefficients,
repetition counts) are centralized here.  Default values match the previous
hardcoded constants exactly, so zero behavior change for existing deployments.

Per-conversation overrides via ``interview_config.decision_config`` in DB
metadata are supported — see ``get_decision_config()``.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DecisionConfig:
    """Immutable container for all interview decision thresholds.

    Field names match the original source locations for easy cross-reference.
    """

    # ── stop_policy.py ──────────────────────────────────────────────────────
    soft_close_message_count: int = 32
    """Coverage complete → ask candidate reverse question."""

    strong_close_message_count: int = 44
    """Strong close — only fill last gap or HR/反问/收尾."""

    hard_stop_message_count: int = 56
    """Hard stop — force summary regardless of coverage."""

    candidate_repeat_degraded: int = 3
    """Consecutive similar user answers → ask candidate question (degraded)."""

    candidate_repeat_close: int = 5
    """Consecutive similar user answers → force close interview."""

    # ── question_plan.py — repetition thresholds ────────────────────────────
    max_consecutive_same_question: int = 2
    """Max consecutive similar interviewer questions before hard constraint."""

    question_overlap_threshold: float = 0.15
    """Token overlap coefficient for detecting similar interviewer questions."""

    answer_overlap_threshold: float = 0.5
    """Token overlap coefficient for detecting similar user answers."""

    topic_overlap_threshold: float = 0.45
    """Token overlap coefficient for detecting repeated topics in candidates."""

    # ── question_plan.py — phase coverage minimums ──────────────────────────
    min_project_followup: int = 2
    min_knowledge_probe: int = 1
    min_algorithm_coding: int = 1
    algorithm_after_asked_count: int = 3
    min_system_design: int = 1
    system_design_after_asked_count: int = 5
    min_behavioral: int = 1
    behavioral_after_asked_count: int = 6
    behavioral_after_message_count: int = 14

    # ── nodes.py — phase determination thresholds ───────────────────────────
    phase_opening_max: int = 2
    phase_active_max: int = 32
    phase_soft_close_max: int = 44
    phase_strong_close_max: int = 56

    # ── answer.py — dedup parameters ────────────────────────────────────────
    dedup_window_size: int = 8
    dedup_jaccard_threshold: float = 0.7
    transition_min_length: int = 5
    """Min text length to consider transition rewrite valid."""


def get_decision_config(interview_config: dict | None = None) -> DecisionConfig:
    """Build a ``DecisionConfig`` from per-conversation interview_config.

    Unknown keys in ``interview_config.get("decision_config")`` are silently
    ignored, so callers don't need to know the full schema.
    """
    overrides = (interview_config or {}).get("decision_config") or {}
    if not overrides:
        return DecisionConfig()

    # Only pass known fields to the constructor
    known_fields = {f.name for f in DecisionConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in overrides.items() if k in known_fields}
    return DecisionConfig(**filtered)
