"""Stable configuration for grouping related interview positions."""

from __future__ import annotations

import re
import unicodedata


JOB_FAMILY_BY_POSITION = {
    "Agent开发": "agent_llm",
    "Agent 开发": "agent_llm",
    "大模型应用开发": "agent_llm",
    "大模型开发": "agent_llm",
    "Agent开发/大模型应用开发/大模型开发": "agent_llm",
    "后端开发": "backend",
}


def _normalize_position(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).strip()
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s*/\s*", "/", text).casefold()


def derive_job_family(job_position: str | None) -> str:
    """Return an explicit family without silently mixing unknown positions."""
    normalized = _normalize_position(job_position)
    for position, family in JOB_FAMILY_BY_POSITION.items():
        if _normalize_position(position) == normalized:
            return family
    return JOB_FAMILY_BY_POSITION.get(
        job_position or "", f"position:{str(job_position or '').strip() or 'system'}"
    )


def positions_for_family(job_family: str) -> tuple[str, ...]:
    """Return every configured position in a known family.

    An unknown ``position:<name>`` family represents exactly that position.
    """
    if job_family.startswith("position:"):
        return (job_family.removeprefix("position:"),)
    return tuple(
        position for position, family in JOB_FAMILY_BY_POSITION.items() if family == job_family
    )
