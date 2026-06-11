"""Chat Agent Nodes — 面试对话状态机的各节点实现"""

import json
import logging
from typing import AsyncGenerator
from app.services.llm import stream_llm_messages, _call_llm_with_retry, _extract_json
from app.services import chat_service
from app.services.fts_service import search_questions_fts
from app.agents.chat.state import ChatState
from app.agents.chat.prompts import (
    INTERVIEW_SYSTEM_PROMPT_JD,
    INTERVIEW_SYSTEM_PROMPT_PRACTICE,
    INTENT_CLASSIFY_PROMPT,
    KEYWORD_EXTRACT_PROMPT,
    CONTEXT_COMPRESS_PROMPT,
    MEMORY_EXTRACT_PROMPT,
    BASIS_EXTRACT_GUIDANCE,
)
from app.agents.chat.skills import get_default_registry, build_skill_prompt

logger = logging.getLogger("interview-boss")

# ── 上下文压缩阈值（字符数）──
COMPRESS_THRESHOLD = 12000  # Tier 0 上限：不压缩
SNIP_THRESHOLD = 24000  # Tier 1 上限：模板截断（无 LLM）
KEEP_RECENT_ROUNDS = 5  # 保留最近完整消息轮数

# ── Token Budget（字符数估算，~4 chars/token）──
SYSTEM_BUDGET = 3000  # ~750 tokens (increased for interview context)
MEMORY_BUDGET = 800  # ~200 tokens
COMPRESSED_BUDGET = 1200  # ~300 tokens
RETRIEVED_BUDGET = 1000  # ~250 tokens


def _count_chars(messages: list[dict]) -> int:
    """估算消息的总字符数"""
    return sum(len(m.get("content", "")) for m in messages)


def _format_messages_for_llm(messages: list[dict]) -> list[dict]:
    """将内部消息格式转换为 LLM API 消息格式"""
    result = []
    for msg in messages:
        role = msg.get("role", "user")
        if role in ("user", "assistant", "system"):
            result.append({"role": role, "content": msg.get("content", "")})
    return result


def _truncate_to_budget(text: str, budget: int) -> str:
    """截断文本到预算范围，在句子边界处断开"""
    if len(text) <= budget:
        return text
    search_from = int(budget * 0.8)
    chunk = text[search_from:budget]
    for sep in ["\n", "。", "；", ". ", "，"]:
        idx = chunk.rfind(sep)
        if idx != -1:
            return text[: search_from + idx + len(sep)]
    return text[:budget] + "..."


def _snip_messages(messages: list[dict]) -> str:
    """模板截断：将旧消息缩减为一行摘要，零 LLM 成本"""
    lines = []
    for msg in messages:
        role = "面试官" if msg["role"] == "assistant" else "候选人"
        content = msg.get("content", "")
        if len(content) <= 60:
            lines.append(f"{role}: {content}")
        else:
            lines.append(f"{role}: {content[:50]}...（共{len(content)}字）")
    return "\n".join(lines)


def _format_compressed_brief(compressed_json: dict) -> str:
    """将结构化压缩 JSON 格式化为可读摘要"""
    parts = []
    if compressed_json.get("topics"):
        parts.append("已讨论话题: " + "、".join(compressed_json["topics"]))
    if compressed_json.get("weaknesses_exposed"):
        parts.append("暴露弱点: " + "; ".join(compressed_json["weaknesses_exposed"]))
    if compressed_json.get("strengths_shown"):
        parts.append("展示强项: " + "; ".join(compressed_json["strengths_shown"]))
    if compressed_json.get("unanswered"):
        parts.append("待续话题: " + "; ".join(compressed_json["unanswered"]))
    return "\n".join(parts) if parts else ""


# ═══════════════════════════════════════════════════
#  节点实现
# ═══════════════════════════════════════════════════


async def recall_memories(state: ChatState) -> dict:
    """加载简历记忆（轻量级预加载，其他记忆延迟到意图分类后）"""
    user_id = state["user_id"]
    resume_summary = chat_service.get_resume_memory(user_id)
    return {
        "memory_summaries": [],
        "resume_summary": resume_summary,
    }


async def load_history(state: ChatState) -> dict:
    """加载对话历史"""
    conversation_id = state["conversation_id"]

    messages = chat_service.get_messages(conversation_id, limit=100)

    return {
        "message_history": messages,
    }


