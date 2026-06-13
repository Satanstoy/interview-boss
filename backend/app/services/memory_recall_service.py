"""LLM 语义记忆召回服务 — 合并意图分类 + 关键词提取 + 记忆选择

设计哲学（来自 Claude Code）:
- "Use an LLM for recall, not keywords or embeddings"
- 合并多个 LLM 调用为一次，减少 per-turn 延迟和成本
- 优雅降级：LLM 失败时回退到规则分类
"""

import re
import json
import logging
from app.services.llm import _call_llm_with_retry, _extract_json
from app.agents.chat.prompts import INTENT_CLASSIFY_PROMPT

logger = logging.getLogger("interview-boss")

# answer_complete 启发式判断
_EXPLICIT_COMPLETE_MARKERS = {"就这些", "答完了", "大概就是这样", "大概就是这样吧", "说完了", "完了", "没有了"}
_EXPLICIT_INCOMPLETE_MARKERS = {"嗯", "好的", "对", "是的", "没错", "ok", "OK"}
_QUESTION_PREFIXES = ("你是说", "能不能", "可以再", "再解释", "怎么", "为什么")


def _heuristic_answer_complete(message: str) -> bool:
    """Heuristic for answer_complete when LLM classification is unavailable.

    Rules:
    - Explicit completion markers → True
    - Very short messages / filler words → False
    - Questions → False
    - Long substantive messages (> 30 chars) → True
    """
    text = message.strip()

    # Explicit completion
    for marker in _EXPLICIT_COMPLETE_MARKERS:
        if marker in text:
            return True

    # Filler / short
    if text in _EXPLICIT_INCOMPLETE_MARKERS:
        return False
    if len(text) < 15:
        return False

    # Questions / confirmations. Be conservative: full answers often contain
    # words like "怎么" or "为什么", so only treat them as questions at the
    # beginning or when the message ends with a question mark.
    if text.endswith(("?", "？")):
        return False
    if text.startswith(_QUESTION_PREFIXES):
        return False

    # Long substantive
    if len(text) >= 30:
        return True

    # Default: not complete
    return False


# ── 结构化查询改写 ──

STRUCTURED_REWRITE_PROMPT = """基于面试官的问题，生成结构化检索查询。

字段说明:
- retrieval_intent: 检索意图，三选一
  - find_similar: 查找相似的面试题（用户正在回答问题）
  - expand_knowledge: 扩展相关知识（用户在追问、想深入）
  - review_weakness: 回顾薄弱环节（用户回答不完整或出错）
- main_topic: 话题核心技术点，2-4 字（如"Redis 缓存穿透"、"LRU 缓存"）
- positive_terms: 必须包含的检索词（技术术语，最多 5 个）
- negative_terms: 必须排除的检索词（容易混淆的概念，最多 3 个）

示例:
- 面试官问"说说 Redis 缓存穿透" → {{"retrieval_intent": "find_similar", "main_topic": "Redis 缓存穿透", "positive_terms": ["Redis", "缓存穿透", "布隆过滤器"], "negative_terms": []}}
- 面试官问"高并发怎么做" → {{"retrieval_intent": "find_similar", "main_topic": "高并发限流", "positive_terms": ["高并发", "限流", "令牌桶"], "negative_terms": []}}
- 用户问"能再详细说说吗" → {{"retrieval_intent": "expand_knowledge", "main_topic": "当前话题", "positive_terms": [], "negative_terms": []}}
- 用户回答很短且不完整 → {{"retrieval_intent": "review_weakness", "main_topic": "薄弱点", "positive_terms": [], "negative_terms": []}}

## 面试官问题
{question}

## 用户消息
{user_message}

## 最近对话
{recent_context}

返回 JSON 格式:
{{"retrieval_intent": "...", "main_topic": "...", "positive_terms": [...], "negative_terms": [...]}}"""


def _parse_structured_rewrite(llm_output: str | None) -> dict | None:
    """解析 LLM 返回的结构化改写 JSON。

    Returns:
        解析后的 dict 或 None（JSON 无效或缺少必填字段时）
    """
    if not llm_output:
        return None

    try:
        parsed = json.loads(llm_output)
    except (json.JSONDecodeError, TypeError):
        return None

    # 必填字段: main_topic
    if "main_topic" not in parsed or not parsed["main_topic"]:
        return None

    # retrieval_intent 验证，默认 find_similar
    valid_intents = {"find_similar", "expand_knowledge", "review_weakness"}
    intent = parsed.get("retrieval_intent", "find_similar")
    if intent not in valid_intents:
        intent = "find_similar"

    # positive_terms: 最多 5 个，过滤空值
    positive = _clean_terms(parsed.get("positive_terms", []), limit=5)

    # negative_terms: 最多 3 个，过滤空值
    negative = _clean_terms(parsed.get("negative_terms", []), limit=3)

    main_topic = str(parsed["main_topic"]).strip()
    if _is_polluted_term(main_topic):
        if positive:
            main_topic = positive[0]
        else:
            return None

    return {
        "retrieval_intent": intent,
        "main_topic": main_topic,
        "positive_terms": positive,
        "negative_terms": negative,
    }


