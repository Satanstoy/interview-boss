"""Chat Agent Nodes — 面试对话状态机的各节点实现"""

import json
import logging
import os
import re
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
    LLM_RERANK_PROMPT,
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
RERANK_CANDIDATE_LIMIT = 15
RERANK_RETURN_LIMIT = 5


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


def _restore_active_skills_from_metadata(
    state: ChatState,
    metadata: dict,
    registry=None,
) -> None:
    """Restore active skills from persisted names and load latest instructions.

    Called at start of each round to re-activate skills that were active at end
    of the previous round.  Loads fresh instructions from the registry so
    edits to SKILL.md are picked up immediately.
    """
    persisted_skill_names = metadata.get("active_skill_names", [])
    if not persisted_skill_names:
        return
    if registry is None:
        from app.agents.chat.skills import get_default_registry
        registry = get_default_registry()
    restored_instructions: list[dict] = []
    valid_skill_names: list[str] = []
    for name in persisted_skill_names:
        skill = registry.get(name)
        if not skill:
            continue
        valid_skill_names.append(name)
        instruction = skill.get_instruction()
        if instruction:
            restored_instructions.append({"skill_name": name, "instruction": instruction})
    state["active_skills"] = valid_skill_names
    state["active_skill_instructions"] = restored_instructions


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

    # 结束面试关键词（优先于 practice_request，避免"结束"被误判为换题）
    end_keywords = [
        "结束面试", "面试结束", "面试到此", "到此为止", "面试先到这里",
        "请你结束", "请结束", "生成面试总结", "生成一份面试总结",
        "面试总结", "收尾吧", "可以结束了", "今天就到这里", "先到这里吧",
    ]
    if any(kw in user_message for kw in end_keywords):
        return {"intent": "end_interview"}

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
    search_query = state.get("search_query", "")
    keywords = state.get("keywords", [])
    negative_terms = state.get("search_negative_terms", [])
    question_type = state.get("question_type")
    retrieval_intent = state.get("retrieval_intent")

    if search_query:
        query_keywords = search_query.split()
    elif keywords:
        query_keywords = keywords
    else:
        logger.info("RAG 检索: 无 search_query 和 keywords，跳过")
        return {"retrieved_questions": []}

    logger.info(
        f"RAG 检索: search_query='{search_query}', keywords={keywords}, "
        f"negative_terms={negative_terms}, question_type={question_type}, "
        f"retrieval_intent={retrieval_intent}"
    )

    exclude_ids = {q["id"] for q in state.get("retrieved_questions", []) if "id" in q}
    job_position = state.get("job_position")

    from app.services.fts_service import hybrid_search

    results = hybrid_search(
        keywords=query_keywords,
        query_text=search_query or " ".join(keywords),
        limit=RERANK_CANDIDATE_LIMIT,
        job_position=job_position,
        exclude_ids=exclude_ids,
        negative_terms=negative_terms,
        question_type=question_type,
        retrieval_intent=retrieval_intent,
    )
    logger.info(
        "RAG 检索: 返回 "
        f"{len(results)} 条候选，top={[{'id': q.get('id'), 'title': q.get('question', '')[:30], 'rrf': round(q.get('_rrf_score', 0), 5)} for q in results[:5]]}"
    )
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


def _determine_interview_phase(recent_count: int) -> str:
    """根据对话轮数判定当前面试阶段

    目标：12-15 个问题，约 30-50 分钟（每题 ~2 条消息）。
    开场(2) + 12题(24) = 26 条，15题(30) = 32 条。

    Args:
        recent_count: 总消息数（不含当前用户消息）
    """
    if recent_count <= 2:
        return "开场阶段：候选人刚做完自我介绍。简短过渡（不要夸奖），直接问第一个技术问题，从项目深挖开始。"
    if recent_count <= 32:
        return "面试进行中。根据候选人回答和你的判断，自由穿插项目深挖、八股、算法。"
    if recent_count <= 44:
        return '面试已进行较长时间。如果已覆盖项目、八股、算法至少各 1 轮，可以收尾。'
    return '面试时间已到。请结束技术提问，问一句"你有什么想问的吗？"后收尾。'


