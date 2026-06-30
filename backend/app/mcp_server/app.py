"""Embedded MCP app for InterviewBoss backend tools."""

from typing import Any

from mcp.server.fastmcp import FastMCP

from app.mcp_server import interview_tools


mcp = FastMCP(
    "InterviewBoss",
    instructions=(
        "InterviewBoss MCP exposes deterministic backend actions for the "
        "mock interview agent: search questions, draw questions, and bind the "
        "next question plan."
    ),
    streamable_http_path="/",
    stateless_http=True,
)


@mcp.tool()
def load_skill(
    skill_name: str,
    active_skills: list = None,
) -> dict:
    """Load one interview skill instruction."""
    state: dict[str, Any] = {"active_skills": active_skills or []}
    result = interview_tools.load_skill_tool({"skill_name": skill_name}, state)
    result["state"] = {
        "active_skills": state.get("active_skills", []),
        "active_skill_instructions": state.get("active_skill_instructions", []),
    }
    return result


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
) -> dict:
    """Search interview questions with a stable backend envelope."""
    args: dict[str, Any] = {"keywords": keywords or []}
    if question_type:
        args["question_type"] = question_type

    state: dict[str, Any] = {
        "user_id": user_id,
        "bank_mode": bank_mode,
    }
    if search_query:
        state["search_query"] = search_query
    if job_position:
        state["job_position"] = job_position
    if retrieval_intent:
        state["retrieval_intent"] = retrieval_intent
    if negative_terms:
        state["search_negative_terms"] = negative_terms

    return await interview_tools.search_questions_tool(args, state)


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

    state: dict[str, Any] = {
        "user_id": user_id,
        "bank_mode": bank_mode,
    }
    if session_notes:
        state["session_notes"] = session_notes

    return await interview_tools.draw_questions_tool(args, state)


@mcp.tool()
def select_question(
    candidates: list,
    question_type: str = None,
    question_source: str = "draw",
) -> dict:
    """Select one candidate and bind it as the next-question plan."""
    state: dict[str, Any] = {"question_source": question_source}
    if question_type:
        state["question_type"] = question_type
    return interview_tools.select_question_tool({"candidates": candidates}, state)


mcp_app = mcp.streamable_http_app()
