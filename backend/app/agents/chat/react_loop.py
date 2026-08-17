"""ReAct loop core and supporting infrastructure.

Split from pipeline.py — contains the main autonomous tool-calling loop,
budget control, tool validation, trace logging, and event emission.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import AsyncGenerator

from app.agents.chat.answer import (
    OutputDeduplicator,
    _stream_final_answer,  # kept for backward compat, no longer called in main path
)
from app.agents.chat.chat_constants import PUBLIC_QUESTION_PREVIEW_LIMIT
from app.agents.chat.routing import should_record_retrieval_gap
from app.agents.chat.metadata import _extract_company, _extract_round
from app.agents.chat.nodes import (
    _build_next_question_plan_prompt,
    build_react_system_prompt,  # noqa: F401 - compatibility for existing imports/tests
    build_react_prompt_parts,
    build_runtime_tool_contract_message,
)
from app.agents.chat.prompt_cache import build_prompt_cache_fingerprint
from app.agents.chat.question_plan import (
    _build_previously_asked_section,
    _build_repetition_protection_note,
    _maybe_create_question_plan,
)
from app.agents.chat.state import ChatState
from app.agents.chat.stop_policy import evaluate_interview_stop
from app.agents.chat.tool_gateway import validate_tool_arguments
from app.agents.chat.tool_policy import (
    ToolPolicy,
    ToolPolicyViolation,
    build_tool_policy,
    enforce_tool_call,
)
from app.agents.chat.summary import (
    _generate_structured_summary,
)
from app.agents.chat.writers.closing_writer import generate_closing_utterance
from app.agents.chat.trace import build_skill_trace_from_tool, build_tool_trace
from app.agents.chat import tools as chat_tools
from app.agents.shared.events import _event_queue_var
from app.services import llm as llm_service
from app.services.llm import make_tool_result_message

logger = logging.getLogger("interview-boss")

MAX_REACT_STEPS = 5
FINAL_ANSWER_STREAM_MAX_ATTEMPTS = 3
FINAL_ANSWER_ERROR_MESSAGE = "模型生成失败，已重试 3 次，请稍后再试。"
_TRACE_STRING_LIMIT = 120
_TRACE_LIST_LIMIT = 5
_SAFE_TOOL_ARG_KEYS = {
    "cat1",
    "count",
    "difficulty",
    "keywords",
    "question_type",
    "skill_name",
    "topic",
    "capability",
    "interview_format",
}
_ALLOWED_TOOL_NAMES = frozenset(
    {
        "load_skill",
        "search_questions",
        "draw_questions",
        "select_question",
        "search_agent_private_questions",
        "draw_agent_private_questions",
        "select_agent_private_question",
    }
)
_PERSISTENT_SKILLS = frozenset({"interview-rhythm"})


# ── ReAct Budget & Control ──────────────────────────────


@dataclass(frozen=True)
class Budget:
    """Three-dimensional runtime budget for the ReAct loop."""

    max_steps: int = 5
    max_tool_calls: int = 10
    max_seconds: float = 30.0


class StopRun(Exception):
    """Raised when the ReAct loop must stop for a governance reason."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


REACT_BUDGET = Budget()


# ── Event Emission ────────────────────────────────────────


def _emit(event: dict) -> None:
    queue = _event_queue_var.get()
    if queue:
        queue.put_nowait(event)


def _step(step: str, message: str, reason: str = "", insight: str = "") -> None:
    event: dict = {"type": "step", "step": step, "message": message}
    if reason:
        event["reason"] = reason
    if insight:
        event["insight"] = insight
    _emit(event)


# ── Step reason templates ─────────────────────────────────────
STEP_REASONS = {
    "loading": "加载最近 20 条对话历史和用户记忆，为理解问题提供上下文",
    "context": "构建面试上下文，包含简历和 JD 信息",
    "understanding_first": "首次消息快速分类，确定面试开场策略",
    "understanding_follow": "分析你的回答质量，决定下一步追问方向",
    "load_skill": "根据对话阶段加载对应的面试技巧",
    "search_questions": "根据你的问题关键词，从题库检索相关面试题",
    "draw_questions": "从题库随机抽取一道面试题",
    "generating": "综合上下文和检索结果，生成口述级回答",
    "closing": "面试已达到足够轮次，生成总结评价",
}


# ── Tool Validation ───────────────────────────────────────


