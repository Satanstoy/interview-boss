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
    _collect_question_exclusion_ids,
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
from app.services.job_position_service import (
    list_job_positions,
    load_active_position_rows,
    position_suggestions,
    resolve_job_position,
)


_TOOL_SERVICE_TIMEOUT = 30.0
_NO_MATCH_MESSAGE = (
    "当前岗位和主题下没有可用题目，请直接向候选人说明题库为空，"
    "或等待用户调整岗位/主题。"
)


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
        envelope["metadata"]["skill_version"] = str(getattr(skill, "version", "1"))
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
    envelope["metadata"]["skill_version"] = str(getattr(skill, "version", "1"))
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


async def _list_job_positions_for_tool() -> list[dict]:
    return await asyncio.to_thread(list_job_positions)


async def _resolve_state_position(state: ChatState):
    """Resolve and persist the canonical position used by question services."""

    raw_value = state.get("job_position")
    if raw_value is None or not str(raw_value).strip():
        return None, None
    rows = await asyncio.to_thread(load_active_position_rows)
    resolution = resolve_job_position(str(raw_value), position_rows=rows)
    if resolution is None:
        return None, position_suggestions(rows)
    state["job_position"] = resolution.canonical_name
    state["canonical_job_position"] = resolution.canonical_name
    state["job_position_id"] = resolution.position_id
    state["job_position_resolution"] = {
        "canonical_name": resolution.canonical_name,
        "position_id": resolution.position_id,
        "job_family": resolution.job_family,
    }
    return resolution, None


async def list_job_positions_tool(args: dict, state: ChatState) -> dict:
    """List active positions and exact aliases for role discovery."""

    started = time.monotonic()
    try:
        items = await asyncio.wait_for(
            _maybe_await(_list_job_positions_for_tool()),
            timeout=_TOOL_SERVICE_TIMEOUT,
        )
    except asyncio.TimeoutError:
        total_ms = int((time.monotonic() - started) * 1000)
        logger.warning("MCP tool=list_job_positions timeout")
        return build_error_envelope(
            tool="list_job_positions",
            error_code="SERVICE_TIMEOUT",
            message="Unable to load supported job positions in time",
            total_ms=total_ms,
            debug_reason="position_service_timeout",
            empty_reason="service_unavailable",
        )
    except Exception:
        total_ms = int((time.monotonic() - started) * 1000)
        logger.exception("MCP tool=list_job_positions failed")
        return build_error_envelope(
            tool="list_job_positions",
            error_code="SERVICE_ERROR",
            message="Unable to load supported job positions",
            total_ms=total_ms,
            debug_reason="position_service_error",
            empty_reason="service_unavailable",
        )

    total_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "MCP tool=list_job_positions session_id=%s result_count=%s total_ms=%s",
        state.get("session_id"),
        len(items or []),
        total_ms,
    )
    return build_success_envelope(
        tool="list_job_positions",
        items=items or [],
        total_ms=total_ms,
        debug_reason="positions_loaded",
    )


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