def validate_basis(basis: dict, retrieved_ids: set[int]) -> dict:
    """验证并修正 basis 数据（纯函数，易于测试）。

    规则：
    - 无 basis_type → conversation, 不展示
    - interview_question/mixed: 过滤非 retrieved 的 question_ids
      - 过滤后无有效 ID → 不展示，confidence 降至 0.3
      - confidence < 0.65 → 不展示
      - 否则展示
    - 其他类型 (resume/jd/knowledge/clarification): 清空 question_ids, 不展示

    Args:
        basis: _parse_basis_from_response 的输出
        retrieved_ids: 当前检索到的题目 ID 集合

    Returns:
        修正后的 basis dict
    """
    if not basis["basis_type"]:
        basis["basis_type"] = "conversation"
        basis["basis_confidence"] = 0.0
        basis["should_show_references"] = False
    elif basis["basis_type"] in ("interview_question", "mixed"):
        valid_ids = [qid for qid in basis["basis_question_ids"] if qid in retrieved_ids]
        basis["basis_question_ids"] = valid_ids
        if not valid_ids:
            basis["should_show_references"] = False
            basis["basis_confidence"] = min(basis["basis_confidence"], 0.3)
        elif basis["basis_confidence"] < 0.65:
            basis["should_show_references"] = False
        else:
            basis["should_show_references"] = True
    else:
        basis["basis_question_ids"] = []
        basis["should_show_references"] = False

    return basis


_BASIS_STOP_TERMS = {
    "详细",
    "介绍",
    "一下",
    "具体",
    "什么",
    "怎么",
    "如何",
    "为什么",
    "项目",
    "问题",
    "流程",
    "作用",
    "场景",
    "区别",
}


def _basis_tokens(text: str) -> set[str]:
    tokens = set()
    for token in re.findall(r"[a-zA-Z][a-zA-Z0-9_.+#-]{1,}|[一-鿿]{2,8}", text or ""):
        normalized = token.lower().strip()
        if normalized and normalized not in _BASIS_STOP_TERMS:
            tokens.add(normalized)
    return tokens


def _filter_basis_ids_by_response(
    response_text: str, basis_ids: list[int], retrieved: list[dict]
) -> list[int]:
    """Keep only basis questions that are visibly aligned with the final reply."""
    if not basis_ids or not retrieved:
        return []
    response_tokens = _basis_tokens(response_text)
    if not response_tokens:
        return []

    retrieved_map = {q.get("id"): q for q in retrieved}
    aligned = []
    for qid in basis_ids:
        question = retrieved_map.get(qid)
        if not question:
            continue
        question_tokens = _basis_tokens(question.get("question", ""))
        english_overlap = {
            t
            for t in question_tokens & response_tokens
            if re.search(r"[a-zA-Z]", t) and len(t) >= 2
        }
        cjk_overlap = {
            t for t in question_tokens & response_tokens if re.search(r"[一-鿿]", t)
        }
        if english_overlap or len(cjk_overlap) >= 2:
            aligned.append(qid)
    return aligned


def _build_next_question_plan_prompt(plan: dict) -> str:
    if not plan:
        return ""
    if plan.get("must_ask") and plan.get("question_text"):
        return (
            "<next_question_plan>\n"
            f"basis_type: {plan.get('basis_type')}\n"
            f"question_id: {plan.get('question_id')}\n"
            f"question_text: {plan.get('question_text')}\n"
            f"strategy: {plan.get('strategy')}\n"
            f"allowed_focus: {plan.get('allowed_focus', [])}\n"
            f"forbidden_focus: {plan.get('forbidden_focus', [])}\n"
            "must_ask: true\n"
            "Instruction: 你必须围绕 question_text 提出下一道面试题。可以自然改写，"
            "可以加一句短转场，但不能换成别的技术点、别的题目或纯自由追问。\n"
            "</next_question_plan>"
        )
    return (
        "<next_question_plan>\n"
        "basis_type: conversation\n"
        f"strategy: {plan.get('strategy')}\n"
        f"allowed_focus: {plan.get('allowed_focus', [])}\n"
        "must_ask: false\n"
        "Instruction: 没有强制题库题时，围绕候选人最新回答做自然追问。\n"
        "</next_question_plan>"
    )


def _question_plan_adherence(response_text: str, plan: dict) -> dict:
    if not plan or not plan.get("must_ask") or not plan.get("question_text"):
        return {"adheres": True, "score": 1.0, "reason": "conversation_plan"}

    response_tokens = _basis_tokens(response_text)
    plan_tokens = _basis_tokens(str(plan.get("question_text", "")))
    focus_tokens = set()
    for term in plan.get("allowed_focus", []) or []:
        focus_tokens.update(_basis_tokens(str(term)))
    expected = plan_tokens | focus_tokens
    if not expected:
        return {"adheres": True, "score": 1.0, "reason": "no_plan_tokens"}

    overlap = response_tokens & expected
    response_lower = (response_text or "").lower()
    phrase_hits = set()
    for term in (plan.get("allowed_focus", []) or []):
        text = str(term or "").strip().lower()
        if len(text) >= 2 and text in response_lower:
            phrase_hits.add(text)
    for token in plan_tokens:
        if len(token) >= 2 and token in response_lower:
            phrase_hits.add(token)
            if len(phrase_hits) >= 3:
                break
    overlap = overlap | phrase_hits
    score = len(overlap) / max(1, min(len(expected), 8))
    adheres = len(overlap) >= 2 or score >= 0.35
    return {
        "adheres": adheres,
        "score": round(score, 3),
        "reason": "keyword_overlap" if adheres else "weak_plan_overlap",
        "overlap": sorted(overlap)[:10],
    }


