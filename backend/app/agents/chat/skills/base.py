"""Compatibility exports for chat skills.

The reusable implementation lives in `app.agents.shared.skills`.
"""

from app.agents.shared.skills.base import Skill, SkillRegistry

__all__ = ["Skill", "SkillRegistry"]
