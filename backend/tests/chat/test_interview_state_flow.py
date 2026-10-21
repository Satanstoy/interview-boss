def test_full_interview_flow_with_state():
    """Integration test for full interview flow with state management."""
    from app.agents.chat.coverage_config import InterviewPhase, get_coverage_thresholds
    from app.agents.chat.rhythm_profile import classify_question_phase
    from app.agents.chat.interview_state import build_interview_state_snapshot
    from app.agents.chat.question_plan import InterviewLedger

    # Verify all components work together
    thresholds = get_coverage_thresholds("agent_llm", "mid")
    assert InterviewPhase.PROJECT_FOLLOWUP in thresholds

    phase = classify_question_phase("如何设计高可用系统？")
    assert phase == "system_design"

    ledger = InterviewLedger()
    state = {
        "conversation_id": "test",
        "job_position": "agent_llm",
        "difficulty": "mid",
    }
    snapshot = build_interview_state_snapshot(state, ledger)
    assert "current_phase" in snapshot
    assert "coverage" in snapshot
