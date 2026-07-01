from app.agents.chat.coverage_config import (
    DEFAULT_COVERAGE_THRESHOLDS,
    InterviewPhase,
    get_coverage_thresholds,
)


def test_interview_phase_enum_values():
    assert InterviewPhase.WARMUP == "warmup"
    assert InterviewPhase.PROJECT_FOLLOWUP == "project_followup"
    assert InterviewPhase.KNOWLEDGE_PROBE == "knowledge_probe"
    assert InterviewPhase.ALGORITHM_CODING == "algorithm_coding"
    assert InterviewPhase.SYSTEM_DESIGN == "system_design"
    assert InterviewPhase.BEHAVIORAL == "behavioral"
    assert InterviewPhase.WRAP_UP == "wrap_up"


def test_get_coverage_thresholds_known_position_and_difficulty():
    thresholds = get_coverage_thresholds("agent_llm", "mid")

    assert thresholds[InterviewPhase.PROJECT_FOLLOWUP] == 5
    assert thresholds[InterviewPhase.KNOWLEDGE_PROBE] == 3
    assert thresholds[InterviewPhase.ALGORITHM_CODING] == 1


def test_get_coverage_thresholds_unknown_position_falls_back_to_default():
    thresholds = get_coverage_thresholds("unknown_position", "mid")

    assert thresholds == DEFAULT_COVERAGE_THRESHOLDS[("agent_llm", "mid")]


def test_get_coverage_thresholds_adjusts_with_high_confidence_rhythm_profile():
    rhythm_profile = {
        "confidence": 0.8,
        "distribution": {
            "project_followup": 4,
            "knowledge_probe": 2,
        },
    }

    thresholds = get_coverage_thresholds("agent_llm", "mid", rhythm_profile)

    assert thresholds[InterviewPhase.PROJECT_FOLLOWUP] == 8
    assert thresholds[InterviewPhase.KNOWLEDGE_PROBE] == 4


def test_get_coverage_thresholds_ignores_low_confidence_rhythm_profile():
    rhythm_profile = {
        "confidence": 0.3,
        "distribution": {"project_followup": 10},
    }

    thresholds = get_coverage_thresholds("agent_llm", "mid", rhythm_profile)

    assert thresholds == DEFAULT_COVERAGE_THRESHOLDS[("agent_llm", "mid")]