def validate_tool_call(tool_call: dict, policy: ToolPolicy | None = None) -> dict:
    """Validate a tool call from the LLM before execution.

    Enforces the global allowlist, the current execution policy, and strict
    per-tool argument schemas.  ``policy`` remains optional for legacy pure
    callers; the live ReAct loop always supplies it.
    Returns the validated tool call dict, or raises StopRun.
    """
    try:
        # A pure caller has no state from which to derive policy. Keep its
        # historical global/schema validation while live callers pass state.
        if policy is None:
            func = tool_call.get("function")
            name = func.get("name") if isinstance(func, dict) else ""
            if not isinstance(func, dict) or not name:
                raise StopRun("invalid_tool_call")
            if name not in _ALLOWED_TOOL_NAMES:
                raise StopRun(f"tool_denied:{name}")
            validate_tool_arguments(name, func.get("arguments", "{}"))
            return tool_call
        return enforce_tool_call(tool_call, {}, policy)
    except ToolPolicyViolation as exc:
        reason = {
            "TOOL_NOT_ALLOWED": "tool_denied",
            "UNKNOWN_TOOL": "tool_denied",
            "SKILL_NOT_ALLOWED": "skill_not_allowed",
            "INVALID_TOOL_ARGUMENTS": "invalid_args",
        }.get(exc.code, "invalid_tool_call")
        name = tool_call.get("function", {}).get("name", "") if isinstance(tool_call, dict) else ""
        raise StopRun(f"{reason}:{name}") from exc
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        name = tool_call.get("function", {}).get("name", "") if isinstance(tool_call, dict) else ""
        raise StopRun(f"invalid_args:{name}") from exc


# ── Tracing ───────────────────────────────────────────────


def _trace_safe_value(value):
    """Keep ReAct trace fields compact and free of arbitrary payloads."""
    if isinstance(value, str):
        return value[:_TRACE_STRING_LIMIT]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple, set)):
        return [_trace_safe_value(v) for v in list(value)[:_TRACE_LIST_LIMIT]]
    if isinstance(value, dict):
        return {
            str(k)[:40]: _trace_safe_value(v)
            for k, v in list(value.items())[:_TRACE_LIST_LIMIT]
        }
    return str(type(value).__name__)


def _sanitize_tool_args(tool_call: dict) -> dict:
    raw_args = tool_call.get("function", {}).get("arguments", "{}")
    try:
        args = json.loads(raw_args or "{}")
    except (TypeError, json.JSONDecodeError):
        return {"_parse_error": "invalid_json"}

    if not isinstance(args, dict):
        return {"_shape": type(args).__name__}

    sanitized = {}
    for key, value in args.items():
        if key in _SAFE_TOOL_ARG_KEYS:
            sanitized[key] = _trace_safe_value(value)
        else:
            sanitized[key] = "<redacted>"
    return sanitized


def _summarize_tool_output(tool_name: str, output: str, state: ChatState) -> dict:
    summary: dict[str, object] = {"ok": True}
    try:
        parsed = json.loads(output or "null")
    except (TypeError, json.JSONDecodeError):
        parsed = None
        summary["ok"] = False
        summary["error"] = "invalid_json_output"

    if isinstance(parsed, dict) and parsed.get("error"):
        summary["ok"] = False
        summary["error"] = str(parsed["error"])[:_TRACE_STRING_LIMIT]

    if tool_name == "load_skill":
        summary["active_skills"] = list(state.get("active_skills", []))
        if isinstance(parsed, dict) and "ok" in parsed:
            summary["ok"] = bool(parsed.get("ok"))
            if not summary["ok"] and parsed.get("error"):
                summary["error"] = str(
                    parsed["error"].get("error_code") or "tool_error"
                )[:_TRACE_STRING_LIMIT]
        return summary

    if tool_name in {
        "search_questions",
        "draw_questions",
        "select_question",
        "search_agent_private_questions",
        "draw_agent_private_questions",
        "select_agent_private_question",
    }:
        if (
            isinstance(parsed, dict)
            and "ok" in parsed
            and ("items" in parsed or "selected_question" in parsed)
        ):
            summary["ok"] = bool(parsed.get("ok"))
            if not summary["ok"] and parsed.get("error"):
                error = parsed.get("error") or {}
                summary["error"] = str(error.get("error_code") or "tool_error")[
                    :_TRACE_STRING_LIMIT
                ]
            if tool_name == "select_question" and parsed.get("selected_question"):
                selected = parsed["selected_question"]
                summary["result_count"] = 1
                summary["result_ids"] = (
                    [selected.get("id")]
                    if isinstance(selected, dict) and selected.get("id") is not None
                    else []
                )
            else:
                items = (
                    parsed.get("items") if isinstance(parsed.get("items"), list) else []
                )
                summary["result_count"] = len(items)
                summary["result_ids"] = [
                    q.get("id")
                    for q in items[:_TRACE_LIST_LIMIT]
                    if isinstance(q, dict) and q.get("id") is not None
                ]
            metadata = parsed.get("metadata") or {}
            summary["fallback_used"] = bool(metadata.get("fallback_used", False))
            summary["empty_reason"] = metadata.get("empty_reason")
            return summary

        results = (
            [] if not summary["ok"] else state.get("retrieved_questions", []) or []
        )
        summary["result_count"] = len(results)
        summary["result_ids"] = [
            q.get("id")
            for q in results[:_TRACE_LIST_LIMIT]
            if isinstance(q, dict) and q.get("id") is not None
        ]
        return summary

    if parsed is not None:
        summary["output_type"] = type(parsed).__name__
    return summary


