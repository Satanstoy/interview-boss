"""Public reasoning/tool trace helpers for chat message metadata."""

from __future__ import annotations

import json
from typing import Any

from app.agents.chat.chat_constants import PUBLIC_QUESTION_PREVIEW_LIMIT
from app.agents.chat.metadata import _extract_company, _extract_round

SAFE_TOOL_ARG_KEYS = {
    "keywords",
    "count",
    "difficulty",
    "question_type",
    "skill_name",
    "cat1",
    "cat2",
    "candidate_index",
    "question_id",
    "topic",
}

TOOL_LABELS = {
    "load_skill": "加载策略",
    "search_questions": "检索题库",
    "draw_questions": "抽取题目",
    "select_question": "采用面试题",
}

SKILL_LABELS = {
    "adaptive-difficulty": "自适应难度策略",
    "algorithm-coding": "算法面试策略",
    "hr-soft-skills": "HR 软技能策略",
    "interview-rhythm": "面试节奏策略",
    "project-deep-dive": "项目深挖策略",
    "system-design": "系统设计策略",
    "theory-qa": "理论问答策略",
}

SKILL_REASONS = {
    "adaptive-difficulty": "根据候选人的回答质量调整追问难度",
    "algorithm-coding": "当前阶段需要考察手撕代码和算法思路",
    "hr-soft-skills": "当前阶段需要考察行为面和稳定性信号",
    "interview-rhythm": "根据面试进度调整本轮追问节奏",
    "project-deep-dive": "候选人正在介绍项目，需要追问职责、架构和取舍",
    "system-design": "当前阶段需要考察系统设计和场景题能力",
    "theory-qa": "当前阶段需要考察基础知识和技术原理",
}

PERSISTENT_SKILL_NAMES = {"interview-rhythm"}

SUMMARY_BY_STEP = {
    "understanding": "分析候选人回答，判断下一步追问方向",
    "load_skill": "加载面试策略，调整本轮追问方式",
    "search_questions": "根据关键词检索题库中的相关面试题",
    "draw_questions": "从题库抽取符合当前阶段的题目",
    "select_question": "选择一道题作为本轮追问依据",
    "generating": "综合上下文、题库结果和面试阶段组织追问",
    "closing": "根据本轮对话生成面试总结",
}


def _parse_tool_args(tool_call: dict) -> dict:
    raw_args = tool_call.get("function", {}).get("arguments", "{}")
    if isinstance(raw_args, dict):
        return raw_args
    try:
        parsed = json.loads(raw_args or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_value(value: Any) -> Any:
    if isinstance(value, str):
        return value[:120]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_safe_value(item) for item in value[:5]]
    if isinstance(value, dict):
        return {
            str(key)[:40]: _safe_value(item)
            for key, item in list(value.items())[:5]
        }
    return str(type(value).__name__)


def safe_tool_args(tool_call: dict) -> dict:
    args = _parse_tool_args(tool_call)
    return {
        key: _safe_value(value)
        for key, value in args.items()
        if key in SAFE_TOOL_ARG_KEYS
    }


def _preview_question(question: dict) -> dict:
    return {
        "id": question.get("id"),
        "question": str(question.get("question") or "")[:160],
        "cat1": question.get("cat1") or "",
        "cat2": question.get("cat2") or "",
        "company": _extract_company(question),
        "round": _extract_round(question),
    }


def _question_candidates(state: dict) -> list[dict]:
    candidates = state.get("retrieved_questions") or state.get("candidate_questions") or []
    return [item for item in candidates if isinstance(item, dict)]


def _selected_question_id(state: dict):
    selected = state.get("selected_question")
    if isinstance(selected, dict):
        return selected.get("id")
    return None