def _strip_basis_markup(text: str) -> str:
    text = re.sub(r"\[BASIS\].*?\[/BASIS\]", "", text or "", flags=re.DOTALL)
    text = re.sub(r"\[BASIS\]\{[^}]*\}", "", text)
    return text.strip()


async def _repair_response_to_question_plan(
    *,
    user_id: int,
    user_message: str,
    original_response: str,
    plan: dict,
) -> dict:
    """Rewrite a drifted interviewer question so it follows the selected plan."""
    if not plan or not plan.get("must_ask") or not plan.get("question_text"):
        return {"response": original_response, "repaired": False, "reason": "no_plan"}

    question_text = str(plan.get("question_text") or "").strip()
    strategy = str(plan.get("strategy") or "").strip()
    source = str(plan.get("source") or "").strip()
    prompt = f"""
你是模拟面试官的出题修复器。上一版问题没有遵守本轮已选中的题目，请只输出修复后的面试官下一问。

必须遵守：
1. 下一问必须围绕 planned_question，可以自然改写，但不能换成别的题。
2. 可以根据候选人最新回答加一句很短的转场。
3. 不要输出解释、JSON、标签、编号或 [BASIS]。
4. 输出 1 个中文面试问题，长度控制在 80 字以内。

strategy: {strategy}
source: {source}
planned_question: {question_text}
allowed_focus: {plan.get("allowed_focus", [])}
forbidden_focus: {plan.get("forbidden_focus", [])}

候选人最新回答：
{user_message[:1200]}

上一版偏离的问题：
{original_response[:800]}
""".strip()

    try:
        repaired = await _call_llm_with_retry(
            prompt,
            system_msg="你只负责把偏离的面试问题改写为符合既定题目的下一问。",
            user_id=user_id,
        )
    except Exception as e:
        logger.warning(f"Question plan repair failed: {e}")
        repaired = ""

    repaired = _strip_basis_markup(repaired)
    if not repaired:
        repaired = f"换个方向，{question_text}"

    adherence = _question_plan_adherence(repaired, plan)
    return {
        "response": repaired,
        "repaired": True,
        "reason": "plan_drift_repaired",
        "adherence": adherence,
    }


def _contains_negative_term(question: dict, negative_terms: list[str]) -> bool:
    if not negative_terms:
        return False
    text = " ".join(
        str(question.get(field) or "") for field in ("question", "cat1", "cat2", "tags")
    ).lower()
    return any(str(term).lower() in text for term in negative_terms if term)


def _keyword_overlap_score(question: dict, terms: list[str]) -> int:
    text = " ".join(
        str(question.get(field) or "") for field in ("question", "cat1", "cat2", "tags")
    ).lower()
    score = 0
    for term in terms or []:
        term = str(term or "").strip().lower()
        if len(term) >= 2 and term in text:
            score += 1
    return score


def _clamp_confidence(value) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError, OverflowError):
        return 0.0


def _format_rerank_candidates(candidates: list[dict]) -> str:
    lines = []
    for idx, q in enumerate(candidates[:RERANK_CANDIDATE_LIMIT], 1):
        lines.append(
            f"{idx}. id={q.get('id')} | cat={q.get('cat1', '')}/{q.get('cat2', '')} | "
            f"rrf={round(float(q.get('_rrf_score') or 0), 5)} | "
            f"h={q.get('_heuristic_score', 0)} | freq={q.get('frequency', '')} | "
            f"tags={q.get('tags', '')} | question={q.get('question', '')}"
        )
    return "\n".join(lines)