def _log_react_llm_step(
    state: ChatState,
    *,
    react_step: int,
    finish_reason: str | None,
    tool_count: int,
    elapsed_ms: int,
    cache_fingerprint: str | None = None,
    cache_usage: dict | None = None,
) -> None:
    logger.info(
        "ReAct trace: event=llm_step conversation_id=%s react_step=%s "
        "finish_reason=%s tool_count=%s elapsed_ms=%s "
        "cache_fingerprint=%s cached_input_tokens=%s input_tokens=%s",
        state.get("conversation_id"),
        react_step,
        finish_reason,
        tool_count,
        elapsed_ms,
        cache_fingerprint,
        (cache_usage or {}).get("cached_input_tokens"),
        (cache_usage or {}).get("input_tokens"),
    )


def _log_react_tool_call(
    state: ChatState,
    *,
    react_step: int,
    tool_name: str,
    args: dict,
    result: dict,
    elapsed_ms: int,
) -> None:
    logger.info(
        "ReAct trace: event=tool_call conversation_id=%s react_step=%s "
        "tool_name=%s args=%s result=%s elapsed_ms=%s",
        state.get("conversation_id"),
        react_step,
        tool_name,
        args,
        result,
        elapsed_ms,
    )


def _record_tool_observability(
    state: ChatState,
    *,
    tool_name: str,
    tool_call: dict,
    summary: dict,
    elapsed_ms: int,
    message: str,
    output: str = "",
) -> dict:
    private_tool = tool_name in {
        "search_agent_private_questions",
        "draw_agent_private_questions",
        "select_agent_private_question",
    }
    public_tool_name = "agent_question_engine" if private_tool else tool_name
    step_data = {
        "step": public_tool_name,
        "tool_name": public_tool_name,
        "message": message,
        "elapsed_ms": elapsed_ms,
        "result_count": summary.get("result_count", 0),
        "fallback_used": summary.get("fallback_used", False),
    }
    state.setdefault("tool_steps", []).append(step_data)
    trace = build_tool_trace(tool_name, tool_call, summary, elapsed_ms, state, output)
    trace["message"] = message
    state.setdefault("tool_calls_trace", []).append(trace)
    skill_trace = build_skill_trace_from_tool(tool_name, tool_call, summary)
    if skill_trace:
        state.setdefault("skill_trace", []).append(skill_trace)
    _emit({"type": "tool_step", "data": step_data})
    return step_data


def _emit_reasoning_content(reasoning_content: str | None, elapsed_ms: int) -> None:
    """Bridge OpenAI-compatible reasoning_content into public thinking events."""
    if not isinstance(reasoning_content, str) or not reasoning_content.strip():
        return
    duration = round(max(elapsed_ms, 0) / 1000, 1)
    _emit({"type": "thinking_start", "content": ""})
    _emit({"type": "thinking", "content": reasoning_content})
    _emit(
        {
            "type": "thinking_done",
            "duration": duration,
            "content": reasoning_content,
        }
    )


# ── Closing Context ──────────────────────────────────────


def _build_closing_context(state: ChatState) -> str:
    """为 closing_writer 构建最近面试上下文。"""
    history = state.get("message_history", []) or []
    recent = history[-6:] if len(history) > 6 else history
    lines: list[str] = []
    for msg in recent:
        role = "面试官" if msg.get("role") == "assistant" else "候选人"
        content = str(msg.get("content") or "")[:100]
        if content.strip():
            lines.append(f"{role}: {content}")
    session_notes = state.get("session_notes", "") or ""
    context = "\n".join(lines)
    if session_notes:
        context += f"\n\n面试备注: {session_notes[:200]}"
    return context


async def _generate_close_with_summary(
    state: ChatState,
    closing_reason: str,
) -> dict:
    """Generate the required natural close and structured summary atomically."""
    closing_result = await generate_closing_utterance(
        closing_reason=closing_reason,
        recent_context=_build_closing_context(state),
        llm_call=lambda msgs: llm_service._call_llm_with_retry_messages(
            msgs, user_id=state.get("user_id")
        ),
    )
    if closing_result["status"] != "success":
        return {
            "status": "error",
            "error_code": closing_result.get("error_code", "closing_generation_failed"),
            "message": closing_result.get("message", "自然收尾语生成失败"),
            "writer_trace": {"writer": "closing_writer", "result": "error"},
        }

    try:
        summary_text = await _generate_structured_summary(state, allow_fallback=False)
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
        }

    return {
        "status": "success",
        "text": f"{closing_result['text']}\n\n{summary_text}",
        "writer_trace": {
            "writer": "closing_writer",
            "result": "success",
            "summary_writer": "success",
        },
    }


