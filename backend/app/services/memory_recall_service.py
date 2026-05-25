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

INTENT_AND_MEMORY_PROMPT = """分析用户的最新消息，完成四个任务：

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

## 任务3: 检索查询生成（重要！必须是短技术词）
基于面试官的问题，提取面试话题的核心技术关键词，用于题库检索。

规则:
- keywords 必须是 2-4 字的技术术语，不是完整的句子
- 从面试官的问题中提取话题，不是从用户回答中提取
- 题库中的题目是"Redis 缓存穿透怎么解决"、"高并发限流方案"这类形式

示例:
- 面试官问"说说 Redis 缓存穿透"，用户答"布隆过滤器" → keywords: ["Redis", "缓存", "穿透"]
- 面试官问"手写 LRU 缓存"，用户开始写代码 → keywords: ["LRU", "缓存"]
- 面试官问"整体架构怎么设计的" → keywords: ["架构", "设计"]
- 面试官问"State Graph 状态怎么定义的" → keywords: ["LangGraph", "状态机", "图"]
- 面试官问"怎么保证高并发" → keywords: ["高并发", "限流"]
- 用户说"出一道算法题" → keywords: ["算法"]

search_query = keywords 用空格拼接即可。

## 任务4: 回答完整性判断
判断用户对当前面试问题的回答是否完整（面试官可以出下一道题了）。

判断标准:
- answer_complete=true: 用户给出了较完整的回答（有结论、有解释、有示例），或者用户明确表示不知道/跳过
- answer_complete=false: 用户只回答了一部分、回答很短（<20字且无实质内容）、或者明显在思考/打字中

注意: 如果意图不是 interview_question（如闲聊、追问），answer_complete 设为 false。

## 可用记忆
{memory_list}

## 用户消息
{user_message}

## 最近对话
{recent_context}

严格返回JSON格式:
{{"intent": "类别", "relevant_memory_ids": [id1, id2], "keywords": ["技术词1", "技术词2"], "search_query": "技术词1 技术词2", "answer_complete": true/false}}"""


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
    """降级关键词提取（纯规则，零 LLM 成本）

    提取 2-4 字的中文技术词和英文单词，排除常见停用词。
    """
    # 英文技术术语（优先）
    eng_words = re.findall(r'[a-zA-Z][a-zA-Z0-9]{1,}', message)
    eng_keywords = [w for w in eng_words if len(w) >= 2]

    # 中文技术词（2-4字，排除太长的短语）
    cjk_words = re.findall(r'[一-鿿]{2,4}', message)
    stop_words = {"你好", "我是", "目前", "在读", "方向是", "的是", "可以", "已经", "然后", "如果", "进行", "使用", "通过", "整体", "分为", "请求从", "转发到", "这个", "那个", "一个", "就是", "所以", "但是", "怎么", "如何", "什么"}
    cjk_keywords = [w for w in cjk_words if w not in stop_words and len(w) >= 2]

    keywords = eng_keywords + cjk_keywords
    return keywords[:5]


async def classify_and_recall_fast(
    user_message: str,
    memory_summaries: list[dict],
    recent_context: str = "",
) -> tuple[str, list[int], list[str], str, bool]:
    """快速分类 + 记忆召回（零 LLM 成本）

    用于第一条消息或规则可判断的场景，跳过 LLM 调用。
    使用规则分类 + 最近记忆（不经过 LLM 选择）。

    Returns:
        (intent, memory_ids, keywords, search_query, answer_complete)
    """
    # 1. 规则分类
    intent = _rule_based_intent(user_message) or "interview_question"

    # 2. 关键词提取（纯规则）
    keywords = _extract_keywords_fallback(user_message)

    # 3. 检索查询：用关键词拼接（快速路径无法做上下文改写）
    search_query = " ".join(keywords) if keywords else ""

    # 4. 记忆选择：直接用最近的记忆（不经过 LLM 选择）
    memory_ids = [m["id"] for m in memory_summaries[:3]] if memory_summaries else []

    # 5. 回答完整性：快速路径默认 True（第一条消息视为完整）
    answer_complete = True

    return intent, memory_ids, keywords, search_query, answer_complete


async def classify_and_recall(
    user_message: str,
    recent_context: str,
    memory_summaries: list[dict],
    user_id: int,
) -> tuple[str, list[int], list[str], str, bool]:
    """合并意图分类 + 记忆召回 + 检索查询生成 + 回答完整性判断（单次 LLM 调用）

    Returns:
        (intent, relevant_memory_ids, keywords, search_query, answer_complete)
    """
    # 1. 规则预判断（零 LLM 成本）
    rule_intent = _rule_based_intent(user_message)
    if rule_intent == "chat":
        return "chat", [], [], "", False
    if rule_intent == "practice_request":
        kw = _extract_keywords_fallback(user_message)
        return "practice_request", [], kw, " ".join(kw), False
    if rule_intent == "follow_up":
        kw = _extract_keywords_fallback(user_message)
        return "follow_up", [], kw, " ".join(kw), False

    # 2. 无记忆时，跳过召回，仅用 LLM 做意图分类
    if not memory_summaries:
        intent = await _classify_intent_only(user_message, recent_context, user_id)
        keywords = _extract_keywords_fallback(user_message)
        search_query = " ".join(keywords)
        answer_complete = len(user_message.strip()) >= 20
        return intent, [], keywords, search_query, answer_complete

    # 3. 合并 LLM 调用：意图 + 记忆选择 + 检索查询
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

        # 验证 search_query
        search_query = parsed.get("search_query", "")
        if not search_query or not isinstance(search_query, str):
            search_query = " ".join(keywords)
        search_query = search_query.strip()[:200]

        # 验证 answer_complete
        answer_complete = parsed.get("answer_complete", False)
        if not isinstance(answer_complete, bool):
            answer_complete = False

        return intent, memory_ids, keywords, search_query, answer_complete

    except Exception as e:
        logger.warning(f"合并意图+召回 LLM 调用失败，降级到规则: {e}")
        intent = await _classify_intent_only(user_message, recent_context, user_id)
        keywords = _extract_keywords_fallback(user_message)
        answer_complete = len(user_message.strip()) >= 20
        return intent, [], keywords, " ".join(keywords), answer_complete


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
