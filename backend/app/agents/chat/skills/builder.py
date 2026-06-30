"""Chat-specific skill prompt builders."""

from app.agents.shared.skills.base import SkillRegistry
from app.agents.shared.skills.builder import (
    build_skill_catalog as _build_shared_skill_catalog,
    build_skill_prompt,
)
from app.agents.chat.skills.defaults import get_default_registry

__all__ = ["build_skill_catalog", "build_skill_prompt"]


def build_skill_catalog(registry: SkillRegistry | None = None) -> str:
    """Build the chat agent's Layer 1 skill catalog.

    Shared code only renders generic skill metadata. Chat-specific wording
    about loading skills belongs here, while concrete MCP tool policy stays in
    the always-injected interview-tool-use skill and dynamic tool_strategy.
    """
    if registry is None:
        registry = get_default_registry()

    catalog = _build_shared_skill_catalog(registry)
    if not catalog:
        return ""

    return "\n".join(
        [
            catalog,
            "",
            "面试过程中如需切换面试策略，可通过 load_skill 加载相关技能。",
            "MCP 工具调用规范由常驻 interview-tool-use 技能提供；当前回合的硬约束由 tool_strategy 提供。",
        ]
    )