def _deterministic_rerank_result(
    candidates: list[dict],
    negative_terms: list[str],
    strategy: str,
    target_topic: str,
    search_query: str,
) -> dict:
    """Fast local rerank used by default to avoid an extra LLM round-trip."""
    terms = []
    terms.extend((search_query or "").split())
    terms.extend((target_topic or "").split())
    terms = [term for term in terms if len(str(term).strip()) >= 2]

    scored = []
    filtered_reasons = []
    for idx, candidate in enumerate(candidates):
        qid = candidate.get("id")
        if qid is None:
            continue
        if _contains_negative_term(candidate, negative_terms):
            filtered_reasons.append(f"negative_term:{qid}")
            continue

        overlap = _keyword_overlap_score(candidate, terms)
        rrf = float(candidate.get("_rrf_score") or 0.0)
        heuristic = float(candidate.get("_heuristic_score") or 0.0)
        frequency = float(candidate.get("frequency") or 0.0)
        cat_text = f"{candidate.get('cat1', '')} {candidate.get('cat2', '')}".lower()

        strategy_bonus = 0.0
        if strategy == "deep_dive" and any(
            token in cat_text for token in ("项目", "agent", "rag", "llm", "系统")
        ):
            strategy_bonus += 1.0
        elif strategy == "topic_shift":
            strategy_bonus += 0.4

        score = (
            overlap * 4.0
            + rrf * 100.0
            + min(heuristic, 50.0) / 10.0
            + min(frequency, 20.0) / 20.0
            + strategy_bonus
            - idx * 0.01
        )
        scored.append((score, overlap, int(qid), candidate))

    scored.sort(key=lambda item: item[0], reverse=True)
    ranked_questions = [item[3] for item in scored[:RERANK_RETURN_LIMIT]]
    ranked_ids = [int(q["id"]) for q in ranked_questions if q.get("id") is not None]

    selected_basis_ids = []
    if strategy != "clarification":
        for score, overlap, qid, _candidate in scored:
            if overlap > 0:
                selected_basis_ids.append(qid)
            if len(selected_basis_ids) >= 2:
                break

    if strategy == "clarification":
        confidence = 0.0
    elif selected_basis_ids:
        top_score = scored[0][0] if scored else 0.0
        confidence = 0.82 if top_score >= 4.0 else 0.68
    else:
        confidence = 0.35

    return {
        "ranked_question_ids": ranked_ids,
        "selected_basis_ids": selected_basis_ids,
        "ranked_questions": ranked_questions,
        "selected_basis_questions": [
            q for q in ranked_questions if q.get("id") in set(selected_basis_ids)
        ],
        "confidence": confidence,
        "should_show_references": bool(selected_basis_ids) and confidence >= 0.55,
        "reasoning_summary": "deterministic_rrf_overlap_rerank",
        "filtered_reasons": filtered_reasons,
    }


def _should_use_llm_rerank(state: ChatState, deterministic: dict) -> bool:
    """Gate expensive LLM rerank. Default is off for latency."""
    mode = os.getenv("CHAT_LLM_RERANK_MODE", "off").strip().lower()
    if mode in {"0", "false", "off", "disabled"}:
        return False
    if mode in {"1", "true", "always", "on"}:
        return True
    if mode != "auto":
        return False

    # Auto mode is intentionally conservative: only call LLM when local ranking
    # cannot find any aligned basis but the user explicitly asks to change topics.
    return (
        state.get("strategy") == "topic_shift"
        and not deterministic.get("selected_basis_ids")
        and len(state.get("retrieved_questions", [])) >= 8
    )


def validate_rerank_result(
    rerank: dict,
    candidates: list[dict],
    negative_terms: list[str],
    strategy: str,
    target_topic: str,
    search_query: str,
) -> dict:
    """硬校验 LLM rerank 输出，保证不编 ID、不选噪声 basis。"""
    candidate_map = {int(q["id"]): q for q in candidates if q.get("id") is not None}
    candidate_ids = set(candidate_map)
    filtered_reasons = []

    def valid_id_list(values) -> list[int]:
        result = []
        if not isinstance(values, list):
            return result
        for raw in values:
            try:
                qid = int(raw)
            except (TypeError, ValueError, OverflowError):
                filtered_reasons.append(f"invalid_id:{raw}")
                continue
            if qid not in candidate_ids:
                filtered_reasons.append(f"non_candidate:{qid}")
                continue
            if _contains_negative_term(candidate_map[qid], negative_terms):
                filtered_reasons.append(f"negative_term:{qid}")
                continue
            if qid not in result:
                result.append(qid)
        return result

    ranked_ids = valid_id_list(rerank.get("ranked_question_ids"))[:RERANK_RETURN_LIMIT]
    if not ranked_ids:
        ranked_ids = [
            int(q["id"])
            for q in candidates
            if q.get("id") is not None
            and not _contains_negative_term(q, negative_terms)
        ][:RERANK_RETURN_LIMIT]

    selected_basis_ids = valid_id_list(rerank.get("selected_basis_ids"))[:2]
    selected_basis_ids = [qid for qid in selected_basis_ids if qid in ranked_ids]

    confidence = _clamp_confidence(rerank.get("confidence", 0.0))
    should_show = bool(rerank.get("should_show_references", False))

    relevance_terms = []
    relevance_terms.extend((search_query or "").split())
    relevance_terms.extend((target_topic or "").split())
    if strategy == "deep_dive":
        strongly_related = [
            qid
            for qid in selected_basis_ids
            if _keyword_overlap_score(candidate_map[qid], relevance_terms) > 0
        ]
        if len(strongly_related) != len(selected_basis_ids):
            filtered = set(selected_basis_ids) - set(strongly_related)
            for qid in filtered:
                filtered_reasons.append(f"deep_dive_weak_basis:{qid}")
            selected_basis_ids = strongly_related
    elif strategy == "clarification":
        selected_basis_ids = []
        should_show = False

    if confidence < 0.55 or not selected_basis_ids:
        should_show = False

    ranked_questions = [
        candidate_map[qid] for qid in ranked_ids if qid in candidate_map
    ]
    selected_basis_questions = [
        candidate_map[qid] for qid in selected_basis_ids if qid in candidate_map
    ]

    return {
        "ranked_question_ids": ranked_ids,
        "selected_basis_ids": selected_basis_ids,
        "ranked_questions": ranked_questions,
        "selected_basis_questions": selected_basis_questions,
        "confidence": confidence,
        "should_show_references": should_show,
        "reasoning_summary": str(rerank.get("reasoning_summary", ""))[:500],
        "filtered_reasons": filtered_reasons,
    }