def _build_search_params(rewrite: dict) -> dict:
    """将结构化改写转换为搜索参数。

    Returns:
        dict with keys: query, exclude_keywords, boost
    """
    intent = rewrite.get("retrieval_intent", "find_similar")
    main_topic = rewrite.get("main_topic", "")
    positive = rewrite.get("positive_terms", [])
    negative = rewrite.get("negative_terms", [])

    # 构建查询：main_topic + positive_terms 去重
    terms = []
    if main_topic:
        terms.append(main_topic)
    for t in positive:
        if t not in terms:
            terms.append(t)
    query = " ".join(terms) if terms else main_topic

    # 根据意图设置 boost
    boost = None
    if intent == "expand_knowledge":
        boost = "broad"
    elif intent == "review_weakness":
        boost = "weakness"

    return {
        "query": query,
        "exclude_keywords": negative,
        "boost": boost,
    }


def _infer_question_type(rewrite: dict) -> str:
    """从结构化改写中推断题目类型（用于 rerank boost）。"""
    intent = rewrite.get("retrieval_intent", "find_similar")
    positive = [t.lower() for t in rewrite.get("positive_terms", [])]

    project_keywords = {"项目", "架构", "系统设计", "agent", "rag", "微服务", "分布式"}
    if intent == "find_similar" and any(
        kw in " ".join(positive) for kw in project_keywords
    ):
        return "project_followup"

    if intent == "review_weakness":
        return "knowledge_probe"

    return "new_question"


# ── 项目/架构相关关键词（用于规则推断 question_type）──
_PROJECT_KEYWORDS = {
    "项目",
    "架构",
    "系统设计",
    "langgraph",
    "rag",
    "检索",
    "引用",
    "状态",
    "链路",
    "agent",
    "微服务",
    "分布式",
    "图",
    "workflow",
}
_KNOWLEDGE_KEYWORDS = {
    "redis",
    "mysql",
    "网络",
    "操作系统",
    "jvm",
    "算法",
    "数据结构",
    "tcp",
    "http",
    "缓存",
    "数据库",
    "线程",
    "进程",
    "内存",
}
_NEGATIVE_PATTERNS = [
    "这个参考题不对",
    "参考题不对",
    "题目不对",
    "AI Coding 是例子",
    "是例子",
    "举例",
    "比如说",
    "例如",
    "比如",
    "像",
    "不要召回",
    "不该召回",
    "噪声",
    "无关",
    "不是",
    "排除",
]

# 状态字段和内部术语（不能作为核心关键词）
_STATE_FIELDS = {
    "intent",
    "answer",
    "complete",
    "answer_complete",
    "keywords",
    "search",
    "query",
    "search_query",
    "rewrite",
    "retrieval_intent",
    "main_topic",
    "positive_terms",
    "negative_terms",
    "conversation_id",
    "retrieved_questions",
    "selected_basis_questions",
    "basis_type",
    "basis_question_ids",
    "metadata",
    "payload",
    "message_id",
    "request_id",
    "id",
    "json",
    "question_ids",
    "rrf_score",
    "heuristic_score",
    "frequency",
    "sources",
    "true",
    "false",
}

_META_TERM_PATTERNS = [
    "用户",
    "面试官",
    "候选人",
    "回答",
    "问题",
    "字段",
    "比如",
    "例如",
    "一个题",
    "在讲",
]


def _is_polluted_term(term: str, *, allow_space: bool = True) -> bool:
    term = str(term or "").strip()
    if not term:
        return True
    lower = term.lower().strip("`\"'[]{}():：，,。.；;")
    if lower in _STATE_FIELDS:
        return True
    parts = re.findall(r"[a-zA-Z_]+|[一-鿿]+", lower)
    if parts and all(part in _STATE_FIELDS for part in parts):
        return True
    if len(term) > 32:
        return True
    if not allow_space and re.search(r"\s", term):
        return True
    if any(pattern in term for pattern in _META_TERM_PATTERNS):
        return True
    return False


