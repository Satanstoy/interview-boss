"""Opt-in HTTP verifier for interview-distribution facts and live execution."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


_CANONICAL_TYPES = {
    "project_followup",
    "knowledge_probe",
    "algorithm_coding",
    "system_design",
    "behavioral",
}
_CANDIDATE_ANSWERS = (
    "我是后端与大模型应用方向候选人。做过 Agent 和 RAG 项目，负责过检索、工作流编排和服务稳定性。请继续技术面。",
    "请基于题库继续下一道技术题，我已经准备好回答。",
    "请从题库选择下一道不同类型的技术题，继续模拟面试。",
    "我希望继续下一轮技术考察，请直接出题库题。",
    "请继续技术面，并从题库抽取下一道题目。",
    "请切换到下一道技术题，使用题库中的题目即可。",
    "请继续模拟面试，直接出下一道题库技术题。",
    "我已准备好下一题，请基于题库继续考察。",
    "请从题库中继续下一道技术问题，不需要总结。",
    "请继续出下一道技术题，并保持模拟面试进行中。",
    "请直接进入下一道题库技术题的考察。",
    "请继续下一题，基于题库选择新的技术考察点。",
    "请继续模拟面试并从题库抽取下一道技术题。",
    "请不要结束面试，继续出下一道题库技术题。",
    "请继续进行技术考察，直接从题库选择下一题。",
)


def _request_json(
    method: str,
    url: str,
    token: str | None,
    body: dict[str, Any] | None = None,
) -> dict:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if body is not None:
        headers["Content-Type"] = "application/json"
    with urlopen(Request(url, data=data, headers=headers, method=method), timeout=90) as response:
        raw = response.read().decode("utf-8")
        return json.loads(raw) if raw.strip() else {}


def _request_sse(url: str, token: str, body: dict[str, Any]) -> list[dict]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {
        "Accept": "text/event-stream",
        "Content-Type": "application/json",
        "X-Requested-With": "XMLHttpRequest",
        "Authorization": f"Bearer {token}",
    }
    events: list[dict] = []
    with urlopen(Request(url, data=data, headers=headers, method="POST"), timeout=300) as response:
        buffer = ""
        while True:
            chunk = response.read(4096)
            if not chunk:
                break
            buffer += chunk.decode("utf-8", errors="replace")
            while "\n\n" in buffer:
                raw_event, buffer = buffer.split("\n\n", 1)
                data_lines = [line[5:].strip() for line in raw_event.splitlines() if line.startswith("data:")]
                if not data_lines:
                    continue
                try:
                    parsed = json.loads("\n".join(data_lines))
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    events.append(parsed)
    return events


def _payload_data(payload: dict) -> dict:
    value = payload.get("data") if isinstance(payload, dict) else None
    return value if isinstance(value, dict) else payload


def _evaluate_runtime_alignment(
    plan: dict,
    execution: dict | None,
    messages: list[dict],
) -> dict[str, Any]:
    """Check that persisted execution is backed by matching, bound questions."""

    errors: list[str] = []
    if not isinstance(execution, dict):
        return {"passed": False, "errors": ["distribution execution missing"]}
    if execution.get("status") != "completed":
        errors.append(f"distribution execution status is {execution.get('status')}")
    if execution.get("actual_primary_count") != plan.get("target_question_count"):
        errors.append("actual primary count does not match frozen target")
    if execution.get("actual_counts") != plan.get("soft_target_counts"):
        errors.append("actual type counts do not match frozen soft targets")

    counted_events: list[dict] = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        metadata = message.get("metadata") or {}
        selected_question = metadata.get("selected_question")
        for event in metadata.get("coverage_events") or []:
            if not isinstance(event, dict) or event.get("plan_id") != plan.get("plan_id"):
                continue
            if event.get("counts_toward_target") is not True:
                continue
            counted_events.append(event)
            if not isinstance(selected_question, dict) or not selected_question.get("id"):
                errors.append("counted distribution event is not bank-bound")
            if event.get("confidence") != "high":
                errors.append("counted distribution event is not high-confidence")
            if event.get("question_type") not in _CANONICAL_TYPES:
                errors.append("counted distribution event has non-canonical type")

    if len(counted_events) != int(plan.get("target_question_count") or 0):
        errors.append("counted event total does not match frozen target")
    return {
        "passed": not errors,
        "errors": errors,
        "counted_event_count": len(counted_events),
        "actual_counts": execution.get("actual_counts"),
        "target_counts": plan.get("soft_target_counts"),
    }


def _verify_live_runtime(base_url: str, token: str, *, max_turns: int, keep_conversation: bool) -> dict[str, Any]:
    base = base_url.rstrip("/")
    title = f"distribution-live-e2e-{int(time.time())}-{uuid4().hex[:8]}"
    created = _payload_data(
        _request_json(
            "POST",
            f"{base}/api/chat/conversations",
            token,
            {
                "mode": "free_practice",
                "title": title,
                "resume_text": "候选人有 Agent、RAG、FastAPI 与分布式系统项目经验。",
            },
        )
    )
    conversation_id = str(created.get("id") or "")
    if not conversation_id:
        raise RuntimeError(f"create conversation did not return id: {created}")

    report: dict[str, Any] = {"conversation_id": conversation_id, "turns": [], "alignment": None}
    try:
        details = _payload_data(_request_json("GET", f"{base}/api/chat/conversations/{conversation_id}", token))
        plan = ((details.get("metadata") or {}).get("interview_config") or {}).get("distribution_plan")
        if not isinstance(plan, dict):
            raise RuntimeError("created conversation is missing distribution plan")
        report["plan"] = plan
        turn_limit = max(max_turns, int(plan.get("target_question_count") or 0) + 2)

        for index in range(turn_limit):
            events = _request_sse(
                f"{base}/api/chat/conversations/{conversation_id}/messages",
                token,
                {"content": _CANDIDATE_ANSWERS[index % len(_CANDIDATE_ANSWERS)]},
            )
            errors = [event.get("message", "unknown SSE error") for event in events if event.get("type") == "error"]
            details = _payload_data(_request_json("GET", f"{base}/api/chat/conversations/{conversation_id}", token))
            execution = details.get("distribution_execution")
            report["turns"].append(
                {
                    "index": index + 1,
                    "error_count": len(errors),
                    "errors": errors,
                    "execution": execution,
                }
            )
            if errors:
                break
            if isinstance(execution, dict) and execution.get("status") == "completed":
                break

        message_payload = _request_json("GET", f"{base}/api/chat/conversations/{conversation_id}/messages", token)
        messages = message_payload.get("data") if isinstance(message_payload.get("data"), list) else []
        report["alignment"] = _evaluate_runtime_alignment(
            plan,
            details.get("distribution_execution"),
            messages,
        )
        return report
    finally:
        if not keep_conversation:
            try:
                _request_json("DELETE", f"{base}/api/chat/conversations/{conversation_id}", token)
            except (HTTPError, OSError, ValueError):
                pass


def main() -> int:
    if os.environ.get("RUN_REAL_INTERVIEW_DISTRIBUTION_E2E") != "1":
        print("Set RUN_REAL_INTERVIEW_DISTRIBUTION_E2E=1 to run real distribution E2E", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.environ.get("INTERVIEW_BOSS_BASE_URL", "http://localhost"))
    parser.add_argument("--token", default=os.environ.get("INTERVIEW_BOSS_E2E_TOKEN"))
    parser.add_argument("--job-position", default=os.environ.get("INTERVIEW_BOSS_E2E_POSITION", ""))
    parser.add_argument("--report", required=True)
    parser.add_argument("--exercise-runtime", action="store_true")
    parser.add_argument("--max-turns", type=int, default=16)
    parser.add_argument("--keep-conversation", action="store_true")
    args = parser.parse_args()
    query = f"?job_position={args.job_position}" if args.job_position else ""
    report: dict[str, Any] = {"verdict": "fail", "stats_response": None, "comparison": {}, "runtime": None, "error": None}
    try:
        payload = _request_json("GET", f"{args.base_url.rstrip('/')}/api/interview/distribution/default{query}", args.token)
        stats = _payload_data(payload)
        distribution = stats["distribution"]
        valid = set(distribution) == _CANONICAL_TYPES
        total = sum(distribution.values())
        report["stats_response"] = stats
        report["comparison"] = {"has_all_canonical_types": valid, "ratio_sum": total}
        passed = valid and abs(total - 1.0) <= 1e-6
        if args.exercise_runtime:
            if not args.token:
                raise RuntimeError("--token is required for --exercise-runtime")
            runtime = _verify_live_runtime(
                args.base_url,
                args.token,
                max_turns=args.max_turns,
                keep_conversation=args.keep_conversation,
            )
            report["runtime"] = runtime
            plan = runtime.get("plan") or {}
            passed = (
                passed
                and runtime.get("alignment", {}).get("passed") is True
                and plan.get("stats_version") == stats.get("stats_version")
                and plan.get("distribution") == stats.get("distribution")
            )
        report["verdict"] = "pass" if passed else "fail"
    except (HTTPError, KeyError, OSError, ValueError, RuntimeError) as exc:
        report["error"] = str(exc)
    Path(args.report).parent.mkdir(parents=True, exist_ok=True)
    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["verdict"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