async def summarize_context(state: ChatState) -> dict:
    """五级渐进式上下文压缩（委托给 TokenBudgetManager）"""
    from app.agents.chat.budget import TokenBudgetManager

    budget = TokenBudgetManager()
    snapshot = budget.measure(state)

    messages = state.get("message_history", [])

    if not budget.needs_compression(snapshot):
        # Tier 0: 不需要压缩
        return {
            "recent_messages": messages[-KEEP_RECENT_ROUNDS * 2 :] if messages else [],
            "compressed_context": state.get("compressed_context"),
            "budget_snapshot": snapshot,
        }

    recent, compressed, tier = await budget.compress(
        messages=messages,
        session_notes=state.get("session_notes", ""),
        existing_compressed=state.get("compressed_context"),
        user_id=state.get("user_id"),
    )

    snapshot.compression_tier = tier
    logger.info(f"上下文压缩: tier={tier}, 利用率={snapshot.utilization_pct}%")

    return {
        "recent_messages": recent,
        "compressed_context": compressed,
        "budget_snapshot": snapshot,
    }


async def classify_intent(state: ChatState) -> dict:
    """LLM 意图分类：判断用户消息类型"""
    user_message = state["user_message"]
    recent = state.get("recent_messages", [])

    # 构建最近对话上下文
    recent_context = ""
    if recent:
        recent_context = "\n".join(
            f"{'面试官' if m['role'] == 'assistant' else '候选人'}: {m['content'][:100]}"
            for m in recent[-4:]
        )

    # 简单规则预判断（减少 LLM 调用）
    lower_msg = user_message.lower()

    # 问候/闲聊关键词
    chat_keywords = ["你好", "hello", "hi", "谢谢", "再见", "拜拜", "ok", "好的", "嗯"]
    if any(kw == lower_msg.strip() for kw in chat_keywords):
        return {"intent": "chat"}

    # 练习请求关键词
    practice_keywords = ["出题", "来一道", "换一个", "换个", "练习", "开始", "出个"]
    if any(kw in user_message for kw in practice_keywords):
        return {"intent": "practice_request"}

    # 追问关键词
    follow_up_keywords = [
        "解释",
        "详细",
        "具体",
        "为什么",
        "怎么",
        "能再说",
        "不太明白",
        "什么意思",
    ]
    if any(kw in user_message for kw in follow_up_keywords) and len(user_message) < 50:
        return {"intent": "follow_up"}

    # 默认：用 LLM 分类
    try:
        prompt = INTENT_CLASSIFY_PROMPT.format(
            user_message=user_message,
            recent_context=recent_context,
        )
        result = await _call_llm_with_retry(prompt, user_id=state.get("user_id"))
        intent = result.strip().lower()

        valid_intents = {"interview_question", "practice_request", "chat", "follow_up"}
        if intent in valid_intents:
            return {"intent": intent}
    except Exception as e:
        logger.warning(f"意图分类 LLM 调用失败: {e}")

    # 默认当作面试回答
    return {"intent": "interview_question"}


async def extract_keywords(state: ChatState) -> dict:
    """从用户消息中提取 FTS5 检索关键词"""
    user_message = state["user_message"]

    # 获取题库分类（用于提示）
    from app.db.connection import get_db_connection

    with get_db_connection() as conn:
        cats = conn.execute(
            "SELECT DISTINCT cat1 FROM question_bank WHERE deleted_at IS NULL AND cat1 != '' LIMIT 20"
        ).fetchall()
    categories = ", ".join(row[0] for row in cats) if cats else ""

    try:
        prompt = KEYWORD_EXTRACT_PROMPT.format(
            user_message=user_message,
            categories=categories,
        )
        result = await _call_llm_with_retry(
            prompt,
            user_id=state.get("user_id"),
            response_format={"type": "json_object"},
        )
        parsed = _extract_json(result)
        keywords = parsed.get("keywords", [])
        if isinstance(keywords, list) and keywords:
            return {"keywords": keywords[:5]}
    except Exception as e:
        logger.warning(f"关键词提取失败: {e}")

    # 降级：简单分词
    import re

    words = re.findall(r"[一-鿿]+|[a-zA-Z]+", user_message)
    keywords = [w for w in words if len(w) >= 2][:5]
    return {"keywords": keywords}


