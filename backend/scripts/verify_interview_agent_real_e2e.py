#!/usr/bin/env python3
"""Manual real E2E verification for the interview agent.

Runs a real InterviewBoss chat conversation through the HTTP/SSE API while a
lightweight LLM candidate answers as the interviewee. This is intentionally not
a default pytest test: it consumes real LLM tokens and requires explicit opt-in
via RUN_REAL_INTERVIEW_E2E=1.
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
from pathlib import Path
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
DEFAULT_RESUME_TEXT = (
    "候选人施杰，计算机技术硕士，研究方向为 LLM 应用、Agent 和 RAG。"
    "做过政策合规审查平台、InterviewBoss 全栈项目，熟悉 FastAPI、LangGraph、"
    "Dify、Pydantic、向量检索和工具调用。"
)
DEFAULT_ABILITY_PROFILE = (
    "Agent/RAG 项目经验较强，后端工程能力较强；算法基础中等，能写常见数据结构题；"
    "回答时会给出真实项目细节，但偶尔会笼统，便于测试面试官追问能力。"
)


@dataclass
class CandidateProfile:
    name: str
    resume_text: str
    ability_profile: str
    answer_style: str = "回答自然，像真人候选人；每次 3-6 句话，不要主动暴露这是测试。"

    def to_system_prompt(self) -> str:
        return (
            f"你是正在参加技术模拟面试的候选人：{self.name}。\n\n"
            f"## 简历\n{self.resume_text.strip()}\n\n"
            f"## 能力画像\n{self.ability_profile.strip()}\n\n"
            f"## 回答风格\n{self.answer_style.strip()}\n\n"
            "规则：\n"
            "1. 只扮演候选人，不评价面试官。\n"
            "2. 如果面试官追问细节，要基于简历和能力画像回答。\n"
            "3. 遇到不会的问题可以坦诚说明，不要编造离谱经历。\n"
            "4. 如果面试官要求写代码，给出完整、简洁的代码和复杂度。"
        )


@dataclass
class CandidateLLMConfig:
    api_key: str
    base_url: str
    model: str
    timeout: int


@dataclass
class TurnResult:
    index: int
    candidate_text: str
    assistant_text: str
    events: list[dict[str, Any]]
    tool_names: list[str] = field(default_factory=list)
    retrieved_count: int = 0
    selected_question_id: int | None = None
    selected_question_text: str = ""
    question_plan_id: int | None = None
    adherence_score: float | None = None
    basis_type: str = ""
    basis_confidence: float | None = None
    internal_marker_leaked: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class InterviewReport:
    verdict: str
    turn_count: int
    tool_turn_count: int
    selected_question_count: int
    basis_count: int
    error_count: int
    leak_count: int
    judge_summary: str | None = None
    errors: list[str] = field(default_factory=list)


class CandidateAgent:
    """Small LLM actor that only knows the candidate profile and transcript."""

    def __init__(self, profile: CandidateProfile, config: CandidateLLMConfig):
        self.config = config
        self.messages: list[dict[str, str]] = [
            {"role": "system", "content": profile.to_system_prompt()}
        ]

    def respond(self, interviewer_text: str) -> str:
        self.messages.append(
            {"role": "user", "content": f"面试官：{interviewer_text.strip()}"}
        )
        reply = _call_openai_compatible_chat(
            self.config,
            self.messages,
            temperature=0.75,
            max_tokens=1200,
        )
        self.messages.append({"role": "assistant", "content": reply})
        return reply


def _read_text_or_value(value: str | None, fallback: str) -> str:
    if not value:
        return fallback
    path = Path(value)
    if path.exists() and path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return value.strip()


def _resolve_candidate_config(args: argparse.Namespace) -> CandidateLLMConfig:
    api_key = (
        args.candidate_api_key
        or os.getenv("CANDIDATE_OPENAI_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )
    base_url = (
        args.candidate_base_url
        or os.getenv("CANDIDATE_OPENAI_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    ).rstrip("/")
    model = (
        args.candidate_model
        or os.getenv("CANDIDATE_LLM_MODEL")
        or os.getenv("LLM_MODEL_NAME")
        or "gpt-4o-mini"
    )
    timeout = int(args.candidate_timeout or os.getenv("CANDIDATE_LLM_TIMEOUT") or "120")
    if not api_key:
        raise RuntimeError(
            "Candidate LLM API key missing. Set CANDIDATE_OPENAI_API_KEY or OPENAI_API_KEY."
        )
    return CandidateLLMConfig(api_key=api_key, base_url=base_url, model=model, timeout=timeout)


def _call_openai_compatible_chat(
    config: CandidateLLMConfig,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
) -> str:
    data = json.dumps(
        {
            "model": config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"{config.base_url}/chat/completions",
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=config.timeout) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    content = payload["choices"][0]["message"]["content"]
    return str(content).strip()


def _json_request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    """Create/reuse a local E2E user and issue a short-lived access token."""
    from app.core.auth import create_access_token, hash_password
    from app.db.connection import get_db_connection

    fallback_username = "__interview_agent_e2e__"
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
    return create_access_token({"user_id": user_id}, expires_delta=timedelta(minutes=45))


def _resolve_token(args: argparse.Namespace) -> str:
    if args.token:
        return args.token
    if args.username and args.password:
        return _login(args.base_url, args.username, args.password)
    return _ensure_internal_e2e_token(args.internal_username)


def _create_conversation(
    base_url: str,
    token: str,
    *,
    title_prefix: str,
    resume_text: str,
) -> tuple[str, str]:
    title = f"{title_prefix}-{int(time.time())}-{uuid4().hex[:8]}"
    response = _json_request(
        "POST",
        f"{base_url}/api/chat/conversations",
        token=token,
        body={"mode": "free_practice", "title": title, "resume_text": resume_text},
    )
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    conversation_id = response.get("id") or response.get("conversation_id") or data.get("id")
    opening = data.get("opening_message") or response.get("opening_message") or ""
    if not conversation_id:
        raise RuntimeError(f"create conversation response missing id: {response}")
    return str(conversation_id), str(opening)


def _delete_conversation(base_url: str, token: str, conversation_id: str) -> None:
    _json_request("DELETE", f"{base_url}/api/chat/conversations/{conversation_id}", token=token)


def _iter_sse_events(
    base_url: str,
    token: str,
    conversation_id: str,
    content: str,
    model: str | None,
) -> list[dict[str, Any]]:
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
        with urllib.request.urlopen(req, timeout=300) as resp:
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


def _extract_turn_result(
    index: int,
    candidate_text: str,
    events: list[dict[str, Any]],
) -> TurnResult:
    chunks: list[str] = []
    result = TurnResult(index=index, candidate_text=candidate_text, assistant_text="", events=events)
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
        elif event_type == "selected_question":
            question = event.get("question")
            if isinstance(question, dict):
                result.selected_question_id = question.get("id")
                result.selected_question_text = str(question.get("question") or "")
        elif event_type == "question_plan":
            result.question_plan_id = event.get("question_id")
            adherence = event.get("adherence") if isinstance(event.get("adherence"), dict) else {}
            score = adherence.get("score")
            if isinstance(score, (int, float)):
                result.adherence_score = float(score)
        elif event_type == "basis":
            result.basis_type = str(event.get("basis_type") or "")
            confidence = event.get("basis_confidence")
            if isinstance(confidence, (int, float)):
                result.basis_confidence = float(confidence)
        elif event_type == "error":
            result.errors.append(str(event.get("message") or event))
    result.assistant_text = "".join(chunks)
    result.internal_marker_leaked = any(marker in result.assistant_text for marker in INTERNAL_MARKERS)
    return result


def _build_interview_report(
    turns: list[TurnResult],
    judge_summary: str | None,
) -> InterviewReport:
    errors: list[str] = []
    if not turns:
        errors.append("no turns collected")
    if any(not turn.assistant_text.strip() for turn in turns):
        errors.append("one or more turns are missing assistant text")
    if not any(turn.tool_names or turn.selected_question_id for turn in turns):
        errors.append("no observable tool use or selected question across the interview")

    error_count = sum(1 for turn in turns if turn.errors)
    leak_count = sum(1 for turn in turns if turn.internal_marker_leaked)
    if error_count:
        errors.append(f"{error_count} turn(s) had SSE errors")
    if leak_count:
        errors.append(f"{leak_count} turn(s) leaked internal markers")

    verdict = "PASS" if not errors else "FAIL"
    return InterviewReport(
        verdict=verdict,
        turn_count=len(turns),
        tool_turn_count=sum(1 for turn in turns if turn.tool_names),
        selected_question_count=sum(1 for turn in turns if turn.selected_question_id),
        basis_count=sum(1 for turn in turns if turn.basis_type),
        error_count=error_count,
        leak_count=leak_count,
        judge_summary=judge_summary,
        errors=errors,
    )


def _judge_with_llm(
    config: CandidateLLMConfig,
    turns: list[TurnResult],
) -> str:
    transcript = []
    for turn in turns:
        transcript.append(f"候选人：{turn.candidate_text}")
        transcript.append(f"面试官：{turn.assistant_text}")
    messages = [
        {
            "role": "system",
            "content": (
                "你是模拟面试质量评估员。只评估面试官，不评估候选人。"
                "输出 200 字以内中文总结，指出追问深度、问题覆盖、节奏和明显风险。"
            ),
        },
        {"role": "user", "content": "\n".join(transcript)},
    ]
    return _call_openai_compatible_chat(
        config,
        messages,
        temperature=0.2,
        max_tokens=900,
    )


def _run_interview(args: argparse.Namespace) -> tuple[list[TurnResult], str | None, str]:
    token = _resolve_token(args)
    resume_text = _read_text_or_value(args.resume, DEFAULT_RESUME_TEXT)
    ability_profile = _read_text_or_value(args.ability, DEFAULT_ABILITY_PROFILE)
    profile = CandidateProfile(
        name=args.candidate_name,
        resume_text=resume_text,
        ability_profile=ability_profile,
        answer_style=args.answer_style,
    )
    candidate_config = _resolve_candidate_config(args)
    candidate = CandidateAgent(profile, candidate_config)
    conversation_id, opening = _create_conversation(
        args.base_url,
        token,
        title_prefix="real-e2e-interview-agent",
        resume_text=resume_text,
    )

    turns: list[TurnResult] = []
    try:
        interviewer_text = opening or "你好，我们开始今天的模拟面试，请先做一个简单自我介绍。"
        for index in range(1, args.turns + 1):
            candidate_text = candidate.respond(interviewer_text)
            events = _iter_sse_events(
                args.base_url,
                token,
                conversation_id,
                candidate_text,
                args.interviewer_model,
            )
            turn = _extract_turn_result(index, candidate_text, events)
            turns.append(turn)
            interviewer_text = turn.assistant_text
            if any(keyword in interviewer_text for keyword in ("模拟面试就到这里", "面试结束", "感谢你的时间")):
                break
        judge_summary = _judge_with_llm(candidate_config, turns) if args.judge_with_llm else None
        return turns, judge_summary, conversation_id
    finally:
        if args.keep_conversation:
            print(f"\nConversation kept: {conversation_id}")
        else:
            try:
                _delete_conversation(args.base_url, token, conversation_id)
            except Exception as exc:
                print(f"Warning: failed to delete conversation {conversation_id}: {exc}", file=sys.stderr)


def _print_report(turns: list[TurnResult], report: InterviewReport) -> None:
    print("========== Interview Agent Real E2E Report ==========")
    for turn in turns:
        print(f"\nTurn {turn.index}")
        print(f"- tools: {', '.join(turn.tool_names) or '-'}")
        print(f"- retrieved_count: {turn.retrieved_count}")
        print(f"- selected_question: {turn.selected_question_id or '-'}")
        print(f"- question_plan: {turn.question_plan_id or '-'}")
        print(f"- basis: {turn.basis_type or '-'}")
        print(f"- internal_marker_leaked: {turn.internal_marker_leaked}")
        print(f"- candidate_preview: {turn.candidate_text[:120].replace(chr(10), ' ')}")
        print(f"- interviewer_preview: {turn.assistant_text[:160].replace(chr(10), ' ')}")
        if turn.errors:
            print(f"- errors: {'; '.join(turn.errors)}")

    print("\nSummary:")
    print(f"- verdict: {report.verdict}")
    print(f"- turns: {report.turn_count}")
    print(f"- tool_turns: {report.tool_turn_count}")
    print(f"- selected_question_count: {report.selected_question_count}")
    print(f"- basis_count: {report.basis_count}")
    print(f"- error_count: {report.error_count}")
    print(f"- leak_count: {report.leak_count}")
    if report.judge_summary:
        print(f"- judge_summary: {report.judge_summary}")
    if report.errors:
        print(f"- errors: {'; '.join(report.errors)}")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify the real interview agent using a lightweight LLM candidate."
    )
    parser.add_argument("--base-url", default=os.getenv("E2E_BASE_URL", "http://localhost:8000"))
    parser.add_argument("--username", default=os.getenv("E2E_USERNAME"))
    parser.add_argument("--password", default=os.getenv("E2E_PASSWORD"))
    parser.add_argument("--token", default=os.getenv("E2E_ACCESS_TOKEN"))
    parser.add_argument("--internal-username", default=os.getenv("E2E_INTERNAL_USERNAME", "sj"))
    parser.add_argument("--interviewer-model", default=os.getenv("E2E_MODEL"))
    parser.add_argument("--turns", type=int, default=int(os.getenv("E2E_INTERVIEW_TURNS", "8")))
    parser.add_argument("--candidate-name", default=os.getenv("CANDIDATE_NAME", "施杰"))
    parser.add_argument("--resume", default=os.getenv("CANDIDATE_RESUME"))
    parser.add_argument("--ability", default=os.getenv("CANDIDATE_ABILITY"))
    parser.add_argument(
        "--answer-style",
        default=os.getenv(
            "CANDIDATE_ANSWER_STYLE",
            "回答自然，像真人候选人；每次 3-6 句话，偶尔可以略笼统。",
        ),
    )
    parser.add_argument("--candidate-api-key", default=os.getenv("CANDIDATE_OPENAI_API_KEY"))
    parser.add_argument("--candidate-base-url", default=os.getenv("CANDIDATE_OPENAI_BASE_URL"))
    parser.add_argument("--candidate-model", default=os.getenv("CANDIDATE_LLM_MODEL"))
    parser.add_argument("--candidate-timeout", type=int, default=None)
    parser.add_argument("--judge-with-llm", action="store_true")
    parser.add_argument("--keep-conversation", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if os.getenv("RUN_REAL_INTERVIEW_E2E") != "1":
        print("Refusing to run real interview E2E. Set RUN_REAL_INTERVIEW_E2E=1.", file=sys.stderr)
        return 2

    try:
        turns, judge_summary, _conversation_id = _run_interview(args)
        report = _build_interview_report(turns, judge_summary)
        _print_report(turns, report)
        return 0 if report.verdict == "PASS" else 1
    except Exception as exc:
        print(f"Real interview E2E failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
