"""Embedded MCP app for InterviewBoss backend tools."""

import os
import inspect
import logging
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.mcp_server.principal import (
    MCPPrincipal,
    get_mcp_principal,
    reset_mcp_principal,
    set_mcp_principal,
)
from app.mcp_server import interview_tools
from app.mcp_server.session import (
    load_mcp_session_async,
    new_session_id,
    save_mcp_session_async,
)


MCP_API_KEY = os.getenv("MCP_API_KEY", "")
logger = logging.getLogger(__name__)
MCP_ALLOW_ANONYMOUS = os.getenv("MCP_ALLOW_ANONYMOUS", "").lower() in {
    "1",
    "true",
    "yes",
}
MCP_USAGE_SKILL_NAME = "interview-tool-use"


def _load_mcp_usage_skill_instructions() -> str:
    """Read the canonical tool-use skill for MCP initialize instructions."""
    try:
        from app.agents.chat.skills import get_default_registry

        skill = get_default_registry().get(MCP_USAGE_SKILL_NAME)
        if skill is not None:
            return skill.get_instruction()
    except Exception:
        logger.exception("Failed to load the MCP usage skill")
    return (
        "Use session_id consistently across one interview. Load a relevant "
        "skill before specialized questions, pass job_position when known, "
        "and call select_question using only a server-returned candidate_index."
    )


def _activate_mcp_usage_skill(state: dict[str, Any]) -> None:
    """Activate the tool-use skill in every MCP session automatically."""
    active_skills = state.setdefault("active_skills", [])
    if MCP_USAGE_SKILL_NAME in active_skills:
        return
    interview_tools.load_skill_tool(
        {"skill_name": MCP_USAGE_SKILL_NAME},
        state,
    )


async def _load_account_mcp_principal(request: Request) -> MCPPrincipal:
    """Validate the per-account MCP bearer token."""
    authorization = request.headers.get("authorization", "")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise ValueError("missing bearer token")

    from app.db.connection import run_db
    from app.services.mcp_token_service import authenticate_mcp_token

    identity = await run_db(lambda: authenticate_mcp_token(parts[1].strip()))
    if not identity:
        raise ValueError("invalid MCP token")
    return MCPPrincipal(**identity)


async def _load_mcp_principal(request: Request) -> MCPPrincipal:
    """Keep the old global API key + access JWT integration working."""
    authorization = request.headers.get("authorization", "")
    parts = authorization.split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise ValueError("missing bearer token")

    from app.core.auth import decode_token
    from app.db.connection import get_db_connection, run_db

    payload = decode_token(parts[1].strip(), expected_type="access")
    try:
        user_id = int(payload.get("user_id"))
    except (TypeError, ValueError):
        raise ValueError("invalid user id")
    if user_id <= 0:
        raise ValueError("invalid user id")

    def _query_user():
        with get_db_connection() as conn:
            return conn.execute("SELECT id FROM users WHERE id = ?", (user_id,)).fetchone()

    row = await run_db(_query_user)
    if not row:
        raise ValueError("user does not exist")
    return MCPPrincipal(user_id=user_id, bank_mode="all")


async def _send_mcp_error(scope, receive, send, status_code: int, detail: str) -> None:
    response = JSONResponse(status_code=status_code, content={"detail": detail})
    await response(scope, receive, send)


