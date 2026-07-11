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


def _scale_stop_thresholds(
    base: DecisionConfig,
    difficulty: str,
) -> DecisionConfig:
    """Scale stop-policy thresholds by interview difficulty.

    Easy interviews are shorter (×0.75), hard interviews are longer (×1.25).
    Only the three message-count thresholds are scaled; repetition and
    coverage minimums stay unchanged.
    """
    import math

    if difficulty == "easy":
        factor = 0.75
    elif difficulty == "hard":
        factor = 1.25
    else:
        return base  # mid or unknown → no change

    return DecisionConfig(
        soft_close_message_count=math.floor(base.soft_close_message_count * factor),
        strong_close_message_count=math.floor(base.strong_close_message_count * factor),
        hard_stop_message_count=math.floor(base.hard_stop_message_count * factor),
        candidate_repeat_degraded=base.candidate_repeat_degraded,
        candidate_repeat_close=base.candidate_repeat_close,
        max_consecutive_same_question=base.max_consecutive_same_question,
        question_overlap_threshold=base.question_overlap_threshold,
        answer_overlap_threshold=base.answer_overlap_threshold,
        topic_overlap_threshold=base.topic_overlap_threshold,
        min_project_followup=base.min_project_followup,
        min_knowledge_probe=base.min_knowledge_probe,
        min_algorithm_coding=base.min_algorithm_coding,
        algorithm_after_asked_count=base.algorithm_after_asked_count,
        min_system_design=base.min_system_design,
        system_design_after_asked_count=base.system_design_after_asked_count,
        min_behavioral=base.min_behavioral,
        behavioral_after_asked_count=base.behavioral_after_asked_count,
        behavioral_after_message_count=base.behavioral_after_message_count,
        phase_opening_max=base.phase_opening_max,
        phase_active_max=base.phase_active_max,
        phase_soft_close_max=base.phase_soft_close_max,
        phase_strong_close_max=base.phase_strong_close_max,
        dedup_window_size=base.dedup_window_size,
        dedup_jaccard_threshold=base.dedup_jaccard_threshold,
        transition_min_length=base.transition_min_length,
    )


def get_decision_config(interview_config: dict | None = None) -> DecisionConfig:
    """Build a ``DecisionConfig`` from per-conversation interview_config.

    Unknown keys in ``interview_config.get("decision_config")`` are silently
    ignored, so callers don't need to know the full schema.

    Stop-policy thresholds are scaled by ``interview_config["difficulty"]``
    (easy ×0.75, hard ×1.25).  Explicit ``decision_config`` overrides take
    precedence over the difficulty-based scaling.
    """
    overrides = (interview_config or {}).get("decision_config") or {}
    difficulty = (interview_config or {}).get("difficulty") or "mid"

    # Start with scaled defaults.
    base = _scale_stop_thresholds(DecisionConfig(), difficulty)

    # Apply explicit overrides on top.
    if overrides:
        known_fields = {f.name for f in DecisionConfig.__dataclass_fields__.values()}
        filtered = {k: v for k, v in overrides.items() if k in known_fields}
        # Merge: explicit overrides replace scaled values.
        return DecisionConfig(**{**base.__dict__, **filtered})

    return base
