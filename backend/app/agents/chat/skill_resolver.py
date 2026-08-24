"""Harness-compatible deterministic SkillResolver."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.agents.shared.skills.base import Skill, SkillRegistry


@dataclass(frozen=True)
class ResolvedSkill:
    skill_key: str
    skill_version: str
    harness_compatibility: str
    content_hash: str
    description: str
    instruction: str
    priority: int
    always_active: bool


def _metadata_value(skill: Skill, *keys: str):
    metadata = skill.metadata or {}
    for key in keys:
        if key in metadata:
            return metadata[key]
    return None


def _compatible(value: object, harness_version: str) -> bool:
    if value is None:
        return True
    if isinstance(value, (list, tuple, set)):
        return harness_version in {str(item) for item in value}
    return str(value).strip() in {harness_version, "*", "all"}


def resolve_skills(
    registry: SkillRegistry,
    state: dict,
    *,
    harness_version: str = "2.0",
) -> list[ResolvedSkill]:
    """Resolve only skills compatible with this Harness version."""
    resolved: list[ResolvedSkill] = []
    for skill in sorted(
        registry.match_skills(state), key=lambda item: (-item.priority, item.name)
    ):
        compatibility = _metadata_value(
            skill,
            "interview-boss.harness_compatibility",
            "harness_compatibility",
        )
        if not _compatible(compatibility, harness_version):
            continue
        version = str(
            _metadata_value(skill, "interview-boss.skill_version", "skill_version")
            or "1.0"
        )
        compatibility_text = (
            ",".join(str(item) for item in compatibility)
            if isinstance(compatibility, (list, tuple, set))
            else str(compatibility or harness_version)
        )
        instruction = skill.get_instruction(state)
        content_hash = hashlib.sha256(
            json.dumps(
                {
                    "skill_key": skill.name,
                    "skill_version": version,
                    "description": skill.description,
                    "instruction": instruction,
                    "strategy_rules": skill.get_strategy_rules(),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        resolved.append(
            ResolvedSkill(
                skill_key=skill.name,
                skill_version=version,
                harness_compatibility=compatibility_text,
                content_hash=content_hash,
                description=skill.description,
                instruction=instruction,
                priority=skill.priority,
                always_active=skill.always_active,
            )
        )
    return resolved


__all__ = ["ResolvedSkill", "resolve_skills"]
