"""Interview MCP-style tools.

These functions are the backend execution boundary for interview actions.
The chat agent may decide *which* tool to call, but question retrieval,
drawing, and selection are executed here with stable envelopes.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time

from pydantic import ValidationError

from app.agents.chat.question_plan import (
    _build_interview_ledger,
    _maybe_create_question_plan,
)

logger = logging.getLogger(__name__)
from app.agents.chat.state import ChatState
from app.agents.chat.tool_gateway import (
    DrawQuestionsInput,
    SearchQuestionsInput,
    build_error_envelope,
    build_success_envelope,
    normalize_question_item,
)


_TOOL_SERVICE_TIMEOUT = 30.0


def _get_default_skill_registry():
    from app.agents.chat.skills import get_default_registry

    return get_default_registry()


def load_skill_tool(args: dict, state: ChatState, registry_getter=None) -> dict:
    """Load a skill instruction and store it in chat state."""
    started = time.monotonic()
    skill_name = args.get("skill_name", "")
    registry = (registry_getter or _get_default_skill_registry)()
    skill = registry.get(skill_name)

    if skill is None:
        total_ms = int((time.monotonic() - started) * 1000)
        return build_error_envelope(
            tool="load_skill",
            error_code="UNKNOWN_SKILL",
            message=f"Unknown skill: {skill_name}",
            total_ms=total_ms,
            debug_reason="unknown_skill",
        )

    active_skills = state.setdefault("active_skills", [])
    if skill_name in active_skills:
        total_ms = int((time.monotonic() - started) * 1000)
        envelope = build_success_envelope(
            tool="load_skill",
            items=[],
            total_ms=total_ms,
            debug_reason="already_active",
        )
        envelope["metadata"]["status"] = "already_active"
        envelope["metadata"]["skill"] = skill_name
        envelope["metadata"]["summary"] = f"技能「{skill.description}」已在激活状态。"
        return envelope

    active_skills.append(skill_name)
    instruction = skill.get_instruction()
    if instruction:
        state.setdefault("active_skill_instructions", []).append(
            {"skill_name": skill_name, "instruction": instruction}
        )

    total_ms = int((time.monotonic() - started) * 1000)
    envelope = build_success_envelope(
        tool="load_skill",
        items=[],
        total_ms=total_ms,
        debug_reason="loaded",
    )
    envelope["metadata"]["status"] = "loaded"
    envelope["metadata"]["skill"] = skill_name
    envelope["metadata"]["summary"] = (
        f"技能「{skill.description}」已激活，将注入到当前 ReAct loop 的系统提示中。"
    )
    return envelope


async def _hybrid_search_for_tool(**kwargs):
    from app.services.fts_service import hybrid_search

    return await asyncio.to_thread(hybrid_search, **kwargs)


async def _draw_questions_for_tool(**kwargs):
    from app.services.question_draw_service import draw_questions

    return await asyncio.to_thread(draw_questions, **kwargs)


async def _maybe_await(value):
    return await value if inspect.isawaitable(value) else value


def _positive_int_ids(values) -> set[int]:
    ids: set[int] = set()
    for value in values or []:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            ids.add(parsed)
    return ids


def _fallback_metadata(items: list[dict]) -> tuple[bool, list[str]]:
    reasons = []
    for item in items:
        reason = item.get("_fallback_reason")
        if reason and reason not in reasons:
            reasons.append(str(reason))
    return bool(reasons), reasons


async def search_questions_tool(args: dict, state: ChatState) -> dict:
    """Search questions and update chat state with a stable result envelope."""
    started = time.monotonic()
    try:
        parsed_args = SearchQuestionsInput(**args)
    except ValidationError:
        total_ms = int((time.monotonic() - started) * 1000)
        return build_error_envelope(
            tool="search_questions",
            error_code="VALIDATION_ERROR",
            message="Invalid search_questions arguments",
            total_ms=total_ms,
            debug_reason="validation_failed",
        )

    if not parsed_args.keywords and not state.get("search_query"):
        total_ms = int((time.monotonic() - started) * 1000)
        state["candidate_questions"] = []
        state["retrieved_questions"] = []
        state["question_source"] = "search"
        state["question_source_reason"] = "search_questions_no_query"
        return build_error_envelope(
            tool="search_questions",
            error_code="NO_QUERY",
            message="search_questions requires keywords or search_query",
            total_ms=total_ms,
            debug_reason="no_query",
            empty_reason="no_query",
        )

    search_args: dict[str, object] = {"keywords": parsed_args.keywords, "limit": 15}
    if state.get("search_query"):
        search_args["query_text"] = state["search_query"]
    if parsed_args.question_type:
        search_args["question_type"] = parsed_args.question_type
    if state.get("question_type") and "question_type" not in search_args:
        search_args["question_type"] = state["question_type"]
    if state.get("job_position"):
        search_args["job_position"] = state["job_position"]
    if state.get("retrieval_intent"):
        search_args["retrieval_intent"] = state["retrieval_intent"]
    if state.get("search_negative_terms"):
        search_args["negative_terms"] = state["search_negative_terms"]
    exclude_ids = set(_build_interview_ledger(state).asked_question_ids)
    # Cross-conversation dedup: exclude questions asked in previous interviews
    try:
        from app.db.operations import get_db_connection, get_asked_question_ids

        with get_db_connection() as conn:
            cross_conversation_ids = get_asked_question_ids(conn, state.get("user_id"))
        exclude_ids.update(cross_conversation_ids)
    except Exception as e:
        logger.debug("Cross-conversation dedup query failed: %s", e)
    if state.get("retrieved_questions"):
        exclude_ids.update(
            q.get("id")
            for q in state["retrieved_questions"]
            if isinstance(q, dict) and q.get("id")
        )
    if exclude_ids:
        search_args["exclude_ids"] = _positive_int_ids(exclude_ids)

    try:
        results = await asyncio.wait_for(
            _maybe_await(_hybrid_search_for_tool(**search_args)),
            timeout=_TOOL_SERVICE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.exception("search_questions service timed out")
        total_ms = int((time.monotonic() - started) * 1000)
        return build_error_envelope(
            tool="search_questions",
            error_code="TIMEOUT",
            message="search_questions service timed out",
            total_ms=total_ms,
            debug_reason="service_timeout",
            empty_reason="service_unavailable",
        )
    except Exception:
        logger.exception("search_questions service failed")
        total_ms = int((time.monotonic() - started) * 1000)
        return build_error_envelope(
            tool="search_questions",
            error_code="SERVICE_ERROR",
            message="search_questions service failed",
            total_ms=total_ms,
            debug_reason="service_error",
            empty_reason="service_unavailable",
        )

    state["candidate_questions"] = results
    state["retrieved_questions"] = results
    state["question_source"] = "search"
    state["question_source_reason"] = "search_questions returned candidate questions"

    items = [
        normalize_question_item(item, source="search", reason="rrf_ranked")
        for item in results
        if isinstance(item, dict) and item.get("id") and item.get("question")
    ]
    total_ms = int((time.monotonic() - started) * 1000)
    return build_success_envelope(
        tool="search_questions",
        items=items,
        total_ms=total_ms,
        debug_reason="hybrid_search_ok" if items else "no_match",
        empty_reason=None if items else "no_match",
    )


async def draw_questions_tool(args: dict, state: ChatState) -> dict:
    """Draw questions and update chat state with a stable result envelope."""
    started = time.monotonic()
    try:
        parsed_args = DrawQuestionsInput(**args)
    except ValidationError:
        total_ms = int((time.monotonic() - started) * 1000)
        return build_error_envelope(
            tool="draw_questions",
            error_code="VALIDATION_ERROR",
            message="Invalid draw_questions arguments",
            total_ms=total_ms,
            debug_reason="validation_failed",
        )

    user_id = state.get("user_id")
    if not user_id:
        total_ms = int((time.monotonic() - started) * 1000)
        return build_error_envelope(
            tool="draw_questions",
            error_code="USER_REQUIRED",
            message="user_id is required for draw_questions",
            total_ms=total_ms,
            debug_reason="missing_user_id",
        )

    draw_args: dict[str, object] = {
        "user": {
            "id": user_id,
            "bank_mode": state.get("bank_mode", "public"),
        },
        "count": parsed_args.count,
        "session_notes": state.get("session_notes") or None,
    }
    for key in ("difficulty", "cat1", "cat2", "topic", "question_type"):
        value = getattr(parsed_args, key)
        if value:
            draw_args[key] = value
    exclude_ids = set(_build_interview_ledger(state).asked_question_ids)
    if state.get("retrieved_questions"):
        exclude_ids.update(
            q.get("id")
            for q in state["retrieved_questions"]
            if isinstance(q, dict) and q.get("id")
        )
    if exclude_ids:
        draw_args["exclude_ids"] = _positive_int_ids(exclude_ids)

    try:
        results = await asyncio.wait_for(
            _maybe_await(_draw_questions_for_tool(**draw_args)),
            timeout=_TOOL_SERVICE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        logger.exception("draw_questions service timed out")
        total_ms = int((time.monotonic() - started) * 1000)
        return build_error_envelope(
            tool="draw_questions",
            error_code="TIMEOUT",
            message="draw_questions service timed out",
            total_ms=total_ms,
            debug_reason="service_timeout",
            empty_reason="service_unavailable",
        )
    except Exception:
        logger.exception("draw_questions service failed")
        total_ms = int((time.monotonic() - started) * 1000)
        return build_error_envelope(
            tool="draw_questions",
            error_code="SERVICE_ERROR",
            message="draw_questions service failed",
            total_ms=total_ms,
            debug_reason="service_error",
            empty_reason="service_unavailable",
        )

    state["candidate_questions"] = results
    state["retrieved_questions"] = results
    state["question_source"] = "draw"
    state["question_source_reason"] = "draw_questions returned candidate questions"

    items = [
        normalize_question_item(item, source="draw", reason="weighted_draw")
        for item in results
        if isinstance(item, dict) and item.get("id") and item.get("question")
    ]
    fallback_used, fallback_steps = _fallback_metadata(items)
    total_ms = int((time.monotonic() - started) * 1000)
    return build_success_envelope(
        tool="draw_questions",
        items=items,
        total_ms=total_ms,
        debug_reason="weighted_draw_ok" if items else "no_match",
        fallback_used=fallback_used,
        fallback_steps=fallback_steps,
        empty_reason=None if items else "no_match",
    )


def select_question_tool(
    args: dict,
    state: ChatState,
    *,
    force_candidate: dict | None = None,
    candidate_index: int | None = None,
) -> dict:
    """Select and bind one question as the next-question plan.

    When *force_candidate* is provided (agent explicit selection via ``tools.py``),
    it is forwarded to ``_maybe_create_question_plan`` which uses it directly
    instead of running the local ``viable[0]`` / ``algorithm_candidate_match``
    heuristic.
    """
    candidates = (
        args.get("candidates")
        or state.get("candidate_questions")
        or state.get("retrieved_questions")
        or []
    )

    if not candidates:
        return build_error_envelope(
            tool="select_question",
            error_code="NO_CANDIDATES",
            message="No candidate questions available to select",
            total_ms=0,
            debug_reason="no_candidates",
            empty_reason="no_candidates",
        )

    if candidate_index is not None:
        if (
            not isinstance(candidate_index, int)
            or candidate_index < 0
            or candidate_index >= len(candidates)
        ):
            return build_error_envelope(
                tool="select_question",
                error_code="INDEX_OUT_OF_RANGE",
                message=f"candidate_index {candidate_index} is out of range (0-{len(candidates) - 1})",
                total_ms=0,
                debug_reason="index_out_of_range",
                empty_reason="index_out_of_range",
            )
        force_candidate = candidates[candidate_index]

    args_candidates = args.get("candidates")
    if isinstance(args_candidates, list):
        state["candidate_questions"] = args_candidates
        state["retrieved_questions"] = args_candidates

    plan = _maybe_create_question_plan(state, force_candidate=force_candidate)

    reason = state.get("question_plan_reason")
    if force_candidate is not None and not plan and reason == "negative_term_filtered":
        return build_error_envelope(
            tool="select_question",
            error_code="NEGATIVE_TERM_FILTERED",
            message="Selected candidate contains negative-term filter match",
            total_ms=0,
            debug_reason="negative_term_filtered",
            empty_reason="negative_term_filtered",
        )

    selected = state.get("selected_question")
    if not plan or not selected:
        return build_error_envelope(
            tool="select_question",
            error_code="NO_CANDIDATES",
            message="No viable question candidate could be selected",
            total_ms=0,
            debug_reason=state.get("question_plan_reason") or "no_viable_candidate",
            empty_reason="no_viable_candidate",
        )

    item = normalize_question_item(
        selected,
        source="draw" if state.get("question_source") == "draw" else "search",
        reason=state.get("question_source_reason") or "question_plan_bound",
    )
    debug_reason = (
        "agent_explicit_selection"
        if force_candidate is not None
        else "question_plan_bound"
    )
    envelope = build_success_envelope(
        tool="select_question",
        items=[item],
        total_ms=0,
        debug_reason=debug_reason,
    )
    envelope["selected_question"] = item
    envelope["question_plan"] = plan
    return envelope
