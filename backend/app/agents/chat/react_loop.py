"""ReAct loop core and supporting infrastructure.

Split from pipeline.py — contains the main autonomous tool-calling loop,
budget control, tool validation, trace logging, and event emission.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import AsyncGenerator

from app.agents.chat.answer import (
    OutputDeduplicator,
    _ensure_final_answer_quality,
    _fallback_interviewer_response,
    _fallback_react_answer,
    _final_answer_events_from_text,
    _is_internal_react_marker,
    _stream_final_answer,
)
from app.agents.chat.metadata import _extract_company, _extract_round
from app.agents.chat.nodes import (
    _build_next_question_plan_prompt,
    build_react_system_prompt,
)
from app.agents.chat.question_plan import (
    _build_previously_asked_section,
    _build_repetition_protection_note,
    _maybe_create_question_plan,
    _should_require_bank_question,
)
from app.agents.chat.state import ChatState
from app.agents.chat.summary import _forced_closing_response
from app.agents.chat import tools as chat_tools
from app.agents.shared.events import _event_queue_var
from app.services import llm as llm_service
from app.services.llm import make_tool_result_message

logger = logging.getLogger("interview-boss")

MAX_REACT_STEPS = 5
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
}
_ALLOWED_TOOL_NAMES = frozenset(
    {"load_skill", "search_questions", "draw_questions", "select_question"}
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


def validate_tool_call(tool_call: dict) -> dict:
    """Validate a tool call from the LLM before execution.

    Enforces allowlist, required fields, and arg type safety.
    Returns the validated tool call dict, or raises StopRun.
    """
    func = tool_call.get("function")
    if not isinstance(func, dict):
        raise StopRun("invalid_tool_call:no_function")

    name = func.get("name")
    if not isinstance(name, str) or not name:
        raise StopRun("invalid_tool_call:missing_name")

    if name not in _ALLOWED_TOOL_NAMES:
        raise StopRun(f"tool_denied:{name}")

    # Validate JSON parseability (downstream expects string format)
    raw_args = func.get("arguments", "{}")
    if isinstance(raw_args, str):
        try:
            json.loads(raw_args)
        except (json.JSONDecodeError, TypeError):
            raise StopRun(f"invalid_args:{name}")
    elif not isinstance(raw_args, dict):
        raise StopRun(f"invalid_args:{name}")

    return tool_call  # return original; downstream expects string arguments


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

    if tool_name in {"search_questions", "draw_questions", "select_question"}:
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
) -> None:
    logger.info(
        "ReAct trace: event=llm_step conversation_id=%s react_step=%s "
        "finish_reason=%s tool_count=%s elapsed_ms=%s",
        state.get("conversation_id"),
        react_step,
        finish_reason,
        tool_count,
        elapsed_ms,
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


# ── ReAct Loop ────────────────────────────────────────────


async def _react_loop(state: ChatState) -> AsyncGenerator[dict, None]:
    """ReAct loop: LLM autonomously selects tools, then streams final answer.

    Flow:
    1. Build system prompt (with skill catalog + tool guidance)
    2. Build messages
    3. ReAct loop: LLM calls tools or answers directly
    4. Stream final answer
    """
    forced_closing = await _forced_closing_response(state)
    if forced_closing:
        _emit(
            {
                "type": "step",
                "step": "closing",
                "message": "正在收尾面试...",
                "reason": STEP_REASONS["closing"],
            }
        )
        yield {"type": "chunk", "content": forced_closing}
        yield {"type": "done"}
        return

    # 1. Build system prompt
    system_prompt = build_react_system_prompt(state)
    state["active_skill_instructions"] = []  # consumed; skills baked into system prompt

    # 1.5 Inject repetition protection if needed
    repetition_note = _build_repetition_protection_note(state)
    if repetition_note:
        system_prompt += f"\n\n{repetition_note}"

    # 2. Build messages
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # Compressed context
    compressed = state.get("compressed_context")
    if compressed:
        messages.append(
            {
                "role": "user",
                "content": f"[以下是更早对话的压缩摘要，由系统生成，不是候选人的话]\n{compressed}",
            }
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

    # Current user message
    messages.append({"role": "user", "content": state["user_message"]})

    # 3. ReAct loop
    react_started = time.monotonic()
    tool_call_count = 0
    # Tracks whether any search_questions/draw_questions was actually executed
    # in this turn — the force_search_guard below keys off this (not off
    # tool_call_count) because load_skill-only turns still leave the contract
    # unfulfilled (interview_question + answer_complete must produce a bank
    # question plan before final answer).
    search_or_draw_called = False
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
        # Rebuild system prompt if skills were loaded in previous step
        if step > 0 and state.get("active_skill_instructions"):
            system_prompt = build_react_system_prompt(state)
            if repetition_note:
                system_prompt += f"\n\n{repetition_note}"
            messages[0] = {"role": "system", "content": system_prompt}
            state["active_skill_instructions"] = []  # consumed
        llm_started = time.monotonic()
        try:
            result = await llm_service.llm_with_tools(
                messages,
                chat_tools.ALL_TOOLS,
                user_id=state["user_id"],
                model=state.get("model"),
            )
        except Exception as e:
            logger.error(f"ReAct step {step} LLM call failed: {e}")
            break

        tool_calls = result.get("tool_calls") or []
        _log_react_llm_step(
            state,
            react_step=react_step,
            finish_reason=result.get("finish_reason"),
            tool_count=len(tool_calls),
            elapsed_ms=int((time.monotonic() - llm_started) * 1000),
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
                tc = validate_tool_call(tc)
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
            tool_args = _sanitize_tool_args(tc)

            # Emit progress
            _emit(
                {
                    "type": "step",
                    "step": tool_name,
                    "message": chat_tools.tool_progress_message(tc),
                    "reason": STEP_REASONS.get(tool_name, ""),
                }
            )

            # Execute tool
            tool_started = time.monotonic()
            output = await chat_tools.execute_tool(tc, state)
            _log_react_tool_call(
                state,
                react_step=react_step,
                tool_name=tool_name,
                args=tool_args,
                result=_summarize_tool_output(tool_name, output, state),
                elapsed_ms=int((time.monotonic() - tool_started) * 1000),
            )
            if tool_name in ("search_questions", "draw_questions"):
                search_or_draw_called = True
                _maybe_create_question_plan(state)

            # Emit retrieved events for search/draw results
            if tool_name in (
                "search_questions",
                "draw_questions",
            ) and state.get("retrieved_questions"):
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
                            for q in state["retrieved_questions"][:3]
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
            if tool_name in ("search_questions", "draw_questions"):
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
                tool_name in ("search_questions", "draw_questions", "select_question")
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

    # 3.5 Forced search guard: when the LLM skipped search_questions in a
    # scenario where it is contractually required (interview_question +
    # answer_complete + no candidates), inject a hard instruction and retry
    # exactly once.  Uses a local counter — Budget is for token/step caps,
    # not policy retries.
    guard_retry_count = 0
    needs_forced_search = (
        not stop_reason
        and final_answer_text
        and state.get("intent") == "interview_question"
        and _should_require_bank_question(state)
        and not state.get("retrieved_questions")
        and not state.get("candidate_questions")
        and not search_or_draw_called
        and guard_retry_count < 1
    )
    if needs_forced_search:
        guard_retry_count += 1
        _emit(
            {
                "type": "step",
                "step": "force_search_guard",
                "message": "正在强制检索题库...",
            }
        )
        logger.info(
            "ReAct trace: event=react_force_search_guard_triggered "
            "conversation_id=%s intent=%s active_skills=%s retry=%s",
            state.get("conversation_id"),
            state.get("intent"),
            state.get("active_skills"),
            guard_retry_count,
        )
        messages.append(
            {
                "role": "user",
                "content": (
                    "【系统硬契约】当前回合必须先调用 search_questions 工具检索题库题目，"
                    "禁止直接向用户发问。\n"
                    "从刚才用户回答里提取 2-5 个技术关键词，立即调用 search_questions；"
                    "返回结果非空后再决定是否继续追问。"
                ),
            }
        )
        final_answer_text = ""

        guard_result = await llm_service.llm_with_tools(
            messages,
            chat_tools.ALL_TOOLS,
            user_id=state["user_id"],
            model=state.get("model"),
        )
        guard_tool_calls = guard_result.get("tool_calls") or []

        if guard_tool_calls:
            messages.append(
                {
                    "role": "assistant",
                    "content": guard_result.get("content"),
                    "tool_calls": guard_tool_calls,
                }
            )
            for gtc in guard_tool_calls:
                try:
                    gtc = validate_tool_call(gtc)
                except StopRun as exc:
                    logger.warning(
                        "ReAct trace: event=force_search_guard_validation_failed "
                        "conversation_id=%s reason=%s",
                        state.get("conversation_id"),
                        exc.reason,
                    )
                    messages.append(
                        make_tool_result_message(
                            gtc.get("id", "invalid"),
                            json.dumps({"error": exc.reason}),
                        )
                    )
                    continue

                gtc_name = gtc["function"]["name"]
                if gtc_name not in ("search_questions", "draw_questions"):
                    logger.warning(
                        "ReAct trace: event=force_search_guard_contract_failed "
                        "conversation_id=%s tool_name=%s",
                        state.get("conversation_id"),
                        gtc_name,
                    )
                    messages.append(
                        make_tool_result_message(
                            gtc["id"],
                            json.dumps(
                                {
                                    "error": "guard_requires_search_or_draw",
                                    "message": (
                                        "force_search_guard accepts only "
                                        "search_questions or draw_questions"
                                    ),
                                },
                                ensure_ascii=False,
                            ),
                        )
                    )
                    continue

                _emit(
                    {
                        "type": "step",
                        "step": gtc_name,
                        "message": chat_tools.tool_progress_message(gtc),
                        "reason": STEP_REASONS.get(gtc_name, ""),
                    }
                )
                gtc_output = await chat_tools.execute_tool(gtc, state)
                if gtc_name in ("search_questions", "draw_questions"):
                    _maybe_create_question_plan(state)
                if gtc_name in (
                    "search_questions",
                    "draw_questions",
                ) and state.get("retrieved_questions"):
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
                                for q in state["retrieved_questions"][:3]
                            ],
                        }
                    )
                messages.append(make_tool_result_message(gtc["id"], gtc_output))

            final_llm = await llm_service.llm_with_tools(
                messages,
                chat_tools.ALL_TOOLS,
                user_id=state["user_id"],
                model=state.get("model"),
            )
            final_content = final_llm.get("content")
            if isinstance(final_content, str) and final_content.strip():
                final_answer_text = final_content
        else:
            guard_content = guard_result.get("content")
            if isinstance(guard_content, str) and guard_content.strip():
                final_answer_text = guard_content
            logger.warning(
                "ReAct trace: event=react_force_search_guard_exhausted "
                "conversation_id=%s",
                state.get("conversation_id"),
            )

    # 4. Stream final answer
    _emit(
        {
            "type": "step",
            "step": "generating",
            "message": "正在生成回答...",
            "reason": STEP_REASONS["generating"],
        }
    )
    try:
        if stop_reason == "max_seconds":
            yield {
                "type": "chunk",
                "content": _fallback_react_answer(state, stop_reason),
            }
        elif final_answer_text:
            # Check output dedup for direct-answer path
            final_text_clean = _ensure_final_answer_quality(
                _fallback_interviewer_response(final_answer_text, state)
                if _is_internal_react_marker(final_answer_text)
                else final_answer_text,
                state,
            )
            deduplicator = state.setdefault("output_deduplicator", OutputDeduplicator())
            dup_result = (
                deduplicator.check(final_text_clean) if final_text_clean else "ok"
            )

            if dup_result == "exact":
                logger.info(
                    "ReAct trace: event=output_dedup_exact conversation_id=%s",
                    state.get("conversation_id"),
                )
                messages.append(
                    {
                        "role": "user",
                        "content": "【系统提示】你刚才的回答和之前的完全相同，请换一个角度或切换话题。",
                    }
                )
                async for event in _stream_final_answer(messages, state):
                    yield event
            elif dup_result == "similar":
                logger.info(
                    "ReAct trace: event=output_dedup_similar conversation_id=%s",
                    state.get("conversation_id"),
                )
                messages.append(
                    {
                        "role": "user",
                        "content": "【系统提示】你刚才的回答和之前的高度相似，请用不同的话术重新回答。",
                    }
                )
                async for event in _stream_final_answer(messages, state):
                    yield event
            else:
                if final_text_clean:
                    deduplicator.record(final_text_clean)
                for event in await _final_answer_events_from_text(
                    final_answer_text, state
                ):
                    yield event
        else:
            async for event in _stream_final_answer(messages, state):
                yield event
    except Exception as e:
        logger.exception(
            "ReAct trace: event=final_answer_failed conversation_id=%s reason=%s",
            state.get("conversation_id"),
            type(e).__name__,
        )
        yield {
            "type": "chunk",
            "content": _fallback_react_answer(state, type(e).__name__),
        }

    yield {"type": "done"}
