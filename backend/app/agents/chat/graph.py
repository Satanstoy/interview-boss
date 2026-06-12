"""Chat Agent Graph — LangGraph-backed interview conversation pipeline."""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import AsyncGenerator

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph

from app.agents.chat.context_builder import build_interview_context
from app.agents.chat.nodes import (
    check_round_limit,
    extract_memory,
    fts_retrieve,
    generate_direct_response,
    generate_response,
    llm_rerank_questions,
    load_history,
    plan_skill_guided_strategy,
    recall_memories,
    resolve_active_skills,
    route_after_classify,
    summarize_context,
)
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


async def load_context_node(state: ChatState) -> dict:
    _step("loading", "正在加载对话历史...")
    memory_result, history_result = await asyncio.gather(
        recall_memories(state),
        load_history(state),
    )
    updates = {**memory_result, **history_result}
    state_for_context = {**state, **updates}
    state_for_context["session_notes"] = chat_service.get_session_notes(
        state["conversation_id"]
    )

    _step("context", "正在加载个人画像...")
    interview_context, job_position = build_interview_context(
        state["user_id"], conversation_id=state["conversation_id"]
    )
    state_for_context["interview_context"] = interview_context
    state_for_context["job_position"] = job_position

    if not check_round_limit(state_for_context.get("message_history", [])):
        raise RuntimeError("对话已达最大轮次限制（50轮），请新建对话继续")

    return {
        **updates,
        "session_notes": state_for_context["session_notes"],
        "interview_context": interview_context,
        "job_position": job_position,
    }


async def summarize_context_node(state: ChatState) -> dict:
    _step("analyzing", "正在分析对话上下文...")
    return await summarize_context(state)


async def classify_and_recall_node(state: ChatState) -> dict:
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

    updates = {
        "intent": intent,
        "keywords": keywords,
        "search_query": search_query,
        "answer_complete": answer_complete,
    }
    if structured_rewrite:
        updates.update(
            {
                "retrieval_intent": structured_rewrite.get("retrieval_intent"),
                "search_positive_terms": structured_rewrite.get("positive_terms", []),
                "search_negative_terms": structured_rewrite.get("negative_terms", []),
                "question_type": structured_rewrite.get("question_type"),
            }
        )

    if memory_ids:
        full_memories = await asyncio.to_thread(
            chat_service.get_memories_by_ids, memory_ids, state["user_id"]
        )
        updates["memory_summaries"] = [
            {
                "id": m["id"],
                "memory_type": m["memory_type"],
                "summary": m["content"][:80],
                "updated_at": m["created_at"],
            }
            for m in full_memories
        ]
    else:
        updates["memory_summaries"] = chat_service.get_memory_summaries(
            state["user_id"], limit=3
        )

    if intent == "interview_question" and keywords:
        topic_tag = ", ".join(keywords[:3])
        pre_note = f"[pending] 候选人正在回答: {topic_tag}"
        current_notes = state.get("session_notes", "")
        updates["session_notes"] = (
            f"{current_notes}\n{pre_note}" if current_notes else pre_note
        )

    return updates


async def resolve_strategy_node(state: ChatState) -> dict:
    skill_result = resolve_active_skills(state)
    state_with_skills = {**state, **skill_result}
    strategy_result = plan_skill_guided_strategy(state_with_skills)
    return {**skill_result, **strategy_result}


def route_after_strategy(state: ChatState) -> str:
    route = route_after_classify(state)
    logger.info(
        f"路由决策: intent={state.get('intent')}, route={route}, "
        f"strategy={state.get('strategy')}, tool_policy={state.get('tool_policy')}, "
        f"keywords={state.get('keywords')}, search_query='{state.get('search_query')}'"
    )
    return route


async def retrieve_and_rerank_node(state: ChatState) -> dict:
    _step("searching", "正在搜索相关面试题...")
    retrieve_result = await fts_retrieve(state)
    state_after_retrieve = {**state, **retrieve_result}
    rerank_result = await llm_rerank_questions(state_after_retrieve)
    updates = {**retrieve_result, **rerank_result}
    updates["next_question_plan"] = _build_next_question_plan(
        {**state, **updates}, source="retrieved_question"
    )

    questions = updates.get("retrieved_questions", [])
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
    return updates