# ── ReAct Loop ────────────────────────────────────────────


def _record_retrieval_gap(state: ChatState, tool_names: list[str]) -> None:
    """Record that retrieval was recommended but the model answered directly."""
    state["retrieval_gap"] = {
        "reason": "model_answered_without_retrieval",
        "intent": state.get("intent"),
        "answer_quality": state.get("answer_quality"),
        "should_retrieve": bool(state.get("should_retrieve")),
        "requires_bank_question": bool(state.get("requires_bank_question")),
        "tool_names": tool_names,
    }
    state.setdefault("question_source", "conversation")
    state.setdefault(
        "question_source_reason",
        "retrieval_recommended_but_skipped",
    )


async def _prepare_distribution_primary_question(state: ChatState) -> bool:
    """Deterministically bind the controller-selected primary question.

    A distribution plan is a product control, so it cannot depend on whether
    the ReAct model happens to make a tool call.  The normal writer still owns
    wording and validation after this function has supplied its bank-backed
    question.
    """

    control = state.get("distribution_control") or {}
    question_type = control.get("preferred_type")
    if not state.get("distribution_primary_required") or not question_type:
        return False

    tool_call = {
        "id": "distribution-controlled-draw",
        "function": {
            "name": "draw_questions",
            "arguments": json.dumps(
                {"count": 5, "question_type": question_type}, ensure_ascii=False
            ),
        },
    }
    _emit(
        {
            "type": "step",
            "step": "draw_questions",
            "message": "正在按面试分布从题库抽题...",
            "reason": "distribution_plan_target_deficit",
        }
    )
    output = await chat_tools.execute_tool(tool_call, state)
    plan = _maybe_create_question_plan(state)
    reused_cross_conversation_question = False
    if not plan or not state.get("selected_question"):
        # The distribution plan must remain feasible when the user has already
        # seen every compatible question in earlier conversations.  Keep the
        # current-conversation exclusion ledger intact, but retry once without
        # the cross-conversation exclusion set and record that fallback.
        state["distribution_allow_cross_conversation_reuse"] = True
        output = await chat_tools.execute_tool(tool_call, state)
        plan = _maybe_create_question_plan(state)
        reused_cross_conversation_question = bool(plan and state.get("selected_question"))
    try:
        envelope = json.loads(output)
    except (TypeError, json.JSONDecodeError):
        envelope = {}
    if plan and state.get("selected_question"):
        control["selection_status"] = "bound"
        control["selected_question_id"] = state["selected_question"].get("id")
        control["cross_conversation_reuse"] = reused_cross_conversation_question
        return True

    control["selection_status"] = "pool_exhausted"
    control["tool_error"] = (envelope.get("error") or {}).get("error_code")
    control["selection_reason"] = state.get("question_plan_reason") or "no_viable_candidate"
    state["question_source_reason"] = "distribution_type_pool_exhausted"
    # Continue the interview conversationally, but metadata must not report a
    # fabricated completed primary question for this plan.
    state["distribution_primary_required"] = False
    return False
async def _stream_final_answer_with_retry(
    messages: list[dict],
    state: ChatState,
) -> AsyncGenerator[dict, None]:
    """Stream the final answer with bounded retries, never synthetic fallback.

    DEPRECATED: No longer called in the main _react_loop path. The final answer
    is now taken directly from the ReAct decision phase and processed through
    the quality pipeline without a second LLM streaming call. Kept for backward
    compatibility and potential future use.
    """
    retry_should_replace = False
    streamed_any = False

    for attempt in range(1, FINAL_ANSWER_STREAM_MAX_ATTEMPTS + 1):
        try:
            first_replacement_chunk = retry_should_replace
            async for event in _stream_final_answer(messages, state):
                if (
                    first_replacement_chunk
                    and event.get("type") == "chunk"
                    and event.get("content")
                ):
                    event = {**event, "replace": True}
                    first_replacement_chunk = False
                    retry_should_replace = False
                if event.get("type") == "chunk" and event.get("content"):
                    streamed_any = True
                yield event
            return
        except Exception as e:
            if streamed_any:
                retry_should_replace = True
            logger.warning(
                "ReAct trace: event=final_answer_retry conversation_id=%s "
                "attempt=%s max_attempts=%s reason=%s",
                state.get("conversation_id"),
                attempt,
                FINAL_ANSWER_STREAM_MAX_ATTEMPTS,
                type(e).__name__,
                exc_info=True,
            )

    state["final_answer_error"] = {
        "reason": "stream_generation_failed",
        "attempts": FINAL_ANSWER_STREAM_MAX_ATTEMPTS,
    }
    yield {"type": "error", "message": FINAL_ANSWER_ERROR_MESSAGE}