async def llm_rerank_questions(state: ChatState) -> dict:
    """RRF 后重排候选题。

    默认使用本地确定性排序，避免每轮额外一次 LLM 调用；如需旧的 LLM
    精排，可设置 CHAT_LLM_RERANK_MODE=always 或 auto。
    """
    candidates = state.get("retrieved_questions", [])
    if not candidates:
        return {
            "retrieved_questions": [],
            "rerank_metadata": {
                "ranked_question_ids": [],
                "selected_basis_ids": [],
                "confidence": 0.0,
                "should_show_references": False,
                "filtered_reasons": ["no_candidates"],
            },
        }

    strategy = state.get("strategy", "deep_dive")
    negative_terms = state.get("search_negative_terms", [])
    search_query = state.get("search_query") or " ".join(state.get("keywords", []))
    target_topic = state.get("strategy_target_topic", search_query)
    rerank_goal = state.get("strategy_rerank_goal", "")

    deterministic = _deterministic_rerank_result(
        candidates,
        negative_terms,
        strategy,
        target_topic,
        search_query,
    )

    if strategy == "clarification":
        return {
            "retrieved_questions": [],
            "rerank_metadata": deterministic,
        }

    if not _should_use_llm_rerank(state, deterministic):
        logger.info(
            "Deterministic rerank: "
            f"strategy={strategy}, ranked={deterministic['ranked_question_ids']}, "
            f"selected={deterministic['selected_basis_ids']}, "
            f"confidence={deterministic['confidence']}, "
            f"show_refs={deterministic['should_show_references']}, "
            f"filtered={deterministic['filtered_reasons']}"
        )
        return {
            "retrieved_questions": deterministic["ranked_questions"],
            "rerank_metadata": deterministic,
        }

    recent = state.get("recent_messages", [])
    conversation_summary = "\n".join(
        f"{'面试官' if m.get('role') == 'assistant' else '候选人'}: {m.get('content', '')[:160]}"
        for m in recent[-6:]
    )
    if state.get("compressed_context"):
        conversation_summary = (
            f"{state.get('compressed_context')[:600]}\n{conversation_summary}"
        ).strip()

    prompt = LLM_RERANK_PROMPT.format(
        user_message=state.get("user_message", ""),
        conversation_summary=conversation_summary or "暂无",
        active_skills=", ".join(state.get("active_skills", [])) or "无",
        strategy=strategy,
        target_topic=target_topic,
        rerank_goal=rerank_goal,
        search_query=search_query,
        negative_terms=", ".join(negative_terms) or "无",
        question_type=state.get("strategy_preferred_question_type")
        or state.get("question_type")
        or "未指定",
        candidates=_format_rerank_candidates(candidates),
    )

    try:
        result = await _call_llm_with_retry(
            prompt,
            user_id=state.get("user_id"),
            response_format={"type": "json_object"},
        )
        parsed = _extract_json(result)
        if not isinstance(parsed, dict):
            parsed = {}
    except Exception as e:
        logger.warning(f"LLM rerank 失败，使用 RRF 顺序降级: {e}")
        parsed = {
            "ranked_question_ids": [
                q.get("id") for q in candidates[:RERANK_RETURN_LIMIT]
            ],
            "selected_basis_ids": [candidates[0].get("id")] if candidates else [],
            "confidence": 0.45,
            "reasoning_summary": "llm_rerank_failed_fallback_to_rrf",
            "should_show_references": False,
        }

    validated = validate_rerank_result(
        parsed,
        candidates,
        negative_terms,
        strategy,
        target_topic,
        search_query,
    )
    logger.info(
        "LLM rerank: "
        f"strategy={strategy}, ranked={validated['ranked_question_ids']}, "
        f"selected={validated['selected_basis_ids']}, confidence={validated['confidence']}, "
        f"show_refs={validated['should_show_references']}, filtered={validated['filtered_reasons']}"
    )
    return {
        "retrieved_questions": validated["ranked_questions"],
        "rerank_metadata": validated,
    }