async def draw_question_node(state: ChatState) -> dict:
    _step("drawing", "正在抽取高频面试题...")
    user = {"id": state["user_id"], "bank_mode": state.get("bank_mode") or "public"}
    exclude_ids = {q["id"] for q in state.get("retrieved_questions", []) if q.get("id")}
    try:
        exclude_ids.update(
            chat_service.get_conversation_question_ids(state["conversation_id"])
        )
    except Exception as e:
        logger.debug(f"读取会话已抽题目失败，跳过历史排除: {e}")
    cat1 = state.get("strategy_target_topic") or state.get("job_position")
    question_type = state.get("strategy_preferred_question_type")
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
    plan = _build_next_question_plan(
        {**state, "retrieved_questions": selected, "selected_basis_questions": selected},
        source="drawn_question",
    )
    if selected:
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
    return {
        "drawn_questions": questions,
        "retrieved_questions": selected,
        "basis_type": "drawn_question" if selected else "conversation",
        "selected_basis_questions": selected,
        "next_question_plan": plan,
        "rerank_metadata": {
            "ranked_question_ids": [q["id"] for q in questions if q.get("id")],
            "selected_basis_ids": [q["id"] for q in selected if q.get("id")],
            "confidence": 0.85 if selected else 0.0,
            "should_show_references": bool(selected),
            "filtered_reasons": [],
            "reasoning_summary": "weighted_draw_question",
        },
    }


async def _run_generation(state: ChatState, *, direct: bool) -> dict:
    _step("generating", "正在生成回复...")
    response = ""
    metadata = {}
    generator = generate_direct_response(state) if direct else generate_response(state)

    async for event in generator:
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

    return {"response": response, "metadata": metadata}


def _build_next_question_plan(state: ChatState, *, source: str) -> dict:
    selected = state.get("selected_basis_questions") or []
    retrieved = state.get("retrieved_questions") or []
    basis = selected[0] if selected else (retrieved[0] if retrieved else None)

    if not basis or not basis.get("id"):
        return {
            "basis_type": "conversation",
            "question_id": None,
            "question_text": "",
            "strategy": state.get("strategy"),
            "must_ask": False,
            "allowed_focus": state.get("keywords", [])[:5],
            "forbidden_focus": state.get("search_negative_terms", [])[:5],
            "source": "conversation",
        }

    question_text = str(basis.get("question", ""))
    focus = []
    for part in re.findall(r"[A-Za-z][A-Za-z0-9_+-]{1,}|[\u4e00-\u9fff]{2,}", question_text):
        if part not in focus:
            focus.append(part)
        if len(focus) >= 8:
            break

    must_ask = source == "drawn_question" or bool(
        state.get("rerank_metadata", {}).get("selected_basis_ids")
    )
    if source == "retrieved_question" and must_ask:
        must_ask = _retrieved_question_supports_current_turn(state, question_text)

    return {
        "basis_type": source,
        "question_id": int(basis["id"]),
        "question_text": question_text,
        "strategy": state.get("strategy"),
        "must_ask": must_ask,
        "allowed_focus": focus,
        "forbidden_focus": state.get("search_negative_terms", [])[:5],
        "source": source,
    }


def _retrieved_question_supports_current_turn(state: ChatState, question_text: str) -> bool:
    """Only hard-bind retrieved questions when they visibly match this turn.

    Retrieval is allowed to provide context, but weakly related retrieved questions
    should not override a natural project follow-up.
    """
    haystack = " ".join(
        str(x or "")
        for x in [
            state.get("strategy_target_topic"),
            state.get("search_query"),
            state.get("user_message"),
        ]
    ).lower()
    negative = " ".join(str(x or "") for x in state.get("search_negative_terms", [])).lower()
    question_lower = (question_text or "").lower()

    tokens = {
        t.lower()
        for t in re.findall(r"[A-Za-z][A-Za-z0-9_+.-]{2,}|[\u4e00-\u9fff]{2,8}", question_text or "")
        if t.lower() not in {"什么", "怎么", "如何", "为什么", "介绍", "一下", "具体", "主要"}
    }
    if not tokens:
        return False
    if any(t and t in negative for t in tokens):
        return False

    overlap = {t for t in tokens if t in haystack}
    if len(overlap) >= 2:
        return True

    strong_terms = {
        "rag",
        "rrf",
        "fts5",
        "langgraph",
        "rerank",
        "embedding",
        "query",
        "selected_basis",
        "references",
        "postgresql",
        "redis",
    }
    return bool(overlap & strong_terms) and any(t in question_lower for t in strong_terms)


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


