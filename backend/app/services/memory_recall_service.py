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
- main_topic: 话题核心技术点，2-4 字（如"Redis 缓存穿透"、"TopK 问题"）
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

    Only used by the explicit LLM-failure fallback in ``classify_and_recall``.
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

INTENT_AND_MEMORY_PROMPT = """分析用户的最新消息，完成以下任务：

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
- 面试官问"手写 TopK 问题"，用户开始写代码 → keywords: ["TopK", "堆"]
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
- main_topic: 话题核心技术点，2-4 字（如"Redis 缓存穿透"、"TopK 问题"）
- positive_terms: 必须包含的检索词（技术术语，最多 5 个）
- negative_terms: 必须排除的检索词（容易混淆的概念，最多 3 个）

示例:
- 面试官问"说说 Redis 缓存穿透" → {{"retrieval_intent": "find_similar", "main_topic": "Redis 缓存穿透", "positive_terms": ["Redis", "缓存穿透", "布隆过滤器"], "negative_terms": []}}
- 面试官问"高并发怎么做" → {{"retrieval_intent": "find_similar", "main_topic": "高并发限流", "positive_terms": ["高并发", "限流", "令牌桶"], "negative_terms": []}}

## 任务5: 回答质量与路由状态判断
根据用户最新消息和最近对话，输出以下结构化状态字段：

- answer_quality: 回答质量，五选一
  - complete: 回答完整，可进入下一题/检索
  - incomplete: 只给片段、反问确认、过渡词
  - off_topic: 回答与问题明显不相关
  - repeated: 与之前回答实质重复
  - vague: 笼统、背书式、缺乏细节
- should_retrieve: boolean（本轮是否需要先调用 search_questions / draw_questions）
  - true 当 intent=interview_question 且 answer_quality 为 complete/vague，且当前没有未使用候选题
  - true 当 intent=practice_request
  - false 当 intent=chat/follow_up/end_interview 或 answer_quality 为 incomplete/off_topic/repeated
- transition_style: 过渡风格，四选一
  - natural: 正常承接
  - from_candidate_keyword: 用候选人上一个回答中的技术关键词承接
  - pivot: 明确切换方向
  - closing: 进入收尾
- escalation_level: 0-3，同一问题/话题的追问升级层级
  - 0: 正常回答或首次追问
  - 1: 已指出问题/要求展开
  - 2: 已给出提示或缩小范围
  - 3: 必须放弃当前问题换方向
- requires_bank_question: boolean（本轮是否必须绑定题库题目）
  - true 当 intent=practice_request 或明确请求算法/代码题
  - false 当开场前 N 轮或 answer_quality 为 incomplete/off_topic/repeated
- candidate_act: answered_question / asked_counter_question / asked_for_summary / requested_end / greeting / chitchat
- asked_counter_question: boolean，候选人是否提出对团队、岗位或流程的反问
- counter_question_topic: 反问主题；没有反问时为 null
- asked_for_summary: boolean，候选人是否要求总结或评价
- requested_end: boolean，候选人是否要求结束本轮面试
- needs_clarification: boolean，当前回答是否需要围绕原题补充证据
- needs_new_dimension: boolean，当前回答完整后是否应切换评估维度
- suggested_question_type: project_followup / knowledge_probe / algorithm_coding / system_design / behavioral / null
- confidence: 0.0-1.0，对上述语义判断的置信度
- evidence: 一句基于当前消息和最近对话的判断依据

判断标准:
- answer_complete 等价于 answer_quality 为 complete 或 vague
- 如果意图不是 interview_question，answer_quality 设为 complete，should_retrieve 设为 false

## 可用记忆
{memory_list}

{rule_hint}

## 用户消息
{user_message}

## 最近对话
{recent_context}

严格返回JSON格式:
{{"intent": "类别", "relevant_memory_ids": [id1, id2], "keywords": ["技术词1", "技术词2"], "search_query": "技术词1 技术词2", "rewrite": {{"retrieval_intent": "...", "main_topic": "...", "positive_terms": [...], "negative_terms": [...]}}, "classify_result": {{"answer_quality": "...", "should_retrieve": true/false, "transition_style": "...", "escalation_level": 0, "requires_bank_question": true/false, "candidate_act": "...", "asked_counter_question": false, "counter_question_topic": null, "asked_for_summary": false, "requested_end": false, "needs_clarification": false, "needs_new_dimension": false, "suggested_question_type": null, "confidence": 0.0, "evidence": "..."}}}}"""


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
_END_INTERVIEW_LIFECYCLE_HINTS = [
    "数据流",
    "流程",
    "系统",
    "模块",
    "链路",
    "pipeline",
    "metadata",
    "trace",
    "rag",
    "工具调用",
    "题目选择",
    "落库",
    "从候选人",
    "进来到",
]
_END_INTERVIEW_DIRECT_PREFIXES = (
    "请",
    "帮我",
    "麻烦",
    "我要",
    "我想",
    "可以",
    "能不能",
    "我们",
    "今天",
    "先",
    "就",
)


