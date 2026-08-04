"""Metrics extraction from eval conversation turns."""

from __future__ import annotations

import os
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from .types import SUMMARY_SIGNALS, CORRECTION_OUTPUT_SIGNALS


def _event_data(event: dict) -> dict:
    """Extract data from an SSE event."""
    return event.get("data", event) if isinstance(event.get("data"), dict) else event


def _event_tool_name(event: dict) -> str | None:
    """Extract a tool name from either public SSE tool representation."""
    event_type = event.get("type")
    if event_type == "tool_step":
        data = _event_data(event)
        step = data.get("tool_name") or data.get("tool") or ""
    elif event_type == "step":
        step = event.get("step", "")
    else:
        return None
    if step in ("search_questions", "draw_questions", "select_question", "load_skill"):
        return step
    return None


def _ids_from_object(obj: Any) -> list[int]:
    """Recursively extract integer IDs from an object."""
    if obj is None:
        return []
    if isinstance(obj, int):
        return [obj]
    if isinstance(obj, str):
        try:
            return [int(obj)]
        except ValueError:
            return []
    if isinstance(obj, list):
        return [id_ for item in obj for id_ in _ids_from_object(item)]
    if isinstance(obj, dict):
        return [id_ for item in obj.values() for id_ in _ids_from_object(item)]
    return []


def _candidate_ids_for_turn(turn: dict) -> list[int]:
    """Extract candidate question IDs from a turn's events."""
    ids = []
    for event in turn.get("events", []):
        data = _event_data(event)
        if event.get("type") in ("candidates", "candidate_questions", "retrieved"):
            for q in data.get("questions", data.get("candidates", [])):
                if isinstance(q, dict):
                    ids.extend(_ids_from_object(q.get("id")))
            ids.extend(_ids_from_object(data.get("ids", data.get("candidate_ids", []))))
    return ids


def find_cross_turn_duplicates(turns: list[dict]) -> list[int]:
    """Find question IDs that appear in multiple turns."""
    seen: dict[int, int] = {}
    for turn in turns:
        for qid in _candidate_ids_for_turn(turn):
            seen[qid] = seen.get(qid, 0) + 1
    return [qid for qid, count in seen.items() if count > 1]


def query_asked_questions_db(conversation_id: str) -> list[int]:
    """Query the DB for asked question IDs."""
    db_path = os.getenv("EVAL_DB_PATH", "backend/data/interview-boss.db")
    if not Path(db_path).exists():
        return []
    try:
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                "SELECT question_id FROM interview_asked_questions WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchall()
            return [int(r[0]) for r in rows]
    except Exception:
        return []


def _detect_early_close_refused(turns: list[dict]) -> bool:
    """Detect if interviewer refused an early close request."""
    for turn in turns:
        user_text = str(turn.get("user") or "")
        assistant_text = str(turn.get("assistant") or "")
        user_asks_close = any(signal in user_text for signal in ("结束", "收尾", "就到这里"))
        assistant_continues = any(signal in assistant_text for signal in ("还需要", "再看", "继续", "补充"))
        if user_asks_close and assistant_continues:
            return True
    return False


def _detect_counter_question_answered(turns: list[dict]) -> bool:
    """Detect if a counter-question was answered."""
    signals = ("想问", "请问", "反问", "您觉得", "你觉得", "想了解")
    for turn in turns:
        user_text = str(turn.get("user") or "")
        assistant_text = str(turn.get("assistant") or "")
        if any(signal in user_text for signal in signals) and assistant_text.strip():
            return True
    return False


def _count_tools_by_turn(turns: list[dict]) -> dict[int, int]:
    """Count tool calls per turn (1-indexed)."""
    result = {}
    for i, turn in enumerate(turns, 1):
        events = turn.get("events", [])
        tool_count = sum(
            1 for e in events
            if e.get("type") == "step"
            and e.get("step") in ("search_questions", "draw_questions", "select_question", "load_skill")
        )
        result[i] = tool_count
    return result


