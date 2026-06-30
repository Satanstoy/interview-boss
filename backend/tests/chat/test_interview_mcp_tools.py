"""Tests for backend-embedded interview MCP tools."""

import json

import pytest
from unittest.mock import MagicMock


async def _call_mcp_json(tool_name: str, args: dict) -> dict:
    from app.mcp_server.app import mcp

    content = await mcp.call_tool(tool_name, args)

    assert len(content) == 1
    assert content[0].type == "text"
    return json.loads(content[0].text)


def test_load_skill_tool_updates_state_with_registry_getter():
    from app.mcp_server import interview_tools

    skill = MagicMock()
    skill.description = "理论问答策略"
    skill.get_instruction.return_value = "## Theory QA full instruction"
    registry = MagicMock()
    registry.get.return_value = skill

    state = {"active_skills": []}
    result = interview_tools.load_skill_tool(
        {"skill_name": "theory-qa"},
        state,
        registry_getter=lambda: registry,
    )

    assert result["ok"] is True
    assert result["metadata"]["status"] == "loaded"
    assert result["metadata"]["skill"] == "theory-qa"
    assert state["active_skills"] == ["theory-qa"]
    assert (
        state["active_skill_instructions"][0]["instruction"]
        == "## Theory QA full instruction"
    )


@pytest.mark.asyncio
async def test_draw_questions_tool_returns_envelope_and_updates_state(monkeypatch):
    from app.mcp_server import interview_tools

    async def fake_draw(**kwargs):
        return [
            {
                "id": 10,
                "question": "算法题：手写 LRU Cache",
                "cat1": "E.算法与数据结构",
                "cat2": "E1.数据结构",
                "tags": "算法手撕,lru",
                "difficulty": "L2-中等",
                "sources": [],
                "_fallback_used": True,
                "_fallback_reason": "position_filter_empty",
            }
        ]

    monkeypatch.setattr(interview_tools, "_draw_questions_for_tool", fake_draw)

    state = {"user_id": 5, "bank_mode": "public"}
    result = await interview_tools.draw_questions_tool(
        {"question_type": "algorithm_coding", "count": 1},
        state,
    )

    assert result["ok"] is True
    assert result["tool"] == "draw_questions"
    assert result["items"][0]["id"] == 10
    assert result["metadata"]["fallback_used"] is True
    assert result["metadata"]["fallback_steps"] == ["position_filter_empty"]
    assert state["candidate_questions"][0]["id"] == 10
    assert state["retrieved_questions"][0]["id"] == 10
    assert state["question_source"] == "draw"


@pytest.mark.asyncio
async def test_search_questions_tool_returns_error_envelope_for_empty_query():
    from app.mcp_server import interview_tools

    state = {"user_id": 5}
    result = await interview_tools.search_questions_tool({}, state)

    assert result["ok"] is False
    assert result["tool"] == "search_questions"
    assert result["items"] == []
    assert result["error"]["error_code"] == "NO_QUERY"
    assert state["candidate_questions"] == []
    assert state["retrieved_questions"] == []


def test_select_question_tool_binds_algorithm_candidate():
    from app.mcp_server import interview_tools

    state = {"question_type": "algorithm_coding"}
    candidates = [
        {
            "id": 20,
            "question": "讲一下 RAG 的重排",
            "cat1": "B.Agent与LLM应用",
            "cat2": "B2.RAG系统设计",
            "tags": "rag",
        },
        {
            "id": 21,
            "question": "算法题：手写 LRU Cache",
            "cat1": "E.算法与数据结构",
            "cat2": "E1.数据结构",
            "tags": "算法手撕,lru",
        },
    ]

    result = interview_tools.select_question_tool({"candidates": candidates}, state)

    assert result["ok"] is True
    assert result["tool"] == "select_question"
    assert result["selected_question"]["id"] == 21
    assert state["selected_question"]["id"] == 21
    assert state["next_question_plan"]["question_id"] == 21


def test_interview_mcp_app_exports_streamable_http_app():
    from app.mcp_server.app import mcp, mcp_app

    assert mcp.name == "InterviewBoss"
    inner = getattr(mcp_app, "app", mcp_app)
    assert hasattr(inner, "routes")


def test_mcp_endpoint_exempt_from_csrf(client):
    response = client.post("/mcp/messages", headers={})
    assert response.status_code != 403


