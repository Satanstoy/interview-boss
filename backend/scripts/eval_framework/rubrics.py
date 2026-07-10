"""Scoring rubrics for interview quality evaluation.

Best practices from eval-layer/rubric-design.md:
- 1-5 integer scale with concrete anchor descriptions
- Max 5 dimensions (beyond that, judge gives all 3s)
- Weights sum to 1.0
"""

from __future__ import annotations

from typing import Any

from .types import _check_ratio, _check_error_corrected


# ── Rubric Builder ─────────────────────────────────────


def _make_rubric(dimensions: list[dict]) -> dict:
    """Build a scoring dict with rubric metadata for the LLM judge."""
    result = {}
    for dim in dimensions:
        key = dim["key"]
        entry: dict[str, Any] = {
            "description": dim["description"],
            "weight": dim["weight"],
            "rubric": dim["rubric"],
        }
        if "check" in dim:
            entry["check"] = dim["check"]
        result[key] = entry
    return result


# ── Shared Rubric Dimensions ───────────────────────────

_ROLE_ADHERENCE = {
    "key": "role_adherence",
    "description": "面试官角色一致性：全程是否保持面试官身份",
    "weight": 0.25,
    "rubric": {
        1: "面试官多次跳出角色，要求候选人提供岗位信息、简历等系统侧内容，或暴露内部工具名/评分逻辑",
        2: "面试官偶尔跳出角色（1-2次），如做元说明或暴露系统信息",
        3: "面试官基本保持角色，但有轻微偏差（如语气偶尔不像真实面试官）",
        4: "面试官全程保持角色，语气专业，无元说明",
        5: "面试官完全像一个真实的中国互联网大厂技术面试官，语气、追问方式、节奏都高度自然",
    },
}

_INTERVIEW_DEPTH = {
    "key": "interview_depth",
    "description": "面试深度：对核心话题的追问是否充分",
    "weight": 0.25,
    "rubric": {
        1: "面试官只问表面问题，没有追问，像在走流程",
        2: "面试官有追问但只到第2层，没有深入到决策原因或困难解决",
        3: "面试官对主要话题追问到第3层（架构→决策→困难），但有些话题浅尝辄止",
        4: "面试官对大多数话题追问到第3-4层，能引导候选人展示真实能力",
        5: "面试官追问层层递进，能从候选人回答中发现盲点并深入考察，像真正的资深面试官",
    },
}

_TOPIC_COVERAGE = {
    "key": "topic_coverage",
    "description": "面试维度覆盖：是否考察了多个技术维度",
    "weight": 0.20,
    "rubric": {
        1: "面试只涉及1个维度（如只问项目），完全偏科",
        2: "面试涉及2个维度（如项目+八股），缺少算法/系统设计",
        3: "面试涉及3个维度（项目+八股+算法或系统设计），基本覆盖",
        4: "面试涉及4个维度，且每个维度都有实质性考察",
        5: "面试覆盖项目深挖、八股基础、算法/编码、系统设计、HR/软素质，且穿插自然",
    },
}

_CONVERSATION_FLOW = {
    "key": "conversation_flow",
    "description": "对话流畅度：话题切换是否自然，节奏是否像真实面试",
    "weight": 0.15,
    "rubric": {
        1: "话题切换生硬（如'换个方向'），对话像在读脚本",
        2: "话题切换偶尔自然，但有明显机械痕迹（如重复使用相同句式）",
        3: "话题切换基本自然，但偶尔缺乏承接（突然跳到不相关话题）",
        4: "话题切换自然，善于用候选人回答中的关键词做承接",
        5: "对话节奏完全像真实面试，深挖→穿插→收尾的过渡流畅自然",
    },
}

_TOOL_EFFECTIVENESS = {
    "key": "tool_effectiveness",
    "description": "工具使用效果：工具调用是否服务于面试质量",
    "weight": 0.15,
    "rubric": {
        1: "工具调用完全无效——调了工具但结果从未被引用到提问中，纯粹浪费",
        2: "工具调用偶尔有效，但大多数调用是多余的（检索了但没用）",
        3: "工具调用基本有效，至少50%的检索结果被引用到后续提问中",
        4: "工具调用高效，检索结果自然融入面试官的提问，不突兀",
        5: "工具调用精准且高效，每次检索都直接服务于面试节奏，候选人感受不到工具的存在",
    },
}

_CLOSING_QUALITY = {
    "key": "closing_quality",
    "description": "收口质量：面试结束时是否给出有价值的总结",
    "weight": 0.20,
    "rubric": {
        1: "面试官突然中断，没有任何总结或评价",
        2: "面试官简单说'面试就到这里'，没有对候选人表现做任何评价",
        3: "面试官给出了简要总结，但缺乏具体评价（如只说'聊得不错'）",
        4: "面试官给出了结构化总结，包含整体印象、亮点和不足",
        5: "面试官给出了专业且有建设性的总结，包含具体技术评价、改进建议和后续流程说明",
    },
}

_COUNTER_QUESTION_QUALITY = {
    "key": "counter_question_handling",
    "description": "反问处理：候选人反问时面试官的应对质量",
    "weight": 0.25,
    "rubric": {
        1: "面试官完全忽略候选人的反问，直接跳到下一个问题",
        2: "面试官敷衍回应反问（如'嗯'），没有实质内容",
        3: "面试官简短回应了反问，但没有展示对候选人问题的尊重",
        4: "面试官认真回应反问（1-2句实质内容），然后自然拉回面试话题",
        5: "面试官对反问给出有深度的回应，展示了对候选人问题的重视，然后平滑过渡回面试",
    },
}


