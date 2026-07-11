"""SmartCandidateAgent and config resolution."""

from __future__ import annotations

import argparse
import os
from typing import Any

from app.agents.shared.skills.builder import build_skill_prompt
from app.agents.shared.skills.resolver import get_agent_skill_registry

from .types import CandidateLLMConfig, JudgeLLMConfig
from .http_client import _call_openai_compatible_chat


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
        """Inject a temporary instruction for the next candidate response."""
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
    if getattr(args, "no_llm_judge", False):
        return None
    api_key = (
        args.judge_api_key
        or os.getenv("JUDGE_OPENAI_API_KEY")
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
        or "mimo-v2.5"
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