async def fts_retrieve(state: ChatState) -> dict:
    """混合检索：FTS5 + 向量 + RRF 融合（优先使用 search_query，降级到 keywords）"""
    # 优先使用基于上下文改写的检索查询
    search_query = state.get("search_query", "")
    keywords = state.get("keywords", [])

    if search_query:
        # search_query 是完整查询语句，拆分为关键词列表传给 FTS
        query_keywords = search_query.split()
    elif keywords:
        query_keywords = keywords
    else:
        logger.info("RAG 检索: 无 search_query 和 keywords，跳过")
        return {"retrieved_questions": []}

    logger.info(
        f"RAG 检索: search_query='{search_query}', keywords={keywords}, 最终查询词={query_keywords}"
    )

    # 收集已展示的题目 ID，避免重复检索
    exclude_ids = {q["id"] for q in state.get("retrieved_questions", []) if "id" in q}

    job_position = state.get("job_position")

    # 混合搜索：FTS5 + 向量 + RRF 融合
    from app.services.fts_service import hybrid_search

    results = hybrid_search(
        keywords=query_keywords,
        query_text=search_query or " ".join(keywords),
        limit=5,
        job_position=job_position,
        exclude_ids=exclude_ids,
    )
    logger.info(f"RAG 检索: 返回 {len(results)} 条题目")
    return {"retrieved_questions": results}


# ── 检索时机门控 ──


def should_retrieve(state: ChatState) -> bool:
    """判断当前轮次是否需要 RAG 检索（检索时机门控）

    核心目的：为面试官出新题提供真实面经参考。
    检索触发时机 = 面试官即将出新题（用户回答完整 或 用户主动要题）。

    决策逻辑：
    - chat/follow_up → 不检索（闲聊/追问不需要出新题）
    - practice_request → 检索（用户主动要题）
    - interview_question + answer_complete=True → 检索（回答完整，面试官要出新题）
    - interview_question + answer_complete=False → 不检索（用户还在回答，面试官会追问，不需要出新题）

    Returns:
        True 如果需要检索，False 如果可以跳过
    """
    intent = state.get("intent", "interview_question")

    # chat 和 follow_up 不需要检索
    if intent in ("chat", "follow_up"):
        return False

    # practice_request 始终检索
    if intent == "practice_request":
        return True

    # interview_question：仅在回答完整时检索
    return state.get("answer_complete", False)


def _determine_interview_phase(
    recent_count: int, active_skills: list[str] = None
) -> str:
    """根据对话轮数和激活的 skills 判定当前面试阶段

    目标：12-15 个问题，约 30-50 分钟（每题 ~2 条消息）。
    开场(2) + 12题(24) = 26 条，15题(30) = 32 条。

    Args:
        recent_count: 总消息数（不含当前用户消息）
        active_skills: 当前激活的 skill 名称列表
    """
    # 开场白(assistant) + 用户自我介绍(user) = 2 条
    if recent_count <= 2:
        return "开场阶段：候选人刚做完自我介绍。简短过渡（不要夸奖），直接问第一个技术问题，从项目深挖开始。"
    # 2~32 条 = 1~15 轮问答 → 主面试阶段
    if recent_count <= 32:
        # 当 hr-soft-skills 激活且已过面试中期（约第10题），提示主动转入 HR
        if active_skills and "hr-soft-skills" in active_skills and recent_count >= 22:
            return '面试中后期。技术考察已进行多轮，现在需要自然地转入 HR 环节：直接问 1-2 个 HR 软素质问题（职业规划、团队角色、选择公司的考量等），不需要说过渡语，然后问"你有什么想问我们的吗？"。'
        return "面试进行中。继续穿插式提问（项目深挖 + 八股 + 算法），根据候选人回答决定追问深度。"
    # 32~44 条 = 16~22 轮 → 可以考虑收尾，可以问 HR 问题
    if recent_count <= 44:
        return '面试已进行较长时间。如果已覆盖项目、八股、算法至少各 1 轮，可以收尾。收尾前可以问 1-2 个 HR 软素质问题（职业规划、团队合作等），然后问"你有什么想问的吗？"。'
    # 超过 22 轮 → 强制收尾
    return '面试时间已到。请结束技术提问，问一句"你有什么想问的吗？"后收尾。'


