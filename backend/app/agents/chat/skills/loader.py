"""SKILL.md 文件加载器 — 从 YAML frontmatter + Markdown body 解析 Skill 定义

遵循 AgentSkills.io 规范：
- YAML frontmatter 包含 metadata（name, description, triggers, priority 等）
- Markdown body 作为 instruction_template（指令内容）
"""
from pathlib import Path

import yaml

from app.agents.chat.skills.base import Skill


def load_skill_from_file(skill_dir: Path) -> Skill:
    """从 SKILL.md 文件加载 skill 定义

    Args:
        skill_dir: skill 目录路径（包含 SKILL.md）

    Returns:
        解析后的 Skill 实例

    Raises:
        FileNotFoundError: SKILL.md 不存在
        ValueError: YAML frontmatter 缺少必填字段
    """
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        raise FileNotFoundError(f"SKILL.md not found in {skill_dir}")

    content = skill_md.read_text(encoding="utf-8")
    frontmatter, body = _parse_skill_md(content)

    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not name or not description:
        raise ValueError(f"SKILL.md in {skill_dir} missing required fields: name, description")

    return Skill(
        name=name,
        description=description,
        triggers=frontmatter.get("triggers", []),
        priority=frontmatter.get("priority", 50),
        instruction_template=body.strip() if body.strip() else None,
        always_active=frontmatter.get("always_active", False),
    )


def _parse_skill_md(content: str) -> tuple[dict, str]:
    """解析 SKILL.md 内容，分离 YAML frontmatter 和 Markdown body

    Args:
        content: SKILL.md 文件完整内容

    Returns:
        (frontmatter_dict, body_text) 元组
    """
    if not content.startswith("---"):
        return {}, content

    # 找到第二个 --- 的位置
    second_delim = content.find("---", 3)
    if second_delim == -1:
        return {}, content

    yaml_str = content[3:second_delim]
    body = content[second_delim + 3:]

    frontmatter = yaml.safe_load(yaml_str) or {}
    return frontmatter, body
