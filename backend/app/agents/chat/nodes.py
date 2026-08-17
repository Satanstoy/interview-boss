"""Chat Agent Nodes — 面试对话状态机的各节点实现"""

import json
import html
import logging
import os
import re
from typing import AsyncGenerator
from app.services.llm import stream_llm_messages, _call_llm_with_retry, _extract_json
from app.services import chat_service
from app.services.fts_service import search_questions_fts
from app.agents.chat.state import ChatState
from app.agents.chat.chat_constants import (
    CHAT_KEYWORDS,
    PRACTICE_KEYWORDS,
    END_KEYWORDS,
    FOLLOW_UP_KEYWORDS,
    FOLLOW_UP_MAX_LENGTH,
    PUBLIC_QUESTION_PREVIEW_LIMIT,
)
from app.agents.chat.decision_config import DecisionConfig


def wrap_untrusted_context(
    source: str,
    value: object,
    max_chars: int | None = None,
) -> str:
    """Delimit dynamic data so embedded text cannot create prompt instructions."""
    text = str(value or "")
    if max_chars is not None:
        text = text[:max_chars]
    safe_source = html.escape(str(source or "unknown"), quote=True)
    safe_text = html.escape(text, quote=False)
    return (
        f'<untrusted_context source="{safe_source}">\n'
        f"{safe_text}\n"
        "</untrusted_context>"
    )
from app.agents.chat.question_plan import (
    _big_tech_next_focus,
    _build_big_tech_interview_harness_prompt,
    _should_require_bank_question,
)
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
PERSISTENT_SKILLS = frozenset({"interview-rhythm"})
REASONING_LANGUAGE_GUARDRAIL = """## 语言约束
你正在扮演中文面试官。所有输出都必须使用简体中文，包括：
- 面向候选人的最终回复
- reasoning_content / 推理过程 / 工具调用前后的分析
- 面试节奏判断、追问依据和题目选择理由

技术名词、代码、库名、英文原文引用可以保留英文，但不得用英文整句组织推理。"""


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
    persisted_skill_names = metadata.get("persistent_skill_names")
    if persisted_skill_names is None:
        # Older conversations persisted every loaded skill. Only restore skills
        # that are safe to carry across turns; interview modes such as
        # algorithm-coding/project-deep-dive must be decided again each turn.
        persisted_skill_names = [
            name
            for name in metadata.get("active_skill_names", [])
            if name in PERSISTENT_SKILLS
        ]
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
        if name not in PERSISTENT_SKILLS:
            continue
        valid_skill_names.append(name)
        instruction = skill.get_instruction()
        if instruction:
            restored_instructions.append(
                {"skill_name": name, "instruction": instruction}
            )
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

    model_capability = state.get("model_capability")
    budget = TokenBudgetManager(model_capability=model_capability)
    snapshot = budget.measure(state)

    messages = state.get("message_history", [])

    if not budget.needs_compression(snapshot):
        # Tier 0: 不需要压缩
        return {
            "recent_messages": messages[-KEEP_RECENT_ROUNDS * 2 :] if messages else [],
            "compressed_context": state.get("compressed_context"),
            "budget_snapshot": snapshot,
            "model_capability": model_capability,
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
        "model_capability": model_capability,
    }


async def classify_intent(state: ChatState) -> dict:
    """LLM 意图分类：输出结构化 ClassifyResult。

    Note: the live pipeline uses memory_recall_service.classify_and_recall.
    This node is kept for backward compatibility / standalone usage and mirrors
    the same structured output shape.
    """
    from app.agents.chat.classify_result import ClassifyResult
    from app.services import llm as llm_service

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
    if any(kw == lower_msg.strip() for kw in CHAT_KEYWORDS):
        return ClassifyResult(intent="chat").to_state()

    # 练习请求关键词
    if any(kw in user_message for kw in PRACTICE_KEYWORDS):
        return ClassifyResult(
            intent="practice_request",
            should_retrieve=True,
            requires_bank_question=True,
        ).to_state()

    # 结束面试关键词（优先于 practice_request，避免"结束"被误判为换题）
    if any(kw in user_message for kw in END_KEYWORDS):
        return ClassifyResult(
            intent="end_interview",
            transition_style="closing",
        ).to_state()

    # 追问关键词
    if (
        any(kw in user_message for kw in FOLLOW_UP_KEYWORDS)
        and len(user_message) < FOLLOW_UP_MAX_LENGTH
    ):
        return ClassifyResult(intent="follow_up").to_state()

    # 默认：用 LLM 分类并输出 JSON
    try:
        prompt = INTENT_CLASSIFY_PROMPT.format(
            user_message=user_message,
            recent_context=recent_context,
        )
        result = await _call_llm_with_retry(
            prompt,
            user_id=state.get("user_id"),
            response_format={"type": "json_object"},
        )
        parsed = _extract_json(result)
        classify_result = ClassifyResult.from_dict(parsed)
        return classify_result.to_state()
    except Exception as e:
        logger.warning(f"意图分类 LLM 调用失败: {e}")

    # 默认当作面试回答
    return ClassifyResult.default().to_state()


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


