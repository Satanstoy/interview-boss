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
class JudgeLLMConfig:
    """Configuration for the LLM judge used in scoring and report generation."""

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
    # Turn-level candidate behavior injection: {turn_number: extra_instruction}
    # When the candidate responds at turn N, if N is in this dict,
    # the extra instruction is appended to the candidate's system prompt.
    candidate_prompt_overrides: dict[int, str] | None = None


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

# ── Per-Scenario Scoring ──────────────────────────────────────

EARLY_CLOSE_SCORING = {
    "early_close_refused": {
        "description": "候选人要求提前收尾时，面试官拒绝并继续提问",
        "weight": 2.0,
    },
    "interviewer_probes_instead_of_closing": {
        "description": "面试官在候选人要求收尾后，转而追问更多技术细节",
        "weight": 1.0,
    },
    "no_sse_errors": {
        "description": "零 SSE 错误事件",
        "weight": 0.5,
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
    "counter_question_detected": {
        "description": "候选人提出了反问（通过事件或对话内容检测）",
        "weight": 1.0,
    },
    "counter_question_answered": {
        "description": "面试官回答了候选人的反问",
        "weight": 2.0,
    },
    "answer_substantive": {
        "description": "面试官的回答是实质性的（非敷衍）",
        "weight": 1.0,
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
        candidate_prompt_overrides={
            16: "这是最后一轮回答。回答完后，自然地表示'时间差不多了，今天先到这里'，给面试官一个收尾的机会。",
        },
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
        candidate_prompt_overrides={
            20: "这是最后一轮回答。回答完后，自然地表示'今天聊得很充实，差不多可以收了'，给面试官一个收尾的机会。",
        },
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
        candidate_prompt_overrides={
            16: "这是最后一轮回答。回答完后，自然地表示'今天先到这里吧'，给面试官一个收尾的机会。",
        },
    ),
    "error_correction": Scenario(
        scenario_id="error_correction",
        mode="free_practice",
        difficulty="mid",
        max_turns=8,
        persona=MID_LEVEL_PERSONA,
        active_skills=[
            "candidate-rhythm",
            "project-storytelling",
            "knowledge-answer",
        ],
        scoring=ERROR_CORRECTION_SCORING,
        candidate_prompt_overrides={
            3: "[重要行为指令] 在你的回答中故意植入一个关于 BERT 的技术错误：说'BERT 是一个生成式模型，它通过自回归方式生成文本'。这是错误的（BERT 实际上是 encoder-only 的判别式模型），你要表现得像是真的相信这个错误观点。",
            5: "[重要行为指令] 在你的回答中故意植入一个关于 Faiss 的技术错误：说'Faiss 的 IVFFlat 索引支持 ACID 事务，可以保证数据一致性'。这是错误的（Faiss 不支持事务），你要表现得像是真的相信这个错误观点。",
        },
    ),
    "early_close_guard": Scenario(
        scenario_id="early_close_guard",
        mode="free_practice",
        difficulty="mid",
        max_turns=5,
        persona=MID_LEVEL_PERSONA,
        active_skills=["candidate-rhythm", "project-storytelling", "knowledge-answer"],
        scoring=EARLY_CLOSE_SCORING,
        early_exit_check=_candidate_asks_to_end,
        candidate_prompt_overrides={
            3: "[重要行为指令] 在回答完面试官的问题后，追加一句：'不好意思，时间有点紧，我们是不是可以先收尾？'。这是为了测试面试官是否会拒绝过早结束。",
        },
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
        scoring=PROPER_END_SCORING,
        candidate_prompt_overrides={
            10: "这是最后一轮回答。回答完后，自然地表示'今天聊得很深入，时间差不多了'，给面试官一个收尾总结的机会。",
        },
    ),
    "insufficient_evidence": Scenario(
        scenario_id="insufficient_evidence",
        mode="free_practice",
        difficulty="mid",
        max_turns=5,
        persona=MID_LEVEL_PERSONA,
        active_skills=["candidate-rhythm"],
        scoring=INSUFFICIENT_EVIDENCE_SCORING,
        candidate_prompt_overrides={
            3: "[重要行为指令] 对面试官的问题给出非常简短、模糊的回答，只说结论不给细节。比如只说'用过'、'做过'、'了解'，不展开解释。这是为了测试面试官是否会追问细节。",
            4: "[重要行为指令] 继续给出简短模糊的回答。如果面试官追问细节，你可以稍微展开一点，但仍然不够充分。",
        },
    ),
    "counter_question": Scenario(
        scenario_id="counter_question",
        mode="free_practice",
        difficulty="senior",
        max_turns=6,
        persona=SENIOR_PERSONA,
        active_skills=["candidate-rhythm", "project-storytelling", "knowledge-answer"],
        scoring=COUNTER_QUESTION_SCORING,
        candidate_prompt_overrides={
            4: "[重要行为指令] 在回答完面试官的问题后，主动向面试官提一个技术相关的问题，比如：'我想了解一下，贵团队在 XX 方面是怎么做的？'或'这个岗位日常工作中，XX 技术栈的使用频率高吗？'。这是为了测试面试官是否会回答候选人的反问。",
        },
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

    def inject_turn_instruction(self, instruction: str) -> None:
        """Inject a temporary instruction for the next candidate response.

        Appends a system message before the candidate's next response,
        guiding specific behavior (e.g., ask to end, give vague answer, ask counter-question).
        The instruction is appended to the system prompt for this turn only.
        """
        self.messages.append({
            "role": "system",
            "content": f"[本轮行为指令] {instruction}",
        })

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


def _resolve_judge_config(args: argparse.Namespace) -> JudgeLLMConfig | None:
    """Resolve judge LLM config from args and env vars.

    Priority: --judge-* CLI args > JUDGE_* env vars > OPENAI_* env vars (same as interviewer).
    Returns None only if --no-llm-judge is set or no API key is available at all.
    """
    if args.no_llm_judge:
        return None
    api_key = (
        args.judge_api_key
        or os.getenv("JUDGE_OPENAI_API_KEY")
        or os.getenv("JUDGE_LLM_API_KEY")
        or os.getenv("OPENAI_API_KEY")
        or ""
    )
    if not api_key:
        return None
    base_url = (
        args.judge_base_url
        or os.getenv("JUDGE_OPENAI_BASE_URL")
        or os.getenv("JUDGE_LLM_BASE_URL")
        or os.getenv("OPENAI_BASE_URL")
        or "https://api.openai.com/v1"
    ).rstrip("/")
    model = (
        args.judge_model
        or os.getenv("JUDGE_LLM_MODEL")
        or os.getenv("LLM_MODEL_NAME")
        or "mimo-v2.5-pro"
    )
    timeout = int(
        args.judge_timeout
        or os.getenv("JUDGE_LLM_TIMEOUT")
        or os.getenv("LLM_TIMEOUT")
        or "120"
    )
    return JudgeLLMConfig(
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
    timeout: int | None = None,
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
    with urllib.request.urlopen(request, timeout=timeout or config.timeout) as response:
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


# ── LLM Judge Scoring & Report ────────────────────────────────


def _build_conversation_transcript(turns: list[dict[str, Any]], max_chars: int = 12000) -> str:
    """Build a compact conversation transcript for the LLM judge.

    Truncates from the middle if the transcript exceeds max_chars,
    preserving the opening and the most recent turns.
    """
    lines: list[str] = []
    for turn in turns:
        user = str(turn.get("user") or "").strip()
        assistant = str(turn.get("assistant") or "").strip()
        tools = _event_tools_for_turn(turn)
        tool_tag = f" [tools: {', '.join(tools)}]" if tools else ""
        lines.append(f"候选人: {user}")
        lines.append(f"面试官{tool_tag}: {assistant}")
        lines.append("")

    transcript = "\n".join(lines)
    if len(transcript) <= max_chars:
        return transcript

    # Truncate from the middle: keep first 40% and last 50%
    head_end = int(max_chars * 0.4)
    tail_start = len(transcript) - int(max_chars * 0.5)
    # Find nearest newline boundaries
    head_end = transcript.rfind("\n", 0, head_end)
    tail_start = transcript.find("\n", tail_start)
    if head_end < 0:
        head_end = int(max_chars * 0.4)
    if tail_start < 0:
        tail_start = len(transcript) - int(max_chars * 0.5)
    return transcript[:head_end] + f"\n\n... [省略 {tail_start - head_end} 字符] ...\n\n" + transcript[tail_start:]


def _build_scoring_criteria_text(scenario: Scenario) -> str:
    """Format scenario scoring criteria as LLM-readable text."""
    lines: list[str] = []
    for key, config in scenario.scoring.items():
        desc = config.get("description", key)
        weight = config.get("weight", 1.0)
        lines.append(f"- **{key}** (weight={weight}): {desc}")
    return "\n".join(lines)


def llm_score_scenario(
    scenario: Scenario,
    turns: list[dict[str, Any]],
    metrics: dict[str, Any],
    judge_config: JudgeLLMConfig,
) -> dict[str, Any]:
    """Use LLM judge to evaluate the interview against scenario criteria.

    Returns the same structure as score_scenario() but with LLM-generated
    pass/fail judgments and reasoning for each dimension.
    """
    transcript = _build_conversation_transcript(turns)
    criteria_text = _build_scoring_criteria_text(scenario)

    # Build hard metrics summary for the judge
    hard_metrics = {
        "turn_count": metrics.get("turn_count", 0),
        "tool_count": metrics.get("tool_count", 0),
        "tool_names": metrics.get("tool_names", []),
        "selected_ids_count": len(metrics.get("selected_ids", [])),
        "cross_turn_duplicates": metrics.get("cross_turn_duplicate_candidates", []),
        "asked_questions_count": len(metrics.get("asked_questions", [])),
        "has_summary": metrics.get("has_summary", False),
        "thinking_turns": metrics.get("thinking_turns", 0),
        "error_count": len(metrics.get("errors", [])),
        "correction_in_output_count": metrics.get("correction_in_output_count", 0),
        "early_close_refused": metrics.get("early_close_refused", False),
        "has_insufficient_evidence_marker": metrics.get("has_insufficient_evidence_marker", False),
        "counter_question_answered": metrics.get("counter_question_answered", False),
    }

    prompt = f"""你是一位资深技术面试质量评审专家。请根据以下面试对话记录和指标数据，对面试质量进行逐项评估。

## 评测场景
- 场景: {scenario.scenario_id}
- 模式: {scenario.mode}
- 难度: {scenario.difficulty}
- 预期轮数: {scenario.max_turns}

## 评分维度
{criteria_text}

## 硬指标数据
```json
{json.dumps(hard_metrics, ensure_ascii=False, indent=2)}
```

## 面试对话记录
{transcript}

## 评估要求

请对每个评分维度进行独立判断。对于每个维度：
1. 结合硬指标数据和对话内容进行综合判断
2. 不要仅依赖硬指标 — 用对话内容验证指标的准确性
3. 给出具体的判断依据（引用对话中的具体轮次或内容）

请严格按以下 JSON 格式返回（不要包含其他文本）：
```json
{{
  "dimensions": {{
    "dimension_key_1": {{
      "passed": true/false,
      "score": 0.0-1.0,
      "reasoning": "具体判断依据，引用对话内容",
      "evidence": "引用的具体对话片段"
    }},
    "dimension_key_2": {{ ... }}
  }},
  "overall_score": 0.0-1.0,
  "overall_passed": true/false,
  "critical_issues": ["严重问题1", "严重问题2"],
  "highlights": ["亮点1", "亮点2"]
}}
```

维度 key 列表: {', '.join(scenario.scoring.keys())}"""

    try:
        raw = _call_openai_compatible_chat(
            judge_config,
            [{"role": "user", "content": prompt}],
            temperature=0.1,
            max_tokens=4000,
        )
        # Extract JSON from response (handle markdown code blocks)
        json_match = re.search(r"```json\s*(.*?)\s*```", raw, re.DOTALL)
        json_str = json_match.group(1) if json_match else raw
        # Try to find JSON object if no code block
        if not json_match:
            obj_match = re.search(r"\{.*\}", raw, re.DOTALL)
            json_str = obj_match.group(0) if obj_match else raw

        parsed = json.loads(json_str)
        dimensions = parsed.get("dimensions", {})

        # Build score items matching the old format
        items: dict[str, dict[str, Any]] = {}
        total_weight = 0.0
        passed_weight = 0.0

        for key, config in scenario.scoring.items():
            weight = float(config.get("weight", 1.0))
            total_weight += weight
            dim = dimensions.get(key, {})
            passed = bool(dim.get("passed", False))
            if passed:
                passed_weight += weight
            items[key] = {
                "passed": passed,
                "weight": weight,
                "description": config.get("description", key),
                "score": float(dim.get("score", 0.0)),
                "reasoning": str(dim.get("reasoning", "")),
                "evidence": str(dim.get("evidence", "")),
                "error": None,
            }

        return {
            "passed": bool(parsed.get("overall_passed", passed_weight == total_weight)),
            "passed_weight": passed_weight,
            "total_weight": total_weight,
            "ratio": passed_weight / total_weight if total_weight else 0.0,
            "items": items,
            "overall_score": float(parsed.get("overall_score", passed_weight / total_weight if total_weight else 0.0)),
            "critical_issues": parsed.get("critical_issues", []),
            "highlights": parsed.get("highlights", []),
            "judge_model": judge_config.model,
        }

    except Exception as exc:
        print(f"Warning: LLM judge scoring failed, falling back to rule-based: {exc}", file=sys.stderr)
        # Fallback to rule-based scoring
        result = score_scenario(scenario, metrics)
        result["judge_error"] = str(exc)
        result["judge_model"] = judge_config.model
        result["fallback_notice"] = (
            f"⚠️ LLM 评分失败（{judge_config.model}: {exc}），已降级为规则评分。"
            f"规则评分使用关键词匹配，可能不够准确。"
        )
        return result


def llm_generate_report(
    result: dict[str, Any],
    judge_config: JudgeLLMConfig,
) -> str:
    """Use LLM to generate a qualitative evaluation report.

    Combines quantitative scores with conversation analysis to produce
    actionable insights and improvement suggestions.
    """
    scenario_id = result["scenario_id"]
    scores = result["scores"]
    metrics = result["metrics"]
    turns = result["turns"]
    transcript = _build_conversation_transcript(turns, max_chars=10000)

    # Build scoring summary
    score_lines: list[str] = []
    for key, item in scores.get("items", {}).items():
        status = "✅ PASS" if item.get("passed") else "❌ FAIL"
        score_val = item.get("score", 0)
        reasoning = item.get("reasoning", "")
        score_lines.append(f"- {key}: {status} (score={score_val:.1f}) — {reasoning}")
    score_summary = "\n".join(score_lines)

    critical_issues = scores.get("critical_issues", [])
    highlights = scores.get("highlights", [])
    overall_score = scores.get("overall_score", 0)
    fallback_notice = scores.get("fallback_notice", "")

    fallback_section = ""
    if fallback_notice:
        fallback_section = f"\n\n## ⚠️ 降级提醒\n{fallback_notice}\n请注意：以下评分基于规则匹配（关键词+阈值），非 LLM 语义判断，评分可能不够准确。\n"

    prompt = f"""你是一位资深技术面试质量分析专家。请根据以下评测数据生成一份结构化的评测报告。

## 评测概况
- 场景: {scenario_id}
- 总轮数: {metrics.get('turn_count', 0)}
- 总体得分: {overall_score:.2f}/1.00
- 通过状态: {'通过' if scores.get('passed') else '未通过'}
- 评测模型: {scores.get('judge_model', 'unknown')}
{fallback_section}
## 各维度评分
{score_summary}

## 严重问题
{chr(10).join(f'- {issue}' for issue in critical_issues) if critical_issues else '- 无'}

## 亮点
{chr(10).join(f'- {h}' for h in highlights) if highlights else '- 无'}

## 硬指标摘要
- 工具调用次数: {metrics.get('tool_count', 0)}
- 选中题目数: {len(metrics.get('selected_ids', []))}
- 跨轮重复候选: {len(metrics.get('cross_turn_duplicate_candidates', []))}
- thinking 轮次: {metrics.get('thinking_turns', 0)}/{metrics.get('turn_count', 0)}
- SSE 错误数: {len(metrics.get('errors', []))}

## 面试对话记录
{transcript}

## 报告要求

请生成一份 Markdown 格式的评测报告，包含以下部分：

1. **执行摘要** — 一句话总结面试质量
2. **评分总览** — 表格形式展示各维度得分和状态
3. **质量分析** — 分析面试官的表现模式（好的和需改进的），引用具体对话轮次
4. **关键发现** — 列出 3-5 个最重要的发现（正面和负面各半）
5. **改进建议** — 针对每个失败维度给出具体可操作的改进方向
6. **代表性对话** — 挑选 2-3 段最能说明问题的对话片段

{'注意：本次评分因 LLM 评分失败而使用了规则评分（关键词匹配），请在报告中明确标注这一限制。' if fallback_notice else ''}
报告语言：中文简体。语气：专业、客观、有建设性。"""

    try:
        report = _call_openai_compatible_chat(
            judge_config,
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=6000,
        )
        # Prepend fallback notice if scoring used rule-based fallback
        if fallback_notice:
            report = f"> ⚠️ **降级提醒**: {fallback_notice}\n\n{report}"
        return report
    except Exception as exc:
        print(f"Warning: LLM report generation failed, falling back to template: {exc}", file=sys.stderr)
        template = _render_markdown_report(result, time.strftime("%Y%m%d_%H%M%S"))
        notice = (
            f"\n\n> ⚠️ **降级提醒**: LLM 报告生成失败（{judge_config.model}: {exc}），"
            f"已降级为模板报告。模板报告仅包含结构化数据，缺少定性分析和改进建议。\n"
        )
        return notice + template


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
    judge_config: JudgeLLMConfig | None = None,
) -> dict[str, Any]:
    conversation_id, opening = create_conversation(args.base_url, auth_token, scenario)
    candidate = SmartCandidateAgent(scenario.persona, scenario.active_skills, candidate_config)
    turns: list[dict[str, Any]] = []
    interviewer_response = opening or "你好，我们开始今天的模拟面试，请先做一个简单自我介绍。"

    try:
        for turn_idx in range(1, scenario.max_turns + 1):
            # Inject turn-level candidate behavior override if configured
            if scenario.candidate_prompt_overrides and turn_idx in scenario.candidate_prompt_overrides:
                override = scenario.candidate_prompt_overrides[turn_idx]
                candidate.inject_turn_instruction(override)

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
        if judge_config:
            scores = llm_score_scenario(scenario, turns, metrics, judge_config)
        else:
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
    llm_report: str | None = None,
) -> tuple[Path, Path]:
    timestamp = timestamp or time.strftime("%Y%m%d_%H%M%S")
    scenario_id = result["scenario_id"]
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"eval_{scenario_id}_{timestamp}.json"
    md_path = output_dir / f"eval_{scenario_id}_{timestamp}.md"

    json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    md_content = llm_report if llm_report else _render_markdown_report(result, timestamp)
    md_path.write_text(md_content, encoding="utf-8")
    return json_path, md_path


def write_unified_report(
    results: list[dict[str, Any]],
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    judge_config: JudgeLLMConfig | None = None,
) -> Path:
    """Generate a unified report summarizing all scenario results.

    Uses LLM to synthesize cross-scenario insights if judge config is available,
    otherwise falls back to a template-based summary.
    """
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    unified_path = output_dir / f"eval_unified_{timestamp}.md"

    # Build summary data for each scenario
    scenario_summaries: list[str] = []
    for r in results:
        scores = r["scores"]
        metrics = r["metrics"]
        overall = scores.get("overall_score", scores.get("ratio", 0))
        passed = scores.get("passed", False)
        status = "✅ PASS" if passed else "❌ FAIL"
        fallback = " ⚠️降级" if scores.get("fallback_notice") else ""
        turn_count = metrics.get("turn_count", len(r.get("turns", [])))

        # Count passed/failed dimensions
        items = scores.get("items", {})
        passed_dims = sum(1 for v in items.values() if v.get("passed"))
        total_dims = len(items)

        scenario_summaries.append(
            f"| {r['scenario_id']} | {turn_count}轮 | {overall:.2f} | {status}{fallback} "
            f"| {passed_dims}/{total_dims} |"
        )

    summary_table = "\n".join(scenario_summaries)

    # Collect all critical issues and highlights
    all_issues: list[str] = []
    all_highlights: list[str] = []
    for r in results:
        sid = r["scenario_id"]
        scores = r["scores"]
        for issue in scores.get("critical_issues", []):
            all_issues.append(f"- **{sid}**: {issue}")
        for h in scores.get("highlights", []):
            all_highlights.append(f"- **{sid}**: {h}")

    if judge_config:
        # Use LLM to generate cross-scenario analysis with full conversation context
        # Build per-scenario sections with transcripts and scoring details
        scenario_sections: list[str] = []
        for r in results:
            sid = r["scenario_id"]
            scores = r["scores"]
            metrics = r["metrics"]
            turns = r.get("turns", [])
            transcript = _build_conversation_transcript(turns, max_chars=1500)
            fallback = scores.get("fallback_notice", "")

            # Scoring details
            score_lines: list[str] = []
            for key, item in scores.get("items", {}).items():
                status = "✅" if item.get("passed") else "❌"
                score_val = item.get("score", 0)
                reasoning = item.get("reasoning", item.get("description", ""))
                evidence = item.get("evidence", "")
                line = f"  - {status} **{key}** ({score_val:.1f}): {reasoning}"
                if evidence:
                    line += f"\n    证据: {evidence[:150]}"
                score_lines.append(line)

            issues = scores.get("critical_issues", [])
            highlights = scores.get("highlights", [])

            section = f"""---
### 场景: {sid}
- 轮数: {len(turns)} | 总分: {scores.get('overall_score', scores.get('ratio', 0)):.2f} | 状态: {'通过' if scores.get('passed') else '未通过'}
- 工具调用: {metrics.get('tool_count', 0)} | thinking轮次: {metrics.get('thinking_turns', 0)}/{len(turns)} | SSE错误: {len(metrics.get('errors', []))}
{f'- 降级: {fallback}' if fallback else ''}

**评分维度:**
{chr(10).join(score_lines)}

**严重问题:**
{chr(10).join(f'  - {i}' for i in issues) if issues else '  - 无'}

**亮点:**
{chr(10).join(f'  - {h}' for h in highlights) if highlights else '  - 无'}

**对话记录:**
{transcript}"""
            scenario_sections.append(section)

        all_scenarios_text = "\n\n".join(scenario_sections)

        prompt = f"""你是一位资深技术面试质量分析专家。请根据以下 8 个场景的完整评测数据（含对话记录），生成一份深度综合评测报告。

## 场景总览
| 场景 | 轮数 | 总分 | 状态 | 通过维度 |
|------|------|------|------|---------|
{summary_table}

## 各场景详细数据（含对话记录）
{all_scenarios_text}

## 报告要求

请生成一份 Markdown 格式的深度综合评测报告，包含以下部分：

1. **总体评价** — 2-3 句话总结面试系统整体质量水平，指出最突出的优势和最紧迫的问题

2. **场景得分对比** — 表格形式展示各场景得分、通过情况、核心失分点

3. **共性问题深度分析** — 对跨场景反复出现的问题进行深入分析：
   - 每个问题必须引用至少 2 个场景的具体对话轮次作为证据
   - 分析问题的根本原因（是 prompt 设计问题、逻辑缺陷、还是评测标准不合理）
   - 评估问题对候选人体验的实际影响

4. **场景逐一分析** — 每个场景单独一节，包含：
   - 场景目标与实际表现的差距分析
   - 引用 1-2 段最具代表性的对话（好的或差的），附专家点评
   - 该场景独有的发现

5. **系统亮点详析** — 面试系统做得好的方面，引用具体对话证据

6. **面试官表现画像** — 基于所有场景的对话，总结面试官的整体风格：
   - 提问策略（追问深度、话题切换、难度控制）
   - 互动模式（反馈频率、鼓励方式、反问处理）
   - 流程管理（节奏控制、收尾质量）

7. **优先改进清单** — 按 P0/P1/P2/P3 排序，每条包含：
   - 具体问题描述
   - 影响的场景和维度
   - 可操作的改进方案
   - 预期改进效果

8. **各场景评分明细表** — 每个场景一个表格

报告语言：中文简体。语气：专业、客观、有建设性。篇幅不限，力求深入。"""

        try:
            report = _call_openai_compatible_chat(
                judge_config,
                [{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=16000,
                timeout=300,
            )
            unified_path.write_text(report, encoding="utf-8")
            return unified_path
        except Exception as exc:
            print(f"Warning: LLM unified report failed, using template: {exc}", file=sys.stderr)

    # Fallback: template-based unified report
    lines = [
        "# 面试系统综合评测报告",
        f"时间: {timestamp}",
        f"场景数: {len(results)}",
        "",
        "## 场景总览",
        "| 场景 | 轮数 | 总分 | 状态 | 通过维度 |",
        "|------|------|------|------|---------|",
        summary_table,
        "",
        "## 共性问题",
        *all_issues,
        "",
        "## 系统亮点",
        *all_highlights,
        "",
    ]

    # Per-scenario detail tables
    for r in results:
        sid = r["scenario_id"]
        scores = r["scores"]
        lines.append(f"## {sid} 评分明细")
        lines.append("| 维度 | 状态 | 得分 | 说明 |")
        lines.append("|------|------|------|------|")
        for key, item in scores.get("items", {}).items():
            status = "✅" if item.get("passed") else "❌"
            score_val = item.get("score", 0)
            reasoning = item.get("reasoning", item.get("description", ""))
            lines.append(f"| {key} | {status} | {score_val:.1f} | {reasoning[:80]} |")
        lines.append("")

    unified_path.write_text("\n".join(lines), encoding="utf-8")
    return unified_path


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
        nargs="+",
        default=["all"],
        choices=["all", *SCENARIOS.keys()],
        help="Scenario id(s) to run, or 'all'. Can specify multiple: --scenario error_correction proper_end",
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
    parser.add_argument("--judge-api-key", default=os.getenv("JUDGE_OPENAI_API_KEY"))
    parser.add_argument("--judge-base-url", default=os.getenv("JUDGE_OPENAI_BASE_URL") or os.getenv("JUDGE_LLM_BASE_URL"))
    parser.add_argument("--judge-model", default=os.getenv("JUDGE_LLM_MODEL"))
    parser.add_argument("--judge-timeout", type=int, default=None)
    parser.add_argument("--no-llm-judge", action="store_true", help="Disable LLM judge, use rule-based scoring only.")
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
        candidate_config = _resolve_candidate_config(args)
        judge_config = _resolve_judge_config(args)
        if judge_config:
            print(f"LLM Judge enabled: model={judge_config.model}, base_url={judge_config.base_url}")
        else:
            print("LLM Judge disabled: using rule-based scoring (set OPENAI_API_KEY or use --judge-api-key to enable).")
        scenario_ids = list(SCENARIOS) if "all" in args.scenario else args.scenario
        all_passed = True
        all_results: list[dict[str, Any]] = []
        for scenario_id in scenario_ids:
            scenario = SCENARIOS[scenario_id]
            print(f"Running scenario: {scenario_id}")
            # Refresh token for each scenario to avoid expiry
            auth_token = _resolve_token(args)
            result = run_evaluation(scenario, args, auth_token, candidate_config, judge_config)

            # Generate report: LLM if judge available, otherwise template
            llm_report = None
            if judge_config:
                print(f"  Generating LLM report for {scenario_id}...")
                llm_report = llm_generate_report(result, judge_config)

            json_path, md_path = write_reports(result, args.output_dir, llm_report=llm_report)
            if args.verbose:
                print(json.dumps(result["scores"], ensure_ascii=False, indent=2))
            print(f"- JSON: {json_path}")
            print(f"- MD: {md_path}")
            all_passed = all_passed and bool(result["scores"]["passed"])
            all_results.append(result)

        # Write unified report when running multiple scenarios
        if len(all_results) > 1:
            unified_path = write_unified_report(all_results, args.output_dir, judge_config)
            print(f"\n统一报告: {unified_path}")
        return 0 if all_passed else 1
    except Exception as exc:
        print(f"Interview eval failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
