"""Tests for DecisionConfig — frozen, configurable, per-conversation overridable."""

from __future__ import annotations

import pytest

from app.agents.chat.decision_config import DecisionConfig, get_decision_config


class TestDefaultValues:
    """Default values must match the original hardcoded constants exactly."""

    def test_stop_policy_thresholds(self):
        dc = DecisionConfig()
        assert dc.soft_close_message_count == 32
        assert dc.strong_close_message_count == 44
        assert dc.hard_stop_message_count == 56

    def test_candidate_repetition_thresholds(self):
        dc = DecisionConfig()
        assert dc.candidate_repeat_degraded == 3
        assert dc.candidate_repeat_close == 5

    def test_question_repetition_thresholds(self):
        dc = DecisionConfig()
        assert dc.max_consecutive_same_question == 2
        assert dc.question_overlap_threshold == 0.15
        assert dc.answer_overlap_threshold == 0.5
        assert dc.topic_overlap_threshold == 0.45

    def test_phase_coverage_minimums(self):
        dc = DecisionConfig()
        assert dc.min_project_followup == 2
        assert dc.min_knowledge_probe == 1
        assert dc.min_algorithm_coding == 1
        assert dc.algorithm_after_asked_count == 3
        assert dc.min_system_design == 1
        assert dc.system_design_after_asked_count == 5
        assert dc.min_behavioral == 1
        assert dc.behavioral_after_asked_count == 6
        assert dc.behavioral_after_message_count == 14

    def test_phase_determination_thresholds(self):
        dc = DecisionConfig()
        assert dc.phase_opening_max == 2
        assert dc.phase_active_max == 32
        assert dc.phase_soft_close_max == 44
        assert dc.phase_strong_close_max == 56

    def test_dedup_thresholds(self):
        dc = DecisionConfig()
        assert dc.dedup_window_size == 8
        assert dc.dedup_jaccard_threshold == 0.7
        assert dc.transition_min_length == 5


class TestConfigFromInterviewConfig:
    """Per-conversation overrides via interview_config.decision_config."""

    def test_override_single_field(self):
        ic = {"decision_config": {"soft_close_message_count": 30}}
        dc = get_decision_config(ic)
        assert dc.soft_close_message_count == 30
        assert dc.hard_stop_message_count == 56  # default preserved

    def test_override_multiple_fields(self):
        ic = {
            "decision_config": {
                "candidate_repeat_degraded": 2,
                "candidate_repeat_close": 4,
            }
        }
        dc = get_decision_config(ic)
        assert dc.candidate_repeat_degraded == 2
        assert dc.candidate_repeat_close == 4
        assert dc.soft_close_message_count == 32  # default

    def test_override_float_field(self):
        ic = {"decision_config": {"question_overlap_threshold": 0.2}}
        dc = get_decision_config(ic)
        assert dc.question_overlap_threshold == 0.2

    def test_ignores_unknown_fields(self):
        ic = {"decision_config": {"unknown_field": 999, "another": "bad"}}
        dc = get_decision_config(ic)
        assert dc == DecisionConfig()  # all defaults

    def test_empty_decision_config(self):
        ic = {"decision_config": {}}
        dc = get_decision_config(ic)
        assert dc == DecisionConfig()

    def test_none_interview_config(self):
        dc = get_decision_config(None)
        assert dc == DecisionConfig()

    def test_missing_decision_config_key(self):
        ic = {"other_key": "value"}
        dc = get_decision_config(ic)
        assert dc == DecisionConfig()


class TestImmutability:
    """DecisionConfig must be frozen (immutable)."""

    def test_cannot_modify_field(self):
        dc = DecisionConfig()
        with pytest.raises(AttributeError):
            dc.soft_close_message_count = 99  # type: ignore[misc]

    def test_cannot_add_field(self):
        dc = DecisionConfig()
        with pytest.raises(AttributeError):
            dc.new_field = "bad"  # type: ignore[misc]