def _determine_interview_phase(
    recent_count: int, config: DecisionConfig | None = None
) -> str:
    """根据对话轮数判定当前面试阶段

    目标：12-15 个问题，约 30-50 分钟（每题 ~2 条消息）。
    开场(2) + 12题(24) = 26 条，15题(30) = 32 条。

    Args:
        recent_count: 总消息数（不含当前用户消息）
        config: 决策配置（可选，默认使用全局默认值）
    """
    cfg = config or DecisionConfig()
    if recent_count <= cfg.phase_opening_max:
        return "开场阶段：候选人刚做完自我介绍。简短过渡（不要夸奖），直接问第一个技术问题，从项目深挖开始。"
    if recent_count <= cfg.phase_active_max:
        return "面试进行中。根据候选人回答和你的判断，自由穿插项目深挖、八股、算法。"
    if recent_count <= cfg.phase_soft_close_max:
        return "面试已进行较长时间。如果已覆盖项目、八股、算法至少各 1 轮，可以收尾。"
    if recent_count <= cfg.phase_strong_close_max:
        return "面试进入强收口阶段。只补最后一个未覆盖维度，或进入 HR/反问/收尾，不要开启新的长链路话题。"
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
    for term in plan.get("allowed_focus", []) or []:
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
    # When repair fails, return empty so the caller (_enforce_question_plan_on_text)
    # can use LLM rewrite for a natural transition instead of a mechanical prefix.
    # Do NOT inject hardcoded text here — it would bypass the LLM rewrite path.

    adherence = _question_plan_adherence(repaired, plan)
    return {
        "response": repaired,
        "repaired": True,
        "reason": "plan_drift_repaired",
        "adherence": adherence,
    }


