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
        "## 工具使用策略",
        "",
        "根据当前对话状态选择合适的工具：",
        "",
        "### 面试追问场景（用户刚回答完一个问题）",
        "1. 从用户回答中提取技术关键词",
        "2. 调用 search_questions(keywords=[...], question_type='project_followup' 或 'knowledge_probe')",
        "3. 如果需要切换面试类型，先调用 load_skill",
        "",
        "### 新话题/练习请求",
        "1. 调用 search_questions 获取相关题目",
        "2. 结果不足时用 draw_questions 补充",
        "",
        "### 普通对话/用户还没回答完",
        "不调用任何工具，直接回复",
        "",
        "重要边界：技能名和工具名是内部控制信号，只能用于 tool calling；不得把 "
        "project-deep-dive、load_skill 等名称作为最终回复正文输出。",
        "最终回复必须是面试官直接对候选人说的话。",
        "",
        "如果不调用任何工具，你将直接生成回答。",
    ])

    return "\n".join(lines)
