"""SKILL.md loader for reusable agent skills."""

from pathlib import Path

import yaml

from app.agents.shared.skills.base import Skill


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

    return Skill(
        name=name,
        description=description,
        triggers=frontmatter.get("triggers", []),
        priority=frontmatter.get("priority", 50),
        instruction_template=body.strip() if body.strip() else None,
        always_active=frontmatter.get("always_active", False),
        strategy_rules=frontmatter.get("strategy_rules"),
        allowed_agents=frontmatter.get("allowed_agents", []),
        prompt_role=frontmatter.get("prompt_role"),
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
