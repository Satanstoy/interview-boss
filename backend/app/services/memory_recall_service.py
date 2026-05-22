"""LLM 语义记忆召回服务 — 合并意图分类 + 关键词提取 + 记忆选择

设计哲学（来自 Claude Code）:
- "Use an LLM for recall, not keywords or embeddings"
- 合并多个 LLM 调用为一次，减少 per-turn 延迟和成本
- 优雅降级：LLM 失败时回退到规则分类
"""
import re
import logging
from app.services.llm import _call_llm_with_retry, _extract_json
from app.agents.chat.prompts import INTENT_CLASSIFY_PROMPT

logger = logging.getLogger("interview-boss")

# ── 合并 Prompt ──

INTENT_AND_MEMORY_PROMPT = """分析用户的最新消息，完成三个任务：

## 任务1: 意图分类
从以下类别中选择一个:
- interview_question: 面试问题回答（用户在回答面试官的问题）
- practice_request: 练习请求（用户想换题、出题）
- chat: 闲聊（打招呼、感谢、告别）
- follow_up: 追问（用户要求解释或补充）

## 任务2: 记忆相关性选择
从以下记忆列表中，选出与当前对话最相关的记忆ID（最多3个）。
考虑：话题相关性、用户当前需要的信息、对话上下文。
如果没有相关记忆，返回空数组。

## 任务3: 关键词提取
从用户消息中提取 1-5 个技术关键词，用于题库全文检索。
关键词应是面试中常见的技术术语或概念。

## 可用记忆
{memory_list}

## 用户消息
{user_message}

## 最近对话
{recent_context}

严格返回JSON格式:
{{"intent": "类别", "relevant_memory_ids": [id1, id2], "keywords": ["词1", "词2"]}}"""


# ── 规则预判断（零 LLM 成本）──

_CHAT_KEYWORDS = ["你好", "hello", "hi", "谢谢", "感谢", "再见", "拜拜", "ok", "好的", "嗯"]
_PRACTICE_KEYWORDS = ["出题", "来一道", "换一个", "换个", "练习", "开始", "出个"]
_FOLLOW_UP_KEYWORDS = ["解释", "详细", "具体", "为什么", "怎么", "能再说", "不太明白", "什么意思"]


def _rule_based_intent(message: str) -> str | None:
    """规则预判断，快速返回明显意图（零 LLM 成本）"""
    lower = message.lower().strip()

    for kw in _CHAT_KEYWORDS:
        if kw == lower:
            return "chat"

    for kw in _PRACTICE_KEYWORDS:
        if kw in message:
            return "practice_request"

    for kw in _FOLLOW_UP_KEYWORDS:
        if kw in message and len(message) < 50:
            return "follow_up"

    return None


def _extract_keywords_fallback(message: str) -> list[str]:
    """降级关键词提取（纯规则，零 LLM 成本）"""
    words = re.findall(r'[一-鿿]+|[a-zA-Z][a-zA-Z0-9]+', message)
    keywords = [w for w in words if len(w) >= 2][:5]
    return keywords


async def classify_and_recall_fast(
    user_message: str,
    memory_summaries: list[dict],
) -> tuple[str, list[int], list[str]]:
    """快速分类 + 记忆召回（零 LLM 成本）

    用于第一条消息或规则可判断的场景，跳过 LLM 调用。
    使用规则分类 + 最近记忆（不经过 LLM 选择）。

    Returns:
        (intent, memory_ids, keywords)
    """
    # 1. 规则分类
    intent = _rule_based_intent(user_message) or "interview_question"

    # 2. 关键词提取（纯规则）
    keywords = _extract_keywords_fallback(user_message)

    # 3. 记忆选择：直接用最近的记忆（不经过 LLM 选择）
    memory_ids = [m["id"] for m in memory_summaries[:3]] if memory_summaries else []

    return intent, memory_ids, keywords


async def classify_and_recall(
    user_message: str,
    recent_context: str,
    memory_summaries: list[dict],
    user_id: int,
) -> tuple[str, list[int], list[str]]:
    """合并意图分类 + 记忆召回 + 关键词提取（单次 LLM 调用）

    Args:
        user_message: 用户当前消息
        recent_context: 最近对话上下文文本
        memory_summaries: 记忆摘要列表 (来自 get_memory_summaries)
        user_id: 用户 ID（用于 LLM 客户端选择）

    Returns:
        (intent, relevant_memory_ids, keywords)
        - intent: "interview_question" | "practice_request" | "chat" | "follow_up"
        - relevant_memory_ids: 选中的记忆 ID 列表
        - keywords: 提取的技术关键词列表
    """
    # 1. 规则预判断（零 LLM 成本）
    rule_intent = _rule_based_intent(user_message)
    if rule_intent == "chat":
        return "chat", [], []
    if rule_intent == "practice_request":
        return "practice_request", [], _extract_keywords_fallback(user_message)
    if rule_intent == "follow_up":
        return "follow_up", [], _extract_keywords_fallback(user_message)

    # 2. 无记忆时，跳过召回，仅用 LLM 做意图分类
    if not memory_summaries:
        intent = await _classify_intent_only(user_message, recent_context, user_id)
        keywords = _extract_keywords_fallback(user_message)
        return intent, [], keywords

    # 3. 合并 LLM 调用：意图 + 记忆选择 + 关键词
    memory_list = "\n".join(
        f"[id:{m['id']} {m['memory_type']}] {m['summary']}"
        for m in memory_summaries
    )

    try:
        prompt = INTENT_AND_MEMORY_PROMPT.format(
            memory_list=memory_list,
            user_message=user_message,
            recent_context=recent_context,
        )
        result = await _call_llm_with_retry(
            prompt,
            user_id=user_id,
            response_format={"type": "json_object"},
        )
        parsed = _extract_json(result)

        # 验证 intent
        intent = parsed.get("intent", "interview_question")
        valid_intents = {"interview_question", "practice_request", "chat", "follow_up"}
        if intent not in valid_intents:
            intent = "interview_question"

        # 验证 memory IDs
        memory_ids = parsed.get("relevant_memory_ids", [])
        valid_ids = {m["id"] for m in memory_summaries}
        memory_ids = [mid for mid in memory_ids if mid in valid_ids][:3]

        # 验证 keywords
        keywords = parsed.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        keywords = [str(k) for k in keywords if k][:5]
        if not keywords:
            keywords = _extract_keywords_fallback(user_message)

        return intent, memory_ids, keywords

    except Exception as e:
        logger.warning(f"合并意图+召回 LLM 调用失败，降级到规则: {e}")
        intent = await _classify_intent_only(user_message, recent_context, user_id)
        keywords = _extract_keywords_fallback(user_message)
        return intent, [], keywords


async def _classify_intent_only(
    user_message: str,
    recent_context: str,
    user_id: int,
) -> str:
    """仅意图分类（当无记忆或合并调用失败时使用）"""
    try:
        prompt = INTENT_CLASSIFY_PROMPT.format(
            user_message=user_message,
            recent_context=recent_context,
        )
        result = await _call_llm_with_retry(prompt, user_id=user_id)
        intent = result.strip().lower()

        valid_intents = {"interview_question", "practice_request", "chat", "follow_up"}
        if intent in valid_intents:
            return intent
    except Exception as e:
        logger.warning(f"意图分类 LLM 调用失败: {e}")

    return "interview_question"
