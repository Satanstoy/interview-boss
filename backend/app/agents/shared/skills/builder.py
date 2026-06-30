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


def build_skill_catalog(registry: SkillRegistry) -> str:
    """Build a generic lightweight skill catalog (names + descriptions only).

    Shared code must stay agent-agnostic: no default registry, no tool names,
    and no agent-specific strategy guidance. Agent packages wrap this helper
    when they need custom intro/outro text or policy.

    Returns:
        Formatted skill catalog text.
    """
    if not registry._skills:
        return ""

    sorted_skills = sorted(
        registry._skills.values(), key=lambda s: s.priority, reverse=True
    )

    lines = [
        "## 可用技能",
        "",
        "以下技能可按需用于指导当前 agent 行为：",
        "",
    ]
    for skill in sorted_skills:
        lines.append(f"- **{skill.name}**: {skill.description}")

    lines.extend(["", "根据当前任务选择最相关的技能。一次可以选择多个。"])

    return "\n".join(lines)
