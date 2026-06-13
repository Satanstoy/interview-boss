"""Chat Pipeline — 纯 async pipeline，替代 LangGraph StateGraph。

设计原则（来自业界研究）：
- Graph 做基础设施，LLM 做对话决策
- Skills 是 prompt 注入，不是 graph 节点
- 检索结果是参考资料，不是强制约束
- 简单 if/elif 路由，不需要 state machine
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import AsyncGenerator

from app.agents.chat.context_builder import build_interview_context
from app.agents.chat.nodes import (
    build_react_system_prompt,
    extract_memory,
    load_history,
    recall_memories,
    summarize_context,
)
from app.agents.chat.tools import (
    ALL_TOOLS,
    SKILL_NAMES,
    execute_tool,
    tool_progress_message,
)
from app.services.llm import llm_with_tools, make_tool_result_message, stream_llm_messages
from app.agents.chat.state import ChatState
from app.agents.shared.events import _event_queue_var
from app.services import chat_service
from app.services.memory_recall_service import (
    classify_and_recall,
    classify_and_recall_fast,
)

logger = logging.getLogger("interview-boss")

_FRIENDLY_ERROR = "AI 服务配置错误，请在系统设置中配置有效的 API Key"
_SENTINEL = object()
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
_INTERNAL_REACT_MARKERS = frozenset(
    {
        "load_skill",
        "search_questions",
        "draw_questions",
        *SKILL_NAMES,
    }
)

_ALLOWED_TOOL_NAMES = frozenset({"load_skill", "search_questions", "draw_questions"})


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


def _emit(event: dict) -> None:
    queue = _event_queue_var.get()
    if queue:
        queue.put_nowait(event)


def _step(step: str, message: str) -> None:
    _emit({"type": "step", "step": step, "message": message})


def _extract_company(question: dict) -> str:
    import json

    sources = question.get("sources", [])
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except Exception:
            return ""
    if sources and isinstance(sources, list):
        return sources[0].get("company", "")
    return ""


def _extract_round(question: dict) -> str:
    import json

    sources = question.get("sources", [])
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except Exception:
            return ""
    if sources and isinstance(sources, list):
        return sources[0].get("round", "")
    return ""


def _sanitize_error_message(e: Exception) -> str:
    err_str = str(e).lower()
    if "401" in err_str or "invalid api key" in err_str or "unauthorized" in err_str:
        return _FRIENDLY_ERROR
    return f"处理消息时出现错误: {str(e)}"


def _basis_event_payload(meta: dict) -> dict:
    return {
        "basis_type": meta.get("basis_type"),
        "basis_question_ids": meta.get("basis_question_ids", []),
        "basis_confidence": meta.get("basis_confidence", 0.0),
        "should_show_references": meta.get("should_show_references", False),
        "selected_basis_questions": meta.get("selected_basis_questions", []),
        "resume_ref": meta.get("resume_ref", ""),
        "jd_ref": meta.get("jd_ref", ""),
    }


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
        return summary

    if tool_name in {"search_questions", "draw_questions"}:
        results = [] if not summary["ok"] else state.get("retrieved_questions", []) or []
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


def _normalize_react_marker(text: str) -> str:
    return text.strip().strip("`'\"“”‘’").lower()


def _is_internal_react_marker(text: str) -> bool:
    normalized = _normalize_react_marker(text)
    if not normalized:
        return False
    return normalized in _INTERNAL_REACT_MARKERS


def _fallback_interviewer_response(marker: str, state: ChatState) -> str:
    """Replace leaked internal markers with a safe interviewer turn."""
    normalized = _normalize_react_marker(marker)
    logger.warning(
        "ReAct trace: event=internal_marker_filtered conversation_id=%s marker=%s",
        state.get("conversation_id"),
        normalized[:_TRACE_STRING_LIMIT],
    )

    if normalized == "project-deep-dive":
        return (
            "我们继续围绕你的项目做深挖。你刚才提到“AI 追问编排”和“题库/JD 匹配”，"
            "请具体讲一下：一次候选人回答进入后端后，从意图判断、关键词提取、题库检索到生成追问，"
            "完整链路是怎么设计的？中间你做过哪些取舍？"
        )

    if normalized == "algorithm-coding":
        return (
            "我们切到算法面试。我会先从基础思路开始考察：请你口述一下两数之和这类题的解法，"
            "包括数据结构选择、时间复杂度和边界情况。"
        )

    return (
        "我继续追问一个具体问题：请结合你刚才的项目，说明其中一个核心模块的设计方案、"
        "关键取舍，以及你如何验证它确实解决了问题。"
    )


async def _stream_final_answer(
    messages: list[dict],
    state: ChatState,
) -> AsyncGenerator[dict, None]:
    """Stream final answer while guarding against internal ReAct marker leakage."""
    buffered_events: list[dict] = []
    chunks: list[str] = []

    async for event in stream_llm_messages(
        messages, user_id=state["user_id"], model=state.get("model")
    ):
        if isinstance(event, dict):
            if event.get("type") == "chunk":
                chunks.append(event.get("content", ""))
            else:
                buffered_events.append(event)
        else:
            chunks.append(event)

    final_text = "".join(chunks)
    if _is_internal_react_marker(final_text):
        final_text = _fallback_interviewer_response(final_text, state)

    for event in buffered_events:
        yield event
    if final_text:
        yield {"type": "chunk", "content": final_text}


def _final_answer_events_from_text(
    final_text: str,
    state: ChatState,
) -> list[dict]:
    if _is_internal_react_marker(final_text):
        final_text = _fallback_interviewer_response(final_text, state)
    if not final_text:
        return []
    return [{"type": "chunk", "content": final_text}]


def _build_react_metadata(state: ChatState, response_text: str) -> tuple[dict, str]:
    """Build done-event metadata from the final streamed response.

    Reuses the existing basis parsing contract so the router can keep emitting
    the same SSE shape as the previous pipeline.
    """
    from app.agents.chat.nodes import (
        _extract_company_from_sources,
        _extract_round_from_sources,
        _filter_basis_ids_by_response,
        _get_jd_title,
        _get_resume_name,
        _parse_basis_from_response,
        _response_references_jd,
        _response_references_resume,
        validate_basis,
    )

    parsed = _parse_basis_from_response(response_text)
    clean_response = parsed.get("clean_response", response_text)
    retrieved = state.get("retrieved_questions", []) or []
    retrieved_ids = {q.get("id") for q in retrieved if q.get("id")}

    basis = validate_basis(parsed, retrieved_ids)
    if basis.get("should_show_references") and basis.get("basis_question_ids"):
        aligned_basis_ids = _filter_basis_ids_by_response(
            clean_response, basis["basis_question_ids"], retrieved
        )
        if len(aligned_basis_ids) != len(basis["basis_question_ids"]):
            logger.info(
                "ReAct basis alignment filtered ids: "
                f"before={basis['basis_question_ids']}, after={aligned_basis_ids}"
            )
        basis["basis_question_ids"] = aligned_basis_ids
        basis["should_show_references"] = bool(aligned_basis_ids)
        if not aligned_basis_ids:
            basis["basis_confidence"] = min(basis["basis_confidence"], 0.3)

    metadata: dict[str, object] = {
        "basis_type": basis["basis_type"],
        "basis_question_ids": basis["basis_question_ids"],
        "basis_confidence": basis["basis_confidence"],
        "should_show_references": basis["should_show_references"],
        "active_skills": state.get("active_skills", []),
        "asked_question_text": clean_response,
    }

    if retrieved:
        metadata["retrieved_questions"] = [
            {
                "id": q.get("id"),
                "question": q.get("question", ""),
                "cat1": q.get("cat1", ""),
                "company": _extract_company_from_sources(q),
                "round": _extract_round_from_sources(q),
            }
            for q in retrieved[:3]
        ]

    if basis["basis_question_ids"]:
        basis_id_set = set(basis["basis_question_ids"])
        basis_qs = [q for q in retrieved if q.get("id") in basis_id_set]
        if not basis_qs:
            try:
                from app.db.connection import get_db_connection

                with get_db_connection() as conn:
                    placeholders = ",".join("?" * len(basis["basis_question_ids"]))
                    rows = conn.execute(
                        f"SELECT id, question, cat1, cat2 FROM question_bank "
                        f"WHERE id IN ({placeholders}) AND deleted_at IS NULL AND status = 'approved'",
                        basis["basis_question_ids"],
                    ).fetchall()
                    basis_qs = [
                        {
                            "id": r[0],
                            "question": r[1],
                            "cat1": r[2],
                            "cat2": r[3],
                        }
                        for r in rows
                    ]
            except Exception as e:
                logger.debug(f"ReAct basis DB fallback failed: {e}")

        metadata["selected_basis_questions"] = [
            {
                "id": q.get("id"),
                "question": q.get("question", ""),
                "cat1": q.get("cat1", ""),
                "company": _extract_company_from_sources(q),
                "round": _extract_round_from_sources(q),
            }
            for q in basis_qs
        ]

    if state.get("resume_summary") and _response_references_resume(
        clean_response, state["resume_summary"]
    ):
        metadata["resume_ref"] = _get_resume_name(state["user_id"])

    if state.get("jd_text") and _response_references_jd(clean_response, state["jd_text"]):
        metadata["jd_ref"] = _get_jd_title(state.get("jd_id"))

    return metadata, clean_response


def _initial_state(
    conversation_id: str,
    user_id: int,
    user_message: str,
    mode: str,
    jd_id: int | None,
    resume_text: str | None,
    jd_text: str | None,
    model: str | None,
    bank_mode: str | None,
) -> ChatState:
    return {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "user_message": user_message,
        "mode": mode,
        "jd_id": jd_id,
        "jd_text": jd_text,
        "resume_text": resume_text,
        "model": model,
        "bank_mode": bank_mode or "public",
        "memories": [],
        "memory_summaries": [],
        "resume_summary": None,
        "session_notes": "",
        "message_history": [],
        "compressed_context": None,
        "recent_messages": [],
        "budget_snapshot": None,
        "interview_context": "",
        "job_position": None,
        "intent": "interview_question",
        "keywords": [],
        "search_query": "",
        "retrieval_intent": None,
        "search_positive_terms": [],
        "search_negative_terms": [],
        "question_type": None,
        "answer_complete": False,
        "retrieved_questions": [],
        "selected_basis_questions": [],
        "rerank_metadata": {},
        "response": "",
        "metadata": {},
        "basis_type": "none",
        "basis_question_ids": [],
        "basis_confidence": 0.0,
        "should_show_references": False,
        "active_skills": [],
    }


# ═══════════════════════════════════════════════════
#  Pipeline Steps
# ═══════════════════════════════════════════════════


async def _step_load_context(state: ChatState) -> ChatState:
    """加载上下文：历史、记忆、简历、session notes"""
    _step("loading", "正在加载对话历史...")
    memory_result, history_result = await asyncio.gather(
        recall_memories(state),
        load_history(state),
    )
    state.update(memory_result)
    state.update(history_result)
    state["session_notes"] = chat_service.get_session_notes(
        state["conversation_id"]
    )

    # 恢复上一轮持久化的 active skill names
    conversation_metadata = await asyncio.to_thread(
        chat_service.get_conversation_metadata,
        state["conversation_id"],
    )
    from app.agents.chat.nodes import _restore_active_skills_from_metadata
    _restore_active_skills_from_metadata(state, conversation_metadata)

    _step("context", "正在加载个人画像...")
    interview_context, job_position = build_interview_context(
        state["user_id"], conversation_id=state["conversation_id"]
    )
    state["interview_context"] = interview_context
    state["job_position"] = job_position

    # 上下文压缩
    result = await summarize_context(state)
    state.update(result)

    # 检查轮次限制
    from app.agents.chat.nodes import check_round_limit

    if not check_round_limit(state.get("message_history", [])):
        raise RuntimeError("对话已达最大轮次限制（50轮），请新建对话继续")

    return state


async def _step_classify(state: ChatState) -> ChatState:
    """意图分类 + 关键词提取 + 记忆召回（单次 LLM 调用）"""
    recent = state.get("recent_messages", [])
    recent_context = ""
    if recent:
        recent_context = "\n".join(
            f"{'面试官' if m['role'] == 'assistant' else '候选人'}: {m['content'][:100]}"
            for m in recent[-4:]
        )

    is_first_message = len(state.get("message_history", [])) <= 1
    if is_first_message:
        _step("understanding", "正在理解你的问题...")
        (
            intent,
            memory_ids,
            keywords,
            search_query,
            answer_complete,
            structured_rewrite,
        ) = await classify_and_recall_fast(
            user_message=state["user_message"],
            memory_summaries=state.get("memory_summaries", []),
            recent_context=recent_context,
        )
    else:
        _step("understanding", "正在分析你的回答...")
        (
            intent,
            memory_ids,
            keywords,
            search_query,
            answer_complete,
            structured_rewrite,
        ) = await classify_and_recall(
            user_message=state["user_message"],
            recent_context=recent_context,
            memory_summaries=state.get("memory_summaries", []),
            user_id=state["user_id"],
        )

    state["intent"] = intent
    state["keywords"] = keywords
    state["search_query"] = search_query
    state["answer_complete"] = answer_complete

    if structured_rewrite:
        state["retrieval_intent"] = structured_rewrite.get("retrieval_intent")
        state["search_positive_terms"] = structured_rewrite.get("positive_terms", [])
        state["search_negative_terms"] = structured_rewrite.get("negative_terms", [])
        state["question_type"] = structured_rewrite.get("question_type")

    if memory_ids:
        full_memories = await asyncio.to_thread(
            chat_service.get_memories_by_ids, memory_ids, state["user_id"]
        )
        state["memory_summaries"] = [
            {
                "id": m["id"],
                "memory_type": m["memory_type"],
                "summary": m["content"][:80],
                "updated_at": m["created_at"],
            }
            for m in full_memories
        ]
    else:
        state["memory_summaries"] = chat_service.get_memory_summaries(
            state["user_id"], limit=3
        )

    if intent == "interview_question" and keywords:
        topic_tag = ", ".join(keywords[:3])
        pre_note = f"[pending] 候选人正在回答: {topic_tag}"
        current_notes = state.get("session_notes", "")
        state["session_notes"] = (
            f"{current_notes}\n{pre_note}" if current_notes else pre_note
        )

    logger.info(
        f"Pipeline classify: intent={intent}, keywords={keywords}, "
        f"search_query='{search_query}', answer_complete={answer_complete}"
    )
    return state


async def _step_extract_memory(state: ChatState) -> None:
    """后台提取记忆（不阻塞主流程）"""
    try:
        await extract_memory(state)
    except Exception as e:
        logger.debug(f"后台记忆提取失败（不影响主流程）: {e}")


# ═══════════════════════════════════════════════════
#  ReAct Loop (core autonomous tool-calling loop)
# ═══════════════════════════════════════════════════

MAX_REACT_STEPS = 5


async def _persist_active_skills(state: ChatState) -> None:
    """Persist active skill names to conversation metadata for cross-round recovery.

    Only skill names are persisted (not full instructions). On next round,
    instructions are reloaded from the skill registry so edits are picked up.
    """
    try:
        conversation_id = state.get("conversation_id")
        if not conversation_id:
            return
        active_skills = state.get("active_skills", [])
        if not active_skills:
            return
        await asyncio.to_thread(
            chat_service.update_conversation_metadata,
            conversation_id,
            {"active_skill_names": active_skills},
        )
    except Exception:
        logger.exception("Failed to persist active_skills")


async def _react_loop(state: ChatState) -> AsyncGenerator[dict, None]:
    """ReAct loop: LLM autonomously selects tools, then streams final answer.

    Flow:
    1. Build system prompt (with skill catalog + tool guidance)
    2. Build messages
    3. ReAct loop: LLM calls tools or answers directly
    4. Stream final answer
    """
    # 1. Build system prompt
    system_prompt = build_react_system_prompt(state)
    state["active_skill_instructions"] = []  # consumed; skills baked into system prompt

    # 2. Build messages
    messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # Compressed context
    compressed = state.get("compressed_context")
    if compressed:
        messages.append(
            {"role": "user", "content": f"[历史对话摘要]\n{compressed}"}
        )

    # Recent messages
    for msg in state.get("recent_messages", [])[-10:]:
        role = msg.get("role", "user")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": msg.get("content", "")})

    # Current user message
    messages.append({"role": "user", "content": state["user_message"]})

    # 3. ReAct loop
    react_started = time.monotonic()
    tool_call_count = 0
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
            messages[0] = {"role": "system", "content": system_prompt}
            state["active_skill_instructions"] = []  # consumed
        llm_started = time.monotonic()
        try:
            result = await llm_with_tools(
                messages,
                ALL_TOOLS,
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
                    state.get("conversation_id"), react_step, exc.reason,
                )
                messages.append(make_tool_result_message(
                    tc.get("id", "invalid"),
                    json.dumps({"error": exc.reason}),
                ))
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
                    state.get("conversation_id"), react_step, tc["function"]["name"],
                )
                messages.append(make_tool_result_message(
                    tc.get("id", "loop"),
                    json.dumps({"error": "loop_detected", "message": "Same tool call repeated — stopping."}),
                ))
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
                    "message": tool_progress_message(tc),
                }
            )

            # Execute tool
            tool_started = time.monotonic()
            output = await execute_tool(tc, state)
            _log_react_tool_call(
                state,
                react_step=react_step,
                tool_name=tool_name,
                args=tool_args,
                result=_summarize_tool_output(tool_name, output, state),
                elapsed_ms=int((time.monotonic() - tool_started) * 1000),
            )

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
                skill_label = tool_progress_message(tc).replace("正在加载", "").replace("...", "")
                _emit({"type": "insight", "text": f"切换到{skill_label}模式"})
            elif tool_name in ("search_questions", "draw_questions") and state.get("retrieved_questions"):
                top_q = state["retrieved_questions"][0] if state["retrieved_questions"] else None
                if top_q:
                    topic = top_q.get("cat2") or top_q.get("cat1") or "相关技术"
                    _emit({"type": "insight", "text": f"从题库检索到关于「{topic}」的题目"})

            messages.append(make_tool_result_message(tc["id"], output))

        # If inner loop broke due to validation failure or loop detection, exit outer loop
        if stop_reason:
            break

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

    # 4. Stream final answer
    _emit({"type": "step", "step": "generating", "message": "正在生成回答..."})
    if final_answer_text:
        for event in _final_answer_events_from_text(final_answer_text, state):
            yield event
    else:
        async for event in _stream_final_answer(messages, state):
            yield event

    yield {"type": "done"}


# ═══════════════════════════════════════════════════
#  Main Entry Point
# ═══════════════════════════════════════════════════


async def run_chat(
    conversation_id: str,
    user_id: int,
    user_message: str,
    mode: str = "free_practice",
    jd_id: int = None,
    resume_text: str = None,
    jd_text: str = None,
    model: str = None,
    bank_mode: str = None,
) -> AsyncGenerator[dict, None]:
    """面试对话 pipeline — SSE 兼容的 async generator。

    替代 LangGraph StateGraph，使用纯 async pipeline。
    所有事件通过 _event_queue_var 上下文变量传递。
    """
    queue: asyncio.Queue = asyncio.Queue()
    token = _event_queue_var.set(queue)

    state = _initial_state(
        conversation_id, user_id, user_message, mode,
        jd_id, resume_text, jd_text, model, bank_mode,
    )

    async def _run_pipeline() -> None:
        t0 = time.monotonic()
        try:
            # 1. 加载上下文
            await _step_load_context(state)

            # 2. 意图分类 + 关键词
            await _step_classify(state)

            # 3-5. ReAct 循环（替代 resolve_skills + route_and_generate）
            response = ""
            metadata = {}
            async for event in _react_loop(state):
                event_type = event.get("type")
                if event_type == "done":
                    metadata = event.get("metadata", {})
                    built_metadata, clean_response = _build_react_metadata(
                        state, response
                    )
                    if built_metadata:
                        metadata = {**built_metadata, **metadata}
                    response = clean_response
                    _emit({"type": "basis", **_basis_event_payload(metadata)})
                    _emit({"type": "done", "metadata": metadata})
                    continue
                if event_type in {"chunk", "thinking", "thinking_start", "thinking_done", "error"}:
                    if event_type == "chunk":
                        response += event.get("content", "")
                    _emit(event)
            state["response"] = response
            state["metadata"] = metadata

            # 持久化 active skill names 到 conversation metadata
            if state.get("active_skills"):
                await _persist_active_skills(state)

            # 后台记忆提取
            asyncio.create_task(_step_extract_memory(dict(state)))

            elapsed = time.monotonic() - t0
            logger.info(
                f"Pipeline completed in {elapsed:.1f}s, "
                f"intent={state.get('intent')}, "
                f"active_skills={state.get('active_skills', [])}"
            )
        except Exception as e:
            logger.exception("Pipeline 执行失败")
            queue.put_nowait(
                {"type": "error", "message": _sanitize_error_message(e)}
            )
        finally:
            queue.put_nowait(_SENTINEL)

    graph_task = asyncio.create_task(_run_pipeline())

    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break
            yield item
            await asyncio.sleep(0)
    finally:
        _event_queue_var.reset(token)
        if not graph_task.done():
            graph_task.cancel()
