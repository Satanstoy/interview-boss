"""Regression tests for the private Agent interview profile and catalog."""

import json

import pytest


def test_private_catalog_is_compiled_and_does_not_expose_source_provenance():
    from app.mcp_server.agent_private_catalog import load_agent_catalog

    catalog = load_agent_catalog()
    assert len(catalog) == 101
    assert any(item["format"] == "code_review" for item in catalog)
    assert any(item["format"] == "protocol_review" for item in catalog)
    assert all("回答示例" not in json.dumps(item, ensure_ascii=False) for item in catalog)
    assert all("source_path" not in item for item in catalog)


def test_private_tools_are_hidden_from_non_agent_tool_schema():
    from app.agents.chat.tools import get_tools_for_state

    names = [tool["function"]["name"] for tool in get_tools_for_state({})]
    assert "search_agent_private_questions" not in names
    assert "draw_agent_private_questions" not in names
    assert "select_agent_private_question" not in names
    assert "agent-interview" not in get_tools_for_state({})[0]["function"]["parameters"]["properties"]["skill_name"]["enum"]


def test_private_tools_are_visible_only_to_internal_agent_profile():
    from app.agents.chat.tools import get_tools_for_state

    state = {"interview_profile": "agent_development"}
    tools = get_tools_for_state(state)
    names = [tool["function"]["name"] for tool in tools]
    assert "search_agent_private_questions" in names
    assert "draw_agent_private_questions" in names
    assert "select_agent_private_question" in names
    assert "agent-interview" in tools[0]["function"]["parameters"]["properties"]["skill_name"]["enum"]


def test_private_profile_is_limited_to_explicit_agent_positions():
    from app.agents.chat.agent_profile import is_agent_development_position

    assert is_agent_development_position("Agent 开发") is True
    assert is_agent_development_position("agent开发 / 大模型应用开发 / 大模型开发") is True
    assert is_agent_development_position("大模型应用开发") is False
    assert is_agent_development_position("后端开发") is False


@pytest.mark.asyncio
async def test_private_search_and_selection_use_server_catalog_only():
    from app.mcp_server import interview_tools

    state = {
        "interview_profile": "agent_development",
        "user_id": 7,
        "intent": "practice_request",
        "question_type": "knowledge_probe",
    }
    result = await interview_tools.search_agent_private_questions_tool(
        {"keywords": ["MCP", "tool calling"]}, state
    )

    assert result["ok"] is True
    assert result["tool"] == "search_agent_private_questions"
    assert result["items"]
    assert all(item["source"] == "agent_internal" for item in result["items"])
    assert all("source_section" not in item for item in result["items"])
    assert state["question_source"] == "agent_internal"

    selected = interview_tools.select_agent_private_question_tool(
        {"candidate_index": 0}, state
    )
    assert selected["ok"] is True
    assert selected["tool"] == "select_agent_private_question"
    assert selected["selected_question"]["source"] == "agent_internal"
    assert state["selected_question"]["id"] >= 900001


@pytest.mark.asyncio
async def test_private_catalog_rejects_external_mcp_and_wrong_profile():
    from app.mcp_server import interview_tools

    external = await interview_tools.search_agent_private_questions_tool(
        {"keywords": ["RAG"]},
        {"interview_profile": "agent_development", "_mcp_external": True},
    )
    assert external["error"]["error_code"] == "PRIVATE_TOOL_UNAVAILABLE"

    wrong_profile = await interview_tools.search_agent_private_questions_tool(
        {"keywords": ["RAG"]},
        {"interview_profile": "backend_development"},
    )
    assert wrong_profile["error"]["error_code"] == "AGENT_PROFILE_REQUIRED"


def test_agent_skill_requires_profile_and_external_mcp_cannot_load_it():
    from app.mcp_server import interview_tools

    wrong_profile = interview_tools.load_skill_tool(
        {"skill_name": "agent-interview"},
        {},
    )
    assert wrong_profile["error"]["error_code"] == "SKILL_NOT_ALLOWED"

    external = interview_tools.load_skill_tool(
        {"skill_name": "agent-interview"},
        {"interview_profile": "agent_development", "_mcp_external": True},
    )
    assert external["error"]["error_code"] == "PRIVATE_SKILL_UNAVAILABLE"


def test_private_metadata_redacts_catalog_references_and_skill_names():
    from app.agents.chat.metadata import _build_react_metadata

    question = {
        "id": 900001,
        "question": "私有 Agent 题干",
        "cat1": "Agent 专项能力",
        "cat2": "agent_orchestration",
        "tags": "agent",
    }
    state = {
        "question_source": "agent_internal",
        "question_source_reason": "private_agent_selection",
        "candidate_questions": [question],
        "retrieved_questions": [question],
        "selected_question": question,
        "next_question_plan": {"must_ask": True, "question_id": 900001, "source": "agent_internal"},
        "question_plan_metadata": {},
        "active_skills": ["agent-interview"],
        "user_id": 1,
    }
    metadata, _ = _build_react_metadata(state, "请你设计一个多智能体系统？")

    serialized = json.dumps(metadata, ensure_ascii=False)
    assert "私有 Agent 题干" not in serialized
    assert "agent-interview" not in serialized
    assert "agent_internal" not in serialized
    assert metadata["should_show_references"] is False
    assert metadata["question_plan"]["question_id"] is None
    assert state.get("candidate_set_id") is None


def test_private_metadata_does_not_persist_candidate_set(monkeypatch):
    from app.agents.chat import metadata as metadata_module
    from app.services import chat_service

    def fail_if_called(**kwargs):
        raise AssertionError("private catalog must not create a public candidate set")

    monkeypatch.setattr(chat_service, "create_candidate_set", fail_if_called)
    question = {
        "id": 900002,
        "question": "私有题",
        "cat1": "Agent 专项能力",
        "cat2": "protocol",
    }
    state = {
        "question_source": "agent_internal",
        "candidate_questions": [question],
        "retrieved_questions": [question],
        "selected_question": question,
        "next_question_plan": {"must_ask": True, "question_id": 900002},
        "question_plan_metadata": {},
        "user_id": 1,
    }

    metadata_module._build_react_metadata(state, "请设计一个 Agent 协议")

    assert state.get("candidate_set_id") is None