def test_mcp_endpoint_requires_api_key_when_configured(client, monkeypatch):
    from app.mcp_server import app as mcp_app_module

    monkeypatch.setattr(mcp_app_module, "MCP_API_KEY", "test-mcp-key")
    assert mcp_app_module.MCP_API_KEY == "test-mcp-key"

    response = client.post("/mcp/messages", headers={})
    assert response.status_code == 401

    response = client.post(
        "/mcp/messages",
        headers={"x-mcp-api-key": "test-mcp-key"},
    )
    assert response.status_code != 401


@pytest.mark.asyncio
async def test_interview_mcp_app_call_tool_io_contract():
    from app.mcp_server.app import mcp

    tools = await mcp.list_tools()
    assert [tool.name for tool in tools] == [
        "load_skill",
        "search_questions",
        "draw_questions",
        "select_question",
    ]

    no_query = await _call_mcp_json("search_questions", {"keywords": []})
    assert no_query["ok"] is False
    assert no_query["tool"] == "search_questions"
    assert no_query["error"]["error_code"] == "NO_QUERY"

    missing_user = await _call_mcp_json("draw_questions", {"count": 1})
    assert missing_user["ok"] is False
    assert missing_user["tool"] == "draw_questions"
    assert missing_user["error"]["error_code"] == "USER_REQUIRED"

    selected = await _call_mcp_json(
        "select_question",
        {
            "question_type": "algorithm_coding",
            "candidates": [
                {
                    "id": 20,
                    "question": "讲一下 RAG 的重排",
                    "cat1": "B.Agent与LLM应用",
                    "cat2": "B2.RAG系统设计",
                    "tags": "rag",
                },
                {
                    "id": 21,
                    "question": "算法题：手写 LRU Cache",
                    "cat1": "E.算法与数据结构",
                    "cat2": "E1.数据结构",
                    "tags": "算法手撕,lru",
                },
            ],
        },
    )
    assert selected["ok"] is True
    assert selected["selected_question"]["id"] == 21
    assert selected["question_plan"]["question_id"] == 21


@pytest.mark.asyncio
async def test_mcp_session_persists_across_load_and_draw(monkeypatch):
    from app.mcp_server import interview_tools

    async def fake_draw(**kwargs):
        return [
            {
                "id": 101,
                "question": "算法题：手写 LRU Cache",
                "cat1": "E.算法与数据结构",
                "cat2": "E1.数据结构",
                "tags": "算法手撕,lru",
                "difficulty": "L2-中等",
                "sources": [],
            }
        ]

    monkeypatch.setattr(interview_tools, "_draw_questions_for_tool", fake_draw)

    loaded = await _call_mcp_json("load_skill", {"skill_name": "algorithm-coding"})
    assert loaded["ok"] is True
    session_id = loaded["metadata"]["session_id"]
    assert session_id
    assert loaded["metadata"]["state"]["active_skills"] == ["algorithm-coding"]

    drawn = await _call_mcp_json(
        "draw_questions",
        {"user_id": 5, "bank_mode": "public", "count": 1, "session_id": session_id},
    )
    assert drawn["ok"] is True
    assert drawn["metadata"]["session_id"] == session_id
    assert drawn["items"][0]["id"] == 101


@pytest.mark.asyncio
async def test_mcp_session_persists_across_search_and_select(monkeypatch):
    from app.mcp_server import interview_tools

    async def fake_search(**kwargs):
        return [
            {
                "id": 201,
                "question": "讲一下 RAG 的重排",
                "cat1": "B.Agent与LLM应用",
                "cat2": "B2.RAG系统设计",
                "tags": "rag",
            },
            {
                "id": 202,
                "question": "算法题：手写 LRU Cache",
                "cat1": "E.算法与数据结构",
                "cat2": "E1.数据结构",
                "tags": "算法手撕,lru",
            },
        ]

    monkeypatch.setattr(interview_tools, "_hybrid_search_for_tool", fake_search)

    searched = await _call_mcp_json(
        "search_questions",
        {"keywords": ["RAG"], "user_id": 5, "bank_mode": "public"},
    )
    assert searched["ok"] is True
    session_id = searched["metadata"]["session_id"]
    assert session_id

    selected = await _call_mcp_json(
        "select_question",
        {
            "session_id": session_id,
            "question_type": "algorithm_coding",
            "candidates": searched["items"],
        },
    )
    assert selected["ok"] is True
    assert selected["metadata"]["session_id"] == session_id
    assert selected["selected_question"]["id"] == 202
    assert selected["question_plan"]["question_id"] == 202