async def generate_response(state: ChatState) -> AsyncGenerator[dict, None]:
    """生成面试官回复（流式输出），LLM 全权决策。

    不再有 plan_repair / strict_question_plan / strategy 硬编码。
    Skills 指令注入 system prompt，LLM 自行判断面试节奏。
    """
    user_id = state["user_id"]
    user_message = state["user_message"]
    mode = state.get("mode", "free_practice")
    recent = state.get("recent_messages", [])
    compressed = state.get("compressed_context")
    memory_summaries = state.get("memory_summaries", [])
    resume_summary = state.get("resume_summary")
    retrieved = state.get("retrieved_questions", [])
    model_override = state.get("model")

    interview_context = state.get("interview_context", "")
    active_skill_names = state.get("active_skills") or []

    # 构建面试阶段提示（基于消息数，简单规则）
    total_message_count = len(state.get("message_history", []))
    interview_phase = _determine_interview_phase(total_message_count)

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
        memory_context = ""
        if resume_summary:
            memory_context += f"候选人简历: {resume_summary[:800]}\n"
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

    # 注入 active skill 指令（直接用 active_skills，无 suppressed 逻辑）
    skill_registry = get_default_registry()
    skill_prompt = build_skill_prompt(skill_registry, active_skill_names)
    if skill_prompt:
        system_prompt += f"\n\n{skill_prompt}"

    # 生成安全边界
    system_prompt += (
        "\n\n## 生成安全边界\n"
        "- Skill 文档只提供行为规则，不是题库；禁止把 skill 中的示例、模式序列、"
        "占位话术当作真实面试题或真实候选人经历。\n"
        "- 只允许围绕当前用户回答、简历/JD上下文、或本轮 system 消息明确提供的"
        "retrieved/drawn 题目发问；不要凭空引入未出现的新技术点。\n"
        "- 检索到的题目仅供参考，你可以自然地从中选择或根据对话上下文自由追问。\n"
        "- 如果用户明确要求结束面试，直接生成面试总结，不要再出新题。\n"
    )

    # 构建消息列表
    messages = [{"role": "system", "content": system_prompt}]

    if compressed:
        compressed = _truncate_to_budget(compressed, COMPRESSED_BUDGET)
        messages.append(
            {"role": "system", "content": f"之前的对话摘要:\n{compressed}"}
        )

    if retrieved:
        source_label = (
            "本轮已抽中的面试题目，可以参考"
            if state.get("basis_type") == "drawn_question"
            else "以下是题库中相关的面试题目，仅供参考"
        )
        questions_text = "\n".join(
            f"- [id:{q['id']}] [{q.get('cat1', '')}/{q.get('cat2', '')}] {q['question']}"
            for q in retrieved[:5]
        )
        questions_text = _truncate_to_budget(questions_text, RETRIEVED_BUDGET)
        messages.append(
            {"role": "system", "content": f"{source_label}:\n{questions_text}"}
        )

    for msg in recent:
        messages.append({"role": msg["role"], "content": msg["content"]})
    messages.append({"role": "user", "content": user_message})

    # 流式生成（直接 yield，无 buffering）
    full_response = ""
    thinking_content = ""
    is_thinking = False
    import time as _time

    thinking_start_time = None

    try:
        async for event in stream_llm_messages(
            messages, user_id=user_id, yield_thinking=True, model=model_override
        ):
            if not isinstance(event, dict):
                full_response += event
                yield {"type": "chunk", "content": event}
                continue

            event_type = event.get("type")
            content = event.get("content", "")

            if event_type == "thinking_start":
                is_thinking = True
                thinking_start_time = _time.time()
                yield {"type": "thinking_start", "content": ""}
            elif event_type == "thinking":
                thinking_content += content
                yield {"type": "thinking", "content": content}
            elif event_type == "content":
                if is_thinking:
                    is_thinking = False
                    duration = (
                        round(_time.time() - thinking_start_time, 1)
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

    if is_thinking:
        duration = (
            round(_time.time() - thinking_start_time, 1) if thinking_start_time else 0
        )
        yield {
            "type": "thinking_done",
            "duration": duration,
            "content": thinking_content,
        }

    # 解析 basis（无 plan_repair，LLM 的回复就是最终回复）
    basis = _parse_basis_from_response(full_response)
    full_response = basis["clean_response"]

    retrieved_ids = {q["id"] for q in retrieved} if retrieved else set()
    basis = validate_basis(basis, retrieved_ids)
    rerank_metadata = state.get("rerank_metadata") or {}

    if state.get("basis_type") == "drawn_question" and retrieved:
        basis["basis_type"] = "drawn_question"
        basis["basis_question_ids"] = [q["id"] for q in retrieved[:2] if q.get("id")]
        basis["basis_confidence"] = 0.85
        basis["should_show_references"] = bool(basis["basis_question_ids"])

    if (
        not basis["should_show_references"]
        and rerank_metadata.get("should_show_references")
        and rerank_metadata.get("selected_basis_ids")
    ):
        basis["basis_type"] = "interview_question"
        basis["basis_question_ids"] = [
            qid for qid in rerank_metadata["selected_basis_ids"] if qid in retrieved_ids
        ]
        basis["basis_confidence"] = rerank_metadata.get("confidence", 0.0)
        basis["should_show_references"] = bool(basis["basis_question_ids"])

    if basis["should_show_references"] and basis["basis_question_ids"]:
        aligned_basis_ids = _filter_basis_ids_by_response(
            full_response, basis["basis_question_ids"], retrieved
        )
        if len(aligned_basis_ids) != len(basis["basis_question_ids"]):
            logger.info(
                "Basis alignment filtered ids: "
                f"before={basis['basis_question_ids']}, after={aligned_basis_ids}"
            )
        basis["basis_question_ids"] = aligned_basis_ids
        basis["should_show_references"] = bool(aligned_basis_ids)
        if not aligned_basis_ids:
            basis["basis_confidence"] = min(basis["basis_confidence"], 0.3)

    # 构建 metadata
    metadata = {
        "basis_type": basis["basis_type"],
        "basis_question_ids": basis["basis_question_ids"],
        "basis_confidence": basis["basis_confidence"],
        "should_show_references": basis["should_show_references"],
        "active_skills": active_skill_names,
        "asked_question_text": full_response,
    }

    if rerank_metadata:
        metadata["llm_rerank"] = {
            "ranked_question_ids": rerank_metadata.get("ranked_question_ids", []),
            "selected_basis_ids": rerank_metadata.get("selected_basis_ids", []),
            "confidence": rerank_metadata.get("confidence", 0.0),
            "should_show_references": rerank_metadata.get(
                "should_show_references", False
            ),
            "filtered_reasons": rerank_metadata.get("filtered_reasons", []),
            "reasoning_summary": rerank_metadata.get("reasoning_summary", ""),
        }

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
                    f"SELECT id, question, cat1, cat2 FROM question_bank "
                    f"WHERE id IN ({placeholders}) AND deleted_at IS NULL AND status = 'approved'",
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

    logger.info(
        f"Chat round complete: "
        f"conversation_id={state.get('conversation_id')}, "
        f"active_skills={active_skill_names}, "
        f"intent={state.get('intent')}, "
        f"search_query='{state.get('search_query', '')}', "
        f"basis_ids={basis['basis_question_ids']}, "
        f"basis_confidence={basis['basis_confidence']}, "
        f"should_show_references={basis['should_show_references']}"
    )

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

    优先解析最后一个 [BASIS] 块（prompt 要求 basis 在最后一行）。
    如果存在多个 [BASIS] 块，记录 warning 并使用最后一个。
    clean_response 删除所有 basis 块。

    Returns:
        dict with keys:
            - basis_type: str (题型分类)
            - basis_question_ids: list[int] (关联题目ID，clamped 1-999999)
            - basis_confidence: float (置信度 0-1)
            - should_show_references: bool (是否展示参考资料)
            - clean_response: str (去除所有 [BASIS] 块后的回复文本)
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

    # Find all [BASIS]...[/BASIS] blocks
    full_matches = list(_re.finditer(r"\[BASIS\](.*?)\[/BASIS\]", response, _re.DOTALL))
    # Also find [BASIS]{...} without closing tag (LLM may omit closing)
    partial_matches = list(_re.finditer(r"\[BASIS\](\{[^}]*\})", response, _re.DOTALL))

    # Combine and deduplicate (full matches take priority).
    # A partial match starting at the same position as a full match is a duplicate.
    all_matches = []
    full_start_positions = {m.start() for m in full_matches}
    for m in full_matches:
        all_matches.append(m)
    for m in partial_matches:
        if m.start() not in full_start_positions:
            all_matches.append(m)
    all_matches.sort(key=lambda x: x.start())

    if not all_matches:
        return defaults

    # Log warning if multiple blocks found
    if len(all_matches) > 1:
        logger.warning(
            f"BASIS parser: 发现 {len(all_matches)} 个 [BASIS] 块，使用最后一个"
        )

    # Use the LAST match (prompt requires basis at end of response)
    match = all_matches[-1]
    basis_block = match.group(1).strip()

    # Strip markdown code fences if present
    basis_block = _re.sub(r"^```(?:json)?\s*", "", basis_block)
    basis_block = _re.sub(r"\s*```$", "", basis_block)

    # Clean response: remove ALL [BASIS] blocks (both full and partial)
    clean_response = response
    for m in sorted(all_matches, key=lambda x: x.start(), reverse=True):
        clean_response = clean_response[: m.start()] + clean_response[m.end() :]
    clean_response = clean_response.strip()
    # Remove trailing markdown code fences from clean response
    clean_response = _re.sub(r"\s*```\s*$", "", clean_response)

    try:
        data = _json.loads(basis_block)
    except (ValueError, _json.JSONDecodeError):
        return {**defaults, "clean_response": clean_response}

    basis_type = str(data.get("type", "") or "").strip()
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError, OverflowError):
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))
    show_refs = bool(data.get("show_refs", False))

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
    tool_policy = state.get("tool_policy")
    if tool_policy == "draw_question":
        return "draw_question"
    if tool_policy == "none" or state.get("strategy_should_retrieve") is False:
        return "direct_respond"
    if tool_policy == "retrieve_related":
        return "rag_retrieve"
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


