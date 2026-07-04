#!/usr/bin/env python3
"""Manual evaluation framework for the InterviewBoss interview agent.

This script runs real HTTP/SSE conversations against a running backend while an
LLM-powered candidate actor answers as the interviewee. It is intentionally a
manual tool: it can consume real tokens, writes reports under backend/data, and
is not meant for CI.
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from app.agents.shared.skills.builder import build_skill_prompt
from app.agents.shared.skills.resolver import get_agent_skill_registry


DEFAULT_BASE_URL = "http://localhost:8000"
DEFAULT_OUTPUT_DIR = Path("backend/data/evaluations")
SUMMARY_SIGNALS = ("面试总结", "整体表现", "模拟面试就到这里", "面试到这里结束")
CORRECTION_OUTPUT_SIGNALS = (
    "不是生成式",
    "判别式",
    "encoder",
    "不支持事务",
    "不支持ACID",
    "向量索引库",
    "Least Recently Used",
    "最近最少使用",
)


@dataclass(frozen=True)
class CandidateLLMConfig:
    api_key: str
    base_url: str
    model: str
    timeout: int


@dataclass(frozen=True)
class Scenario:
    scenario_id: str
    mode: str
    difficulty: str
    max_turns: int
    persona: dict[str, str]
    active_skills: list[str]
    scoring: dict[str, dict[str, Any]]
    extra_args: dict[str, Any] | None = None
    early_exit_check: Callable[[list[dict[str, Any]]], bool] | None = None


MID_LEVEL_PERSONA = {
    "model": "mimo-v2.5",
    "resume_text": (
        "211 硕士，2 年 RAG + Agent 开发经验。做过双路召回 + rerank 的 RAG 系统，"
        "用 LangChain/LangGraph 搭建过 Agent，Faiss 做向量检索，Redis 做缓存。"
    ),
    "ability_profile": """
- RAG 系统：熟练，做过双路召回 + rerank，了解 embedding 模型选型
- Agent 框架：熟悉 LangChain/LangGraph，了解 MCP 协议
- 向量数据库：用过 Faiss，了解 HNSW 原理，知道 IVF
- 数据库：MySQL 基础扎实（B+树、索引），Redis 常用（缓存、分布式锁）
- 算法：中等水平，常见题型（LRU、排序、二叉树）能做
- 系统设计：能做中等复杂度的设计
""",
    "opening": (
        "大家好，我叫张明，211硕士毕业，2年RAG和Agent开发经验。最近一份工作做了一个"
        "企业级RAG系统，用双路召回加rerank提升检索质量，用LangGraph搭建了多Agent协作框架。"
    ),
}

SENIOR_PERSONA = {
    "model": "mimo-v2.5",
    "resume_text": (
        "985 硕士，4 年后端 + 2 年 Agent 开发经验。从零搭建过 MCP 工具平台，"
        "对分布式系统（限流、熔断、幂等）有深入理解，发表过 CCF-B 论文。"
    ),
    "ability_profile": """