async def _react_loop(state: ChatState) -> AsyncGenerator[dict, None]:
    """ReAct loop: LLM autonomously selects tools, then streams final answer.

    Flow:
    1. Build a stable system prefix and dynamic context suffix
    2. Build messages
    3. ReAct loop: LLM calls tools or answers directly
    4. Stream final answer
    """
    stop_decision = evaluate_interview_stop(state)
    state["interview_stop_decision"] = stop_decision
    if stop_decision["action"] == "ask_candidate_question":
        state["question_source"] = "conversation"
        state["question_source_reason"] = stop_decision["reason"]
        _emit(
            {
                "type": "step",
                "step": "closing",
                "message": "正在进入反问收尾...",
                "reason": STEP_REASONS["closing"],
            }
        )
        from app.agents.chat.contract_executor import execute_turn_contract
        from app.agents.chat.turn_contract import plan_turn

        contract = plan_turn(state)
        state["turn_contract"] = contract.to_metadata_dict()
        result = await execute_turn_contract(
            state=state,
            contract=contract,
            llm_call=lambda msgs: llm_service._call_llm_with_retry_messages(
                msgs, user_id=state.get("user_id")
            ),
        )
        state["writer_trace"] = result.get("writer_trace") or {}
        state["validator_trace"] = result.get("validator_trace") or []
        if result["status"] != "success":
            state["generation_error_code"] = result.get("error_code")
        if result["status"] != "success":
            yield {"type": "error", "message": result["message"], "code": result["error_code"]}
            yield {"type": "done", "metadata": {"writer_trace": state["writer_trace"]}}
            return
        state["closing_stage"] = "candidate_question_asked"
        yield {"type": "chunk", "content": result["text"]}
        yield {
            "type": "done",
            "metadata": {
                "closing_stage": "candidate_question_asked",
                "writer_trace": state["writer_trace"],
                "validator_trace": state["validator_trace"],
            },
        }
        return

    if stop_decision["action"] == "close":
        state["question_source"] = "conversation"
        state["question_source_reason"] = stop_decision["reason"]
        _emit(
            {
                "type": "step",
                "step": "closing",
                "message": "正在收尾面试...",
                "reason": STEP_REASONS["closing"],
            }
        )

        from app.agents.chat.contract_executor import execute_turn_contract
        from app.agents.chat.turn_contract import plan_turn

        contract = plan_turn(state)
        state["turn_contract"] = contract.to_metadata_dict()
        close_result = await execute_turn_contract(
            state=state,
            contract=contract,
            llm_call=lambda msgs: llm_service._call_llm_with_retry_messages(
                msgs, user_id=state.get("user_id")
            ),
        )
        state["writer_trace"] = close_result.get("writer_trace") or {}
        state["validator_trace"] = close_result.get("validator_trace") or []
        if close_result["status"] != "success":
            state["generation_error_code"] = close_result.get("error_code")
        if close_result["status"] != "success":
            yield {
                "type": "error",
                "message": close_result["message"],
                "code": close_result["error_code"],
            }
            yield {"type": "done", "metadata": {"writer_trace": state["writer_trace"]}}
            return

        # Mark closing_stage as closed after summary
        state["closing_stage"] = "closed"
        yield {"type": "chunk", "content": close_result["text"]}
        yield {
            "type": "done",
            "metadata": {
                "closing_stage": "closed",
                "has_summary": True,
                "writer_trace": state["writer_trace"],
                "validator_trace": state["validator_trace"],
            },
        }
        return

    await _prepare_distribution_primary_question(state)

    # 1. Build a stable system prefix and a dynamic context suffix.  The
    # provider can only reuse a prompt/KV prefix when it is byte-for-byte
    # identical, so turn-scoped data must not be placed in messages[0].
    prompt_parts = build_react_prompt_parts(state)
    state["active_skill_instructions"] = []  # consumed; skills baked into dynamic context

    # 1.5 Inject repetition protection if needed
    repetition_note = _build_repetition_protection_note(state)
    if repetition_note:
        prompt_parts["dynamic_context"] += f"\n\n{repetition_note}"

    # 2. Build messages
    messages: list[dict] = [
        {"role": "system", "content": prompt_parts["stable_system_prompt"]},
        {"role": "system", "content": prompt_parts["dynamic_context"]},
    ]
    tools = chat_tools.get_tools_for_state(state)
    cache_fingerprint = build_prompt_cache_fingerprint(
        prompt_parts["stable_system_prompt"], tools, state.get("model")
    )

    # Recent messages
    for msg in state.get("recent_messages", [])[-10:]:
        role = msg.get("role", "user")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": msg.get("content", "")})

    # Inject PREVIOUSLY ASKED as dynamic user message (not in cached system prompt)
    asked_section = _build_previously_asked_section(state)
    if asked_section:
        messages.append({"role": "user", "content": asked_section})

    tool_contract = build_runtime_tool_contract_message(state)
    if tool_contract:
        messages.append({"role": "user", "content": tool_contract})

    # Current user message
    messages.append({"role": "user", "content": state["user_message"]})

    # 3. ReAct loop
    react_started = time.monotonic()
    tool_call_count = 0
    # Tracks whether any search_questions/draw_questions was actually executed
    # in this turn. If retrieval was recommended but skipped, we record that
    # as metadata instead of forcing a second tool-calling pass.
    search_or_draw_called = False
    tool_names_seen: list[str] = []
    seen_tool_calls: set[str] = set()
    stop_reason = ""
    final_answer_text = ""
    for step in range(REACT_BUDGET.max_steps):
        react_step = step + 1
        # Budget checks
        if tool_call_count >= REACT_BUDGET.max_tool_calls:
            stop_reason = "max_tool_calls"
            break
        if time.monotonic() - react_started > REACT_BUDGET.max_seconds:
            stop_reason = "max_seconds"
            break
        # A loaded skill changes only the dynamic suffix.  Keep the stable
        # system prefix untouched so the next request can still reuse it when
        # the provider supports prefix caching.
        if step > 0 and state.get("active_skill_instructions"):
            prompt_parts = build_react_prompt_parts(state)
            if repetition_note:
                prompt_parts["dynamic_context"] += f"\n\n{repetition_note}"
            messages[1] = {
                "role": "system",
                "content": prompt_parts["dynamic_context"],
            }
            state["active_skill_instructions"] = []  # consumed
        llm_started = time.monotonic()
        try:
            result = await llm_service.llm_with_tools(
                messages,
                tools,
                user_id=state["user_id"],
                model=state.get("model"),
                prompt_cache_key=cache_fingerprint,
            )
        except Exception as e:
            logger.error(f"ReAct step {step} LLM call failed: {e}")
            stop_reason = "react_llm_failed"
            break

        llm_elapsed_ms = int((time.monotonic() - llm_started) * 1000)
        _emit_reasoning_content(result.get("reasoning_content"), llm_elapsed_ms)

        tool_calls = result.get("tool_calls") or []
        _log_react_llm_step(
            state,
            react_step=react_step,
            finish_reason=result.get("finish_reason"),
            tool_count=len(tool_calls),
            elapsed_ms=llm_elapsed_ms,
            cache_fingerprint=cache_fingerprint,
            cache_usage=result.get("usage"),
        )
        state.setdefault("llm_usage_trace", []).append(
            {
                "react_step": react_step,
                "prompt_cache_fingerprint": cache_fingerprint,
                "usage": result.get("usage") or {},
            }
        )

        if not tool_calls:
            content = result.get("content")
            if isinstance(content, str) and content.strip():
                final_answer_text = content
            break  # LLM decided to answer directly

        # Append assistant message with tool_calls
        messages.append(
            {
                "role": "assistant",
                "content": result.get("content"),
                "tool_calls": tool_calls,
            }
        )

        # Execute each tool call
        for tc in tool_calls:
            # Validate before execution
            try:
                tc = validate_tool_call(tc, build_tool_policy(state))
            except StopRun as exc:
                stop_reason = exc.reason
                logger.warning(
                    "ReAct trace: event=validation_failed conversation_id=%s "
                    "react_step=%s reason=%s",
                    state.get("conversation_id"),
                    react_step,
                    exc.reason,
                )
                messages.append(
                    make_tool_result_message(
                        tc.get("id", "invalid"),
                        json.dumps({"error": exc.reason}),
                    )
                )
                break  # break inner loop, outer loop will check stop_reason

            # Loop detection
            try:
                sig_args = tc["function"]["arguments"]
                if isinstance(sig_args, str):
                    sig_args = json.loads(sig_args)
                call_sig = f"{tc['function']['name']}:{json.dumps(sig_args, sort_keys=True, ensure_ascii=False)}"
            except (json.JSONDecodeError, TypeError, KeyError):
                call_sig = f"{tc.get('function', {}).get('name', '?')}:unparseable"
            if call_sig in seen_tool_calls:
                stop_reason = "loop_detected"
                logger.warning(
                    "ReAct trace: event=loop_detected conversation_id=%s "
                    "react_step=%s tool=%s",
                    state.get("conversation_id"),
                    react_step,
                    tc["function"]["name"],
                )
                messages.append(
                    make_tool_result_message(
                        tc.get("id", "loop"),
                        json.dumps(
                            {
                                "error": "loop_detected",
                                "message": "Same tool call repeated — stopping.",
                            }
                        ),
                    )
                )
                break
            seen_tool_calls.add(call_sig)

            tool_call_count += 1

            tool_name = tc["function"]["name"]
            tool_names_seen.append(tool_name)
            tool_args = _sanitize_tool_args(tc)

            # Emit progress
            step_event = {
                "type": "step",
                "step": "agent_question_engine"
                if tool_name in {
                    "search_agent_private_questions",
                    "draw_agent_private_questions",
                    "select_agent_private_question",
                }
                else tool_name,
                "message": chat_tools.tool_progress_message(tc),
                "reason": STEP_REASONS.get(tool_name, ""),
            }
            # Add skill_name for load_skill observability
            if tool_name == "load_skill":
                raw_args = tc["function"]["arguments"]
                if isinstance(raw_args, dict):
                    skill_args = raw_args
                else:
                    skill_args = json.loads(raw_args)
                step_event["skill_name"] = skill_args.get("skill_name", "")
            _emit(step_event)

            # Execute tool
            tool_started = time.monotonic()
            output = await chat_tools.execute_tool(tc, state)
            tool_elapsed_ms = int((time.monotonic() - tool_started) * 1000)
            tool_summary = _summarize_tool_output(tool_name, output, state)
            _log_react_tool_call(
                state,
                react_step=react_step,
                tool_name=tool_name,
                args=tool_args,
                result=tool_summary,
                elapsed_ms=tool_elapsed_ms,
            )

            # Record a metadata-only tool summary for frontend observability.
            if tool_name in (
                "search_questions",
                "draw_questions",
                "select_question",
                "load_skill",
                "search_agent_private_questions",
                "draw_agent_private_questions",
                "select_agent_private_question",
            ):
                _record_tool_observability(
                    state,
                    tool_name=tool_name,
                    tool_call=tc,
                    summary=tool_summary,
                    elapsed_ms=tool_elapsed_ms,
                    message=chat_tools.tool_progress_message(tc),
                    output=output,
                )

            if tool_name in (
                "search_questions",
                "draw_questions",
                "search_agent_private_questions",
                "draw_agent_private_questions",
            ):
                search_or_draw_called = True
                _maybe_create_question_plan(state)

            # Emit retrieved events for search/draw results
            if tool_name in (
                "search_questions",
                "draw_questions",
                "search_agent_private_questions",
                "draw_agent_private_questions",
            ) and state.get("retrieved_questions") and tool_name not in {
                "search_agent_private_questions",
                "draw_agent_private_questions",
            }:
                _emit(
                    {
                        "type": "retrieved",
                        "questions": [
                            {
                                "id": q.get("id"),
                                "question": q.get("question", ""),
                                "cat1": q.get("cat1", ""),
                                "cat2": q.get("cat2", ""),
                                "company": _extract_company(q),
                                "round": _extract_round(q),
                            }
                            for q in state["retrieved_questions"][
                                :PUBLIC_QUESTION_PREVIEW_LIMIT
                            ]
                        ],
                    }
                )

            # Emit insight events for user-visible decision points
            if tool_name == "load_skill":
                skill_label = (
                    chat_tools.tool_progress_message(tc)
                    .replace("正在加载", "")
                    .replace("...", "")
                )
                _emit({"type": "insight", "text": f"切换到{skill_label}模式"})
            elif tool_name in ("search_questions", "draw_questions") and state.get(
                "retrieved_questions"
            ):
                top_q = (
                    state["retrieved_questions"][0]
                    if state["retrieved_questions"]
                    else None
                )
                if top_q:
                    topic = top_q.get("cat2") or top_q.get("cat1") or "相关技术"
                    _emit(
                        {
                            "type": "insight",
                            "text": f"从题库检索到关于「{topic}」的题目",
                        }
                    )

            # 3d: Pre-prune search/draw tool output to top 3 before appending to messages.
            # Full results remain in state["retrieved_questions"] for downstream use.
            msg_output = output
            if tool_name in (
                "search_questions",
                "draw_questions",
                "search_agent_private_questions",
                "draw_agent_private_questions",
            ):
                try:
                    parsed_out = json.loads(output)
                    if isinstance(parsed_out, dict) and isinstance(
                        parsed_out.get("items"), list
                    ):
                        parsed_out = {**parsed_out, "items": parsed_out["items"][:3]}
                        msg_output = json.dumps(parsed_out, ensure_ascii=False)
                    elif isinstance(parsed_out, list) and len(parsed_out) > 3:
                        msg_output = json.dumps(parsed_out[:3], ensure_ascii=False)
                except (json.JSONDecodeError, TypeError):
                    pass
            messages.append(make_tool_result_message(tc["id"], msg_output))
            plan = state.get("next_question_plan")
            if (
                tool_name in (
                    "search_questions",
                    "draw_questions",
                    "select_question",
                    "search_agent_private_questions",
                    "draw_agent_private_questions",
                    "select_agent_private_question",
                )
                and plan
                and not state.get("question_plan_injected")
            ):
                plan_prompt = _build_next_question_plan_prompt(plan)
                if plan_prompt:
                    messages.append(
                        {
                            "role": "user",
                            "content": "[系统自动生成的下一题约束]\n" + plan_prompt,
                        }
                    )
                    state["question_plan_injected"] = True

        # If inner loop broke due to validation failure or loop detection, exit outer loop
        if stop_reason:
            break

        # 3d: Prune old tool results (>5 turns ago) to a 1-line summary.
        # Keeps context lean without losing the fact that a tool was called.
        _msg_end = len(messages)
        for _mi, _msg in enumerate(messages):
            if _msg.get("role") == "tool" and (_msg_end - _mi) > 5:
                _msg["content"] = "[已裁剪的工具输出]"

        if react_step == REACT_BUDGET.max_steps:
            stop_reason = "max_steps"

    # Log stop reason
    if stop_reason:
        logger.warning(
            "ReAct trace: event=stopped conversation_id=%s reason=%s "
            "steps=%s tool_calls=%s elapsed_ms=%s",
            state.get("conversation_id"),
            stop_reason,
            react_step,
            tool_call_count,
            int((time.monotonic() - react_started) * 1000),
        )

    # 3.5 If max_steps hit without a final answer, force synthesis from
    # accumulated tool results instead of surfacing an error.
    if stop_reason == "max_steps" and not final_answer_text:
        logger.info(
            "ReAct trace: event=max_steps_synthesize conversation_id=%s "
            "tool_calls=%s",
            state.get("conversation_id"),
            tool_call_count,
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    "【系统提示】你已经搜索了足够多的题目。"
                    "请基于已有的搜索结果，直接输出面试官对候选人的下一个问题。"
                    "不要再调用任何工具，直接用文字回复。"
                ),
            }
        )
        try:
            from app.services.llm import raw_llm_call

            result_text = await raw_llm_call(
                user_id=state["user_id"],
                model=state.get("model"),
                messages=messages,
                temperature=0.7,
                max_tokens=1024,
            )
            if result_text and result_text.strip():
                final_answer_text = result_text.strip()
        except Exception as e:
            logger.error("max_steps synthesis failed: %s", e)

    # 3.6 Retrieval gap observability. Retrieval recommendations are part of
    # the strategy prompt, not a post-hoc control-flow takeover.
    if (
        not stop_reason
        and should_record_retrieval_gap(state)
        and not search_or_draw_called
    ):
        _record_retrieval_gap(state, tool_names_seen)

    # 4. Stream final answer
    _emit(
        {
            "type": "step",
            "step": "generating",
            "message": "正在生成回答...",
            "reason": STEP_REASONS["generating"],
        }
    )
    if stop_reason == "react_llm_failed":
        state["final_answer_error"] = {
            "reason": "react_llm_failed",
            "attempts": 0,
        }
        yield {"type": "error", "message": "模型决策失败，请稍后再试。"}
    elif stop_reason == "max_seconds":
        state["final_answer_error"] = {
            "reason": "react_loop_timeout",
            "attempts": 0,
        }
        yield {"type": "error", "message": "模型生成超时，请稍后再试。"}
    else:
        # ReAct content is evidence only. Empty content is valid once tools
        # have completed; a contract writer owns all user-visible wording.
        state["react_evidence_draft"] = final_answer_text
        from app.agents.chat.contract_executor import execute_turn_contract
        from app.agents.chat.turn_contract import plan_turn

        contract = plan_turn(state)
        state["turn_contract"] = contract.to_metadata_dict()
        result = await execute_turn_contract(
            state=state,
            contract=contract,
            llm_call=lambda msgs: llm_service._call_llm_with_retry_messages(
                msgs, user_id=state.get("user_id")
            ),
        )
        state["writer_trace"] = result.get("writer_trace") or {}
        state["validator_trace"] = result.get("validator_trace") or []
        if result["status"] != "success":
            state["generation_error_code"] = result.get("error_code")
        if result["status"] != "success":
            yield {
                "type": "error",
                "message": result["message"],
                "code": result["error_code"],
            }
        else:
            final_text = result["text"]
            deduplicator = state.setdefault("output_deduplicator", OutputDeduplicator())
            dedup_result = deduplicator.check(final_text)
            if dedup_result != "ok":
                logger.info(
                    "ReAct trace: event=output_dedup conversation_id=%s result=%s",
                    state.get("conversation_id"),
                    dedup_result,
                )
            deduplicator.record(final_text)
            metadata = {
                "writer_trace": state["writer_trace"],
                "validator_trace": state["validator_trace"],
            }
            if contract.action.value == "close_with_summary":
                state["closing_stage"] = "closed"
                metadata.update({"closing_stage": "closed", "has_summary": True})
            yield {"type": "chunk", "content": final_text}
            yield {"type": "done", "metadata": metadata}
            return

    yield {"type": "done"}
