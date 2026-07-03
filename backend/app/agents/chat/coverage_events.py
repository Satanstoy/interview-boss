"""Coverage event normalization for interview runtime state.

Coverage events are the durable facts that connect one assistant turn to the
next turn's stop policy.  They keep InterviewLedger from relying only on loose
text inference when the interviewer asks natural conversation-only questions.
"""

from __future__ import annotations

import re
from typing import Any

_COVERAGE_PHASES = {
    "project_followup",
    "knowledge_probe",
    "algorithm_coding",
    "system_design",
    "behavioral",
}


def canonical_coverage_phase(value: Any, text: str = "") -> str:
    """Return a normalized coverage phase, or an empty string."""

    raw = str(value or "").strip().lower()
    if raw in _COVERAGE_PHASES:
        return raw
    if raw in {"hr", "soft_skills", "hr_soft_skills"}:
        return "behavioral"

    combined = " ".join(part for part in (raw, text or "") if part)
    if re.search(r"(行为面|协作|冲突|失败|复盘|star|影响力|稳定性|职业规划)", combined, re.I):
        return "behavioral"
    if re.search(r"(系统设计|架构设计|高可用|扩展性|scalability|限流|降级|容灾)", combined, re.I):
        return "system_design"
    if re.search(r"(算法|代码|手撕|数据结构|链表|排序|二分|lru|滑动窗口)", combined, re.I):
        return "algorithm_coding"
    if re.search(r"(redis|mysql|tcp|http|缓存|锁|线程|进程|索引|mcp|rag|向量|检索)", combined, re.I):
        return "knowledge_probe"
    if re.search(r"(项目|经历|职责|落地|链路|agent|langgraph)", combined, re.I):
        return "project_followup"
    return ""


def coverage_event_from_question(
    question: dict | None,
    *,
    question_type: str | None,
    source: str | None,
    reason: str | None,
    fallback_text: str = "",
) -> dict:
    """Build a high-confidence event from a selected question."""

    if not isinstance(question, dict):
        return {}
    question_text = str(question.get("question") or fallback_text or "").strip()
    phase_text = " ".join(
        str(question.get(field) or "")
        for field in ("question", "cat1", "cat2", "tags")
    )
    phase = canonical_coverage_phase(question_type, phase_text)
    if not phase:
        phase = canonical_coverage_phase(question.get("tags"), phase_text)
    if not phase:
        return {}

    evidence: dict[str, Any] = {"question_type": phase}
    raw_id = question.get("id")
    try:
        qid = int(raw_id)
    except (TypeError, ValueError):
        qid = 0
    if qid > 0:
        evidence["question_id"] = qid

    event = {
        "phase": phase,
        "source": source or "selected_question",
        "confidence": "high",
        "question_text": question_text,
        "evidence": evidence,
        "reason": reason or "selected_question",
    }
    return {key: value for key, value in event.items() if value not in ("", None, {})}


def coverage_event_from_conversation(
    state: dict[str, Any],
    response_text: str,
    *,
    source: str | None,
    reason: str | None,
) -> dict:
    """Build a medium-confidence event for natural conversation-only questions."""

    text = str(response_text or "").strip()
    if not _looks_like_interview_question(text):
        return {}
    interview_state = state.get("interview_state") or {}
    phase = canonical_coverage_phase(state.get("question_type"), text)
    if not phase:
        phase = canonical_coverage_phase(interview_state.get("current_phase"), text)
    if not phase:
        phase = canonical_coverage_phase(interview_state.get("next_focus"), text)
    if not phase:
        return {}

    event = {
        "phase": phase,
        "source": source or "conversation",
        "confidence": "medium",
        "question_text": text,
        "reason": reason or "conversation_followup",
    }
    return {key: value for key, value in event.items() if value not in ("", None)}


def _looks_like_interview_question(text: str) -> bool:
    """Keep explanatory replies and candidate reverse-question answers out of coverage."""

    if "?" in text or "？" in text:
        return True
    return bool(
        re.search(
            r"(请你|能否|可以说说|讲讲|说说|介绍一下|怎么|为什么|如果.*你会)",
            text,
        )
    )


def question_from_coverage_event(event: dict | None) -> tuple[dict, str] | None:
    """Convert a persisted coverage event into an InterviewLedger input."""

    if not isinstance(event, dict):
        return None
    phase = canonical_coverage_phase(event.get("phase"), str(event.get("question_text") or ""))
    if not phase:
        return None
    evidence = event.get("evidence") if isinstance(event.get("evidence"), dict) else {}
    raw_id = evidence.get("question_id")
    try:
        qid = int(raw_id)
    except (TypeError, ValueError):
        qid = 0
    question = {
        "id": qid,
        "question": str(event.get("question_text") or ""),
        "cat1": str(event.get("source") or ""),
        "cat2": phase,
        "tags": phase,
    }
    return question, phase
