"""Chat Agent Graph — 面试对话状态机

由于需要 token 级流式输出，不使用 LangGraph 的 graph.invoke/graph.stream，
而是直接编排节点函数实现流式管道。

流程: recall_memories(简历) → load_history → load_session_notes → summarize_context
      → classify_and_recall(合并: 意图+记忆+关键词)
      → [intent路由] → fts_retrieve → generate_response(流式) → extract_memory(异步)
"""

import logging
from typing import AsyncGenerator
from app.agents.chat.state import ChatState
from app.agents.chat.nodes import (
    recall_memories,
    load_history,
    summarize_context,
    fts_retrieve,
    generate_response,
    generate_direct_response,
    extract_memory,
    check_round_limit,
    route_after_classify,
)
from app.services import chat_service
from app.services.memory_recall_service import (
    classify_and_recall,
    classify_and_recall_fast,
)
from app.agents.chat.context_builder import build_interview_context

logger = logging.getLogger("interview-boss")

_FRIENDLY_ERROR = "AI 服务配置错误，请在系统设置中配置有效的 API Key"


def _extract_company(question: dict) -> str:
    """从题目 sources 中提取公司名"""
    import json

    sources = question.get("sources", [])
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except:
            return ""
    if sources and isinstance(sources, list):
        return sources[0].get("company", "")
    return ""


def _extract_round(question: dict) -> str:
    """从题目 sources 中提取面试轮次"""
    import json

    sources = question.get("sources", [])
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except:
            return ""
    if sources and isinstance(sources, list):
        return sources[0].get("round", "")
    return ""


def _sanitize_error_message(e: Exception) -> str:
    err_str = str(e).lower()
    if "401" in err_str or "invalid api key" in err_str or "unauthorized" in err_str:
        return _FRIENDLY_ERROR
    return f"处理消息时出现错误: {str(e)}"