def _clean_terms(terms: list, *, limit: int, allow_space: bool = True) -> list[str]:
    if not isinstance(terms, list):
        return []
    cleaned = []
    seen = set()
    for term in terms:
        text = str(term or "").strip()
        if _is_polluted_term(text, allow_space=allow_space):
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= limit:
            break
    return cleaned


def _sanitize_search_query(query: str, fallback_terms: list[str]) -> str:
    query = str(query or "").strip()
    fallback = " ".join(_clean_terms(fallback_terms, limit=5))
    if not query:
        return fallback
    tokens = re.findall(r"[a-zA-Z_]+|[一-鿿]+", query)
    if tokens and all(t.lower() in _STATE_FIELDS for t in tokens):
        return fallback
    if _is_polluted_term(query):
        return fallback
    return query[:200]


def _infer_rule_based_rewrite(
    user_message: str, keywords: list[str], intent: str
) -> dict:
    """轻量规则推断 structured rewrite（零 LLM 成本）。

    用于 classify_and_recall_fast 和 classify_and_recall 的非 LLM 路径。
    """
    msg_lower = user_message.lower()
    kw_lower = [k.lower() for k in keywords]

    all_text = " ".join(kw_lower) + " " + msg_lower
    has_project = any(kw in all_text for kw in _PROJECT_KEYWORDS)
    has_knowledge = any(kw in all_text for kw in _KNOWLEDGE_KEYWORDS)

    if intent == "practice_request":
        retrieval_intent = "find_similar"
    elif intent == "follow_up":
        retrieval_intent = "expand_knowledge"
    elif has_project or has_knowledge:
        retrieval_intent = "find_similar"
    elif len(user_message.strip()) < 20:
        retrieval_intent = "review_weakness"
    else:
        retrieval_intent = "find_similar"

    if has_project:
        question_type = "project_followup"
    elif has_knowledge:
        question_type = "knowledge_probe"
    else:
        question_type = "new_question"

    # 提取 negative_terms（用户举错误例子时）
    negative_terms = []
    for pattern in _NEGATIVE_PATTERNS:
        if pattern.lower() in msg_lower:
            # 从用户消息中提取例子词作为 negative_term
            import re

            # 提取引号中的词或 "AI Coding" 这类例子
            example_words = re.findall(r'["""「」]([^"""「」]+)["""「」]', user_message)
            negative_terms.extend(example_words[:2])

            # 提取 "比如/例如/举例" 后面到 "这种/这类/噪声/不该/不要" 之前的内容
            noise_match = re.search(
                r"(?:比如|例如|举例|像)\s*[，,：:\s]*(.+?)(?:\s*(?:这种|这类|作为|是例子|噪声|不该|不要|不要召回|不该召回|无关|排除)|[，,。.；;]|$)",
                user_message,
            )
            if noise_match:
                noise_text = noise_match.group(1).strip()
                # 按顿号、逗号分割
                noise_items = re.split(r"[、，,]", noise_text)
                for item in noise_items:
                    item = item.strip()
                    if len(item) >= 2 and item not in negative_terms:
                        negative_terms.append(item)
            break

    # 过滤掉状态字段和内部术语
    negative_terms = _clean_terms(negative_terms, limit=3)

    # 过滤 positive_terms 中的状态字段
    positive_terms = _clean_terms(keywords, limit=5)

    return {
        "retrieval_intent": retrieval_intent,
        "positive_terms": positive_terms,
        "negative_terms": negative_terms[:3],
        "question_type": question_type,
    }


# ── 合并 Prompt ──

