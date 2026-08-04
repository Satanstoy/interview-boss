"""Explicit profile gates for interview-specific capabilities."""

from __future__ import annotations

import re
import unicodedata

AGENT_DEVELOPMENT_PROFILE = "agent_development"
AGENT_JOB_FAMILY = "agent_llm"
_AGENT_DEVELOPMENT_POSITIONS = {
    "agent开发",
    "agent 开发",
    "agent开发/大模型应用开发/大模型开发",
}


def is_agent_development_position(job_position: str | None) -> bool:
    """Recognize only explicit Agent positions, not every LLM-family role."""

    normalized = unicodedata.normalize("NFKC", str(job_position or "")).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = re.sub(r"\s*/\s*", "/", normalized).casefold()
    return normalized in _AGENT_DEVELOPMENT_POSITIONS


def is_agent_development_profile(state: dict) -> bool:
    """Return whether the server selected the private Agent interview profile.

    This deliberately reads server-owned session/config state only.  A keyword
    in the candidate's message must never unlock a private source.
    """

    profile = state.get("interview_profile")
    if not profile:
        config = state.get("interview_config") or {}
        profile = config.get("interview_profile") if isinstance(config, dict) else None
    return profile == AGENT_DEVELOPMENT_PROFILE