async def generate_response(state: ChatState) -> AsyncGenerator[dict, None]:
    """生成面试官回复（流式输出），带 token budget 控制"""
    user_id = state["user_id"]
    user_message = state["user_message"]
    mode = state.get("mode", "free_practice")
    recent = state.get("recent_messages", [])
    compressed = state.get("compressed_context")
    memory_summaries = state.get("memory_summaries", [])
    resume_summary = state.get("resume_summary")
    retrieved = state.get("retrieved_questions", [])
    model_override = state.get("model")

    # 构建面试上下文（岗位、分类、练习统计）
    interview_context = state.get("interview_context", "")

    # Skills 系统：先匹配 skills（供面试阶段判定使用）
    # 注意：message_count 必须用总消息数（非 recent 窗口），否则 hr-soft-skills 的 12+ 条件永远不满足
    skill_registry = get_default_registry()
    total_message_count = len(state.get("message_history", []))
    state_with_count = {**state, "message_count": total_message_count}
    matched_skills = skill_registry.match_skills(state_with_count)
    active_skill_names = [s.name for s in matched_skills]
    logger.info(f"Active skills: {active_skill_names}")

    # 用 active skills 判定面试阶段（必须用总消息数，recent 窗口被 KEEP_RECENT_ROUNDS 截断）
    interview_phase = _determine_interview_phase(
        total_message_count, active_skill_names
    )

    # 构建 system prompt
    if mode == "jd_resume":
        system_prompt = INTERVIEW_SYSTEM_PROMPT_JD.format(
            jd_text=state.get("jd_text", "未提供 JD"),
            resume_text=resume_summary or state.get("resume_text", "未提供简历"),
            interview_context=interview_context or "",
            interview_phase=interview_phase,
            basis_guidance=BASIS_EXTRACT_GUIDANCE,
        )
    else:
        # 构建记忆上下文（使用摘要而非完整内容）
        memory_context = ""
        if resume_summary:
            memory_context += f"候选人简历: {resume_summary[:500]}\n"
        if memory_summaries:
            weak = [m for m in memory_summaries if m["memory_type"] == "weakness"]
            strong = [m for m in memory_summaries if m["memory_type"] == "strength"]
            if weak:
                memory_context += (
                    "已知弱点: " + "; ".join(m["summary"] for m in weak[:3]) + "\n"
                )
            if strong:
                memory_context += (
                    "已知强项: " + "; ".join(m["summary"] for m in strong[:3]) + "\n"
                )

        memory_context = _truncate_to_budget(memory_context, MEMORY_BUDGET)
        system_prompt = INTERVIEW_SYSTEM_PROMPT_PRACTICE.format(
            memory_context=memory_context or "暂无用户背景信息",
            interview_context=interview_context or "",
            interview_phase=interview_phase,
            basis_guidance=BASIS_EXTRACT_GUIDANCE,
        )

    system_prompt = _truncate_to_budget(system_prompt, SYSTEM_BUDGET)

    # 注入 active skill 指令到 system prompt
    skill_prompt = build_skill_prompt(skill_registry, active_skill_names)
    if skill_prompt:
        system_prompt += f"\n\n{skill_prompt}"

    # 构建消息列表
    messages = [{"role": "system", "content": system_prompt}]

    # 添加压缩上下文（budget 控制）
    if compressed:
        compressed = _truncate_to_budget(compressed, COMPRESSED_BUDGET)
        messages.append(
            {
                "role": "system",
                "content": f"之前的对话摘要:\n{compressed}",
            }
        )

    # 添加检索到的题目信息（budget 控制）
    if retrieved:
        questions_text = "\n".join(
            f"- [{q.get('cat1', '')}/{q.get('cat2', '')}] {q['question']}"
            for q in retrieved[:3]
        )
        questions_text = _truncate_to_budget(questions_text, RETRIEVED_BUDGET)
        messages.append(
            {
                "role": "system",
                "content": f"以下是题库中相关的面试题目，可以参考:\n{questions_text}",
            }
        )

    # 添加最近消息历史
    for msg in recent:
        messages.append(
            {
                "role": msg["role"],
                "content": msg["content"],
            }
        )

    # 添加当前用户消息
    messages.append({"role": "user", "content": user_message})

    # 流式生成回复（支持 thinking）
    full_response = ""
    thinking_content = ""
    is_thinking = False
    import time

    thinking_start_time = None

    try:
        async for event in stream_llm_messages(
            messages, user_id=user_id, yield_thinking=True, model=model_override
        ):
            if not isinstance(event, dict):
                # 向后兼容：如果不是 dict，当作普通 content
                full_response += event
                yield {"type": "chunk", "content": event}
                continue

            event_type = event.get("type")
            content = event.get("content", "")

            if event_type == "thinking_start":
                # ThinkingBlock 开始
                is_thinking = True
                thinking_start_time = time.time()
                yield {"type": "thinking_start", "content": ""}
            elif event_type == "thinking":
                # ThinkingBlock 内容
                thinking_content += content
                yield {"type": "thinking", "content": content}
            elif event_type == "content":
                # TextBlock 内容（thinking 结束后的正式回答）
                if is_thinking:
                    is_thinking = False
                    duration = (
                        round(time.time() - thinking_start_time, 1)
                        if thinking_start_time
                        else 0
                    )
                    yield {
                        "type": "thinking_done",
                        "duration": duration,
                        "content": thinking_content,
                    }
                full_response += content
                yield {"type": "chunk", "content": content}
    except Exception as e:
        logger.error(f"生成回复失败: {e}")
        yield {"type": "error", "message": "生成回复时出现错误，请稍后重试。"}
        return

    # 如果 thinking 还没结束（模型没有显式结束 thinking）
    if is_thinking:
        duration = (
            round(time.time() - thinking_start_time, 1) if thinking_start_time else 0
        )
        yield {
            "type": "thinking_done",
            "duration": duration,
            "content": thinking_content,
        }

    # 解析生成依据（basis）
    basis = _parse_basis_from_response(full_response)
    full_response = basis["clean_response"]

    if not basis["basis_type"] and retrieved:
        basis["basis_type"] = "interview_question"
        basis["basis_question_ids"] = [q["id"] for q in retrieved[:2]]
        basis["basis_confidence"] = 0.6
        basis["should_show_references"] = True

    if not basis["basis_type"]:
        if resume_summary:
            basis["basis_type"] = "resume"
        else:
            basis["basis_type"] = "knowledge"
        basis["basis_confidence"] = 0.5

    metadata = {}
    metadata["basis_type"] = basis["basis_type"]
    metadata["basis_question_ids"] = basis["basis_question_ids"]
    metadata["basis_confidence"] = basis["basis_confidence"]
    metadata["should_show_references"] = basis["should_show_references"]

    if retrieved:
        import json as _json

        metadata["retrieved_questions"] = [
            {
                "id": q["id"],
                "question": q["question"],
                "cat1": q.get("cat1", ""),
                "company": _extract_company_from_sources(q),
                "round": _extract_round_from_sources(q),
            }
            for q in retrieved[:3]
        ]

    if basis["basis_question_ids"] and retrieved:
        basis_id_set = set(basis["basis_question_ids"])
        basis_qs = [q for q in retrieved if q["id"] in basis_id_set]
        if not basis_qs:
            from app.db.connection import get_db_connection

            with get_db_connection() as conn:
                placeholders = ",".join("?" * len(basis["basis_question_ids"]))
                rows = conn.execute(
                    f"SELECT id, question, cat1, cat2 FROM question_bank WHERE id IN ({placeholders})",
                    basis["basis_question_ids"],
                ).fetchall()
                basis_qs = [
                    {"id": r[0], "question": r[1], "cat1": r[2], "cat2": r[3]}
                    for r in rows
                ]
        metadata["selected_basis_questions"] = [
            {
                "id": q["id"],
                "question": q["question"],
                "cat1": q.get("cat1", ""),
                "company": _extract_company_from_sources(q),
                "round": _extract_round_from_sources(q),
            }
            for q in basis_qs
        ]

    if resume_summary and _response_references_resume(full_response, resume_summary):
        metadata["resume_ref"] = _get_resume_name(user_id)
    if state.get("jd_text") and _response_references_jd(
        full_response, state.get("jd_text", "")
    ):
        metadata["jd_ref"] = _get_jd_title(state.get("jd_id"))

    yield {"type": "done", "metadata": metadata}