INTENT_AND_MEMORY_PROMPT = """分析用户的最新消息，完成四个任务：

## 任务1: 意图分类
从以下类别中选择一个:
- interview_question: 面试问题回答（用户在回答面试官的问题）
- end_interview: 结束面试（用户明确要求结束面试、生成面试总结、收尾等）
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

## 任务4: 结构化检索改写（重要！）
基于面试官的问题，生成结构化检索查询。

字段说明:
- retrieval_intent: 检索意图，三选一
  - find_similar: 查找相似的面试题（用户正在回答问题）
  - expand_knowledge: 扩展相关知识（用户在追问、想深入）
  - review_weakness: 回顾薄弱环节（用户回答不完整或出错）
- main_topic: 话题核心技术点，2-4 字（如"Redis 缓存穿透"、"LRU 缓存"）
- positive_terms: 必须包含的检索词（技术术语，最多 5 个）
- negative_terms: 必须排除的检索词（容易混淆的概念，最多 3 个）

示例:
- 面试官问"说说 Redis 缓存穿透" → {{"retrieval_intent": "find_similar", "main_topic": "Redis 缓存穿透", "positive_terms": ["Redis", "缓存穿透", "布隆过滤器"], "negative_terms": []}}
- 面试官问"高并发怎么做" → {{"retrieval_intent": "find_similar", "main_topic": "高并发限流", "positive_terms": ["高并发", "限流", "令牌桶"], "negative_terms": []}}

## 任务5: 回答完整性判断
判断用户对当前面试问题的回答是否完整（面试官可以出下一道题了）。

answer_complete 判断标准：
- true: 用户明确表示回答完毕（"就这些"、"答完了"、"大概就是这样"）
- true: 用户给出了完整的项目描述或技术方案（有开头有结尾，超过 30 字）
- false: 用户只说了几个关键词或片段（"用了 Redis"、"微服务"）
- false: 用户在反问或确认（"你是说...？"、"这样对吗？"）
- false: 用户说"嗯"、"好的"等过渡词（可能是思考中）

注意: 如果意图不是 interview_question（如闲聊、追问），answer_complete 设为 false。

## 可用记忆
{memory_list}

{rule_hint}

## 用户消息
{user_message}

## 最近对话
{recent_context}

严格返回JSON格式:
{{"intent": "类别", "relevant_memory_ids": [id1, id2], "keywords": ["技术词1", "技术词2"], "search_query": "技术词1 技术词2", "rewrite": {{"retrieval_intent": "...", "main_topic": "...", "positive_terms": [...], "negative_terms": [...]}}, "answer_complete": true/false}}"""


# ── 规则预判断（零 LLM 成本）──

_CHAT_KEYWORDS = [
    "你好",
    "hello",
    "hi",
    "谢谢",
    "感谢",
    "再见",
    "拜拜",
    "ok",
    "好的",
    "嗯",
]
_PRACTICE_KEYWORDS = ["出题", "来一道", "换一个", "换个", "练习", "开始", "出个"]
_FOLLOW_UP_KEYWORDS = [
    "解释",
    "详细",
    "具体",
    "为什么",
    "怎么",
    "能再说",
    "不太明白",
    "什么意思",
]
_END_INTERVIEW_KEYWORDS = [
    "结束面试",
    "面试结束",
    "面试到此",
    "到此为止",
    "面试先到这里",
    "请你结束",
    "请结束",
    "生成面试总结",
    "生成一份面试总结",
    "面试总结",
    "收尾吧",
    "可以结束了",
    "今天就到这里",
    "先到这里吧",
]


def _rule_based_intent(message: str) -> str | None:
    """规则预判断，快速返回明显意图（零 LLM 成本）"""
    lower = message.lower().strip()

    for kw in _CHAT_KEYWORDS:
        if kw == lower:
            return "chat"

    # end_interview 检测优先于 practice_request（"结束面试" 包含 "结束" 但不是换题）
    for kw in _END_INTERVIEW_KEYWORDS:
        if kw in message:
            return "end_interview"

    for kw in _PRACTICE_KEYWORDS:
        if kw in message:
            return "practice_request"

    for kw in _FOLLOW_UP_KEYWORDS:
        if kw in message and len(message) < 50:
            return "follow_up"

    return None


def _extract_keywords_fallback(message: str) -> list[str]:
    """降级关键词提取（纯规则，零 LLM 成本）

    提取 2-4 字的中文技术词和英文单词，排除常见停用词和状态字段。
    """
    # 英文技术术语（优先）
    eng_words = re.findall(r"[a-zA-Z][a-zA-Z0-9]{1,}", message)
    eng_keywords = [w for w in eng_words if len(w) >= 2]

    # 中文技术词（2-4字，排除太长的短语）
    cjk_words = re.findall(r"[一-鿿]{2,4}", message)
    stop_words = {
        "你好",
        "我是",
        "目前",
        "在读",
        "方向是",
        "的是",
        "可以",
        "已经",
        "然后",
        "如果",
        "进行",
        "使用",
        "通过",
        "整体",
        "分为",
        "请求从",
        "转发到",
        "这个",
        "那个",
        "一个",
        "就是",
        "所以",
        "但是",
        "怎么",
        "如何",
        "什么",
    }
    # 合并状态字段到 stop_words
    stop_words.update(_STATE_FIELDS)
    cjk_keywords = [w for w in cjk_words if w not in stop_words and len(w) >= 2]

    keywords = eng_keywords + cjk_keywords
    return keywords[:5]