def _detect_meta_remarks(assistant_texts: list[str]) -> bool:
    """Detect meta-remarks that break the interviewer role."""
    meta_patterns = [
        "请提供岗位信息",
        "请告诉我你想练习什么",
        "请提供简历",
        "请告诉我你的背景",
        "你设置这个面试场景",
        "作为AI",
        "作为语言模型",
        "我是一个AI",
    ]
    return any(
        pattern in text for text in assistant_texts for pattern in meta_patterns
    )


def _detect_self_intro_invite(assistant_texts: list[str]) -> bool:
    """Check if the first response invites self-introduction."""
    if not assistant_texts:
        return False
    first = assistant_texts[0]
    intro_signals = ["自我介绍", "介绍一下", "简单介绍", "先说说", "请介绍"]
    return any(signal in first for signal in intro_signals)


def _count_tools_on_counter_turn(turns: list[dict]) -> int:
    """Count tool calls on the turn where candidate asks a counter-question."""
    signals = ("想问", "请问", "反问", "您觉得", "你觉得", "想了解")
    for turn in turns:
        user_text = str(turn.get("user") or "")
        if any(signal in user_text for signal in signals):
            events = turn.get("events", [])
            return sum(
                1 for e in events
                if e.get("type") == "step"
                and e.get("step") in ("search_questions", "draw_questions", "select_question", "load_skill")
            )
    return 0


def extract_metrics(turns: list[dict[str, Any]], conv_id: str) -> dict[str, Any]:
    """Extract all metrics from conversation turns."""
    all_events = [event for turn in turns for event in turn.get("events", [])]
    tool_names = [tool for event in all_events if (tool := _event_tool_name(event))]
    selected_ids = []
    for event in all_events:
        if event.get("type") != "selected_question":
            continue
        data = _event_data(event)
        selected_ids.extend(_ids_from_object(data.get("question_id")))
        selected_ids.extend(_ids_from_object(event.get("question")))

    assistant_texts = [str(turn.get("assistant") or "") for turn in turns]
    recent_turns = turns[-4:]
    errors = [event for event in all_events if event.get("type") == "error"]
    harness_contract_errors = [
        str(turn["terminal_contract_error"])
        for turn in turns
        if turn.get("terminal_contract_error")
    ]
    thinking_events = [
        event for event in all_events if event.get("type") in {"thinking", "reasoning"}
    ]
    return {
        "turn_count": len(turns),
        "event_counts": dict(Counter(str(event.get("type")) for event in all_events)),
        "tool_names": tool_names,
        "tool_count": len(tool_names),
        "selected_ids": selected_ids,
        "candidate_ids": [question_id for turn in turns for question_id in _candidate_ids_for_turn(turn)],
        "cross_turn_duplicate_candidates": find_cross_turn_duplicates(turns),
        "asked_questions": query_asked_questions_db(conv_id),
        "has_summary": any(any(signal in text for signal in SUMMARY_SIGNALS) for text in assistant_texts[-2:]),
        "thinking_turns": sum(
            1
            for turn in turns
            if any(event.get("type") in {"thinking", "reasoning"} for event in turn.get("events", []))
        ),
        "errors": errors,
        "harness_contract_ok": not harness_contract_errors,
        "harness_contract_errors": harness_contract_errors,
        "thinking_chars": sum(
            len(str(_event_data(event).get("text") or event.get("content") or ""))
            for event in thinking_events
        ),
        "recent_turns": recent_turns,
        "correction_in_output_count": sum(
            1 for text in assistant_texts if any(signal in text for signal in CORRECTION_OUTPUT_SIGNALS)
        ),
        "early_close_refused": _detect_early_close_refused(turns),
        "has_insufficient_evidence_marker": any(
            re.search(r"证据不足|信息不足|无法充分判断", text) for text in assistant_texts[-2:]
        ),
        "counter_question_answered": _detect_counter_question_answered(turns),
        # ── New metrics ──
        "tools_by_turn": _count_tools_by_turn(turns),
        "has_meta_remarks": _detect_meta_remarks(assistant_texts),
        "invites_self_intro": _detect_self_intro_invite(assistant_texts),
        "tools_on_counter_turn": _count_tools_on_counter_turn(turns),
    }