from app.agents.chat.rerank import (
    _contains_negative_term,
    _keyword_overlap_score,
    _clamp_confidence,
    _format_rerank_candidates,
    _deterministic_rerank_result,
    _should_use_llm_rerank,
    validate_rerank_result,
    llm_rerank_questions,
)

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
    config = state.get("decision_config") or DecisionConfig()
    interview_phase = _determine_interview_phase(total_message_count, config)

    # 构建 system prompt
    if mode == "jd_resume":
        system_prompt = INTERVIEW_SYSTEM_PROMPT_JD.format(
            jd_text=wrap_untrusted_context(
                "job_description", state.get("jd_text", "未提供 JD")
            ),
            resume_text=wrap_untrusted_context(
                "resume", resume_summary or state.get("resume_text", "未提供简历")
            ),
            interview_context=wrap_untrusted_context(
                "interview_context", interview_context or ""
            ),
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
            memory_context=wrap_untrusted_context(
                "memory", memory_context or "暂无用户背景信息"
            ),
            interview_context=wrap_untrusted_context(
                "interview_context", interview_context or ""
            ),
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
            {
                "role": "system",
                "content": (
                    "之前的对话摘要:\n"
                    + wrap_untrusted_context("compressed_history", compressed)
                ),
            }
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
            {
                "role": "system",
                "content": (
                    f"{source_label}:\n"
                    + wrap_untrusted_context("retrieved_questions", questions_text)
                ),
            }
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
            for q in retrieved[:PUBLIC_QUESTION_PREVIEW_LIMIT]
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


from app.agents.chat.memory_extract import (
    _extract_company_from_sources,
    _extract_round_from_sources,
    _response_references_resume,
    _response_references_jd,
    _get_resume_name,
    _get_jd_title,
    _parse_basis_from_response,
    extract_memory,
)

def route_after_intent(state: ChatState) -> str:
    """根据意图路由到不同节点"""
    intent = state.get("intent", "interview_question")

    if intent in ("practice_request", "interview_question"):
        return "extract_keywords"
    else:
        return "generate_direct"


# ── 最大轮次限制 ──
MAX_MESSAGES = 100  # 最大消息数（约 50 轮对话）


def check_round_limit(
    messages: list[dict], *, allow_incomplete_distribution: bool = False
) -> bool:
    """检查消息数是否在限制内

    Returns:
        True 如果可以继续对话，False 如果已达上限
    """
    return len(messages) < MAX_MESSAGES or allow_incomplete_distribution


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


def _build_tool_strategy(state: ChatState) -> str:
    """Build tool usage strategy guidance based on typed state fields.

    The heavy branching has moved to ``compute_tool_strategy``; this thin
    wrapper preserves the call site in ``build_react_system_prompt``.
    """
    from app.agents.chat.tool_strategy import compute_tool_strategy

    strategy = compute_tool_strategy(state)
    return strategy.to_prompt_text()


def build_runtime_tool_contract_message(state: ChatState) -> str:
    """Build a short current-turn tool contract for ReAct messages.

    This belongs to prompt construction: it does not execute tools or retry the
    model. The ReAct loop remains responsible only for sending messages to the
    model and executing whatever valid tool calls the model returns.
    """
    from app.agents.chat.tool_strategy import compute_tool_strategy

    strategy = compute_tool_strategy(state)
    if not strategy.requires_retrieval:
        # Inject explicit "no tools" instruction for opening/greeting turns.
        # Without this, the model may ignore the system prompt and call tools anyway.
        # Use message_history count to detect early interview phase.
        # message_history includes opening + all user/assistant pairs.
        # Turn 1 (greeting): ~2 messages; Turn 2 (intro): ~4 messages.
        # We block tools for the first 3 turns (greeting + intro + first follow-up).
        message_count = len(state.get("message_history", []) or [])
        if message_count <= 6:
            return (
                "[当前回合工具策略]\n"
                "requires_retrieval=false\n"
                "CRITICAL: 本轮是面试开场阶段（前3轮），绝对不要调用任何工具。\n"
                "直接以面试官身份用文字回复。开场阶段应邀请自我介绍或基于候选人回答自然追问，不需要检索题库。"
            )
        return ""

    allowed = []
    if strategy.allow_search:
        allowed.append("search_questions")
    if strategy.allow_draw:
        allowed.append("draw_questions")
    allowed_text = ", ".join(allowed) if allowed else "none"
    lines = [
        "[当前回合工具策略]",
        "requires_retrieval=true",
        f"allowed_question_tools={allowed_text}",
        "请在回答候选人前先调用允许的题库工具；不要直接输出自然语言问题。",
    ]
    if strategy.next_phase_hint:
        lines.append(f"next_phase_hint={strategy.next_phase_hint}")
    return "\n".join(lines)


def _format_runtime_state_prompt(state: ChatState) -> str:
    """Render the current turn's typed routing state for the LLM."""

    lines = ["## 当前回合状态"]
    for key, label in (
        ("answer_quality", "回答质量"),
        ("should_retrieve", "需要检索"),
        ("transition_style", "过渡风格"),
        ("escalation_level", "追问升级层级"),
        ("off_topic_streak", "连续答非所问"),
        ("repetition_streak", "连续重复回答"),
        ("requires_bank_question", "必须绑定题库"),
    ):
        value = state.get(key)
        if value not in (None, ""):
            lines.append(f"- {label}: {value}")
    if len(lines) == 1:
        return ""
    return "\n".join(lines)


def _format_interview_state_prompt(state: ChatState) -> str:
    """Render a compact interview-state snapshot for the ReAct prompt."""

    snapshot = state.get("interview_state") or {}
    if not isinstance(snapshot, dict):
        return ""
    coverage = snapshot.get("coverage") or {}
    coverage_parts = []
    if isinstance(coverage, dict):
        for phase, data in coverage.items():
            if not isinstance(data, dict):
                continue
            coverage_parts.append(
                f"{phase}={data.get('current_count', 0)}/{data.get('threshold', 0)}"
            )
    return (
        "<interview_state>\n"
        f"current_phase: {snapshot.get('current_phase', '')}\n"
        f"next_focus: {snapshot.get('next_focus') or 'none'}\n"
        f"coverage: {', '.join(coverage_parts)}\n"
        "Instruction: Treat this as a read-only snapshot derived from the ledger. "
        "Use it as a tie-breaker for pacing; do not override a must_ask question plan.\n"
        "</interview_state>"
    )


def build_react_system_prompt(state: ChatState) -> str:
    """Build system prompt for the ReAct loop.

    Structure:
    1. Base prompt (interviewer role + context)
    2. Memory summaries
    3. Session notes
    4. Compressed context
    5. Skill catalog + tool guidance
    5.25. Intent-based tool strategy (dynamic, state-dependent)
    5.5. Skill body injection: always_active tool-use skills are auto-injected
         regardless of state["active_skills"], merged with explicit active skills
    5.6. Mid-loop pending skill instructions
    6. Basis extraction guidance (so the final answer can still emit metadata)
    """
    from app.agents.chat.skills.builder import build_skill_catalog

    mode = state.get("mode", "free_practice")
    interview_context = state.get("interview_context", "")
    session_notes = state.get("session_notes", "")
    memory_summaries = state.get("memory_summaries", [])
    compressed = state.get("compressed_context")
    total_message_count = len(state.get("message_history", []))
    config = state.get("decision_config") or DecisionConfig()
    interview_phase = _determine_interview_phase(total_message_count, config)

    # Layer 1: Base prompt
    if mode == "jd_resume" and state.get("jd_text"):
        base = INTERVIEW_SYSTEM_PROMPT_JD.format(
            jd_text=wrap_untrusted_context("job_description", state.get("jd_text", "")),
            resume_text=wrap_untrusted_context("resume", state.get("resume_text", "")),
            interview_context=wrap_untrusted_context(
                "interview_context", interview_context
            ),
            interview_phase=interview_phase,
            basis_guidance="",
        )
    else:
        # Build memory_context from state
        resume_summary = state.get("resume_summary")
        memory_summaries = state.get("memory_summaries", [])
        memory_parts = []
        if resume_summary:
            memory_parts.append(f"候选人背景：{resume_summary[:800]}")
        if memory_summaries:
            weak = [m for m in memory_summaries if m.get("memory_type") == "weakness"]
            strong = [m for m in memory_summaries if m.get("memory_type") == "strength"]
            if weak:
                memory_parts.append(
                    "薄弱环节：" + "; ".join(m.get("summary", "") for m in weak[:3])
                )
            if strong:
                memory_parts.append(
                    "擅长领域：" + "; ".join(m.get("summary", "") for m in strong[:3])
                )
        memory_context = _truncate_to_budget(
            "\n".join(memory_parts) if memory_parts else "", MEMORY_BUDGET
        )

        base = INTERVIEW_SYSTEM_PROMPT_PRACTICE.format(
            interview_context=wrap_untrusted_context(
                "interview_context", interview_context
            ),
            interview_phase=interview_phase,
            memory_context=wrap_untrusted_context(
                "memory", memory_context or "暂无用户背景信息"
            ),
            basis_guidance="",
        )

    parts = [base, REASONING_LANGUAGE_GUARDRAIL]

    # Layer 1.5: Runtime classification state so the LLM can route naturally
    # instead of relying on hardcoded prompt rules.
    runtime_state = _format_runtime_state_prompt(state)
    if runtime_state:
        parts.append(runtime_state)

    # Layer 2: Memory summaries
    if memory_summaries:
        memory_text = "\n".join(
            f"- [{m.get('memory_type', '')}] {m.get('summary', '')}"
            for m in memory_summaries[:3]
        )
        parts.append(
            "## 候选人相关记忆\n"
            + wrap_untrusted_context("memory_summary", memory_text)
        )

    # Layer 3: Session notes
    if session_notes:
        parts.append(
            "## 本次面试笔记\n"
            + wrap_untrusted_context("session_notes", session_notes)
        )

    # Layer 4: Compressed context
    if compressed:
        parts.append(
            "## 历史对话摘要\n"
            + wrap_untrusted_context("compressed_history", compressed)
        )

    interview_state_prompt = _format_interview_state_prompt(state)
    if interview_state_prompt:
        parts.append(interview_state_prompt)

    # Layer 5: Skill catalog + tool guidance
    catalog = build_skill_catalog(state=state)
    if catalog:
        parts.append(catalog)

    # Layer 5.25: Tool strategy (intent-based guidance)
    tool_strategy = _build_tool_strategy(state)
    if tool_strategy:
        parts.append(tool_strategy)

    # Layer 5.3: Runtime interview harness.
    parts.append(_build_big_tech_interview_harness_prompt(state))

    # Layer 5.5: Always-active and active skill instructions.
    skill_registry = get_default_registry()
    active_skill_names = state.get("active_skills", [])
    always_active_skill_names = [
        skill.name
        for skill in sorted(
            skill_registry._skills.values(),
            key=lambda item: item.priority,
            reverse=True,
        )
        if skill.always_active
        and skill.metadata.get("interview-boss.kind") == "tool-use"
    ]
    prompt_skill_names = list(
        dict.fromkeys(always_active_skill_names + active_skill_names)
    )
    if prompt_skill_names:
        from app.agents.shared.skills.builder import build_skill_prompt as _build_sp

        skill_instr = _build_sp(skill_registry, prompt_skill_names)
        if skill_instr:
            parts.append(skill_instr)

    # Layer 5.6: Mid-loop pending skill instructions (not yet in active_skills)
    from html import escape as _html_escape

    active_skill_instructions = state.get("active_skill_instructions", [])
    if active_skill_instructions:
        skill_parts = []
        for item in active_skill_instructions:
            name = _html_escape(item.get("skill_name", ""), quote=True)
            instruction = item.get("instruction", "")
            if instruction:
                skill_parts.append(f'<skill name="{name}">\n{instruction}\n</skill>')
        if skill_parts:
            parts.append(
                "<active_skill_instructions>\n"
                + "\n\n".join(skill_parts)
                + "\n</active_skill_instructions>"
            )

    return "\n\n".join(parts)
