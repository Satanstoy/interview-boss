"""SKILL.md loader for reusable agent skills."""

import yaml
import re
from pathlib import Path

from app.agents.shared.skills.base import Skill, SkillResourceIndex


_VALID_SKILL_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_STANDARD_RESOURCE_DIRS = ("references", "scripts", "assets")


def load_skill_from_file(skill_dir: Path) -> Skill:
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md not found in {skill_dir}")

    content = skill_md.read_text(encoding="utf-8")
    frontmatter, body = _parse_skill_md(content)

    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not name or not description:
        raise ValueError(
            f"SKILL.md in {skill_dir} missing required fields: name, description"
        )
    _validate_skill_name(str(name), skill_dir)

    metadata = frontmatter.get("metadata") or {}
    if not isinstance(metadata, dict):
        raise ValueError(f"SKILL.md in {skill_dir} metadata must be a mapping")

    return Skill(
        name=name,
        description=description,
        license=frontmatter.get("license"),
        compatibility=frontmatter.get("compatibility"),
        metadata=metadata,
        allowed_tools=_parse_allowed_tools(frontmatter.get("allowed-tools")),
        triggers=_interview_boss_value(frontmatter, metadata, "triggers", []),
        priority=_parse_int(
            _interview_boss_value(frontmatter, metadata, "priority", 50),
            default=50,
        ),
        instruction_template=body.strip() if body.strip() else None,
        always_active=_parse_bool(
            _interview_boss_value(frontmatter, metadata, "always_active", False)
        ),
        strategy_rules=_interview_boss_value(frontmatter, metadata, "strategy_rules"),
        allowed_agents=_interview_boss_value(frontmatter, metadata, "allowed_agents", []),
        prompt_role=_interview_boss_value(frontmatter, metadata, "prompt_role"),
        resources=_index_skill_resources(skill_dir),
    )


def _parse_skill_md(content: str) -> tuple[dict, str]:
    if not content.startswith("---"):
        return {}, content

    second_delim = content.find("---", 3)
    if second_delim == -1:
        return {}, content

    yaml_str = content[3:second_delim]
    body = content[second_delim + 3 :]

    frontmatter = yaml.safe_load(yaml_str) or {}
    return frontmatter, body


def _validate_skill_name(name: str, skill_dir: Path) -> None:
    if not _VALID_SKILL_NAME_RE.match(name):
        raise ValueError(
            f"invalid skill name '{name}': use lowercase letters, numbers, and single hyphens"
        )
    if name != skill_dir.name:
        raise ValueError(
            f"SKILL.md name '{name}' must match parent directory '{skill_dir.name}'"
        )


def _parse_allowed_tools(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item for item in value.split() if item]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _parse_int(value: object, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off", ""}:
            return False
    return bool(value)


def _metadata_key(field: str) -> str:
    return f"interview-boss.{field.replace('_', '-')}"


def _interview_boss_value(
    frontmatter: dict,
    metadata: dict,
    field: str,
    default=None,
):
    if field in frontmatter:
        return frontmatter.get(field)
    metadata_key = _metadata_key(field)
    if metadata_key in metadata:
        return metadata.get(metadata_key)
    return default


def _index_skill_resources(skill_dir: Path) -> SkillResourceIndex:
    resources = SkillResourceIndex(root=skill_dir)
    for dir_name in _STANDARD_RESOURCE_DIRS:
        root = skill_dir / dir_name
        if not root.exists():
            continue
        files = [
            str(path.relative_to(skill_dir))
            for path in sorted(root.rglob("*"))
            if path.is_file()
        ]
        setattr(resources, dir_name, files)
    return resources