- Agent 平台：深入，从零搭建过 MCP Server + 工具市场
- 分布式系统：深入，限流（令牌桶/滑动窗口）、熔断、幂等重试
- 向量检索：深入，HNSW 构建原理、pgvector vs Faiss trade-off
- 数据库：深入，B+树叶分裂、聚簇索引、主键设计
- 算法：较强，能写 LRU Cache、滑动窗口、图搜索
- 系统设计：能做高并发场景设计（SSE 架构、Agent 编排）
""",
    "opening": (
        "大家好，我叫李强，985硕士，4年后端加2年Agent开发。最近在做MCP工具平台，"
        "从协议设计到Server实现到工具市场，全链路都参与过。之前还做过分布式限流和熔断的基础设施。"
    ),
}


def _check_ratio(numerator: int, denominator: int, threshold: float) -> bool:
    return denominator > 0 and numerator / denominator >= threshold


def _check_error_corrected(metrics: dict[str, Any], error_type: str) -> bool:
    correction_keywords = {
        "bert": ("encoder", "判别式", "不是生成式"),
        "faiss": ("不支持事务", "不支持ACID", "向量索引库"),
        "lru": ("Least Recently Used", "最近最少使用"),
    }
    keywords = correction_keywords.get(error_type, ())
    recent_assistant_texts = [
        str(turn.get("assistant") or "") for turn in metrics.get("recent_turns", [])
    ]
    return any(keyword in text for text in recent_assistant_texts for keyword in keywords)


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

END_POLICY_SCORING = {
    "early_close_refused": {
        "description": "过早收尾被拒绝",
        "check": lambda m: bool(m.get("early_close_refused", False)),
    },
    "proper_close_with_summary": {
        "description": "覆盖充分后给出结构化总结",
        "check": lambda m: bool(m.get("has_summary", False)),
    },
    "insufficient_evidence_noted": {
        "description": "证据不足被诚实标注",
        "check": lambda m: bool(m.get("has_insufficient_evidence_marker", False)),
    },
    "counter_question_answered": {
        "description": "候选人反问被回答",
        "check": lambda m: bool(m.get("counter_question_answered", False)),
    },
}


def _candidate_asks_to_end(turns: list[dict[str, Any]]) -> bool:
    if not turns:
        return False
    last_user = str(turns[-1].get("user") or "")
    return any(sig in last_user for sig in ("收尾", "结束", "不聊了", "就到这里", "想请教几个问题就收尾"))


def _interviewer_forces_close(turns: list[dict[str, Any]]) -> bool:
    if not turns:
        return False
    last_assistant = str(turns[-1].get("assistant") or "")
    return any(sig in last_assistant for sig in SUMMARY_SIGNALS)


SCENARIOS = {
    "long_session_mid": Scenario(
        scenario_id="long_session_mid",
        mode="free_practice",
        difficulty="mid",
        max_turns=16,
        persona=MID_LEVEL_PERSONA,
        active_skills=[
            "candidate-rhythm",
            "project-storytelling",
            "knowledge-answer",
            "coding-answer",
        ],
        scoring=LONG_SESSION_SCORING,
    ),
    "long_session_senior": Scenario(
        scenario_id="long_session_senior",
        mode="free_practice",
        difficulty="senior",
        max_turns=20,
        persona=SENIOR_PERSONA,
        active_skills=[
            "candidate-rhythm",
            "project-storytelling",
            "knowledge-answer",
            "coding-answer",
        ],
        scoring=LONG_SESSION_SCORING,
    ),
    "long_session_jd": Scenario(
        scenario_id="long_session_jd",
        mode="jd_resume",
        difficulty="mid",
        max_turns=16,
        persona=MID_LEVEL_PERSONA,
        active_skills=[
            "candidate-rhythm",
            "project-storytelling",
            "knowledge-answer",
            "coding-answer",
        ],
        scoring=LONG_SESSION_SCORING,
        extra_args={"jd_id": None},
    ),
    "error_correction": Scenario(
        scenario_id="error_correction",
        mode="free_practice",
        difficulty="mid",
        max_turns=8,
        persona=MID_LEVEL_PERSONA,
        active_skills=[
            "candidate-rhythm",
            "error-injection",
            "project-storytelling",
            "knowledge-answer",
        ],
        scoring=ERROR_CORRECTION_SCORING,
    ),
    "early_close_guard": Scenario(
        scenario_id="early_close_guard",
        mode="free_practice",
        difficulty="mid",
        max_turns=5,
        persona=MID_LEVEL_PERSONA,
        active_skills=["candidate-rhythm", "stall-and-clarify"],
        scoring=END_POLICY_SCORING,
        early_exit_check=_candidate_asks_to_end,
    ),
    "proper_end": Scenario(
        scenario_id="proper_end",
        mode="free_practice",
        difficulty="senior",
        max_turns=10,
        persona=SENIOR_PERSONA,
        active_skills=[
            "candidate-rhythm",
            "project-storytelling",
            "knowledge-answer",
            "coding-answer",
        ],
        scoring=END_POLICY_SCORING,
    ),
    "insufficient_evidence": Scenario(
        scenario_id="insufficient_evidence",
        mode="free_practice",
        difficulty="mid",
        max_turns=5,
        persona=MID_LEVEL_PERSONA,
        active_skills=["candidate-rhythm", "stall-and-clarify"],
        scoring=END_POLICY_SCORING,
        early_exit_check=_interviewer_forces_close,
    ),
    "counter_question": Scenario(
        scenario_id="counter_question",
        mode="free_practice",
        difficulty="senior",
        max_turns=6,
        persona=SENIOR_PERSONA,
        active_skills=["candidate-rhythm", "project-storytelling", "knowledge-answer"],
        scoring=END_POLICY_SCORING,
    ),
}


class SmartCandidateAgent:
    """LLM actor guided by candidate-specific Agent Skills."""

    def __init__(
        self,
        persona: dict[str, str],
        active_skills: list[str],
        config: CandidateLLMConfig,
    ) -> None:
        self.persona = persona
        self.active_skills = active_skills
        self.config = config
        self.messages: list[dict[str, str]] = []
        self._build_system_prompt()

    def _build_system_prompt(self) -> None:
        registry = get_agent_skill_registry("candidate")
        skill_prompt = build_skill_prompt(registry, self.active_skills)
        system = f"""你是一个正在参加技术面试的候选人。