def _is_explicit_end_interview_request(message: str) -> bool:
    """Return True only when the user is asking to end this interview.

    Candidate answers may mention lifecycle phrases such as "面试结束时" while
    describing an interview product. Those should stay interview_question.
    """

    text = str(message or "").strip()
    if not text:
        return False

    has_end_keyword = any(keyword in text for keyword in _END_INTERVIEW_KEYWORDS)
    if not has_end_keyword:
        return False

    lower = text.lower()
    looks_like_product_lifecycle = len(text) > 50 and any(
        hint in lower or hint in text for hint in _END_INTERVIEW_LIFECYCLE_HINTS
    )
    if looks_like_product_lifecycle:
        return False

    if len(text) <= 50:
        return True

    return text.startswith(_END_INTERVIEW_DIRECT_PREFIXES)


def _rule_based_intent(message: str) -> str | None:
    """规则预判断，快速返回明显意图（零 LLM 成本）"""
    lower = message.lower().strip()

    for kw in _CHAT_KEYWORDS:
        if kw == lower:
            return "chat"

    # end_interview 检测优先于 practice_request，但必须是明确结束请求。
    if _is_explicit_end_interview_request(message):
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


def _build_classify_result(
    *,
    intent: str,
    answer_complete: bool,
    question_type: str | None = None,
    llm_classify: dict | None = None,
) -> "ClassifyResult":
    """Build a ClassifyResult from rule/LLM inputs.

    The LLM may suggest routing fields; rules provide a safety floor.
    """
    from app.agents.chat.classify_result import ClassifyResult

    llm = llm_classify or {}
    quality = str(llm.get("answer_quality") or "").strip()
    if quality not in ("complete", "incomplete", "off_topic", "repeated", "vague"):
        quality = "complete" if answer_complete else "incomplete"

    should_retrieve = bool(llm.get("should_retrieve", False))
    if intent in ("chat", "follow_up", "end_interview"):
        should_retrieve = False
    elif quality in ("incomplete", "off_topic", "repeated"):
        should_retrieve = False
    elif intent == "practice_request":
        should_retrieve = True

    requires_bank = bool(llm.get("requires_bank_question", False))
    if intent == "practice_request":
        requires_bank = True
    elif quality in ("incomplete", "off_topic", "repeated"):
        requires_bank = False

    transition = str(llm.get("transition_style") or "").strip()
    if transition not in ("natural", "from_candidate_keyword", "pivot", "closing"):
        transition = "natural"

    escalation = llm.get("escalation_level", 0)
    try:
        escalation = max(0, min(3, int(escalation)))
    except (TypeError, ValueError):
        escalation = 0

    def semantic_bool(name: str) -> bool:
        value = llm.get(name, False)
        return value if isinstance(value, bool) else False

    try:
        confidence = max(0.0, min(1.0, float(llm.get("confidence", 0.0))))
    except (TypeError, ValueError):
        confidence = 0.0

    candidate_act = llm.get("candidate_act")
    candidate_act = candidate_act.strip() if isinstance(candidate_act, str) else None
    counter_topic = llm.get("counter_question_topic")
    counter_topic = counter_topic.strip() if isinstance(counter_topic, str) else None
    suggested_type = llm.get("suggested_question_type")
    suggested_type = suggested_type.strip() if isinstance(suggested_type, str) else None
    evidence = llm.get("evidence")
    evidence = evidence.strip() if isinstance(evidence, str) else None

    return ClassifyResult(
        intent=intent,  # type: ignore[arg-type]
        answer_quality=quality,  # type: ignore[arg-type]
        question_type=question_type,  # type: ignore[arg-type]
        should_retrieve=should_retrieve,
        transition_style=transition,  # type: ignore[arg-type]
        escalation_level=escalation,
        requires_bank_question=requires_bank,
        candidate_act=candidate_act,
        asked_counter_question=semantic_bool("asked_counter_question"),
        counter_question_topic=counter_topic,
        asked_for_summary=semantic_bool("asked_for_summary"),
        requested_end=semantic_bool("requested_end"),
        needs_clarification=semantic_bool("needs_clarification"),
        needs_new_dimension=semantic_bool("needs_new_dimension"),
        suggested_question_type=suggested_type,
        confidence=confidence,
        evidence=evidence,
    )


