"""Reusable Agent Skills components.

Each agent can keep its own `skills/<skill-name>/SKILL.md` directories while
sharing the same loader, registry, matching, and prompt composition logic.
"""

from app.agents.shared.skills.base import Skill, SkillRegistry, SkillResourceIndex
from app.agents.shared.skills.builder import build_skill_catalog, build_skill_prompt
from app.agents.shared.skills.loader import load_skill_from_file
from app.agents.shared.skills.resolver import get_agent_skill_registry

__all__ = [
    "Skill",
    "SkillRegistry",
    "SkillResourceIndex",
    "build_skill_catalog",
    "build_skill_prompt",
    "load_skill_from_file",
    "get_agent_skill_registry",
]
