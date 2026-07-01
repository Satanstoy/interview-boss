import json
from dataclasses import asdict

from app.agents.chat.interview_state import (
    InterviewStateSnapshot,
    _determine_current_phase,
    _determine_next_focus,
    build_interview_state_snapshot,
)
from app.agents.chat.question_plan import InterviewLedger
from app.agents.chat.nodes import _format_interview_state_prompt


def test_build_interview_state_snapshot_from_ledger():
    state = {
        "conversation_id": "test-123",
        "job_position": "agent_llm",
        "difficulty": "mid",
        "message_history": [{"role": "user", "content": "test"}],
    }
    ledger = InterviewLedger()
    ledger.record_question(
        {"id": 1, "question": "请介绍一下你的项目经历"},
        question_type="project_followup",
    )
    ledger.record_question(
        {"id": 2, "question": "Redis 持久化机制有哪些？"},
        question_type="knowledge_probe",
    )

    snapshot = build_interview_state_snapshot(state, ledger)

    assert snapshot["conversation_id"] == "test-123"
    assert snapshot["job_position"] == "agent_llm"
    assert snapshot["difficulty"] == "mid"
    assert snapshot["turn_count"] == 1
    assert snapshot["coverage"]["project_followup"]["current_count"] == 1
    assert snapshot["coverage"]["knowledge_probe"]["current_count"] == 1


def test_determine_current_phase_prefers_first_uncovered_phase():
    coverage = {
        "project_followup": {
            "current_count": 2,
            "threshold": 5,
            "is_covered": False,
        },
        "knowledge_probe": {
            "current_count": 3,
            "threshold": 3,
            "is_covered": True,
        },
    }

    assert _determine_current_phase(coverage) == "project_followup"


def test_determine_current_phase_returns_most_recent_count_when_all_covered():
    coverage = {
        "project_followup": {
            "current_count": 5,
            "threshold": 5,
            "is_covered": True,
        },
        "knowledge_probe": {
            "current_count": 3,
            "threshold": 3,
            "is_covered": True,
        },
    }

    assert _determine_current_phase(coverage) == "project_followup"


def test_determine_next_focus_skips_current_phase():
    coverage = {
        "project_followup": {
            "current_count": 2,
            "threshold": 5,
            "is_covered": False,
        },
        "knowledge_probe": {
            "current_count": 1,
            "threshold": 3,
            "is_covered": False,
        },
        "algorithm_coding": {
            "current_count": 0,
            "threshold": 1,
            "is_covered": False,
        },
    }

    assert _determine_next_focus(coverage, "project_followup") == "knowledge_probe"


def test_determine_next_focus_returns_none_when_all_covered():
    coverage = {
        "project_followup": {
            "current_count": 5,
            "threshold": 5,
            "is_covered": True,
        },
        "knowledge_probe": {
            "current_count": 3,
            "threshold": 3,
            "is_covered": True,
        },
    }

    assert _determine_next_focus(coverage, "project_followup") is None


def test_interview_state_snapshot_json_serializable():
    snapshot = InterviewStateSnapshot(
        conversation_id="test-123",
        job_position="agent_llm",
        difficulty="mid",
        current_phase="project_followup",
        next_focus="knowledge_probe",
        turn_count=5,
        coverage={
            "project_followup": {
                "current_count": 2,
                "threshold": 5,
                "is_covered": False,
            },
        },
        last_answer_evaluation=None,
        recent_decisions=[],
        rhythm_profile={},
        generated_at=1234567890.0,
    )

    json_str = json.dumps(asdict(snapshot))

    assert "test-123" in json_str


def test_format_interview_state_prompt_includes_snapshot_focus():
    state = {
        "interview_state": {
            "current_phase": "project_followup",
            "next_focus": "knowledge_probe",
            "coverage": {
                "project_followup": {
                    "current_count": 2,
                    "threshold": 5,
                    "is_covered": False,
                }
            },
        }
    }

    prompt = _format_interview_state_prompt(state)

    assert "<interview_state>" in prompt
    assert "current_phase: project_followup" in prompt
    assert "next_focus: knowledge_probe" in prompt
    assert "project_followup=2/5" in prompt