class MCPAuthMiddleware:
    """Authenticate account MCP tokens, with a legacy compatibility path."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive)
        header_key = request.headers.get("x-mcp-api-key", "")
        query_key = request.query_params.get("mcp_api_key", "")
        authorization = request.headers.get("authorization", "")
        principal = None
        if authorization:
            try:
                principal = _load_account_mcp_principal(request)
                if inspect.isawaitable(principal):
                    principal = await principal
            except Exception:
                # Older installations can continue using X-MCP-API-Key plus
                # the normal short-lived access JWT.
                legacy_key_valid = bool(
                    MCP_API_KEY
                    and (header_key == MCP_API_KEY or query_key == MCP_API_KEY)
                )
                if not legacy_key_valid:
                    logger.warning("MCP bearer authentication failed")
                    await _send_mcp_error(
                        scope, receive, send, 401, "Unauthorized MCP request"
                    )
                    return
                try:
                    principal = _load_mcp_principal(request)
                    if inspect.isawaitable(principal):
                        principal = await principal
                except Exception:
                    logger.warning("Legacy MCP access-token authentication failed")
                    await _send_mcp_error(
                        scope, receive, send, 401, "Unauthorized MCP request"
                    )
                    return
        elif MCP_API_KEY and (header_key == MCP_API_KEY or query_key == MCP_API_KEY):
            await _send_mcp_error(
                scope, receive, send, 401, "Bearer token required"
            )
            return
        elif not MCP_ALLOW_ANONYMOUS:
            status_code = 401 if MCP_API_KEY else 503
            detail = "MCP account token required" if MCP_API_KEY else "MCP endpoint is not configured"
            await _send_mcp_error(scope, receive, send, status_code, detail)
            return

        principal_token = set_mcp_principal(principal)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_mcp_principal(principal_token)


mcp = FastMCP(
    "InterviewBoss",
    instructions=(
        "InterviewBoss MCP exposes deterministic backend actions for an "
        "interview agent: load_skill, search_questions, draw_questions, and "
        "select_question. The client should persist the returned metadata "
        "session_id and reuse it across one interview. Load a relevant skill "
        "before a specialized interview. Use job_position when the user names "
        "a target role. search_questions and draw_questions return server-owned "
        "candidates; call select_question with candidate_index before asking a "
        "question. The bearer token determines the account; do not rely on "
        "client-supplied user_id or bank_mode.\n\n"
        "The InterviewBoss tool-use skill is loaded automatically during MCP "
        "initialization and activated in each MCP session. Follow it before "
        "using the question tools; load additional domain skills only when "
        "needed.\n\n"
        + _load_mcp_usage_skill_instructions()
    ),
    streamable_http_path="/",
    stateless_http=True,
)


async def _init_tool_state_async(
    session_id: str | None, overrides: dict[str, Any]
) -> tuple[str, dict[str, Any]]:
    """Async session loader for ASGI paths backed by async Redis clients."""
    sid = session_id or new_session_id()
    principal = get_mcp_principal()
    state = (
        await load_mcp_session_async(
            sid,
            user_id=principal.user_id if principal else None,
        )
        or {}
    )
    state.update(overrides)
    if principal is not None:
        state["user_id"] = principal.user_id
        state["bank_mode"] = principal.bank_mode
    else:
        # Anonymous MCP is intentionally public-only. Never let request
        # arguments or an anonymous session turn into a user-scoped identity.
        state["user_id"] = None
        state["bank_mode"] = "public"
    _activate_mcp_usage_skill(state)
    return sid, state


async def _save_tool_state_async(session_id: str, state: dict[str, Any]) -> None:
    principal = get_mcp_principal()
    await save_mcp_session_async(
        session_id,
        state,
        user_id=principal.user_id if principal else None,
    )


def _attach_session_metadata(result: dict[str, Any], session_id: str) -> dict[str, Any]:
    """Inject session_id into the result metadata envelope."""
    metadata = result.setdefault("metadata", {})
    metadata["session_id"] = session_id
    return result


@mcp.tool()
async def load_skill(
    skill_name: str,
    session_id: str = None,
    active_skills: list = None,
) -> dict:
    """Load one interview skill instruction."""
    skill_overrides = {}
    if active_skills is not None:
        skill_overrides["active_skills"] = active_skills
    sid, state = await _init_tool_state_async(
        session_id, skill_overrides
    )
    result = interview_tools.load_skill_tool({"skill_name": skill_name}, state)
    result.setdefault("metadata", {})["state"] = {
        "active_skills": state.get("active_skills", []),
        "active_skill_instructions": state.get("active_skill_instructions", []),
    }
    await _save_tool_state_async(sid, state)
    return _attach_session_metadata(result, sid)


@mcp.tool()
async def search_questions(
    keywords: list = None,
    question_type: str = None,
    user_id: int = None,
    bank_mode: str = "all",
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

    sid, state = await _init_tool_state_async(session_id, overrides)
    result = await interview_tools.search_questions_tool(args, state)
    await _save_tool_state_async(sid, state)
    return _attach_session_metadata(result, sid)


@mcp.tool()
async def draw_questions(
    user_id: int = None,
    bank_mode: str = "all",
    count: int = 3,
    difficulty: str = None,
    cat1: str = None,
    cat2: str = None,
    topic: str = None,
    job_position: str = None,
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
    if job_position:
        overrides["job_position"] = job_position.strip()[:100]

    sid, state = await _init_tool_state_async(session_id, overrides)
    result = await interview_tools.draw_questions_tool(args, state)
    await _save_tool_state_async(sid, state)
    return _attach_session_metadata(result, sid)


@mcp.tool()
async def select_question(
    user_id: int = None,
    bank_mode: str = "all",
    session_id: str = None,
    question_type: str = None,
    question_source: str = "draw",
    candidate_index: int = 0,
) -> dict:
    """Select one server-owned candidate by index and bind the next plan."""
    overrides: dict[str, Any] = {"question_source": question_source}
    if user_id is not None:
        overrides["user_id"] = user_id
    if bank_mode:
        overrides["bank_mode"] = bank_mode
    if question_type:
        overrides["question_type"] = question_type

    sid, state = await _init_tool_state_async(session_id, overrides)
    result = interview_tools.select_question_tool(
        {"candidate_index": candidate_index},
        state,
        candidate_index=candidate_index,
    )
    await _save_tool_state_async(sid, state)
    return _attach_session_metadata(result, sid)


mcp_app = MCPAuthMiddleware(mcp.streamable_http_app())