## 你的背景
{self.persona["resume_text"].strip()}

## 你的能力画像
{self.persona["ability_profile"].strip()}

{skill_prompt}
"""
        self.messages = [{"role": "system", "content": system.strip()}]

    def respond(self, interviewer_message: str) -> str:
        self.messages.append({"role": "user", "content": interviewer_message})
        reply = _call_openai_compatible_chat(
            self.config,
            self.messages,
            temperature=0.7,
            max_tokens=1400,
        )
        self.messages.append({"role": "assistant", "content": reply})
        return reply


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
        or os.getenv("CANDIDATE_LLM_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    ).rstrip("/")
    model = (
        args.candidate_model
        or os.getenv("CANDIDATE_LLM_MODEL")
        or os.getenv("LLM_MODEL_NAME")
        or "mimo-v2.5"
    )
    timeout = int(args.candidate_timeout or os.getenv("CANDIDATE_LLM_TIMEOUT") or "120")
    if not api_key:
        raise RuntimeError(
            "Candidate LLM API key missing. Set CANDIDATE_OPENAI_API_KEY or OPENAI_API_KEY."
        )
    return CandidateLLMConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
        timeout=timeout,
    )


def _call_openai_compatible_chat(
    config: CandidateLLMConfig,
    messages: list[dict[str, str]],
    *,
    temperature: float,
    max_tokens: int,
) -> str:
    body = json.dumps(
        {
            "model": config.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        f"{config.base_url}/chat/completions",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(request, timeout=config.timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return str(payload["choices"][0]["message"]["content"]).strip()


def _json_request(
    method: str,
    url: str,
    *,
    token: str | None = None,
    body: dict[str, Any] | None = None,
    timeout: int = 120,
) -> dict[str, Any]:
    data = json.dumps(body or {}).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        headers["X-Requested-With"] = "XMLHttpRequest"
    if token:
        headers["Authorization"] = f"Bearer {token}"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
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
    from app.core.auth import create_access_token, hash_password
    from app.db.connection import get_db_connection

    fallback_username = "__interview_eval_e2e__"
    with get_db_connection() as conn:
        row = conn.execute("SELECT id FROM users WHERE username = ?", (internal_username,)).fetchone()
        if not row:
            row = conn.execute("SELECT id FROM users WHERE username = ?", (fallback_username,)).fetchone()
        if row:
            user_id = int(row["id"] if hasattr(row, "keys") else row[0])
        else:
            cursor = conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, bank_mode) VALUES (?, ?, ?, ?)",
                (fallback_username, hash_password(uuid4().hex), 0, "public"),
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


def create_conversation(
    base_url: str,
    token: str,
    scenario: Scenario,
) -> tuple[str, str]:
    title = f"eval-{scenario.scenario_id}-{int(time.time())}-{uuid4().hex[:8]}"
    body = {
        "mode": scenario.mode,
        "title": title,
        "resume_text": scenario.persona["resume_text"],
        "difficulty": scenario.difficulty,
    }
    extra_args = scenario.extra_args or {}
    if extra_args.get("jd_id") is not None:
        body["jd_id"] = extra_args["jd_id"]

    response = _json_request(
        "POST",
        f"{base_url}/api/chat/conversations",
        token=token,
        body=body,
    )
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    conversation_id = response.get("id") or response.get("conversation_id") or data.get("id")
    opening = data.get("opening_message") or response.get("opening_message") or ""
    if not conversation_id:
        raise RuntimeError(f"create conversation response missing id: {response}")
    return str(conversation_id), str(opening)


def _delete_conversation(base_url: str, token: str, conversation_id: str) -> None:
    _json_request("DELETE", f"{base_url}/api/chat/conversations/{conversation_id}", token=token)


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


def _iter_sse_events(
    base_url: str,
    token: str,
    conversation_id: str,
    content: str,
    model: str | None,
    *,
    timeout: int,
) -> list[dict[str, Any]]:
    body: dict[str, Any] = {"content": content}
    if model:
        body["model"] = model
    request = urllib.request.Request(
        f"{base_url}/api/chat/conversations/{conversation_id}/messages",
        data=json.dumps(body).encode("utf-8"),
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
        with urllib.request.urlopen(request, timeout=timeout) as response:
            buffer = ""
            while True:
                chunk = response.read(4096)
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


def _assistant_text_from_events(events: list[dict[str, Any]]) -> str:
    chunks = []
    for event in events:
        if event.get("type") == "chunk":
            chunks.append(str(event.get("content") or ""))
    return "".join(chunks)


def _event_data(event: dict[str, Any]) -> dict[str, Any]:
    data = event.get("data")
    return data if isinstance(data, dict) else {}


def _event_tool_name(event: dict[str, Any]) -> str | None:
    data = _event_data(event)
    if event.get("type") == "tool_step":
        return str(data.get("tool") or event.get("tool") or "")
    if event.get("type") == "step":
        step = str(event.get("step") or "")
        if step in {"search_questions", "draw_questions", "select_question", "load_skill"}:
            return step
    return None


def _ids_from_object(value: Any) -> list[int]:
    ids: list[int] = []
    if isinstance(value, int):
        ids.append(value)
    elif isinstance(value, str) and value.isdigit():
        ids.append(int(value))
    elif isinstance(value, dict):
        for key in ("id", "question_id"):
            ids.extend(_ids_from_object(value.get(key)))
        for key in ("ids", "question_ids", "questions", "items"):
            ids.extend(_ids_from_object(value.get(key)))
    elif isinstance(value, list):
        for item in value:
            ids.extend(_ids_from_object(item))
    return ids


def _candidate_ids_for_turn(turn: dict[str, Any]) -> list[int]:
    ids: list[int] = []
    for event in turn.get("events", []):
        event_type = event.get("type")
        data = _event_data(event)
        if event_type in {"retrieved", "candidates", "candidate_questions"}:
            ids.extend(_ids_from_object(event.get("questions")))
            ids.extend(_ids_from_object(data))
        elif event_type in {"tool_result", "tool_step"}:
            ids.extend(_ids_from_object(data.get("items")))
            ids.extend(_ids_from_object(data.get("candidate_questions")))
    return ids


def find_cross_turn_duplicates(turns: list[dict[str, Any]]) -> list[int]:
    seen: set[int] = set()
    duplicates: list[int] = []
    for turn in turns:
        current = set(_candidate_ids_for_turn(turn))
        for question_id in sorted(current):
            if question_id in seen and question_id not in duplicates:
                duplicates.append(question_id)
        seen.update(current)
    return duplicates


def query_asked_questions_db(conv_id: str) -> list[int]:
    db_path = os.getenv("DB_PATH", "backend/data/interview-boss.db")
    if not Path(db_path).exists():
        return []
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT question_id FROM interview_asked_questions WHERE conversation_id = ?",
            (conv_id,),
        ).fetchall()
        return [int(row[0]) for row in rows]
    finally:
        conn.close()


def extract_metrics(turns: list[dict[str, Any]], conv_id: str) -> dict[str, Any]:
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
    }


def _detect_early_close_refused(turns: list[dict[str, Any]]) -> bool:
    for turn in turns:
        user_text = str(turn.get("user") or "")
        assistant_text = str(turn.get("assistant") or "")
        user_asks_close = any(signal in user_text for signal in ("结束", "收尾", "就到这里"))
        assistant_continues = any(signal in assistant_text for signal in ("还需要", "再看", "继续", "补充"))
        if user_asks_close and assistant_continues:
            return True
    return False


def _detect_counter_question_answered(turns: list[dict[str, Any]]) -> bool:
    for turn in turns:
        user_text = str(turn.get("user") or "")
        assistant_text = str(turn.get("assistant") or "")
        if any(signal in user_text for signal in ("想问", "请问", "反问")) and assistant_text.strip():
            return True
    return False


def score_scenario(scenario: Scenario, metrics: dict[str, Any]) -> dict[str, Any]:
    items: dict[str, dict[str, Any]] = {}
    total_weight = 0.0
    passed_weight = 0.0

    for key, config in scenario.scoring.items():
        weight = float(config.get("weight", 1.0))
        total_weight += weight
        try:
            passed = bool(config["check"](metrics))
            error = None
        except Exception as exc:  # pragma: no cover - defensive report detail
            passed = False
            error = str(exc)
        if passed:
            passed_weight += weight
        items[key] = {
            "passed": passed,
            "weight": weight,
            "description": config.get("description", key),
            "error": error,
        }

    return {
        "passed": passed_weight == total_weight,
        "passed_weight": passed_weight,
        "total_weight": total_weight,
        "ratio": passed_weight / total_weight if total_weight else 0.0,
        "items": items,
    }


def send_message_and_collect(
    base_url: str,
    token: str,
    conv_id: str,
    user_msg: str,
    interviewer_model: str | None,
    *,
    timeout: int,
) -> dict[str, Any]:
    started_at = time.monotonic()
    events = _iter_sse_events(
        base_url,
        token,
        conv_id,
        user_msg,
        interviewer_model,
        timeout=timeout,
    )
    return {
        "assistant": _assistant_text_from_events(events),
        "events": events,
        "latency_sec": round(time.monotonic() - started_at, 3),
    }


def run_evaluation(
    scenario: Scenario,
    args: argparse.Namespace,
    auth_token: str,
    candidate_config: CandidateLLMConfig,
) -> dict[str, Any]:
    conversation_id, opening = create_conversation(args.base_url, auth_token, scenario)
    candidate = SmartCandidateAgent(scenario.persona, scenario.active_skills, candidate_config)
    turns: list[dict[str, Any]] = []
    interviewer_response = opening or "你好，我们开始今天的模拟面试，请先做一个简单自我介绍。"

    try:
        for turn_idx in range(1, scenario.max_turns + 1):
            if turn_idx == 1:
                user_msg = scenario.persona["opening"]
            else:
                user_msg = candidate.respond(interviewer_response)

            try:
                result = send_message_and_collect(
                    args.base_url,
                    auth_token,
                    conversation_id,
                    user_msg,
                    args.interviewer_model,
                    timeout=args.turn_timeout,
                )
                interviewer_response = result["assistant"]
                events = result["events"]
                latency_sec = result["latency_sec"]
            except Exception as exc:
                events = [{"type": "error", "message": str(exc)}]
                latency_sec = 0.0
                interviewer_response = ""

            turn = {
                "turn": turn_idx,
                "user": user_msg,
                "assistant": interviewer_response,
                "events": events,
                "latency_sec": latency_sec,
            }
            turns.append(turn)
            if scenario.early_exit_check and scenario.early_exit_check(turns):
                break

        metrics = extract_metrics(turns, conversation_id)
        scores = score_scenario(scenario, metrics)
        return {
            "scenario_id": scenario.scenario_id,
            "conversation_id": conversation_id,
            "turns": turns,
            "metrics": metrics,
            "scores": scores,
        }
    finally:
        if args.keep_conversation:
            print(f"Conversation kept: {conversation_id}")
        else:
            try:
                _delete_conversation(args.base_url, auth_token, conversation_id)
            except Exception as exc:
                print(f"Warning: failed to delete conversation {conversation_id}: {exc}", file=sys.stderr)


def _event_tools_for_turn(turn: dict[str, Any]) -> list[str]:
    return [tool for event in turn.get("events", []) if (tool := _event_tool_name(event))]


def _preview(text: str, limit: int = 80) -> str:
    compact = " ".join(str(text).split())
    return compact[:limit] + ("..." if len(compact) > limit else "")


def write_reports(
    result: dict[str, Any],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    *,
    timestamp: str | None = None,
) -> tuple[Path, Path]:
    timestamp = timestamp or time.strftime("%Y%m%d_%H%M%S")
    scenario_id = result["scenario_id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"eval_{scenario_id}_{timestamp}.json"
    md_path = output_dir / f"eval_{scenario_id}_{timestamp}.md"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_render_markdown_report(result, timestamp), encoding="utf-8")
    return json_path, md_path


def _render_markdown_report(result: dict[str, Any], timestamp: str) -> str:
    scenario_id = result["scenario_id"]
    scores = result["scores"]
    metrics = result["metrics"]
    turns = result["turns"]

    lines = [
        f"# 评测报告：{scenario_id}",
        f"时间：{timestamp}",
        f"场景：{scenario_id} · {metrics.get('turn_count', 0)} 轮",
        "",
        "## 评分",
        "| 维度 | 得分 | 说明 |",
        "|------|------|------|",
    ]
    for key, item in scores["items"].items():
        state = "PASS" if item["passed"] else "FAIL"
        lines.append(f"| {key} | {state} | {item['description']} |")

    lines.extend(
        [
            "",
            "## 面试流程",
            "| 轮次 | 候选人摘要 | 面试官摘要 | 工具 | 耗时 |",
            "|------|-----------|-----------|------|------|",
        ]
    )
    for turn in turns:
        tools = ", ".join(_event_tools_for_turn(turn)) or "-"
        lines.append(
            f"| T{turn['turn']} | {_preview(turn.get('user', ''))} | "
            f"{_preview(turn.get('assistant', ''))} | {tools} | {turn.get('latency_sec', 0)}s |"
        )

    lines.extend(["", "## 关键事件"])
    key_events = []
    for turn in turns:
        for event in turn.get("events", []):
            tool = _event_tool_name(event)
            if tool:
                key_events.append(f"- T{turn['turn']}: {tool}")
            elif event.get("type") in {"selected_question", "question_plan", "error"}:
                key_events.append(f"- T{turn['turn']}: {event.get('type')}")
    lines.extend(key_events or ["- 无"])

    lines.extend(["", "## 代表性输出"])
    for turn in turns[-2:]:
        if turn.get("assistant"):
            lines.append(f"> T{turn['turn']}: {_preview(turn['assistant'], 200)}")
    return "\n".join(lines) + "\n"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluate the real interview agent with LLM candidates.")
    parser.add_argument(
        "--scenario",
        default="all",
        choices=["all", *SCENARIOS.keys()],
        help="Scenario id to run, or all.",
    )
    parser.add_argument("--base-url", default=os.getenv("E2E_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--username", default=os.getenv("EVAL_USER_NAME") or os.getenv("E2E_USERNAME"))
    parser.add_argument("--password", default=os.getenv("EVAL_USER_PASSWORD") or os.getenv("E2E_PASSWORD"))
    parser.add_argument("--token", default=os.getenv("E2E_ACCESS_TOKEN"))
    parser.add_argument("--internal-username", default=os.getenv("E2E_INTERNAL_USERNAME", "sj"))
    parser.add_argument("--interviewer-model", default=os.getenv("E2E_MODEL"))
    parser.add_argument("--candidate-api-key", default=os.getenv("CANDIDATE_OPENAI_API_KEY"))
    parser.add_argument(
        "--candidate-base-url",
        default=os.getenv("CANDIDATE_OPENAI_BASE_URL") or os.getenv("CANDIDATE_LLM_BASE_URL"),
    )
    parser.add_argument("--candidate-model", default=os.getenv("CANDIDATE_LLM_MODEL"))
    parser.add_argument("--candidate-timeout", type=int, default=None)
    parser.add_argument("--turn-timeout", type=int, default=int(os.getenv("EVAL_TURN_TIMEOUT", "120")))
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--keep-conversation", action="store_true")
    parser.add_argument("--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if os.getenv("RUN_REAL_INTERVIEW_EVAL") != "1":
        print("Refusing to run real interview eval. Set RUN_REAL_INTERVIEW_EVAL=1.", file=sys.stderr)
        return 2

    try:
        auth_token = _resolve_token(args)
        candidate_config = _resolve_candidate_config(args)
        scenario_ids = list(SCENARIOS) if args.scenario == "all" else [args.scenario]
        all_passed = True
        for scenario_id in scenario_ids:
            scenario = SCENARIOS[scenario_id]
            print(f"Running scenario: {scenario_id}")
            result = run_evaluation(scenario, args, auth_token, candidate_config)
            json_path, md_path = write_reports(result, args.output_dir)
            if args.verbose:
                print(json.dumps(result["scores"], ensure_ascii=False, indent=2))
            print(f"- JSON: {json_path}")
            print(f"- MD: {md_path}")
            all_passed = all_passed and bool(result["scores"]["passed"])
        return 0 if all_passed else 1
    except Exception as exc:
        print(f"Interview eval failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