async def classify_and_recall(
    user_message: str,
    recent_context: str,
    memory_summaries: list[dict],
    user_id: int,
) -> tuple[str, list[int], list[str], str, bool, dict, dict]:
    """合并意图分类 + 记忆召回 + 检索查询生成 + 回答完整性判断（单次 LLM 调用）

    Returns:
        (intent, relevant_memory_ids, keywords, search_query, answer_complete, structured_rewrite, classify_result)
    """
    from app.agents.chat.classify_result import ClassifyResult

    # 3. 合并 LLM 调用：意图 + 记忆选择 + 检索查询
    memory_list = "\n".join(
        f"[id:{m['id']} {m['memory_type']}] {m['summary']}" for m in memory_summaries
    ) if memory_summaries else ""

    try:
        prompt = INTENT_AND_MEMORY_PROMPT.format(
            memory_list=memory_list,
            user_message=user_message,
            recent_context=recent_context,
            rule_hint="",
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
        if not keywords and intent in ("interview_question", "practice_request", "follow_up"):
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

        llm_classify = parsed.get("classify_result") if isinstance(parsed.get("classify_result"), dict) else {}
        classify_result = _build_classify_result(
            intent=intent,
            answer_complete=answer_complete,
            question_type=structured_rewrite.get("question_type"),
            llm_classify=llm_classify,
        ).to_state()

        return (
            intent,
            memory_ids,
            keywords,
            search_query,
            answer_complete,
            structured_rewrite,
            classify_result,
        )

    except Exception as e:
        logger.warning(f"合并意图+召回 LLM 调用失败，降级到规则: {e}")
        intent = _rule_based_intent(user_message) or "interview_question"
        keywords = (
            _extract_keywords_fallback(user_message)
            if intent in ("interview_question", "practice_request", "follow_up")
            else []
        )
        answer_complete = _heuristic_answer_complete(user_message)
        structured = _infer_rule_based_rewrite(user_message, keywords, intent)
        classify_result = _build_classify_result(
            intent=intent,
            answer_complete=answer_complete,
            question_type=structured.get("question_type"),
        ).to_state()
        return intent, [], keywords, " ".join(keywords), answer_complete, structured, classify_result


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
            if intent == "end_interview" and not _is_explicit_end_interview_request(
                user_message
            ):
                return "interview_question"
            return intent
    except Exception as e:
        logger.warning(f"意图分类 LLM 调用失败: {e}")

    return "interview_question"
