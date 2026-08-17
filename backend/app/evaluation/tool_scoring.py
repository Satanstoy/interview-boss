"""Deterministic tool-call and intent scoring for interview E2E runs."""

from __future__ import annotations

from typing import Any


def _metadata(turn: dict[str, Any]) -> dict[str, Any]:
    value = turn.get("metadata") or {}
    return value if isinstance(value, dict) else {}


def _tool_calls(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []
    for turn in turns:
        metadata = _metadata(turn)
        traces = metadata.get("tool_calls_trace") or []
        if not isinstance(traces, list):
            traces = []
        if not traces:
            for event in turn.get("events") or []:
                if event.get("type") != "tool_step":
                    continue
                data = event.get("data") if isinstance(event.get("data"), dict) else event
                traces.append(data)
        for trace in traces:
            if not isinstance(trace, dict):
                continue
            tool_name = str(trace.get("tool_name") or trace.get("step") or "").strip()
            if not tool_name:
                continue
            calls.append(
                {
                    "turn": turn.get("turn"),
                    "tool_name": tool_name,
                    "ok": bool(trace.get("ok", True)),
                    "result_count": int(trace.get("result_count") or 0),
                    "elapsed_ms": int(trace.get("elapsed_ms") or 0),
                    "fallback_used": bool(trace.get("fallback_used", False)),
                }
            )
    return calls


def _assertion(assertion_id: str, passed: bool, evidence: str) -> dict[str, Any]:
    return {"id": assertion_id, "passed": bool(passed), "evidence": evidence}


def _intent_records(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records = []
    for turn in turns:
        metadata = _metadata(turn)
        classify = metadata.get("classify_result") or {}
        turn_intent = metadata.get("turn_intent") or {}
        if not isinstance(classify, dict):
            classify = {}
        if not isinstance(turn_intent, dict):
            turn_intent = {}
        records.append(
            {
                "turn": turn.get("turn"),
                "intent": metadata.get("intent") or classify.get("intent"),
                "candidate_act": classify.get("candidate_act"),
                "should_retrieve": classify.get("should_retrieve"),
                "requires_question_bank": classify.get("requires_bank_question"),
                "strategy": turn_intent.get("strategy"),
                "tool_requires_question_bank": (
                    (turn_intent.get("tool_intent") or {}).get("requires_question_bank")
                    if isinstance(turn_intent.get("tool_intent"), dict)
                    else None
                ),
            }
        )
    return records


def evaluate_interview_trace(
    turns: list[dict[str, Any]], contract: dict[str, Any]
) -> dict[str, Any]:
    """Score explicit tool and intent expectations without using an LLM."""
    turns = turns if isinstance(turns, list) else []
    contract = contract if isinstance(contract, dict) else {}
    calls = _tool_calls(turns)
    names = [call["tool_name"] for call in calls]
    expectations = contract.get("tool_expectations") or {}
    required_tools = [str(name) for name in expectations.get("required_tools") or []]
    forbidden_tools = [str(name) for name in expectations.get("forbidden_tools") or []]
    missing_tools = [name for name in required_tools if name not in names]
    forbidden_used = [name for name in forbidden_tools if name in names]
    failed_calls = [call for call in calls if not call["ok"]]
    min_calls = int(expectations.get("min_calls") or 0)
    max_calls = expectations.get("max_calls")
    max_calls = int(max_calls) if max_calls is not None else None
    result_used = any(
        call["result_count"] > 0
        and any(
            _turn_uses_question_result(turn)
            for turn in turns
            if int(turn.get("turn") or 0) >= int(call["turn"] or 0)
        )
        for call in calls
    )
    if not calls:
        result_used = False
    tool_assertions = [
        _assertion(
            "tool_calls_valid",
            not missing_tools
            and not forbidden_used
            and len(calls) >= min_calls
            and (max_calls is None or len(calls) <= max_calls)
            and len(failed_calls) <= int(expectations.get("max_failed_calls") or 0),
            f"calls={len(calls)}, missing={missing_tools}, forbidden={forbidden_used}, failed={len(failed_calls)}",
        )
    ]
    if expectations.get("require_result_used"):
        tool_assertions.append(
            _assertion(
                "tool_result_used",
                result_used,
                "后续回答使用了工具结果" if result_used else "没有观察到后续回答使用工具结果",
            )
        )

    records = _intent_records(turns)
    observed_intents = [record for record in records if record.get("intent")]
    observed_strategies = [record for record in records if record.get("strategy")]
    intent_expectations = contract.get("intent_expectations") or []
    intent_results = []
    for expected in intent_expectations:
        if not isinstance(expected, dict):
            continue
        turn_number = expected.get("turn")
        actual = next((record for record in records if record["turn"] == turn_number), None)
        failures = []
        if actual is None:
            failures.append("缺少对应轮次")
        else:
            for expected_key, actual_key in (
                ("expected_intent", "intent"),
                ("expected_candidate_act", "candidate_act"),
                ("expected_strategy", "strategy"),
            ):
                if expected.get(expected_key) is not None and actual.get(actual_key) != expected[expected_key]:
                    failures.append(f"{actual_key}={actual.get(actual_key)!r}")
            if expected.get("requires_question_bank") is not None:
                actual_requires = bool(
                    actual.get("requires_question_bank")
                    or actual.get("tool_requires_question_bank")
                )
                if actual_requires != bool(expected["requires_question_bank"]):
                    failures.append(f"requires_question_bank={actual_requires}")
        intent_results.append(
            {
                "turn": turn_number,
                "passed": not failures,
                "expected": expected,
                "actual": actual,
                "failures": failures,
            }
        )

    intent_failed = [item for item in intent_results if not item["passed"]]
    assertions = tool_assertions
    if records:
        assertions.append(
            _assertion(
                "intent_trace_complete",
                len(observed_intents) == len(records)
                and len(observed_strategies) == len(records),
                f"turns={len(records)}, intents={len(observed_intents)}, strategies={len(observed_strategies)}",
            )
        )
    if intent_results:
        assertions.append(
            _assertion(
                "intent_alignment",
                not intent_failed,
                "所有声明的意图与策略均匹配" if not intent_failed else f"失败轮次={len(intent_failed)}",
            )
        )
    return {
        "tool_calls": calls,
        "tool_metrics": {
            "call_count": len(calls),
            "tool_names": names,
            "failed_call_count": len(failed_calls),
            "required_tools": required_tools,
            "required_tools_missing": missing_tools,
            "forbidden_tools_used": forbidden_used,
            "result_used": result_used,
        },
        "intent_records": records,
        "intent_metrics": {
            "evaluated_count": len(intent_results),
            "failed_count": len(intent_failed),
            "observed_turn_count": len(records),
            "missing_intent_count": len(records) - len(observed_intents),
            "intent_coverage": round(len(observed_intents) / len(records), 4) if records else None,
            "strategy_coverage": round(len(observed_strategies) / len(records), 4) if records else None,
            "accuracy": round(
                (len(intent_results) - len(intent_failed)) / len(intent_results), 4
            )
            if intent_results
            else None,
            "results": intent_results,
        },
        "assertions": assertions,
    }


def _turn_uses_question_result(turn: dict[str, Any]) -> bool:
    """Return whether the turn records a question/action derived from a tool result."""
    metadata = _metadata(turn)
    selected_question = metadata.get("selected_question")
    if isinstance(selected_question, dict) and selected_question.get("id") is not None:
        return True
    source = str(metadata.get("question_source") or "").lower()
    if source in {"search", "draw", "retrieval", "agent_internal", "question_bank"}:
        return True
    return any(
        event.get("type") in {"retrieved", "selected_question"}
        or event.get("step") in {"search_questions", "draw_questions", "select_question"}
        for event in turn.get("events") or []
        if isinstance(event, dict)
    )