async def classify_and_recall_fast(
    user_message: str,
    memory_summaries: list[dict],
    recent_context: str = "",
) -> tuple[str, list[int], list[str], str, bool, dict]:
    """快速分类 + 记忆召回（零 LLM 成本）

    Returns:
        (intent, memory_ids, keywords, search_query, answer_complete, structured_rewrite)
    """
    intent = _rule_based_intent(user_message) or "interview_question"
    keywords = _extract_keywords_fallback(user_message)
    search_query = " ".join(keywords) if keywords else ""
    memory_ids = [m["id"] for m in memory_summaries[:3]] if memory_summaries else []
    answer_complete = _heuristic_answer_complete(user_message)

    structured_rewrite = _infer_rule_based_rewrite(user_message, keywords, intent)

    return (
        intent,
        memory_ids,
        keywords,
        search_query,
        answer_complete,
        structured_rewrite,
    )


async def classify_and_recall(
    user_message: str,
    recent_context: str,
    memory_summaries: list[dict],
    user_id: int,
) -> tuple[str, list[int], list[str], str, bool, dict]:
    """合并意图分类 + 记忆召回 + 检索查询生成 + 回答完整性判断（单次 LLM 调用）

    Returns:
        (intent, relevant_memory_ids, keywords, search_query, answer_complete, structured_rewrite)
    """
    rule_intent = _rule_based_intent(user_message)
    if rule_intent == "chat":
        structured = _infer_rule_based_rewrite(user_message, [], "chat")
        return "chat", [], [], "", False, structured
    if rule_intent == "end_interview":
        structured = _infer_rule_based_rewrite(user_message, [], "end_interview")
        return "end_interview", [], [], "", False, structured

    # Rules are now only hints, not authoritative
    rule_hint = ""
    if rule_intent in ("practice_request", "follow_up"):
        rule_hint = f"\n注意：规则预判为 {rule_intent}，但请根据完整上下文重新判断，规则可能误判。"

    # 3. 合并 LLM 调用：意图 + 记忆选择 + 检索查询
    memory_list = "\n".join(
        f"[id:{m['id']} {m['memory_type']}] {m['summary']}" for m in memory_summaries
    ) if memory_summaries else ""

    try:
        prompt = INTENT_AND_MEMORY_PROMPT.format(
            memory_list=memory_list,
            user_message=user_message,
            recent_context=recent_context,
            rule_hint=rule_hint,
        )
        result = await _call_llm_with_retry(
            prompt,
            user_id=user_id,
            response_format={"type": "json_object"},
        )
        parsed = _extract_json(result)

        # 验证 intent
        intent = parsed.get("intent", "interview_question")
        valid_intents = {"interview_question", "end_interview", "practice_request", "chat", "follow_up"}
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
        keywords = _clean_terms(keywords, limit=5)
        if not keywords:
            keywords = _extract_keywords_fallback(user_message)

        # 验证 search_query
        search_query = _sanitize_search_query(parsed.get("search_query", ""), keywords)

        # 尝试用结构化改写优化 search_query
        structured_rewrite = {}
        rewrite = parsed.get("rewrite")
        if rewrite and isinstance(rewrite, dict):
            parsed_rewrite = _parse_structured_rewrite(json.dumps(rewrite))
            if parsed_rewrite:
                search_params = _build_search_params(parsed_rewrite)
                if search_params["query"]:
                    search_query = _sanitize_search_query(
                        search_params["query"], keywords
                    )
                structured_rewrite = {
                    "retrieval_intent": parsed_rewrite.get(
                        "retrieval_intent", "find_similar"
                    ),
                    "positive_terms": parsed_rewrite.get("positive_terms", []),
                    "negative_terms": parsed_rewrite.get("negative_terms", []),
                    "question_type": _infer_question_type(parsed_rewrite),
                }

        answer_complete = parsed.get("answer_complete", False)
        if not isinstance(answer_complete, bool):
            answer_complete = False

        return (
            intent,
            memory_ids,
            keywords,
            search_query,
            answer_complete,
            structured_rewrite,
        )

    except Exception as e:
        logger.warning(f"合并意图+召回 LLM 调用失败，降级到规则: {e}")
        intent = await _classify_intent_only(user_message, recent_context, user_id)
        keywords = _extract_keywords_fallback(user_message)
        answer_complete = _heuristic_answer_complete(user_message)
        structured = _infer_rule_based_rewrite(user_message, keywords, intent)
        return intent, [], keywords, " ".join(keywords), answer_complete, structured


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

        valid_intents = {"interview_question", "end_interview", "practice_request", "chat", "follow_up"}
        if intent in valid_intents:
            return intent
    except Exception as e:
        logger.warning(f"意图分类 LLM 调用失败: {e}")

    return "interview_question"
