"""默认面试技能注册 — 从 SKILL.md 文件加载

每个 skill 是一个目录，包含 SKILL.md 文件：
- YAML frontmatter: name, description, triggers, priority, always_active
- Markdown body: instruction_template（指令内容）
"""
from pathlib import Path

from app.agents.chat.skills.base import SkillRegistry
from app.agents.chat.skills.loader import load_skill_from_file

SKILLS_DIR = Path(__file__).parent


def get_default_registry() -> SkillRegistry:
    """获取包含所有默认面试 skill 的注册表（从 SKILL.md 文件加载）"""
    registry = SkillRegistry()
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            skill = load_skill_from_file(skill_dir)
            registry.register(skill)
    return registry