async def run_chat(
    conversation_id: str,
    user_id: int,
    user_message: str,
    mode: str = "free_practice",
    jd_id: int = None,
    resume_text: str = None,
    jd_text: str = None,
    model: str = None,
) -> AsyncGenerator[dict, None]:
    """运行面试对话流程，yield SSE 事件。

    Yields:
        {"type": "chunk", "content": "..."}      — 流式文本片段
        {"type": "retrieved", "questions": [...]} — 检索到的相关题目
        {"type": "done", "metadata": {...}}       — 完成
        {"type": "error", "message": "..."}       — 错误
    """
    # 初始化状态
    state: ChatState = {
        "conversation_id": conversation_id,
        "user_id": user_id,
        "user_message": user_message,
        "mode": mode,
        "jd_id": jd_id,
        "jd_text": jd_text,
        "resume_text": resume_text,
        "model": model,
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
        "answer_complete": False,
        "retrieved_questions": [],
        "response": "",
        "metadata": {},
    }

    try:
        # Step 1: 加载简历记忆和历史（并行）
        import asyncio

        yield {"type": "step", "step": "loading", "message": "正在加载对话历史..."}
        memory_result, history_result = await asyncio.gather(
            recall_memories(state),
            load_history(state),
        )
        state.update(memory_result)
        state.update(history_result)

        # Step 1.5: 加载 session notes + 构建面试上下文 + 轮次限制检查
        state["session_notes"] = chat_service.get_session_notes(conversation_id)

        # 构建面试上下文（岗位、分类、练习统计、历史面试）
        yield {"type": "step", "step": "context", "message": "正在加载个人画像..."}
        interview_context, job_position = build_interview_context(
            user_id, conversation_id=conversation_id
        )
        state["interview_context"] = interview_context
        state["job_position"] = job_position

        if not check_round_limit(state.get("message_history", [])):
            yield {
                "type": "error",
                "message": "对话已达最大轮次限制（50轮），请新建对话继续",
            }
            return

        # Step 2: 上下文压缩
        yield {"type": "step", "step": "analyzing", "message": "正在分析对话上下文..."}
        compress_result = await summarize_context(state)
        state.update(compress_result)

        # Step 3: 意图分类 + 记忆召回
        # 优化：第一条消息用快速路径（零 LLM 成本），减少首次响应延迟
        is_first_message = len(state.get("message_history", [])) <= 1

        recent = state.get("recent_messages", [])
        recent_context = ""
        if recent:
            recent_context = "\n".join(
                f"{'面试官' if m['role'] == 'assistant' else '候选人'}: {m['content'][:100]}"
                for m in recent[-4:]
            )

        if is_first_message:
            # 快速路径：规则分类 + 最近记忆，零 LLM 成本
            yield {
                "type": "step",
                "step": "understanding",
                "message": "正在理解你的问题...",
            }
            (
                intent,
                memory_ids,
                keywords,
                search_query,
                answer_complete,
            ) = await classify_and_recall_fast(
                user_message=user_message,
                memory_summaries=state.get("memory_summaries", []),
                recent_context=recent_context,
            )
        else:
            # 完整路径：LLM 分类 + 语义记忆召回 + 检索查询改写
            yield {
                "type": "step",
                "step": "understanding",
                "message": "正在分析你的回答...",
            }
            (
                intent,
                memory_ids,
                keywords,
                search_query,
                answer_complete,
            ) = await classify_and_recall(
                user_message=user_message,
                recent_context=recent_context,
                memory_summaries=state.get("memory_summaries", []),
                user_id=user_id,
            )
        state["intent"] = intent
        state["keywords"] = keywords
        state["search_query"] = search_query
        state["answer_complete"] = answer_complete

        # Step 3.5: 解析 LLM 选中的记忆（按 ID 获取完整内容）
        if memory_ids:
            full_memories = await asyncio.to_thread(
                chat_service.get_memories_by_ids, memory_ids, user_id
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
            # 降级：使用最近的记忆
            state["memory_summaries"] = chat_service.get_memory_summaries(
                user_id, limit=3
            )

        # Step 3.8: 预笔记（零 LLM 成本，为 session notes 提供当前 turn 的预览）
        if state.get("intent") == "interview_question" and keywords:
            topic_tag = ", ".join(keywords[:3])
            pre_note = f"[pending] 候选人正在回答: {topic_tag}"
            current_notes = state.get("session_notes", "")
            state["session_notes"] = (
                f"{current_notes}\n{pre_note}" if current_notes else pre_note
            )

        # Step 4: 显式条件路由（基于 LangGraph 最佳实践）
        route = route_after_classify(state)
        logger.info(
            f"路由决策: intent={state.get('intent')}, route={route}, keywords={state.get('keywords')}, search_query='{state.get('search_query')}'"
        )
        if route == "rag_retrieve":
            # 需要 RAG 检索
            yield {
                "type": "step",
                "step": "searching",
                "message": "正在搜索相关面试题...",
            }
            retrieve_result = await fts_retrieve(state)
            state.update(retrieve_result)

            # 发送检索结果事件
            if state["retrieved_questions"]:
                yield {
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
                        for q in state["retrieved_questions"][:3]
                    ],
                }

            # Step 5: 流式生成回复
            yield {"type": "step", "step": "generating", "message": "正在生成回复..."}
            async for event in generate_response(state):
                if event["type"] == "done":
                    state["metadata"] = event.get("metadata", {})
                    yield {"type": "done", "metadata": state["metadata"]}
                else:
                    state["response"] += event.get("content", "")
                    yield event
        else:
            # direct_respond: 闲聊/追问，直接回复
            yield {"type": "step", "step": "generating", "message": "正在生成回复..."}
            async for event in generate_direct_response(state):
                if event["type"] == "done":
                    state["metadata"] = event.get("metadata", {})
                    yield {"type": "done", "metadata": state["metadata"]}
                else:
                    state["response"] += event.get("content", "")
                    yield event

        # Step 6: 异步提取记忆（不影响响应）
        try:
            await extract_memory(state)
        except Exception as e:
            logger.debug(f"记忆提取失败（不影响主流程）: {e}")

    except Exception as e:
        logger.error(f"Chat 流程异常: {e}", exc_info=True)
        yield {"type": "error", "message": _sanitize_error_message(e)}
