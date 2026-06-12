"""Default chat skill registry loaded from the chat agent's skills directory."""

from app.agents.shared.skills.base import SkillRegistry
from app.agents.shared.skills.resolver import get_agent_skill_registry


def get_default_registry() -> SkillRegistry:
    """获取包含所有默认面试 skill 的注册表（从 SKILL.md 文件加载）"""
    return get_agent_skill_registry("chat")
