"""Chat Pipeline — 纯 async pipeline，替代 LangGraph StateGraph。

设计原则（来自业界研究）：
- Graph 做基础设施，LLM 做对话决策
- Skills 是 prompt 注入，不是 graph 节点
- 检索结果是参考资料，不是强制约束
- 简单 if/elif 路由，不需要 state machine
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncGenerator

from app.agents.chat.context_builder import build_interview_context
from app.agents.chat.nodes import (
    _repair_response_to_question_plan,
    check_round_limit,
    extract_memory,
    load_history,
    recall_memories,
    summarize_context,
)
from app.agents.chat.state import ChatState
from app.agents.shared.events import _event_queue_var
from app.services import chat_service
from app.services.memory_recall_service import (
    classify_and_recall,
    classify_and_recall_fast,
)
from app.mcp_server.session import save_mcp_session

# Re-exports from submodules (backward compatibility for tests and graph.py)
from app.agents.chat.react_loop import (  # noqa: F401
    MAX_REACT_STEPS,
    REACT_BUDGET,
    STEP_REASONS,
    Budget,
    StopRun,
    _ALLOWED_TOOL_NAMES,
    _PERSISTENT_SKILLS,
    _SAFE_TOOL_ARG_KEYS,
    _TRACE_LIST_LIMIT,
    _TRACE_STRING_LIMIT,
    _emit,
    _log_react_llm_step,
    _log_react_tool_call,
    _react_loop,
    _sanitize_tool_args,
    _step,
    _summarize_tool_output,
    _trace_safe_value,
    validate_tool_call,
)
from app.agents.chat.answer import (  # noqa: F401
    OutputDeduplicator,
    _INTERNAL_REACT_MARKERS,
    _ensure_final_answer_quality,
    _fallback_coding_question,
    _fallback_interviewer_response,
    _fallback_react_answer,
    _final_answer_events_from_text,
    _is_bare_coding_prompt,
    _is_internal_react_marker,
    _last_assistant_message,
    _looks_like_candidate_question,
    _normalize_react_marker,
    _regenerate_after_dup,
    _stream_final_answer,
)
from app.agents.chat.question_plan import (  # noqa: F401
    InterviewLedger,
    _MAX_CONSECUTIVE_SAME_QUESTION,
    _allowed_focus_from_question,
    _build_interview_ledger,
    _build_previously_asked_section,
    _build_repetition_protection_note,
    _candidate_contains_negative_term,
    _count_consecutive_similar_questions,
    _is_algorithm_candidate,
    _maybe_create_question_plan,
    _normalize_question_text,
    _select_question_for_plan,
    _should_create_question_plan,
    _should_require_bank_question,
    _tokenize_for_overlap,
)
from app.agents.chat.summary import (  # noqa: F401
    _FRIENDLY_ERROR,
    _SUMMARY_SYSTEM_PROMPT,
    _build_interview_transcript,
    _forced_closing_response,
    _generate_end_interview_response,
    _generate_structured_summary,
    _render_interview_summary_markdown,
    _sanitize_error_message,
    InterviewSummary,
)
from app.agents.chat.metadata import (  # noqa: F401
    _basis_event_payload,
    _build_react_metadata,
    _extract_company,
    _extract_round,
    _infer_selected_question,
    _public_question,
)

logger = logging.getLogger("interview-boss")

_SENTINEL = object()
_MAX_THINKING_CHUNKS = 50


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
        "session_id": conversation_id,
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
        "candidate_questions": [],
        "selected_question": None,
        "question_source": None,
        "question_source_reason": None,
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
    _step("loading", "正在加载对话历史...", reason=STEP_REASONS["loading"])
    memory_result, history_result = await asyncio.gather(
        recall_memories(state),
        load_history(state),
    )
    state.update(memory_result)
    state.update(history_result)
    state["session_notes"] = chat_service.get_session_notes(state["conversation_id"])

    # 恢复上一轮持久化的 active skill names
    conversation_metadata = await asyncio.to_thread(
        chat_service.get_conversation_metadata,
        state["conversation_id"],
    )
    from app.agents.chat.nodes import _restore_active_skills_from_metadata

    _restore_active_skills_from_metadata(state, conversation_metadata)

    _step("context", "正在加载个人画像...", reason=STEP_REASONS["context"])
    interview_context, job_position = build_interview_context(
        state["user_id"], conversation_id=state["conversation_id"]
    )
    state["interview_context"] = interview_context
    state["job_position"] = job_position

    # 上下文压缩
    result = await summarize_context(state)
    state.update(result)

    # 检查轮次限制
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
        _step(
            "understanding",
            "正在理解你的问题...",
            reason=STEP_REASONS["understanding_first"],
        )
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
        _step(
            "understanding",
            "正在分析你的回答...",
            reason=STEP_REASONS["understanding_follow"],
        )
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


async def _persist_active_skills(state: ChatState) -> None:
    """Persist only cross-turn skills to conversation metadata.

    Mode skills such as algorithm-coding/project-deep-dive are turn-scoped; if
    they are persisted, the next unrelated turn can inherit the wrong mode.
    """
    try:
        conversation_id = state.get("conversation_id")
        if not conversation_id:
            return
        active_skills = [
            name
            for name in state.get("active_skills", [])
            if name in _PERSISTENT_SKILLS
        ]
        await asyncio.to_thread(
            chat_service.update_conversation_metadata,
            conversation_id,
            {
                "persistent_skill_names": active_skills,
                "active_skill_names": active_skills,
                "last_turn_skills": state.get("active_skills", []),
            },
        )
    except Exception:
        logger.exception("Failed to persist active_skills")


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
        conversation_id,
        user_id,
        user_message,
        mode,
        jd_id,
        resume_text,
        jd_text,
        model,
        bank_mode,
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

            # Hard route: end_interview bypasses ReAct entirely — no tools
            if state.get("intent") == "end_interview":
                _emit(
                    {
                        "type": "step",
                        "step": "closing",
                        "message": "正在生成面试总结...",
                        "reason": STEP_REASONS["closing"],
                    }
                )
                closing_text = await _generate_end_interview_response(state)
                response = closing_text
                _emit({"type": "chunk", "content": closing_text})
                built_metadata, clean_response = _build_react_metadata(state, response)
                if built_metadata:
                    metadata = built_metadata
                response = clean_response
                _emit({"type": "basis", **_basis_event_payload(metadata)})
                _emit({"type": "done", "metadata": metadata})
            else:
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
                    if event_type in {
                        "chunk",
                        "thinking",
                        "thinking_start",
                        "thinking_done",
                        "error",
                    }:
                        if event_type == "chunk":
                            response += event.get("content", "")
                        _emit(event)
            state["response"] = response
            state["metadata"] = metadata

            # Persist/clear cross-turn skills so turn-scoped modes do not stick.
            await _persist_active_skills(state)

            # Fix 3: persist MCP session for internal ReAct path
            session_id = state.get("session_id") or state.get("conversation_id")
            if session_id:
                try:
                    await asyncio.to_thread(save_mcp_session, session_id, dict(state))
                except Exception:
                    logger.debug("Failed to persist MCP session (non-fatal)")

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
            queue.put_nowait({"type": "error", "message": _sanitize_error_message(e)})
        finally:
            queue.put_nowait(_SENTINEL)

    graph_task = asyncio.create_task(_run_pipeline())

    # Fix 4: accumulate step/thinking/insight events for metadata persistence
    collected_steps: list[dict] = []
    collected_insights: list[dict] = []
    collected_thinking: list[dict] = []
    thinking_start_time: float | None = None

    try:
        while True:
            item = await queue.get()
            if item is _SENTINEL:
                break

            item_type = item.get("type")
            if item_type == "step":
                collected_steps.append(item)
            elif item_type == "insight":
                collected_insights.append(item)
            elif item_type == "thinking_start":
                thinking_start_time = time.monotonic()
                collected_thinking.append({"start": item.get("data", {})})
            elif item_type == "thinking":
                if collected_thinking:
                    # 优先 content，fallback 到 data.text
                    chunk = item.get("content") or item.get("data", {}).get("text", "")
                    if chunk:
                        collected_thinking[-1].setdefault("chunks", []).append(chunk)
            elif item_type == "thinking_done":
                if collected_thinking and thinking_start_time:
                    collected_thinking[-1]["duration_ms"] = int(
                        (time.monotonic() - thinking_start_time) * 1000
                    )
                    thinking_start_time = None
            elif item_type == "done":
                metadata = item.get("metadata", {})
                # Limit thinking chunks to avoid metadata bloat
                for t in collected_thinking:
                    chunks = t.get("chunks", [])
                    if len(chunks) > _MAX_THINKING_CHUNKS:
                        t["chunks"] = chunks[:_MAX_THINKING_CHUNKS]
                metadata["thinking"] = collected_thinking
                metadata["thinking_duration"] = sum(
                    t.get("duration_ms", 0) for t in collected_thinking
                )
                metadata["steps"] = collected_steps
                metadata["insights"] = collected_insights
                item = {**item, "metadata": metadata}

            yield item
            await asyncio.sleep(0)
    finally:
        _event_queue_var.reset(token)
        if not graph_task.done():
            graph_task.cancel()