def _extract_company_from_sources(question: dict) -> str:
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


def _extract_round_from_sources(question: dict) -> str:
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


def _response_references_resume(response: str, resume_summary: str) -> bool:
    if not resume_summary or len(resume_summary) < 20:
        return False
    import re

    cjk_words = re.findall(r"[\u4e00-\u9fff]{2,6}", resume_summary[:500])
    en_words = re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", resume_summary[:500])
    keywords = list(set(cjk_words + en_words))[:15]
    return any(kw in response for kw in keywords)


def _response_references_jd(response: str, jd_text: str) -> bool:
    if not jd_text or len(jd_text) < 20:
        return False
    import re

    cjk_words = re.findall(r"[\u4e00-\u9fff]{2,6}", jd_text[:500])
    en_words = re.findall(r"[A-Za-z][A-Za-z0-9]{2,}", jd_text[:500])
    keywords = list(set(cjk_words + en_words))[:15]
    return any(kw in response for kw in keywords)


def _get_resume_name(user_id: int) -> str:
    try:
        from app.services import resume_service
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            resume = resume_service.get_resume_text(user_id)
            if resume:
                return "我的简历"
    except:
        pass
    return ""


def _get_jd_title(jd_id: int) -> str:
    if not jd_id:
        return ""
    try:
        from app.db.connection import get_db_connection

        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT job_title FROM jd WHERE id = ?", (jd_id,)
            ).fetchone()
            if row and row[0]:
                return row[0]
    except:
        pass
    return ""