def build_tool_trace(
    tool_name: str,
    tool_call: dict,
    summary: dict,
    elapsed_ms: int,
    state: dict,
    output: str = "",
) -> dict:
    del output
    result_preview = [
        _preview_question(q)
        for q in _question_candidates(state)[:PUBLIC_QUESTION_PREVIEW_LIMIT]
    ]
    result_ids = summary.get("result_ids")
    if not isinstance(result_ids, list):
        result_ids = [
            q.get("id")
            for q in _question_candidates(state)[:PUBLIC_QUESTION_PREVIEW_LIMIT]
            if q.get("id") is not None
        ]
    error = summary.get("error") or ""
    ok = bool(summary.get("ok", not error))
    return {
        "tool_name": tool_name,
        "label": TOOL_LABELS.get(tool_name, tool_name),
        "message": str(summary.get("message") or ""),
        "args_summary": safe_tool_args(tool_call),
        "elapsed_ms": max(int(elapsed_ms or 0), 0),
        "ok": ok,
        "result_count": int(summary.get("result_count") or 0),
        "result_ids": result_ids[:PUBLIC_QUESTION_PREVIEW_LIMIT],
        "result_preview": result_preview,
        "selected_question_id": _selected_question_id(state),
        "fallback_used": bool(summary.get("fallback_used", False)),
        "empty_reason": str(summary.get("empty_reason") or ""),
        "debug_reason": str(summary.get("debug_reason") or ""),
        "error": str(error),
    }


def build_skill_trace_from_tool(
    tool_name: str,
    tool_call: dict,
    summary: dict,
) -> dict | None:
    if tool_name != "load_skill":
        return None
    skill_name = str(safe_tool_args(tool_call).get("skill_name") or "")
    if not skill_name:
        return None
    status = "loaded" if summary.get("ok", True) else "error"
    if summary.get("error"):
        status = str(summary["error"])
    return {
        "skill_name": skill_name,
        "label": SKILL_LABELS.get(skill_name, skill_name),
        "reason": SKILL_REASONS.get(skill_name, "根据本轮面试阶段加载对应策略"),
        "persistent": skill_name in PERSISTENT_SKILL_NAMES,
        "status": status,
    }


def build_reasoning_trace(
    collected_thinking: list[dict],
    steps: list[dict],
    tool_traces: list[dict],
    skill_traces: list[dict],
    duration_ms: int,
) -> dict:
    model_reasoning_available = False
    model_reasoning_duration_ms = 0
    model_reasoning_truncated = False
    for item in collected_thinking:
        chunks = [
            str(chunk)
            for chunk in item.get("chunks", [])
            if str(chunk).strip()
        ][:50]
        if chunks:
            model_reasoning_available = True
            model_reasoning_duration_ms += max(int(item.get("duration_ms") or 0), 0)
            model_reasoning_truncated = (
                model_reasoning_truncated or len(item.get("chunks", [])) > 50
            )

    summary = []
    seen = set()
    for step in steps:
        text = SUMMARY_BY_STEP.get(step.get("step"))
        if text and text not in seen:
            summary.append(text)
            seen.add(text)
    for skill in skill_traces:
        label = skill.get("label") or skill.get("skill_name")
        if label:
            text = f"加载{label}，调整本轮面试策略"
            if text not in seen:
                summary.append(text)
                seen.add(text)
    for tool in tool_traces:
        label = tool.get("label")
        if label:
            text = f"{label}，获取本轮追问依据"
            if text not in seen:
                summary.append(text)
                seen.add(text)

    if model_reasoning_available and not summary:
        summary.append("模型分析上下文并组织回答")

    if model_reasoning_available:
        source = "model_reasoning"
    elif summary:
        source = "summary_fallback"
    else:
        source = "timing_only"

    return {
        "version": 1,
        "duration_ms": max(int(duration_ms or 0), 0),
        "source": source,
        "summary": summary[:8],
        "model_reasoning": {
            "available": model_reasoning_available,
            "duration_ms": model_reasoning_duration_ms,
            "truncated": model_reasoning_truncated,
        },
    }


def merge_trace_metadata(
    metadata: dict,
    *,
    reasoning_trace: dict,
    tool_calls_trace: list[dict],
    skill_trace: list[dict],
) -> dict:
    merged = dict(metadata or {})
    merged["reasoning_trace"] = reasoning_trace
    merged["tool_calls_trace"] = tool_calls_trace
    merged["skill_trace"] = skill_trace
    return merged