async def generate_with_context_node(state: ChatState) -> dict:
    return await _run_generation(state, direct=False)


async def generate_direct_node(state: ChatState) -> dict:
    return await _run_generation(state, direct=True)


async def _extract_memory_background(state_snapshot: ChatState) -> None:
    try:
        await extract_memory(state_snapshot)
    except Exception as e:
        logger.debug(f"后台记忆提取失败（不影响主流程）: {e}")


async def extract_memory_node(state: ChatState) -> dict:
    asyncio.create_task(_extract_memory_background(dict(state)))
    return {}


def _build_chat_graph() -> StateGraph:
    workflow = StateGraph(ChatState)
    workflow.add_node("load_context", load_context_node)
    workflow.add_node("summarize_context", summarize_context_node)
    workflow.add_node("classify_and_recall", classify_and_recall_node)
    workflow.add_node("resolve_strategy", resolve_strategy_node)
    workflow.add_node("retrieve_and_rerank", retrieve_and_rerank_node)
    workflow.add_node("draw_question", draw_question_node)
    workflow.add_node("generate_with_context", generate_with_context_node)
    workflow.add_node("generate_direct", generate_direct_node)
    workflow.add_node("extract_memory", extract_memory_node)

    workflow.add_edge(START, "load_context")
    workflow.add_edge("load_context", "summarize_context")
    workflow.add_edge("summarize_context", "classify_and_recall")
    workflow.add_edge("classify_and_recall", "resolve_strategy")
    workflow.add_conditional_edges(
        "resolve_strategy",
        route_after_strategy,
        {
            "rag_retrieve": "retrieve_and_rerank",
            "draw_question": "draw_question",
            "direct_respond": "generate_direct",
        },
    )
    workflow.add_edge("retrieve_and_rerank", "generate_with_context")
    workflow.add_edge("draw_question", "generate_with_context")
    workflow.add_edge("generate_with_context", "extract_memory")
    workflow.add_edge("generate_direct", "extract_memory")
    workflow.add_edge("extract_memory", END)
    return workflow


chat_graph = _build_chat_graph().compile(checkpointer=MemorySaver())


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
        "intent": "interview_question",
        "keywords": [],
        "search_query": "",
        "retrieval_intent": None,
        "search_positive_terms": [],
        "search_negative_terms": [],
        "question_type": None,
        "answer_complete": False,
        "retrieved_questions": [],
        "drawn_questions": [],
        "selected_basis_questions": [],
        "rerank_metadata": {},
        "next_question_plan": {},
        "response": "",
        "metadata": {},
        "basis_type": "none",
        "basis_question_ids": [],
        "basis_confidence": 0.0,
        "should_show_references": False,
        "active_skills": [],
        "suppressed_skills": [],
        "effective_skills": [],
        "active_skill_strategy_rules": {},
        "skill_decision": {},
        "strategy": "deep_dive",
        "tool_policy": "retrieve_related",
        "strategy_reason": "",
        "strategy_target_topic": "",
        "strategy_preferred_question_type": "",
        "strategy_should_retrieve": True,
        "strategy_rerank_goal": "",
    }


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
    """Run the interview graph and yield the existing SSE-compatible events."""
    queue: asyncio.Queue = asyncio.Queue()
    token = _event_queue_var.set(queue)
    input_state = _initial_state(
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
    config = {
        "configurable": {
            "thread_id": f"chat-{conversation_id}-{user_id}-{time.time():.0f}"
        }
    }

    async def _run_graph() -> None:
        t0 = time.monotonic()
        try:
            await chat_graph.ainvoke(input_state, config=config)
            logger.info(f"Chat graph completed in {time.monotonic() - t0:.1f}s")
        except Exception as e:
            logger.exception("Chat graph 执行失败")
            queue.put_nowait(
                {"type": "error", "message": _sanitize_error_message(e)}
            )
        finally:
            queue.put_nowait(_SENTINEL)

    graph_task = asyncio.create_task(_run_graph())

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
