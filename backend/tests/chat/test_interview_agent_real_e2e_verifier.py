"""Tests for the real interview-agent E2E verifier helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "verify_interview_agent_real_e2e.py"
_SPEC = importlib.util.spec_from_file_location("verify_interview_agent_real_e2e", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
verifier = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = verifier
_SPEC.loader.exec_module(verifier)


def test_main_refuses_without_explicit_opt_in(monkeypatch, capsys):
    """Real interview E2E must not run unless the opt-in env var is set."""
    monkeypatch.delenv("RUN_REAL_INTERVIEW_E2E", raising=False)

    exit_code = verifier.main([])

    captured = capsys.readouterr()
    assert exit_code == 2
    assert "RUN_REAL_INTERVIEW_E2E=1" in captured.err


def test_candidate_profile_prompt_uses_resume_and_ability_without_secret_material():
    """Candidate prompt should be lightweight and derived from profile text only."""
    profile = verifier.CandidateProfile(
        name="施杰",
        resume_text="硕士，做过 RAG 和 Agent 项目。",
        ability_profile="熟悉 FastAPI、LangGraph、向量检索；算法中等。",
        answer_style="回答自然，3-5 句话。",
    )

    prompt = profile.to_system_prompt()

    assert "施杰" in prompt
    assert "RAG 和 Agent" in prompt
    assert "FastAPI" in prompt
    assert "API_KEY" not in prompt
    assert "sk-" not in prompt


def test_extract_turn_result_reads_sse_events_and_flags_markers():
    """Turn extraction should preserve observable backend signals and detect leaks."""
    events = [
        {"type": "step", "step": "search_questions"},
        {"type": "retrieved", "questions": [{"id": 1}, {"id": 2}]},
        {"type": "selected_question", "question": {"id": 2, "question": "RAG 怎么评估？"}},
        {"type": "question_plan", "question_id": 2, "adherence": {"score": 0.8}},
        {"type": "basis", "basis_type": "interview_question", "basis_confidence": 0.72},
        {"type": "chunk", "content": "我们追问一下 RAG 评估。"},
        {"type": "chunk", "content": "[BASIS]{hidden}[/BASIS]"},
        {"type": "done"},
    ]

    result = verifier._extract_turn_result(1, "候选人回答", events)

    assert result.tool_names == ["search_questions"]
    assert result.retrieved_count == 2
    assert result.selected_question_id == 2
    assert result.question_plan_id == 2
    assert result.adherence_score == 0.8
    assert result.basis_type == "interview_question"
    assert result.internal_marker_leaked is True


def test_interview_report_fails_low_quality_transcript():
    """Quality verdict should fail empty, broken, or marker-leaking interviews."""
    turns = [
        verifier.TurnResult(
            index=1,
            candidate_text="你好",
            assistant_text="[BASIS]{hidden}[/BASIS]",
            events=[{"type": "done"}],
            internal_marker_leaked=True,
        ),
        verifier.TurnResult(
            index=2,
            candidate_text="继续",
            assistant_text="",
            events=[{"type": "error", "message": "LLM failed"}],
            errors=["LLM failed"],
        ),
    ]

    report = verifier._build_interview_report(turns, judge_summary=None)

    assert report.verdict == "FAIL"
    assert report.turn_count == 2
    assert report.error_count == 1
    assert report.leak_count == 1
    assert "assistant text" in "; ".join(report.errors)
