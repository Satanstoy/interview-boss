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


def build_skill_catalog(registry: SkillRegistry | None = None) -> str:
    """Build lightweight skill catalog (names + descriptions only) for system prompt.

    Unlike build_skill_prompt, this does NOT load full instructions.
    LLM must use the load_skill tool to get full content on demand.

    Returns:
        Formatted skill catalog text, ~300-500 tokens.
    """
    if registry is None:
        from app.agents.chat.skills import get_default_registry

        registry = get_default_registry()

    if not registry._skills:
        return ""

    sorted_skills = sorted(
        registry._skills.values(), key=lambda s: s.priority, reverse=True
    )

    lines = [
        "## 可用技能",
        "",
        "你可以通过 load_skill 工具加载以下技能来指导你的面试行为：",
        "",
    ]
    for skill in sorted_skills:
        lines.append(f"- **{skill.name}**: {skill.description}")

    lines.extend([
        "",
        "根据面试话题选择最相关的技能加载。一次可以加载多个。",
        "",
        "## 工具使用指南",
        "",
        "你有以下工具可用：",
        "- load_skill: 加载面试技能指令（在需要专业面试技巧时调用）",
        "- search_questions: 搜索题库（当需要找相关面试题时调用）",
        "- draw_questions: 随机抽题（当用户要求练习时调用）",
        "",
        "请根据用户的提问内容自主决定使用哪些工具。你可以：",
        "1. 先加载相关技能，再搜索或抽取题目",
        "2. 直接回答简单问题（不需要工具时）",
        "3. 多次调用工具组合使用",
        "",
        "如果不调用任何工具，你将直接生成回答。",
    ])

    return "\n".join(lines)
