#!/usr/bin/env python3
"""Manual real E2E verification for chat tool-calling stability.

Runs against the real backend HTTP/SSE API and real LLM configuration.
This is intentionally not a pytest test: it may consume real LLM tokens and
requires explicit opt-in via RUN_REAL_CHAT_E2E=1.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from uuid import uuid4


INTERNAL_MARKERS = (
    "[BASIS]",
    "<next_question_plan>",
    "search_questions",
    "draw_questions",
    "project-deep-dive",
    "algorithm-coding",
)
ALGORITHM_TERMS = ("算法", "代码", "手撕", "数据结构", "链表", "排序", "二分", "LRU", "lru")


@dataclass
class CaseResult:
    name: str
    user_message: str
    events: list[dict[str, Any]] = field(default_factory=list)
    assistant_text: str = ""
    tool_names: list[str] = field(default_factory=list)
    retrieved_count: int = 0
    selected_question_id: int | None = None
    selected_question_text: str = ""
    question_plan_id: int | None = None
    adherence_score: float | None = None
    repaired: bool = False
    fallback_used: bool = False
    internal_marker_leaked: bool = False
    errors: list[str] = field(default_factory=list)
    verdict: str = "FAIL"


def _json_request(method: str, url: str, *, token: str | None = None, body: dict[str, Any] | None = None) -> dict[str, Any]:
    data = json.dumps(body or {}).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        headers["X-Requested-With"] = "XMLHttpRequest"
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code} {method} {url}: {detail}") from exc


def _login(base_url: str, username: str, password: str) -> str:
    response = _json_request(
        "POST",
        f"{base_url}/api/auth/login",
        body={"username": username, "password": password, "remember_me": False},
    )
    token = response.get("access_token") or response.get("token")
    if not token:
        raise RuntimeError("login response did not contain access_token/token")
    return str(token)


def _ensure_internal_e2e_token(internal_username: str) -> str:
    """Create/reuse a local E2E user and issue a short-lived access token.

    Prefer an existing username such as sj so the request uses that user's
    saved LLM config. If it does not exist, create a dedicated E2E user.
    """
    from app.core.auth import create_access_token, hash_password
    from app.db.connection import get_db_connection

    fallback_username = "__chat_tools_e2e__"
    with get_db_connection() as conn:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (internal_username,)).fetchone()
        if not row:
            row = conn.execute("SELECT id FROM users WHERE username = ?", (fallback_username,)).fetchone()
        if row:
            user_id = int(row["id"] if hasattr(row, "keys") else row[0])
        else:
            password_hash = hash_password(uuid4().hex)
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, bank_mode) VALUES (?, ?, ?, ?)",
                (fallback_username, password_hash, 0, "public"),
            )
            conn.commit()
            user_id = int(cursor.lastrowid)
    return create_access_token({"user_id": user_id}, expires_delta=timedelta(minutes=30))


def _resolve_token(args: argparse.Namespace) -> str:
    if args.token:
        return args.token
    if args.username and args.password:
        return _login(args.base_url, args.username, args.password)
    return _ensure_internal_e2e_token(args.internal_username)


def _create_conversation(base_url: str, token: str) -> str:
    title = f"real-e2e-chat-tools-{int(time.time())}-{uuid4().hex[:8]}"
    response = _json_request(
        "POST",
        f"{base_url}/api/chat/conversations",
        token=token,
        body={"mode": "free_practice", "title": title},
    )
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    conversation_id = response.get("id") or response.get("conversation_id") or data.get("id")
    if not conversation_id:
        raise RuntimeError(f"create conversation response missing id: {response}")
    return str(conversation_id)


def _delete_conversation(base_url: str, token: str, conversation_id: str) -> None:
    _json_request("DELETE", f"{base_url}/api/chat/conversations/{conversation_id}", token=token)


def _iter_sse_events(base_url: str, token: str, conversation_id: str, content: str, model: str | None) -> list[dict[str, Any]]:
    body: dict[str, Any] = {"content": content}
    if model:
        body["model"] = model
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{base_url}/api/chat/conversations/{conversation_id}/messages",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "text/event-stream",
        },
    )
    events: list[dict[str, Any]] = []
    try:
        with urllib.request.urlopen(req, timeout=240) as resp:
            buffer = ""
            while True:
                chunk = resp.read(4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="replace")
                while "\n\n" in buffer:
                    raw_event, buffer = buffer.split("\n\n", 1)
                    parsed = _parse_sse_event(raw_event)
                    if parsed is not None:
                        events.append(parsed)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"HTTP {exc.code} send message: {detail}") from exc
    return events


def _parse_sse_event(raw_event: str) -> dict[str, Any] | None:
    data_lines = []
    for line in raw_event.splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if not data_lines:
        return None
    data = "\n".join(data_lines)
    if data == "[DONE]":
        return {"type": "done"}
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError:
        return {"type": "raw", "content": data}
    return parsed if isinstance(parsed, dict) else {"type": "raw", "content": parsed}


def _extract_case_result(name: str, user_message: str, events: list[dict[str, Any]]) -> CaseResult:
    result = CaseResult(name=name, user_message=user_message, events=events)
    chunks = []
    metadata = {}
    for event in events:
        event_type = event.get("type")
        if event_type == "chunk":
            chunks.append(str(event.get("content") or ""))
        elif event_type == "step" and event.get("step") in {"search_questions", "draw_questions"}:
            tool = str(event.get("step"))
            if tool not in result.tool_names:
                result.tool_names.append(tool)
        elif event_type == "retrieved":
            questions = event.get("questions") if isinstance(event.get("questions"), list) else []
            result.retrieved_count = max(result.retrieved_count, len(questions))
        elif event_type == "error":
            result.errors.append(str(event.get("message") or event))
        elif event_type == "done":
            metadata = event.get("metadata") if isinstance(event.get("metadata"), dict) else metadata

    result.assistant_text = "".join(chunks)
    selected = metadata.get("selected_question") if isinstance(metadata.get("selected_question"), dict) else None
    if selected:
        result.selected_question_id = selected.get("id")
        result.selected_question_text = str(selected.get("question") or "")
    plan = metadata.get("question_plan") if isinstance(metadata.get("question_plan"), dict) else None
    if plan:
        result.question_plan_id = plan.get("question_id")
        adherence = plan.get("adherence") if isinstance(plan.get("adherence"), dict) else {}
        score = adherence.get("score")
        if isinstance(score, (int, float)):
            result.adherence_score = float(score)
        result.repaired = bool(plan.get("repaired", False))
        result.fallback_used = bool(plan.get("fallback_used", False))

    result.internal_marker_leaked = any(marker in result.assistant_text for marker in INTERNAL_MARKERS)
    result.verdict = _verdict_for_case(result)
    return result


def _verdict_for_case(result: CaseResult) -> str:
    if result.errors:
        return "FAIL"
    if not any(event.get("type") == "done" for event in result.events):
        result.errors.append("missing done event")
        return "FAIL"
    if not result.assistant_text.strip():
        result.errors.append("missing assistant text")
        return "FAIL"
    if result.internal_marker_leaked:
        result.errors.append("internal marker leaked")
        return "FAIL"

    has_grounding = bool(
        result.tool_names
        or result.retrieved_count
        or result.selected_question_id
        or result.question_plan_id
    )
    if result.name in {"practice_request_rag", "algorithm_coding", "complete_answer_new_question"} and not has_grounding:
        result.errors.append("expected tool/retrieval/selected question/question plan signal")
        return "FAIL"
    if result.name == "algorithm_coding" and result.selected_question_text:
        if not any(term in result.selected_question_text for term in ALGORITHM_TERMS):
            result.errors.append("selected question is not algorithm related")
            return "FAIL"
    if result.name == "follow_up_negative" and "draw_questions" in result.tool_names:
        result.errors.append("follow-up should not call draw_questions")
        return "FAIL"
    return "PASS"


def _print_report(results: list[CaseResult]) -> None:
    print("========== Chat Tools Real E2E Report ==========")
    for result in results:
        print(f"\nCase: {result.name}")
        print(f"- verdict: {result.verdict}")
        print(f"- tool_called: {'yes' if result.tool_names else 'no'} ({', '.join(result.tool_names) or '-'})")
        print(f"- retrieved_count: {result.retrieved_count}")
        print(f"- selected_question: {result.selected_question_id or '-'}")
        print(f"- question_plan: {result.question_plan_id or '-'}")
        print(f"- adherence_score: {result.adherence_score if result.adherence_score is not None else '-'}")
        print(f"- repaired: {result.repaired}")
        print(f"- fallback_used: {result.fallback_used}")
        print(f"- internal_marker_leaked: {result.internal_marker_leaked}")
        print(f"- assistant_preview: {result.assistant_text[:160].replace(chr(10), ' ')}")
        if result.errors:
            print(f"- errors: {'; '.join(result.errors)}")

    total = len(results)
    passed = sum(1 for result in results if result.verdict == "PASS")
    tool_rate = sum(1 for result in results if result.tool_names) / max(total, 1)
    selected_rate = sum(1 for result in results if result.selected_question_id) / max(total, 1)
    plan_rate = sum(1 for result in results if result.question_plan_id) / max(total, 1)
    print("\nSummary:")
    print(f"- cases: {total}")
    print(f"- passed: {passed}")
    print(f"- failed: {total - passed}")
    print(f"- tool_call_rate: {tool_rate:.0%}")
    print(f"- selected_question_rate: {selected_rate:.0%}")
    print(f"- question_plan_rate: {plan_rate:.0%}")
    print(f"- repair_count: {sum(1 for result in results if result.repaired)}")
    print(f"- fallback_count: {sum(1 for result in results if result.fallback_used)}")
    print(f"- leak_count: {sum(1 for result in results if result.internal_marker_leaked)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify real chat tool-calling stability via HTTP/SSE.")
    parser.add_argument("--base-url", default=os.getenv("E2E_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--username", default=os.getenv("E2E_USERNAME"))
    parser.add_argument("--password", default=os.getenv("E2E_PASSWORD"))
    parser.add_argument("--token", default=os.getenv("E2E_ACCESS_TOKEN"))
    parser.add_argument("--internal-username", default=os.getenv("E2E_INTERNAL_USERNAME", "sj"))
    parser.add_argument("--model", default=os.getenv("E2E_MODEL"))
    parser.add_argument("--keep-conversation", action="store_true")
    args = parser.parse_args()

    if os.getenv("RUN_REAL_CHAT_E2E") != "1":
        print("Refusing to run real LLM E2E. Set RUN_REAL_CHAT_E2E=1.", file=sys.stderr)
        return 2

    token = _resolve_token(args)
    conversation_id = _create_conversation(args.base_url, token)
    cases = [
        ("practice_request_rag", "我想练 RAG 系统设计，来一道题"),
        ("algorithm_coding", "切到手撕代码，来一道中等难度的算法题"),
        (
            "complete_answer_new_question",
            "我在项目里做了一个 RAG 问答系统，流程是先把文档切块，用 bge 向量化，检索后再用 reranker 排序，最后把 top chunks 拼到 prompt 里生成答案。我还做了召回率和答案命中率的评估。",
        ),
        ("follow_up_negative", "刚才那个问题能不能再解释一下？"),
    ]

    results: list[CaseResult] = []
    try:
        for name, message in cases:
            events = _iter_sse_events(args.base_url, token, conversation_id, message, args.model)
            results.append(_extract_case_result(name, message, events))
        _print_report(results)
        return 0 if all(result.verdict == "PASS" for result in results) else 1
    finally:
        if args.keep_conversation:
            print(f"\nConversation kept: {conversation_id}")
        else:
            try:
                _delete_conversation(args.base_url, token, conversation_id)
            except Exception as exc:
                print(f"Warning: failed to delete conversation {conversation_id}: {exc}", file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
