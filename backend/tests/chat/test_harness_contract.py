"""Harness 2.0 core object and deterministic ContextPack contract."""

import pytest


def test_context_pack_has_fixed_three_part_order_and_stable_hash():
    from app.agents.chat.harness_contract import (
        ContextBlock,
        ContextPack,
        build_context_pack,
    )

    stable = ContextBlock(
        block_id="stable-rules",
        block_type="system_rules",
        source="harness",
        content={"rule": "one semantic action"},
        visibility="model",
        sequence=1,
    )
    turn_base = ContextBlock(
        block_id="turn-input",
        block_type="candidate_input",
        source="user",
        content={"text": "我负责过缓存系统"},
        visibility="model",
        sequence=1,
    )
    pack = build_context_pack(
        stable_prefix=[stable],
        turn_base=[turn_base],
        call_suffix=[],
    )

    assert isinstance(pack, ContextPack)
    assert pack.segment_names() == ("stable_prefix", "turn_base", "call_suffix")
    assert pack.stable_prefix_hash == pack.stable_prefix_hash
    assert pack.serialized().index("stable_prefix") < pack.serialized().index("turn_base")
    assert pack.serialized().index("turn_base") < pack.serialized().index("call_suffix")

    appended = pack.append_call_suffix(
        ContextBlock(
            block_id="question-card",
            block_type="question_selection",
            source="question_broker",
            content={"question_ref": "q-1"},
            visibility="model",
            sequence=1,
        )
    )
    assert appended.stable_prefix_hash == pack.stable_prefix_hash
    assert appended.turn_base == pack.turn_base
    assert len(appended.call_suffix) == 1
    assert pack.call_suffix == ()


def test_context_pack_rejects_non_appendable_stable_prefix_content():
    from app.agents.chat.harness_contract import ContextBlock, build_context_pack

    with pytest.raises(ValueError, match="stable prefix"):
        build_context_pack(
            stable_prefix=[
                ContextBlock(
                    block_id="bad",
                    block_type="candidate_input",
                    source="user",
                    content={"text": "dynamic"},
                    visibility="model",
                    sequence=1,
                )
            ],
            turn_base=[],
            call_suffix=[],
        )


def test_harness_contract_exposes_fixed_modes_and_statuses():
    from app.agents.chat.harness_contract import (
        ACTION_STATUSES,
        ATTEMPT_STATUSES,
        CALL_MODES,
        TERMINAL_TURN_STATUSES,
    )

    assert CALL_MODES == (
        "observe_propose",
        "write_response",
        "repair_response",
        "validate_output",
    )
    assert "cancel_requested" in ACTION_STATUSES
    assert "superseded" in ATTEMPT_STATUSES
    assert TERMINAL_TURN_STATUSES == (
        "completed",
        "failed",
        "cancelled",
        "timed_out",
        "budget_exhausted",
    )


def test_agent_result_is_bound_to_harness_selected_call_mode():
    from app.agents.chat.harness_contract import (
        AgentResult,
        normalize_agent_result,
    )

    result = normalize_agent_result(
        expected_call_mode="observe_propose",
        turn_run_id="turn-1",
        action_id="action-1",
        attempt=1,
        raw={
            "payload": {"intent": "answer"},
            "usage": {"input_tokens": 10},
        },
    )

    assert isinstance(result, AgentResult)
    assert result.schema_version == "agent-result-v1"
    assert result.call_mode == "observe_propose"
    assert result.status == "completed"

    with pytest.raises(ValueError, match="call_mode"):
        normalize_agent_result(
            expected_call_mode="observe_propose",
            turn_run_id="turn-1",
            action_id="action-1",
            attempt=1,
            raw={"call_mode": "commit_turn", "payload": {}},
        )


def test_policy_gate_ignores_model_next_mode_and_applies_lifecycle_first():
    from app.agents.chat.harness_contract import evaluate_policy_gate

    decision = evaluate_policy_gate(
        session={"status": "active"},
        ledger={"current_phase": "technical"},
        proposal={"action": "ask_followup", "next_call_mode": "commit_turn"},
        question_broker={"question_card": {"question_ref": "q-1"}},
        budget={"available_tokens": 1000},
    )
    assert decision.decision == "allow"
    assert decision.next_call_mode == "write_response"

    cancelled = evaluate_policy_gate(
        session={"status": "active", "cancel_requested": True},
        ledger={"current_phase": "technical"},
        proposal={"action": "ask_followup"},
        question_broker={},
        budget={"available_tokens": 1000},
    )
    assert cancelled.decision == "deny"
    assert cancelled.reason_code == "TURN_CANCEL_REQUESTED"


def test_harness_context_builder_keeps_prefix_fixed_and_appends_call_suffix():
    from app.agents.chat.harness_contract import build_harness_context_pack

    first = build_harness_context_pack(
        state={
            "user_message": "第一轮回答",
            "interview_config": {"difficulty": "mid"},
            "interview_state": {"current_phase": "technical"},
            "recent_messages": [{"role": "user", "content": "第一轮回答"}],
            "budget_snapshot": {"available_tokens": 1000},
        },
        call_mode="observe_propose",
        action_id="action-1",
        call_suffix={"proposal": {"action": "ask_followup"}},
    )
    second = build_harness_context_pack(
        state={
            "user_message": "第二轮回答",
            "interview_config": {"difficulty": "senior"},
            "interview_state": {"current_phase": "closing"},
            "recent_messages": [{"role": "user", "content": "第二轮回答"}],
            "budget_snapshot": {"available_tokens": 900},
        },
        call_mode="observe_propose",
        action_id="action-1",
        call_suffix={"proposal": {"action": "finish_interview"}},
    )

    assert first.stable_prefix_hash == second.stable_prefix_hash
    assert first.turn_base != second.turn_base
    assert first.call_suffix[-1].block_type == "action"