def _load_authoritative_question(
    question_id: int,
    state: ChatState,
) -> dict | None:
    """Reload one visible question from the database for selection.

    Candidate rows are model-visible hints, not an authorization boundary.  A
    selection must be checked again against the current user's bank mode and
    current job position so a stale or tampered session cannot bind arbitrary
    question text or another user's private question.
    """
    try:
        question_id = int(question_id)
        user_id = int(state.get("user_id") or 0)
    except (TypeError, ValueError):
        return None
    if question_id <= 0 or user_id <= 0:
        return None

    try:
        from app.db.connection import get_db_connection
        from app.routers.questions import _build_bank_where_clause

        user = {
            "id": user_id,
            "bank_mode": state.get("bank_mode", "all"),
        }
        if state.get("job_position"):
            from_clause, where_clause, params = _build_bank_where_clause(
                user,
                "qb",
                job_position=state["job_position"],
                job_position_id=state.get("job_position_id"),
            )
        else:
            from_clause, where_clause, params = _build_bank_where_clause(user, "qb")
        sql = (
            "SELECT qb.id, qb.question, qb.cat1, qb.cat2, qb.tags, "
            "qb.difficulty, qb.sources, qb.owner_id, qb.status, qb.job_position "
            f"{from_clause} {where_clause} AND qb.id = ? LIMIT 1"
        )
        with get_db_connection() as conn:
            row = conn.execute(sql, [*params, question_id]).fetchone()
        return dict(row) if row is not None else None
    except Exception:
        logger.exception(
            "Failed to reload authoritative question question_id=%s user_id=%s",
            question_id,
            user_id,
        )
        return None


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

    if parsed_args.search_query and not state.get("search_query"):
        state["search_query"] = parsed_args.search_query
    if parsed_args.job_position and not state.get("job_position"):
        state["job_position"] = parsed_args.job_position
    if parsed_args.retrieval_intent and not state.get("retrieval_intent"):
        state["retrieval_intent"] = parsed_args.retrieval_intent
    if parsed_args.negative_terms and not state.get("search_negative_terms"):
        state["search_negative_terms"] = parsed_args.negative_terms

    try:
        resolution, suggestions = await _resolve_state_position(state)
    except Exception:
        logger.exception("MCP tool=search_questions position resolution failed")
        total_ms = int((time.monotonic() - started) * 1000)
        return build_error_envelope(
            tool="search_questions",
            error_code="SERVICE_ERROR",
            message="Unable to resolve job position",
            total_ms=total_ms,
            debug_reason="position_resolution_error",
            empty_reason="service_unavailable",
        )
    if state.get("job_position") and resolution is None:
        state["candidate_questions"] = []
        state["retrieved_questions"] = []
        state["question_source"] = "search"
        state["question_source_reason"] = "unknown_job_position"
        total_ms = int((time.monotonic() - started) * 1000)
        return build_error_envelope(
            tool="search_questions",
            error_code="UNKNOWN_JOB_POSITION",
            message="Unsupported job position",
            total_ms=total_ms,
            debug_reason="unknown_job_position",
            empty_reason="unknown_job_position",
            suggestions=suggestions,
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
    if state.get("_mcp_external"):
        search_args["user_id"] = state.get("user_id")
        search_args["bank_mode"] = state.get("bank_mode", "public")
    if state.get("search_query"):
        search_args["query_text"] = state["search_query"]
    if parsed_args.question_type:
        search_args["question_type"] = parsed_args.question_type
    if state.get("question_type") and "question_type" not in search_args:
        search_args["question_type"] = state["question_type"]
    if state.get("job_position"):
        search_args["job_position"] = state["job_position"]
    if state.get("job_position_id"):
        search_args["job_position_id"] = state["job_position_id"]
    if state.get("retrieval_intent"):
        search_args["retrieval_intent"] = state["retrieval_intent"]
    if state.get("search_negative_terms"):
        search_args["negative_terms"] = state["search_negative_terms"]
    exclude_ids = set(_collect_question_exclusion_ids(state))
    # Cross-conversation dedup: exclude questions asked in previous interviews
    try:
        from app.db.operations import get_db_connection, get_asked_question_ids

        with get_db_connection() as conn:
            if state.get("conversation_id"):
                rows = conn.execute(
                    "SELECT question_id FROM interview_asked_questions WHERE conversation_id = ?",
                    (state["conversation_id"],),
                ).fetchall()
                exclude_ids.update(_positive_int_ids(row[0] for row in rows))
            cross_conversation_ids = get_asked_question_ids(conn, state.get("user_id"))
        exclude_ids.update(cross_conversation_ids)
    except Exception as e:
        logger.debug("Cross-conversation dedup query failed: %s", e)
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
            error_code="SERVICE_TIMEOUT",
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
    logger.info(
        "MCP tool=search_questions session_id=%s job_position=%s result_count=%s total_ms=%s",
        state.get("session_id"),
        state.get("job_position"),
        len(items),
        total_ms,
    )
    return build_success_envelope(
        tool="search_questions",
        items=items,
        total_ms=total_ms,
        debug_reason="hybrid_search_ok" if items else "no_match",
        empty_reason=None if items else "no_match",
        message=None if items else _NO_MATCH_MESSAGE,
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

    if parsed_args.job_position and not state.get("job_position"):
        state["job_position"] = parsed_args.job_position
    if parsed_args.session_notes is not None:
        state["session_notes"] = parsed_args.session_notes
    try:
        resolution, suggestions = await _resolve_state_position(state)
    except Exception:
        logger.exception("MCP tool=draw_questions position resolution failed")
        total_ms = int((time.monotonic() - started) * 1000)
        return build_error_envelope(
            tool="draw_questions",
            error_code="SERVICE_ERROR",
            message="Unable to resolve job position",
            total_ms=total_ms,
            debug_reason="position_resolution_error",
            empty_reason="service_unavailable",
        )
    if state.get("job_position") and resolution is None:
        state["candidate_questions"] = []
        state["retrieved_questions"] = []
        state["question_source"] = "draw"
        state["question_source_reason"] = "unknown_job_position"
        total_ms = int((time.monotonic() - started) * 1000)
        return build_error_envelope(
            tool="draw_questions",
            error_code="UNKNOWN_JOB_POSITION",
            message="Unsupported job position",
            total_ms=total_ms,
            debug_reason="unknown_job_position",
            empty_reason="unknown_job_position",
            suggestions=suggestions,
        )

    control = state.get("distribution_control") or {}
    preferred_type = control.get("preferred_type") if state.get("distribution_primary_required") else None
    if preferred_type:
        parsed_args = parsed_args.model_copy(update={"question_type": preferred_type})

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
            "bank_mode": state.get("bank_mode", "all"),
        },
        "count": parsed_args.count,
        "session_notes": state.get("session_notes") or None,
    }
    if state.get("job_position"):
        draw_args["job_position"] = str(state["job_position"]).strip()[:100]
    if state.get("job_position_id"):
        draw_args["job_position_id"] = state["job_position_id"]
    for key in ("difficulty", "cat1", "cat2", "topic", "question_type"):
        value = getattr(parsed_args, key)
        if value:
            draw_args[key] = value
    exclude_ids = set(_collect_question_exclusion_ids(state))
    try:
        from app.db.operations import get_db_connection, get_asked_question_ids

        with get_db_connection() as conn:
            if state.get("conversation_id"):
                rows = conn.execute(
                    "SELECT question_id FROM interview_asked_questions WHERE conversation_id = ?",
                    (state["conversation_id"],),
                ).fetchall()
                exclude_ids.update(_positive_int_ids(row[0] for row in rows))
            if not state.get("distribution_allow_cross_conversation_reuse"):
                exclude_ids.update(get_asked_question_ids(conn, user_id))
    except Exception as e:
        logger.debug("Cross-conversation dedup query failed: %s", e)
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
            error_code="SERVICE_TIMEOUT",
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
    total_ms = int((time.monotonic() - started) * 1000)
    logger.info(
        "MCP tool=draw_questions session_id=%s job_position=%s result_count=%s total_ms=%s",
        state.get("session_id"),
        state.get("job_position"),
        len(items),
        total_ms,
    )
    return build_success_envelope(
        tool="draw_questions",
        items=items,
        total_ms=total_ms,
        debug_reason="weighted_draw_ok" if items else "no_match",
        # Position and bank scope are hard constraints.  An empty result is
        # reported as no_match; it is never marked as a hidden fallback.
        fallback_used=False,
        fallback_steps=[],
        empty_reason=None if items else "no_match",
        message=None if items else _NO_MATCH_MESSAGE,
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
    if "candidates" in args:
        return build_error_envelope(
            tool="select_question",
            error_code="INVALID_TOOL_ARGUMENTS",
            message="select_question accepts only candidate_index; candidates are server-owned",
            total_ms=0,
            debug_reason="client_candidates_rejected",
            empty_reason="invalid_arguments",
        )

    requested_source = args.get("question_source")
    actual_source = state.get("question_source")
    if requested_source and requested_source not in {"search", "draw"}:
        return build_error_envelope(
            tool="select_question",
            error_code="VALIDATION_ERROR",
            message="question_source must be search or draw",
            total_ms=0,
            debug_reason="invalid_question_source",
            empty_reason="invalid_arguments",
        )
    if requested_source and actual_source and requested_source != actual_source:
        return build_error_envelope(
            tool="select_question",
            error_code="QUESTION_SOURCE_MISMATCH",
            message="question_source does not match the server candidate set",
            total_ms=0,
            debug_reason="question_source_mismatch",
            empty_reason="invalid_arguments",
        )

    candidates = state.get("candidate_questions") or state.get("retrieved_questions") or []

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
            or isinstance(candidate_index, bool)
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

    selected_candidate_id = (
        force_candidate.get("id")
        if isinstance(force_candidate, dict)
        else None
    )
    used_question_ids = _positive_int_ids(state.get("used_question_ids"))
    if selected_candidate_id is not None:
        try:
            if int(selected_candidate_id) in used_question_ids:
                return build_error_envelope(
                    tool="select_question",
                    error_code="QUESTION_ALREADY_USED",
                    message="This question has already been used in the current session",
                    total_ms=0,
                    debug_reason="question_already_used",
                    empty_reason="question_not_available",
                )
        except (TypeError, ValueError):
            pass

    if not state.get("user_id"):
        return build_error_envelope(
            tool="select_question",
            error_code="USER_REQUIRED",
            message="user_id is required for select_question",
            total_ms=0,
            debug_reason="missing_user_id",
            empty_reason="user_required",
        )

    if force_candidate is not None:
        raw_id = force_candidate.get("id") if isinstance(force_candidate, dict) else None
        authoritative = _load_authoritative_question(raw_id, state)
        if authoritative is None:
            return build_error_envelope(
                tool="select_question",
                error_code="QUESTION_NOT_AVAILABLE",
                message="Selected question is no longer available",
                total_ms=0,
                debug_reason="authoritative_reload_failed",
                empty_reason="question_not_available",
            )
        force_candidate = authoritative
    else:
        # No explicit index means the local planner may choose among the
        # server-owned candidates. Rehydrate every candidate before it runs.
        authoritative_candidates = []
        for candidate in candidates:
            raw_id = candidate.get("id") if isinstance(candidate, dict) else None
            authoritative = _load_authoritative_question(raw_id, state)
            if authoritative is not None:
                authoritative_candidates.append(authoritative)
        if not authoritative_candidates:
            return build_error_envelope(
                tool="select_question",
                error_code="QUESTION_NOT_AVAILABLE",
                message="No selected candidate is currently available",
                total_ms=0,
                debug_reason="authoritative_reload_failed",
                empty_reason="question_not_available",
            )
        state["candidate_questions"] = authoritative_candidates
        state["retrieved_questions"] = authoritative_candidates

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

    try:
        selected_id = int(selected.get("id"))
    except (TypeError, ValueError):
        selected_id = 0
    if selected_id in used_question_ids:
        return build_error_envelope(
            tool="select_question",
            error_code="QUESTION_ALREADY_USED",
            message="This question has already been used in the current session",
            total_ms=0,
            debug_reason="question_already_used",
            empty_reason="question_not_available",
        )
    if selected_id > 0:
        used_question_ids.add(selected_id)
        state["used_question_ids"] = sorted(used_question_ids)

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
