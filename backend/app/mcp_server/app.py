"""Embedded MCP app for InterviewBoss backend tools."""

import os
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.mcp_server import interview_tools
from app.mcp_server.session import load_mcp_session, new_session_id, save_mcp_session


MCP_API_KEY = os.getenv("MCP_API_KEY", "")


class MCPAuthMiddleware:
    """Optional API-key gate for the embedded MCP endpoint."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not MCP_API_KEY:
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        header_key = request.headers.get("x-mcp-api-key", "")
        query_key = request.query_params.get("mcp_api_key", "")
        if header_key != MCP_API_KEY and query_key != MCP_API_KEY:
            response = JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized MCP request"},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


mcp = FastMCP(
    "InterviewBoss",
    instructions=(
        "InterviewBoss MCP exposes deterministic backend actions for the "
        "mock interview agent: search questions, draw questions, and bind the "
        "next question plan. Pass session_id to keep state across calls."
    ),
    streamable_http_path="/",
    stateless_http=True,
)


def _init_tool_state(
    session_id: str | None, overrides: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Load persisted session state or start fresh, then apply call-specific overrides."""
    sid = session_id or new_session_id()
    state = load_mcp_session(sid) or {}
    state.update(overrides)
    return sid, state


def _attach_session_metadata(result: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Inject session_id into the result metadata envelope."""
    metadata = result.setdefault("metadata", {})
    metadata["session_id"] = session_id
    return result


@mcp.tool()
def load_skill(
    skill_name: str,
    session_id: str = None,
    active_skills: list = None,
) -> dict:
    """Load one interview skill instruction."""
    sid, state = _init_tool_state(session_id, {"active_skills": active_skills or []})
    result = interview_tools.load_skill_tool({"skill_name": skill_name}, state)
    result.setdefault("metadata", {})["state"] = {
        "active_skills": state.get("active_skills", []),
        "active_skill_instructions": state.get("active_skill_instructions", []),
    }
    save_mcp_session(sid, state)
    return _attach_session_metadata(result, sid)


@mcp.tool()
async def search_questions(
    keywords: list = None,
    question_type: str = None,
    user_id: int = None,
    bank_mode: str = "public",
    search_query: str = None,
    job_position: str = None,
    retrieval_intent: str = None,
    negative_terms: list = None,
    session_id: str = None,
) -> dict:
    """Search interview questions with a stable backend envelope."""
    args: dict[str, Any] = {"keywords": keywords or []}
    if question_type:
        args["question_type"] = question_type

    overrides: dict[str, Any] = {
        "user_id": user_id,
        "bank_mode": bank_mode,
    }
    if search_query:
        overrides["search_query"] = search_query
    if job_position:
        overrides["job_position"] = job_position
    if retrieval_intent:
        overrides["retrieval_intent"] = retrieval_intent
    if negative_terms:
        overrides["search_negative_terms"] = negative_terms

    sid, state = _init_tool_state(session_id, overrides)
    result = await interview_tools.search_questions_tool(args, state)
    save_mcp_session(sid, state)
    return _attach_session_metadata(result, sid)


@mcp.tool()
async def draw_questions(
    user_id: int = None,
    bank_mode: str = "public",
    count: int = 3,
    difficulty: str = None,
    cat1: str = None,
    cat2: str = None,
    topic: str = None,
    question_type: str = None,
    session_notes: str = None,
    session_id: str = None,
) -> dict:
    """Draw interview questions through the backend question service."""
    args: dict[str, Any] = {"count": count}
    for key, value in {
        "difficulty": difficulty,
        "cat1": cat1,
        "cat2": cat2,
        "topic": topic,
        "question_type": question_type,
    }.items():
        if value:
            args[key] = value

    overrides: dict[str, Any] = {
        "user_id": user_id,
        "bank_mode": bank_mode,
    }
    if session_notes:
        overrides["session_notes"] = session_notes

    sid, state = _init_tool_state(session_id, overrides)
    result = await interview_tools.draw_questions_tool(args, state)
    save_mcp_session(sid, state)
    return _attach_session_metadata(result, sid)


@mcp.tool()
def select_question(
    candidates: list,
    session_id: str = None,
    question_type: str = None,
    question_source: str = "draw",
    candidate_index: int = None,
) -> dict:
    """Select one candidate and bind it as the next-question plan."""
    overrides: dict[str, Any] = {"question_source": question_source}
    if question_type:
        overrides["question_type"] = question_type

    sid, state = _init_tool_state(session_id, overrides)
    result = interview_tools.select_question_tool(
        {"candidates": candidates},
        state,
        candidate_index=candidate_index,
    )
    save_mcp_session(sid, state)
    return _attach_session_metadata(result, sid)


mcp_app = MCPAuthMiddleware(mcp.streamable_http_app())
