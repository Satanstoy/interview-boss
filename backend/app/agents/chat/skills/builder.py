"""Skill Prompt Builder — 将 active skills 的指令合并为 prompt 片段"""
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.chat.skills.base import SkillRegistry


def build_skill_prompt(registry: SkillRegistry, active_skills: list[str]) -> str:
    """将 active skills 的 Layer 2 instruction 合并为一个 prompt 片段。

    Args:
        registry: SkillRegistry 实例
        active_skills: 当前激活的 skill 名称列表

    Returns:
        合并后的指令文本，无 active skills 时返回空字符串
    """
    if not active_skills:
        return ""

    parts = []
    for name in active_skills:
        skill = registry.get(name)
        if skill is None:
            continue
        instruction = skill.get_instruction()
        if instruction:
            parts.append(instruction)

    return "\n\n".join(parts)
