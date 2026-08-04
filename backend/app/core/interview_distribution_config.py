"""Stable configuration for grouping related interview positions."""

from __future__ import annotations


JOB_FAMILY_BY_POSITION = {
    "Agent开发": "agent_llm",
    "大模型应用开发": "agent_llm",
    "大模型开发": "agent_llm",
    "Agent开发/大模型应用开发/大模型开发": "agent_llm",
    "后端开发": "backend",
}


def derive_job_family(job_position: str | None) -> str:
    """Return an explicit family without silently mixing unknown positions."""
    normalized = (job_position or "").strip()
    return JOB_FAMILY_BY_POSITION.get(normalized, f"position:{normalized or 'system'}")


def positions_for_family(job_family: str) -> tuple[str, ...]:
    """Return every configured position in a known family.

    An unknown ``position:<name>`` family represents exactly that position.
    """
    if job_family.startswith("position:"):
        return (job_family.removeprefix("position:"),)
    return tuple(
        position for position, family in JOB_FAMILY_BY_POSITION.items() if family == job_family
    )