def _parse_basis_from_response(response: str) -> dict:
    """从 LLM 回复中提取 [BASIS]...[/BASIS] 块并解析为结构化数据。

    Returns:
        dict with keys:
            - basis_type: str (题型分类)
            - basis_question_ids: list[int] (关联题目ID，clamped 1-999999)
            - basis_confidence: float (置信度 0-1)
            - should_show_references: bool (是否展示参考资料)
            - clean_response: str (去除 [BASIS] 块后的回复文本)
    """
    import re as _re
    import json as _json

    defaults = {
        "basis_type": "",
        "basis_question_ids": [],
        "basis_confidence": 0.0,
        "should_show_references": False,
        "clean_response": response,
    }

    # Try full [BASIS]...[/BASIS] pattern first
    match = _re.search(r"\[BASIS\](.*?)\[/BASIS\]", response, _re.DOTALL)
    if not match:
        # Fallback: [BASIS] followed by JSON object (LLM may omit closing tag)
        match = _re.search(r"\[BASIS\](\{[^}]*\})", response, _re.DOTALL)
    if not match:
        return defaults

    basis_block = match.group(1).strip()
    # Strip markdown code fences if present
    basis_block = _re.sub(r"^```(?:json)?\s*", "", basis_block)
    basis_block = _re.sub(r"\s*```$", "", basis_block)
    clean_response = (response[: match.start()] + response[match.end() :]).strip()
    # Remove trailing markdown code fences from clean response
    clean_response = _re.sub(r"\s*```\s*$", "", clean_response)

    try:
        data = _json.loads(basis_block)
    except (ValueError, _json.JSONDecodeError):
        return {**defaults, "clean_response": clean_response}

    basis_type = data.get("type", "")
    confidence = data.get("confidence", 0.0)
    show_refs = data.get("show_refs", False)

    raw_ids = data.get("question_ids", [])
    if isinstance(raw_ids, list):
        question_ids = []
        for qid in raw_ids:
            try:
                val = int(float(qid))
                question_ids.append(max(1, min(999999, val)))
            except (ValueError, TypeError, OverflowError):
                continue
    else:
        question_ids = []

    return {
        "basis_type": basis_type,
        "basis_question_ids": question_ids,
        "basis_confidence": confidence,
        "should_show_references": show_refs,
        "clean_response": clean_response,
    }