# ── Legacy Scoring Dicts (code-based, non-rubric) ─────

LONG_SESSION_SCORING = {
    "tool_call_rate": {
        "description": "至少 60% 的轮次有工具调用信号",
        "weight": 1.0,
        "check": lambda m: _check_ratio(m["tool_count"], m["turn_count"], 0.6),
    },
    "selected_question_present": {
        "description": "至少出现 1 次 selected_question 事件",
        "weight": 1.0,
        "check": lambda m: len(m["selected_ids"]) >= 1,
    },
    "asked_questions_recorded": {
        "description": "DB 中有 asked_questions 记录",
        "weight": 1.0,
        "check": lambda m: len(m["asked_questions"]) >= 1,
    },
    "no_cross_turn_duplicate_candidates": {
        "description": "跨轮候选题无重复",
        "weight": 0.5,
        "check": lambda m: len(m["cross_turn_duplicate_candidates"]) == 0,
    },
    "has_summary": {
        "description": "最后一轮包含结构化总结",
        "weight": 1.0,
        "check": lambda m: bool(m["has_summary"]),
    },
    "no_sse_errors": {
        "description": "零 SSE 错误事件",
        "weight": 1.0,
        "check": lambda m: len(m["errors"]) == 0,
    },
    "thinking_transparency": {
        "description": "至少 50% 的轮次有 thinking 事件",
        "weight": 0.5,
        "check": lambda m: _check_ratio(m["thinking_turns"], m["turn_count"], 0.5),
    },
}

ERROR_CORRECTION_SCORING = {
    "bert_error_corrected": {
        "description": "BERT 生成式错误在输出层被纠正",
        "check": lambda m: _check_error_corrected(m, "bert"),
    },
    "faiss_error_corrected": {
        "description": "Faiss ACID 错误在输出层被纠正",
        "check": lambda m: _check_error_corrected(m, "faiss"),
    },
    "correction_in_output": {
        "description": "纠正出现在 assistant 回复中，而非仅在 thinking 中",
        "check": lambda m: m["correction_in_output_count"] > 0,
    },
}

EARLY_CLOSE_SCORING = {
    "early_close_refused": {
        "description": "过早收尾被拒绝",
        "weight": 2.0,
        "check": lambda m: bool(m.get("early_close_refused", False)),
    },
    "probes_instead": {
        "description": "面试官追问细节而非直接收尾",
        "weight": 1.0,
        "check": lambda m: not m.get("has_summary", False),
    },
    "no_sse_errors": {
        "description": "零 SSE 错误事件",
        "weight": 0.5,
        "check": lambda m: len(m["errors"]) == 0,
    },
}

PROPER_END_SCORING = {
    "has_summary": {
        "description": "面试官在候选人表示收尾后，给出结构化面试总结",
        "weight": 2.0,
    },
    "summary_mentions_topics": {
        "description": "总结中提到本次面试讨论的具体技术主题",
        "weight": 1.0,
    },
    "no_sse_errors": {
        "description": "零 SSE 错误事件",
        "weight": 0.5,
    },
}

INSUFFICIENT_EVIDENCE_SCORING = {
    "interviewer_probes_for_details": {
        "description": "面试官在候选人回答模糊时，主动追问具体细节",
        "weight": 2.0,
    },
    "probe_count": {
        "description": "面试官至少追问 2 次细节",
        "weight": 1.0,
    },
    "no_sse_errors": {
        "description": "零 SSE 错误事件",
        "weight": 0.5,
    },
}

COUNTER_QUESTION_SCORING = {
    "counter_question_answered": {
        "description": "候选人反问被回答",
        "weight": 2.0,
    },
    "answer_substantive": {
        "description": "回答有实质内容，不是敷衍",
        "weight": 1.0,
    },
    "no_sse_errors": {
        "description": "零 SSE 错误事件",
        "weight": 0.5,
    },
}


# ── Rubric-Based Scoring (1-5 scale) ──────────────────

GREETING_SCORING = _make_rubric([
    {**_ROLE_ADHERENCE, "weight": 0.30, "check": lambda m: not m.get("has_meta_remarks", False)},
    _INTERVIEW_DEPTH,
    _TOPIC_COVERAGE,
    _CONVERSATION_FLOW,
    {**_TOOL_EFFECTIVENESS, "weight": 0.10},
])

TOOL_TIMING_SCORING = _make_rubric([
    _TOOL_EFFECTIVENESS,
    _INTERVIEW_DEPTH,
    _TOPIC_COVERAGE,
    _CONVERSATION_FLOW,
    {**_ROLE_ADHERENCE, "check": lambda m: not m.get("has_meta_remarks", False)},
])

NATURAL_CLOSING_SCORING = _make_rubric([
    _CLOSING_QUALITY,
    _INTERVIEW_DEPTH,
    _TOPIC_COVERAGE,
    _CONVERSATION_FLOW,
    {**_ROLE_ADHERENCE, "weight": 0.10, "check": lambda m: not m.get("has_meta_remarks", False)},
])

COUNTER_QUESTION_FLOW_SCORING = _make_rubric([
    _COUNTER_QUESTION_QUALITY,
    _INTERVIEW_DEPTH,
    _TOPIC_COVERAGE,
    _CONVERSATION_FLOW,
    {**_ROLE_ADHERENCE, "weight": 0.10, "check": lambda m: not m.get("has_meta_remarks", False)},
])
