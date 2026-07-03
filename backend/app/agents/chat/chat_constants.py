"""Shared constants for the interview chat agent.

All hardcoded Chinese keyword lists, signal tuples, prompt strings, and
fallback text templates are centralized here.  This eliminates magic strings
scattered across ``nodes.py``, ``react_loop.py``, ``stop_policy.py``, and
``answer.py``.
"""

from __future__ import annotations


# ── Intent classification keywords (nodes.py: classify_intent) ──────────────

CHAT_KEYWORDS: frozenset[str] = frozenset(
    {
        "你好",
        "hello",
        "hi",
        "谢谢",
        "再见",
        "拜拜",
        "ok",
        "好的",
        "嗯",
    }
)

PRACTICE_KEYWORDS: tuple[str, ...] = (
    "出题",
    "来一道",
    "换一个",
    "换个",
    "练习",
    "开始",
    "出个",
)

END_KEYWORDS: tuple[str, ...] = (
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
)

FOLLOW_UP_KEYWORDS: tuple[str, ...] = (
    "解释",
    "详细",
    "具体",
    "为什么",
    "怎么",
    "能再说",
    "不太明白",
    "什么意思",
)

FOLLOW_UP_MAX_LENGTH: int = 50
"""Max user message length to qualify as follow-up (characters)."""


# ── Public observability limits ─────────────────────────────────────────────

PUBLIC_QUESTION_PREVIEW_LIMIT: int = 5
"""Max question items exposed in public SSE/metadata/tool previews."""


# ── Stop policy prompts (stop_policy.py) ────────────────────────────────────

CANDIDATE_QUESTION_PROMPT: str = "技术问题先到这里。你有什么想问我们的吗？"

CANDIDATE_QUESTION_MARKER: str = "你有什么想问"
"""Substring to detect whether assistant already asked candidate's question."""


# ── Fallback text templates (answer.py) ─────────────────────────────────────

FALLBACK_PROJECT_DEEP_DIVE: str = (
    '我们继续围绕你的项目做深挖。你刚才提到"AI 追问编排"，'
    "能展开说说你在架构设计上做的关键取舍吗？比如上下文压缩策略、"
    "记忆召回方式这些。"
)

FALLBACK_ALGORITHM_CODING: str = (
    "我们切到算法面试。我会先从基础思路开始考察，然后逐步深入到优化和边界情况。"
    "准备好了吗？"
)

FALLBACK_GENERIC: str = (
    "我继续追问一个具体问题：请结合你刚才的项目，说说你在技术选型时做了哪些关键权衡。"
)

FALLBACK_EMPTY_QUESTION: str = (
    "我先追问你刚才提到的一个点。选一个你最熟的模块，把关键设计和你当时做的取舍讲清楚。"
)
