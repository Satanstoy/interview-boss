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

    assert result["status"] == "loaded"
    assert result["skill"] == "theory-qa"
    assert state["active_skills"] == ["theory-qa"]
    assert state["active_skill_instructions"][0]["instruction"] == "## Theory QA full instruction"


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
    assert hasattr(mcp_app, "routes")


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
