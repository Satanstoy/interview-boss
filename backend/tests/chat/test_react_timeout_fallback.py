"""Regression tests for graceful ReAct budget exhaustion."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.agents.chat import react_loop


@pytest.mark.asyncio
async def test_react_timeout_uses_contract_writer_instead_of_failing_turn(monkeypatch):
    """A slow but valid ReAct pass should still produce a committed answer."""

    state = {
        "conversation_id": "react-timeout-regression",
        "user_id": 1,
        "user_message": "继续追问",
        "model": None,
        "intent": "interview_question",
        "classify_result": {"answer_quality": "complete"},
    }
    executor = AsyncMock(
        return_value={
            "status": "success",
            "text": "请结合刚才的方案，继续说明你如何验证系统稳定性。",
            "writer_trace": {"writer": "followup_writer", "result": "success"},
            "validator_trace": [],
        }
    )

    monkeypatch.setattr(react_loop, "REACT_BUDGET", react_loop.Budget(max_seconds=-1))
    monkeypatch.setattr(
        react_loop,
        "evaluate_interview_stop",
        lambda _state: {"action": "continue"},
    )
    monkeypatch.setattr(
        react_loop,
        "_prepare_distribution_primary_question",
        AsyncMock(return_value=False),
    )
    monkeypatch.setattr(
        react_loop,
        "build_react_prompt_parts",
        lambda _state: {
            "stable_system_prompt": "stable prompt",
            "dynamic_context": "dynamic context",
        },
    )
    monkeypatch.setattr(react_loop.chat_tools, "get_tools_for_state", lambda _state: [])
    monkeypatch.setattr(react_loop, "build_runtime_tool_contract_message", lambda _state: "")
    monkeypatch.setattr(react_loop, "build_prompt_cache_fingerprint", lambda *_args: "cache-key")
    monkeypatch.setattr(
        react_loop,
        "_apply_policy_gate",
        lambda _state, _contract: SimpleNamespace(decision="allow"),
    )
    monkeypatch.setattr(
        "app.agents.chat.contract_executor.execute_turn_contract",
        executor,
    )

    events = [event async for event in react_loop._react_loop(state)]

    assert [event["type"] for event in events] == ["chunk", "done"]
    assert events[0]["content"] == "请结合刚才的方案，继续说明你如何验证系统稳定性。"
    assert "final_answer_error" not in state
    executor.assert_awaited_once()
