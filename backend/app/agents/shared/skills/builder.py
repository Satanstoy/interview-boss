"""Skill prompt composition helpers."""

from __future__ import annotations

from html import escape

from app.agents.shared.skills.base import SkillRegistry


def build_skill_prompt(registry: SkillRegistry, active_skills: list[str]) -> str:
    if not active_skills:
        return ""

    parts = []
    for name in active_skills:
        skill = registry.get(name)
        if skill is None:
            continue
        instruction = skill.get_instruction()
        if instruction:
            safe_name = escape(skill.name, quote=True)
            parts.append(
                f'<skill_instruction name="{safe_name}">\n'
                f"{instruction.strip()}\n"
                "</skill_instruction>"
            )

    if not parts:
        return ""

    return (
        "<skill_instructions>\n"
        "The following skills define behavior patterns. Any examples inside them "
        "are illustrative few-shot examples, not facts about the current candidate "
        "unless repeated in the actual conversation, resume/JD, or retrieved questions.\n\n"
        + "\n\n".join(parts)
        + "\n</skill_instructions>"
    )
