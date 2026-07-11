"""Execute a TurnContract after ReAct has finished collecting evidence."""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from app.agents.chat.turn_contract import TurnContract, TurnContractAction
from app.agents.chat.validators.semantic_question_adherence import (
    validate_question_adherence,
)
from app.agents.chat.writers.clarify_writer import generate_clarification
from app.agents.chat.writers.closing_writer import (
    _contains_summary_content,
    generate_closing_utterance,
)
from app.agents.chat.writers.counter_writer import generate_counter_answer
from app.agents.chat.writers.followup_writer import generate_followup
from app.agents.chat.writers.question_writer import generate_question_with_validation
from app.agents.chat.writers.summary_writer import generate_structured_summary

logger = logging.getLogger("interview-boss")


def _recent_context(state: dict[str, Any]) -> str:
    history = state.get("recent_messages") or state.get("message_history") or []
    lines: list[str] = []
    for message in history[-6:]:
        if not isinstance(message, dict):
            continue
        role = "面试官" if message.get("role") == "assistant" else "候选人"
        content = str(message.get("content") or "").strip()
        if content:
            lines.append(f"{role}: {content[:300]}")
    return "\n".join(lines)


_INTERNAL_OUTPUT_MARKERS = (
    "load_skill",
    "search_questions",
    "draw_questions",
    "select_question",
    "thought:",
    "action:",
    "observation:",
    "final answer:",
)


def _deterministic_validation(text: str, rules: list[str]) -> list[dict[str, Any]]:
    """Record inexpensive output guards before any user-visible event."""
    trace: list[dict[str, Any]] = []
    if "non_empty" in rules:
        trace.append(
            {
                "name": "non_empty",
                "blocking": True,
                "passes": bool(text and text.strip()),
            }
        )
    if "no_internal_marker" in rules:
        normalized = text.lower()
        marker = next(
            (item for item in _INTERNAL_OUTPUT_MARKERS if item in normalized), None
        )
        trace.append(
            {
                "name": "no_internal_marker",
                "blocking": True,
                "passes": marker is None,
                "issue": marker,
            }
        )
    return trace


def _success(
    text: str,
    writer_trace: dict[str, Any],
    validator_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": "success",
        "text": text,
        "writer_trace": writer_trace,
        "validator_trace": validator_trace or [],
    }


def _error(
    result: dict[str, Any],
    writer: str,
    validator_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "status": "error",
        "error_code": result.get("error_code", "contract_generation_failed"),
        "message": result.get("message", "合同话术生成失败"),
        "writer_trace": {"writer": writer, "result": "error"},
        "validator_trace": validator_trace or [],
    }


