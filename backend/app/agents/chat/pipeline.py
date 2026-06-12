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
    build_react_system_prompt,
    extract_memory,
    fts_retrieve,
    generate_direct_response,
    generate_response,
    llm_rerank_questions,
    load_history,
    recall_memories,
    resolve_active_skills,
    summarize_context,
)
from app.agents.chat.tools import (
    ALL_TOOLS,
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
from app.services.question_draw_service import draw_questions

logger = logging.getLogger("interview-boss")

_FRIENDLY_ERROR = "AI 服务配置错误，请在系统设置中配置有效的 API Key"
_SENTINEL = object()


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


def _step_resolve_skills(state: ChatState) -> ChatState:
    """匹配 active skills（用于 prompt 注入）"""
    skill_result = resolve_active_skills(state)
    state.update(skill_result)
    logger.info(f"Active skills: {state.get('active_skills', [])}")
    return state


async def _step_retrieve(state: ChatState) -> ChatState:
    """RAG 检索 + 排序"""
    _step("searching", "正在搜索相关面试题...")
    retrieve_result = await fts_retrieve(state)
    state.update(retrieve_result)

    rerank_result = await llm_rerank_questions(state)
    state.update(rerank_result)

    questions = state.get("retrieved_questions", [])
    if questions:
        _emit(
            {
                "type": "retrieved",
                "questions": [
                    {
                        "id": q["id"],
                        "question": q["question"],
                        "cat1": q.get("cat1", ""),
                        "cat2": q.get("cat2", ""),
                        "company": _extract_company(q),
                        "round": _extract_round(q),
                    }
                    for q in questions[:3]
                ],
            }
        )

    logger.info(
        f"Pipeline retrieve: {len(questions)} questions, "
        f"basis_ids={state.get('rerank_metadata', {}).get('selected_basis_ids', [])}"
    )
    return state


async def _step_draw(state: ChatState) -> ChatState:
    """从题库抽取高频题"""
    _step("drawing", "正在抽取高频面试题...")
    user = {"id": state["user_id"], "bank_mode": state.get("bank_mode") or "public"}
    exclude_ids = {q["id"] for q in state.get("retrieved_questions", []) if q.get("id")}
    try:
        exclude_ids.update(
            chat_service.get_conversation_question_ids(state["conversation_id"])
        )
    except Exception as e:
        logger.debug(f"读取会话已抽题目失败，跳过历史排除: {e}")

    cat1 = state.get("job_position")
    question_type = state.get("question_type")
    questions = await asyncio.to_thread(
        draw_questions,
        user=user,
        count=5,
        cat1=cat1,
        question_type=question_type,
        exclude_ids=exclude_ids,
    )
    if not questions and cat1:
        questions = await asyncio.to_thread(
            draw_questions,
            user=user,
            count=5,
            question_type=question_type,
            exclude_ids=exclude_ids,
        )
    if not questions:
        questions = await asyncio.to_thread(
            draw_questions,
            user=user,
            count=5,
            exclude_ids=exclude_ids,
        )

    selected = questions[:2]
    if selected:
        state["retrieved_questions"] = selected
        state["basis_type"] = "drawn_question"
        state["selected_basis_questions"] = selected
        state["rerank_metadata"] = {
            "ranked_question_ids": [q["id"] for q in questions if q.get("id")],
            "selected_basis_ids": [q["id"] for q in selected if q.get("id")],
            "confidence": 0.85,
            "should_show_references": True,
            "filtered_reasons": [],
            "reasoning_summary": "draw_question",
        }
        _emit(
            {
                "type": "retrieved",
                "questions": [
                    {
                        "id": q["id"],
                        "question": q["question"],
                        "cat1": q.get("cat1", ""),
                        "cat2": q.get("cat2", ""),
                        "company": _extract_company(q),
                        "round": _extract_round(q),
                    }
                    for q in selected
                ],
            }
        )

    logger.info(f"Pipeline draw: {len(selected)} questions selected")
    return state


async def _step_generate(state: ChatState) -> ChatState:
    """流式生成面试官回复"""
    _step("generating", "正在生成回复...")
    response = ""
    metadata = {}

    async for event in generate_response(state):
        event_type = event.get("type")
        if event_type == "done":
            metadata = event.get("metadata", {})
            _emit({"type": "basis", **_basis_event_payload(metadata)})
            _emit({"type": "done", "metadata": metadata})
            continue
        if event_type in {"chunk", "thinking", "thinking_start", "thinking_done", "error"}:
            if event_type == "chunk":
                response += event.get("content", "")
            _emit(event)

    state["response"] = response
    state["metadata"] = metadata
    return state


async def _step_generate_direct(state: ChatState) -> ChatState:
    """直接生成（无检索）"""
    _step("generating", "正在生成回复...")
    response = ""
    metadata = {}

    state_copy = dict(state)
    state_copy["retrieved_questions"] = []
    state_copy["keywords"] = []

    async for event in generate_direct_response(state_copy):
        event_type = event.get("type")
        if event_type == "done":
            metadata = event.get("metadata", {})
            _emit({"type": "basis", **_basis_event_payload(metadata)})
            _emit({"type": "done", "metadata": metadata})
            continue
        if event_type in {"chunk", "thinking", "thinking_start", "thinking_done", "error"}:
            if event_type == "chunk":
                response += event.get("content", "")
            _emit(event)

    state["response"] = response
    state["metadata"] = metadata
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
    for step in range(MAX_REACT_STEPS):
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

        if not result.get("tool_calls"):
            break  # LLM decided to answer directly

        # Append assistant message with tool_calls
        messages.append(
            {
                "role": "assistant",
                "content": result.get("content"),
                "tool_calls": result["tool_calls"],
            }
        )

        # Execute each tool call
        for tc in result["tool_calls"]:
            tool_name = tc["function"]["name"]

            # Emit progress
            _emit(
                {
                    "type": "step",
                    "step": tool_name,
                    "message": tool_progress_message(tc),
                }
            )

            # Execute tool
            output = await execute_tool(tc, state)

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

            messages.append(make_tool_result_message(tc["id"], output))

    # 4. Stream final answer
    _emit({"type": "step", "step": "generating", "message": "正在生成回答..."})
    async for event in stream_llm_messages(
        messages, user_id=state["user_id"], model=state.get("model")
    ):
        if isinstance(event, dict):
            yield event
        else:
            yield {"type": "chunk", "content": event}

    yield {"type": "done"}


# ═══════════════════════════════════════════════════
#  Intent Routing（简单 if/elif，替代 graph 条件路由）
# ═══════════════════════════════════════════════════


async def _route_and_generate(state: ChatState) -> ChatState:
    """根据意图路由到对应的检索+生成路径"""
    intent = state.get("intent", "interview_question")

    if intent == "end_interview":
        # 结束面试：无检索，LLM 生成总结
        logger.info("Pipeline route: end_interview → direct generate")
        return await _step_generate_direct(state)

    if intent in ("chat", "follow_up"):
        # 闲聊/追问：无检索，直接生成
        logger.info(f"Pipeline route: {intent} → direct generate")
        return await _step_generate_direct(state)

    if intent == "practice_request":
        # 用户要新题：从题库抽取
        logger.info("Pipeline route: practice_request → draw → generate")
        state = await _step_draw(state)
        return await _step_generate(state)

    # interview_question（默认）：RAG 检索
    logger.info("Pipeline route: interview_question → retrieve → generate")
    state = await _step_retrieve(state)
    return await _step_generate(state)


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

            # 3. 匹配 skills
            _step_resolve_skills(state)

            # 4. 路由 + 检索 + 生成
            await _route_and_generate(state)

            # 5. 后台记忆提取
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