async def extract_memory(state: ChatState) -> dict:
    """从对话中自动提取用户记忆（弱点、强项等），并更新 session notes"""
    user_id = state["user_id"]
    user_message = state["user_message"]
    response = state.get("response", "")

    if not response or len(user_message) < 10:
        return {}

    # 构建对话片段（包含面试官提问上下文，提高记忆提取准确性）
    recent = state.get("recent_messages", [])
    prior_question = ""
    if recent:
        for msg in reversed(recent):
            if msg["role"] == "assistant":
                prior_question = msg["content"][:200]
                break

    history_text = f"面试官提问: {prior_question}\n候选人回答: {user_message}\n面试官追问: {response[:500]}"

    try:
        prompt = MEMORY_EXTRACT_PROMPT.format(message_history=history_text)
        result = await _call_llm_with_retry(
            prompt,
            user_id=user_id,
            response_format={"type": "json_object"},
        )
        parsed = _extract_json(result)

        if isinstance(parsed, list):
            memories = parsed
        elif isinstance(parsed, dict):
            memories = parsed.get("memories", parsed.get("items", []))
        else:
            memories = []

        for mem in memories:
            if isinstance(mem, dict) and mem.get("type") in (
                "weakness",
                "strength",
                "preference",
            ):
                chat_service.save_memory(
                    user_id=user_id,
                    memory_type=mem["type"],
                    content=mem["content"],
                    source="auto_extract",
                )

        # 累积 session notes（增强增量记忆）
        note_parts = []
        for mem in memories:
            if isinstance(mem, dict) and mem.get("type") in (
                "weakness",
                "strength",
                "preference",
            ):
                note_parts.append(f"[{mem['type']}] {mem['content']}")

        # 捕获当前话题（从 keywords）
        keywords = state.get("keywords", [])
        if keywords:
            note_parts.append(f"[topics] {', '.join(keywords[:3])}")

        # 记录被问到的题目（从 retrieved_questions）
        intent = state.get("intent", "")
        if intent == "interview_question" and state.get("retrieved_questions"):
            q = state["retrieved_questions"][0]
            note_parts.append(f"[asked] {q.get('cat1', '')}: {q['question'][:60]}")

        if note_parts:
            current_notes = state.get("session_notes", "")
            new_notes = "\n".join(note_parts)
            updated_notes = (
                f"{current_notes}\n{new_notes}" if current_notes else new_notes
            )
            if len(updated_notes) > 2000:
                # 在行边界处截断，避免切断 [tag] 标签
                all_lines = updated_notes.split("\n")
                truncated = ""
                for ln in reversed(all_lines):
                    candidate = ln + "\n" + truncated if truncated else ln
                    if len(candidate) > 2000:
                        break
                    truncated = candidate
                updated_notes = truncated
            chat_service.update_session_notes(state["conversation_id"], updated_notes)
            state["session_notes"] = updated_notes

    except Exception as e:
        logger.debug(f"记忆提取跳过: {e}")

    return {}


def route_after_intent(state: ChatState) -> str:
    """根据意图路由到不同节点"""
    intent = state.get("intent", "interview_question")

    if intent in ("practice_request", "interview_question"):
        return "extract_keywords"
    else:
        return "generate_direct"


# ── 最大轮次限制 ──
MAX_MESSAGES = 100  # 最大消息数（约 50 轮对话）


def check_round_limit(messages: list[dict]) -> bool:
    """检查消息数是否在限制内

    Returns:
        True 如果可以继续对话，False 如果已达上限
    """
    return len(messages) < MAX_MESSAGES


def route_after_classify(state: ChatState) -> str:
    """显式条件路由（基于 LangGraph 最佳实践）

    根据意图分类结果和检索时机门控决定下一步：
    - should_retrieve() 返回 True → rag_retrieve
    - should_retrieve() 返回 False → direct_respond

    Returns:
        "rag_retrieve" 或 "direct_respond"
    """
    if should_retrieve(state):
        return "rag_retrieve"
    else:
        return "direct_respond"


async def load_memories_by_intent(state: ChatState) -> dict:
    """根据意图加载记忆：面试/练习 → 话题匹配，闲聊/追问 → 最近 3 条"""
    user_id = state["user_id"]
    intent = state.get("intent", "interview_question")
    keywords = state.get("keywords", [])

    if intent in ("interview_question", "practice_request"):
        memory_summaries = chat_service.get_topic_memories(user_id, keywords, limit=5)
    else:
        memory_summaries = chat_service.get_memory_summaries(user_id, limit=3)

    return {"memory_summaries": memory_summaries}


async def generate_direct_response(state: ChatState) -> AsyncGenerator[dict, None]:
    """直接回复（无需 RAG 检索）— 用于闲聊和追问"""
    # 复用 generate_response，但不检索
    state_copy = dict(state)
    state_copy["retrieved_questions"] = []
    state_copy["keywords"] = []

    async for event in generate_response(state_copy):
        yield event