def _validate_success(
    text: str,
    writer_trace: dict[str, Any],
    contract: TurnContract,
    validator_trace: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    trace = _deterministic_validation(text, contract.validation)
    if validator_trace:
        trace.extend(validator_trace)
    failed = next(
        (item for item in trace if item["blocking"] and not item["passes"]), None
    )
    if failed:
        return _error(
            {
                "error_code": "contract_output_validation_failed",
                "message": f"输出未通过 {failed['name']} 校验",
            },
            str(writer_trace.get("writer", "contract_writer")),
            trace,
        )
    return _success(text, writer_trace, trace)


def _pick_fallback_candidate(state: dict[str, Any]) -> dict[str, Any] | None:
    """Pick a viable fallback candidate distinct from the current selected_question.

    Used when the first writer/validator fails — we swap to another candidate
    rather than surfacing an error to the candidate. Returns None if no
    distinct viable candidate is available.
    """
    candidates = state.get("candidate_questions") or []
    selected = state.get("selected_question") or {}
    selected_id = selected.get("id")
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if not candidate.get("id") or not candidate.get("question"):
            continue
        if candidate.get("id") == selected_id:
            continue
        return candidate
    return None


async def _run_question_writer_with_fallback(
    *,
    state: dict[str, Any],
    context_anchor: str,
    llm_call: Callable[[list[dict[str, str]]], Awaitable[str]],
    question_validator: Callable[..., Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    """Run question_writer; on failure, swap to a fallback candidate once.

    Restricted to one retry on a distinct viable candidate — never loop.
    Mechanical templates and ReAct drafts stay banned; the fallback still
    goes through the same writer + validator path.
    """
    result = await generate_question_with_validation(
        selected_question=state.get("selected_question") or {},
        context_anchor=context_anchor,
        question_type=str(state.get("question_type") or "unknown"),
        llm_call=llm_call,
        validator=question_validator,
    )
    if result["status"] == "success":
        return {**result, "fallback_attempted": False}

    fallback = _pick_fallback_candidate(state)
    if fallback is None:
        return {**result, "fallback_attempted": False}

    logger.warning(
        "Question writer failed (error_code=%s); retrying with fallback candidate id=%s",
        result.get("error_code"),
        fallback.get("id"),
    )
    state["selected_question"] = fallback
    fallback_result = await generate_question_with_validation(
        selected_question=fallback,
        context_anchor=context_anchor,
        question_type=str(state.get("question_type") or "unknown"),
        llm_call=llm_call,
        validator=question_validator,
    )
    if fallback_result["status"] == "success":
        return {**fallback_result, "fallback_attempted": True}
    # Surface the original error_code as the diagnostic of record; the
    # fallback also failed, but the first failure is the more informative
    # one for the candidate-facing error event.
    return {**result, "fallback_attempted": True}


async def execute_turn_contract(
    *,
    state: dict[str, Any],
    contract: TurnContract,
    llm_call: Callable[[list[dict[str, str]]], Awaitable[str]],
    question_validator: Callable[
        ..., Awaitable[dict[str, Any]]
    ] = validate_question_adherence,
    summary_generator: Callable[..., Awaitable[str]] = generate_structured_summary,
) -> dict[str, Any]:
    """Return the only user-visible response permitted for *contract*."""
    context = _recent_context(state)
    action = contract.action

    if action == TurnContractAction.ASK_SELECTED_QUESTION:
        question_context = "\n\n".join(
            part
            for part in (
                f"候选人当前回答：{state.get('user_message') or ''}",
                f"最近对话：{context}",
                f"面试上下文：{state.get('interview_context') or ''}",
            )
            if part.strip()
        )
        result = await _run_question_writer_with_fallback(
            state=state,
            context_anchor=question_context,
            llm_call=llm_call,
            question_validator=question_validator,
        )
        if result["status"] != "success":
            error = _error(result, "question_writer")
            error["writer_trace"] = {
                "writer": "question_writer",
                "result": "error",
                "fallback_attempted": bool(result.get("fallback_attempted")),
            }
            return error
        validator = result.get("validator_result") or {}
        writer_trace = {
            "writer": "question_writer",
            "result": "success",
            "retry_count": result.get("retry_count", 0),
            "fallback_attempted": bool(result.get("fallback_attempted")),
        }
        return _validate_success(
            result["text"],
            writer_trace,
            contract,
            [
                {
                    "name": "semantic_question_adherence",
                    "blocking": True,
                    "passes": bool(validator.get("passes")),
                    "score": validator.get("score"),
                    "issues": validator.get("issues", []),
                    "reason": validator.get("reason", ""),
                }
            ],
        )

    if action == TurnContractAction.CLARIFY_CANDIDATE_ANSWER:
        result = await generate_clarification(
            candidate_answer=str(state.get("user_message") or ""),
            recent_context=context,
            llm_call=llm_call,
        )
        return (
            _validate_success(
                result["text"],
                {"writer": "clarify_writer", "result": "success"},
                contract,
            )
            if result["status"] == "success"
            else _error(result, "clarify_writer")
        )

    if action == TurnContractAction.ANSWER_COUNTER_QUESTION:
        result = await generate_counter_answer(
            candidate_question=str(state.get("user_message") or ""),
            topic=contract.payload.get("counter_question_topic"),
            recent_context=context,
            llm_call=llm_call,
        )
        return (
            _validate_success(
                result["text"],
                {"writer": "counter_writer", "result": "success"},
                contract,
            )
            if result["status"] == "success"
            else _error(result, "counter_writer")
        )

    if action == TurnContractAction.CONTINUE_NATURAL_FOLLOWUP:
        focus = str(
            contract.payload.get("next_focus")
            or (state.get("interview_state") or {}).get("next_focus")
            or ""
        )
        result = await generate_followup(
            candidate_answer=str(state.get("user_message") or ""),
            next_focus=focus,
            recent_context=context,
            turn_intent=state.get("turn_intent"),
            llm_call=llm_call,
        )
        return (
            _validate_success(
                result["text"],
                {"writer": "followup_writer", "result": "success"},
                contract,
            )
            if result["status"] == "success"
            else _error(result, "followup_writer")
        )

    closing = await generate_closing_utterance(
        closing_reason=str(contract.payload.get("closing_reason") or "turn_contract"),
        recent_context=context,
        llm_call=llm_call,
    )
    if closing["status"] != "success":
        return _error(closing, "closing_writer")
    closing_validator_trace = [
        {
            "name": "no_unrequested_summary",
            "blocking": True,
            "passes": not _contains_summary_content(closing["text"]),
        }
    ]
    try:
        summary = await summary_generator(state, allow_fallback=False)
    except Exception as exc:
        logger.warning("Structured summary generation failed: %s", exc)
        return {
            "status": "error",
            "error_code": "summary_generation_failed",
            "message": "面试总结生成失败，请稍后再试。",
            "writer_trace": {
                "writer": "closing_writer",
                "result": "success",
                "summary_writer": "error",
            },
            "validator_trace": [],
        }
    return _validate_success(
        f"{closing['text']}\n\n{summary}",
        {"writer": "closing_writer", "result": "success", "summary_writer": "success"},
        contract,
        closing_validator_trace,
    )