def build_react_system_prompt(state: ChatState) -> str:
    """Build system prompt for the ReAct loop.

    Structure:
    1. Base prompt (interviewer role + context)
    2. Memory summaries
    3. Session notes
    4. Compressed context
    5. Skill catalog + tool guidance
    6. Basis extraction guidance (so the final answer can still emit metadata)
    """
    from app.agents.shared.skills.builder import build_skill_catalog
    from app.agents.chat.prompts import BASIS_EXTRACT_GUIDANCE

    mode = state.get("mode", "free_practice")
    interview_context = state.get("interview_context", "")
    session_notes = state.get("session_notes", "")
    memory_summaries = state.get("memory_summaries", [])
    compressed = state.get("compressed_context")

    # Layer 1: Base prompt
    if mode == "jd_resume" and state.get("jd_text"):
        base = INTERVIEW_SYSTEM_PROMPT_JD.format(
            jd_text=state.get("jd_text", ""),
            resume_text=state.get("resume_text", ""),
            interview_context=interview_context,
            interview_phase="面试进行中",
            basis_guidance="",
        )
    else:
        base = INTERVIEW_SYSTEM_PROMPT_PRACTICE.format(
            interview_context=interview_context,
            interview_phase="面试进行中",
            memory_context="",
            basis_guidance="",
        )

    parts = [base]

    # Layer 2: Memory summaries
    if memory_summaries:
        memory_text = "\n".join(
            f"- [{m.get('memory_type', '')}] {m.get('summary', '')}"
            for m in memory_summaries[:3]
        )
        parts.append(f"## 候选人相关记忆\n{memory_text}")

    # Layer 3: Session notes
    if session_notes:
        parts.append(f"## 本次面试笔记\n{session_notes}")

    # Layer 4: Compressed context
    if compressed:
        parts.append(f"## 历史对话摘要\n{compressed}")

    # Layer 5: Skill catalog + tool guidance
    catalog = build_skill_catalog()
    if catalog:
        parts.append(catalog)

    # Layer 5.5: Active skill instructions (current-loop pending instructions)
    active_skill_instructions = state.get("active_skill_instructions", [])
    if active_skill_instructions:
        skill_parts = []
        for item in active_skill_instructions:
            name = item.get("skill_name", "")
            instruction = item.get("instruction", "")
            if instruction:
                skill_parts.append(f'<skill name="{name}">\n{instruction}\n</skill>')
        if skill_parts:
            parts.append(
                "<active_skill_instructions>\n"
                + "\n\n".join(skill_parts)
                + "\n</active_skill_instructions>"
            )

    # Layer 6: Preserve the existing basis metadata contract
    if BASIS_EXTRACT_GUIDANCE.strip():
        parts.append(BASIS_EXTRACT_GUIDANCE)

    return "\n\n".join(parts)
