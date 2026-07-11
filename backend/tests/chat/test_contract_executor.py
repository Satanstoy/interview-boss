"""Tests for the contract-owned final-output dispatcher."""

import pytest

from app.agents.chat.turn_contract import TurnContract, TurnContractAction


async def _llm_text(_messages):
    return "这是由 contract writer 生成的自然面试官回复。"


async def _validator(**_kwargs):
    return {
        "passes": True,
        "score": 0.93,
        "reason": "语义一致",
        "detected_question": "Agent 范式如何落地？",
        "issues": [],
    }


async def _summary(_state, *, allow_fallback):
    assert allow_fallback is False
    return "**整体表现**：基于本轮事实的总结。"


def _state(**overrides):
    state = {
        "user_id": 1,
        "user_message": "我想问团队如何评估 Agent 效果？",
        "message_history": [
            {"role": "assistant", "content": "请介绍 Agent 项目。"},
            {"role": "user", "content": "我做了工具调用和评测。"},
        ],
        "recent_messages": [],
        "interview_context": "目标岗位：Agent 工程师",
        "selected_question": {"id": 10, "question": "Agent 范式在项目中如何落地？"},
        "question_type": "knowledge_probe",
        "counter_question_topic": "团队如何评估 Agent 效果",
        "interview_state": {"next_focus": "system_design"},
    }
    state.update(overrides)
    return state


@pytest.mark.asyncio
async def test_executor_runs_question_writer_without_react_draft():
    from app.agents.chat.contract_executor import execute_turn_contract

    result = await execute_turn_contract(
        state=_state(),
        contract=TurnContract(
            action=TurnContractAction.ASK_SELECTED_QUESTION,
            priority="coverage_gap",
            payload={"question_id": 10},
            reason="test",
        ),
        llm_call=_llm_text,
        question_validator=_validator,
        summary_generator=_summary,
    )

    assert result["status"] == "success"
    assert result["writer_trace"]["writer"] == "question_writer"
    assert result["validator_trace"][0]["blocking"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "writer"),
    [
        (TurnContractAction.CLARIFY_CANDIDATE_ANSWER, "clarify_writer"),
        (TurnContractAction.ANSWER_COUNTER_QUESTION, "counter_writer"),
        (TurnContractAction.CONTINUE_NATURAL_FOLLOWUP, "followup_writer"),
    ],
)
async def test_executor_uses_the_contract_specific_writer(action, writer):
    from app.agents.chat.contract_executor import execute_turn_contract

    result = await execute_turn_contract(
        state=_state(),
        contract=TurnContract(action=action, priority="test", payload={}, reason="test"),
        llm_call=_llm_text,
        question_validator=_validator,
        summary_generator=_summary,
    )

    assert result["status"] == "success"
    assert result["text"] == "这是由 contract writer 生成的自然面试官回复。"
    assert result["writer_trace"]["writer"] == writer


@pytest.mark.asyncio
async def test_executor_closes_with_natural_text_then_structured_summary():
    from app.agents.chat.contract_executor import execute_turn_contract

    result = await execute_turn_contract(
        state=_state(),
        contract=TurnContract(
            action=TurnContractAction.CLOSE_WITH_SUMMARY,
            priority="explicit_end_request",
            payload={"closing_reason": "explicit_end_request"},
            reason="test",
        ),
        llm_call=_llm_text,
        question_validator=_validator,
        summary_generator=_summary,
    )

    assert result["status"] == "success"
    assert result["text"] == "这是由 contract writer 生成的自然面试官回复。\n\n**整体表现**：基于本轮事实的总结。"
    assert result["writer_trace"]["writer"] == "closing_writer"
    assert result["writer_trace"]["summary_writer"] == "success"


@pytest.mark.asyncio
async def test_executor_records_closing_guard_in_validator_trace():
    """The close contract must expose the closing writer's summary guard."""
    from app.agents.chat.contract_executor import execute_turn_contract

    result = await execute_turn_contract(
        state=_state(),
        contract=TurnContract(
            action=TurnContractAction.CLOSE_WITH_SUMMARY,
            priority="explicit_end_request",
            payload={"closing_reason": "explicit_end_request"},
            reason="test",
        ),
        llm_call=_llm_text,
        question_validator=_validator,
        summary_generator=_summary,
    )

    assert result["status"] == "success"
    assert {
        "name": "no_unrequested_summary",
        "blocking": True,
        "passes": True,
    } in result["validator_trace"]


@pytest.mark.asyncio
async def test_executor_blocks_internal_react_marker_from_counter_writer():
    from app.agents.chat.contract_executor import execute_turn_contract

    async def leaked_marker(_messages):
        return "Action: search_questions({\"query\": \"Redis\"})"

    result = await execute_turn_contract(
        state=_state(),
        contract=TurnContract(
            action=TurnContractAction.ANSWER_COUNTER_QUESTION,
            priority="counter_question",
            payload={},
            reason="test",
        ),
        llm_call=leaked_marker,
        question_validator=_validator,
        summary_generator=_summary,
    )

    assert result["status"] == "error"
    assert result["error_code"] == "contract_output_validation_failed"
    assert result["validator_trace"][0]["name"] == "non_empty"
    assert result["validator_trace"][1] == {
        "name": "no_internal_marker",
        "blocking": True,
        "passes": False,
        "issue": "search_questions",
    }
