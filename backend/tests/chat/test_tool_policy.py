"""P0 tests for execution-time tool authorization."""

import json
from unittest.mock import AsyncMock, patch


def _tool_call(name: str, arguments: dict) -> dict:
    return {
        "function": {
            "name": name,
            "arguments": json.dumps(arguments, ensure_ascii=False),
        }
    }


def _policy(*allowed_tools: str, allowed_skills=None):
    from app.agents.chat.tool_policy import ToolPolicy

    return ToolPolicy(
        user_id=1,
        conversation_id="conversation-1",
        bank_mode="public",
        allowed_tools=frozenset(allowed_tools),
        allowed_skills=allowed_skills,
    )


async def test_execute_tool_rejects_policy_denied_tool_before_dispatch():
    from app.agents.chat.tools import execute_tool

    state = {"user_id": 1, "conversation_id": "conversation-1"}

    with patch(
        "app.agents.chat.tools._execute_search_questions",
        new_callable=AsyncMock,
    ) as implementation:
        result = await execute_tool(
            _tool_call("search_questions", {"keywords": ["Redis"]}),
            state,
            _policy(),
        )

    parsed = json.loads(result)
    assert parsed["error"]["error_code"] == "TOOL_NOT_ALLOWED"
    implementation.assert_not_awaited()


async def test_live_executor_derives_policy_for_runtime_turn():
    from app.agents.chat.tools import execute_tool

    state = {
        "user_id": 1,
        "conversation_id": "conversation-1",
        "turn_id": "turn-1",
        "intent": "end_interview",
    }

    with patch(
        "app.agents.chat.tools._execute_search_questions",
        new_callable=AsyncMock,
    ) as implementation:
        result = await execute_tool(
            _tool_call("search_questions", {"keywords": ["Redis"]}),
            state,
        )

    parsed = json.loads(result)
    assert parsed["error"]["error_code"] == "TOOL_NOT_ALLOWED"
    implementation.assert_not_awaited()


async def test_executor_rejects_skill_outside_policy_scope():
    from app.agents.chat.tools import execute_tool

    state = {"user_id": 1, "conversation_id": "conversation-1"}
    result = await execute_tool(
        _tool_call("load_skill", {"skill_name": "theory-qa"}),
        state,
        _policy("load_skill", allowed_skills=frozenset({"project-deep-dive"})),
    )

    parsed = json.loads(result)
    assert parsed["error"]["error_code"] == "SKILL_NOT_ALLOWED"


def test_enforce_tool_call_rejects_unknown_arguments_at_shared_boundary():
    from app.agents.chat.tool_policy import ToolPolicyViolation, enforce_tool_call

    state = {"user_id": 1, "conversation_id": "conversation-1"}

    try:
        enforce_tool_call(
            _tool_call(
                "select_question",
                {"candidate_index": 0, "candidates": [{"id": 1}]},
            ),
            state,
            _policy("select_question"),
        )
    except ToolPolicyViolation as exc:
        assert exc.code == "INVALID_TOOL_ARGUMENTS"
    else:
        raise AssertionError("invalid tool arguments were accepted")
