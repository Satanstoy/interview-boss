"""Skills 系统 — 面试官技能模块化架构"""
from app.agents.chat.skills.base import Skill, SkillRegistry
from app.agents.chat.skills.builder import build_skill_prompt
from app.agents.chat.skills.defaults import get_default_registry
from app.agents.chat.skills.loader import load_skill_from_file

__all__ = ["Skill", "SkillRegistry", "build_skill_prompt", "get_default_registry", "load_skill_from_file"]
