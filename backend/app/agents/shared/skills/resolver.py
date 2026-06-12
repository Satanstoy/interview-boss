"""Agent-specific skill registry loading."""

from pathlib import Path
from functools import lru_cache

from app.agents.shared.skills.base import SkillRegistry
from app.agents.shared.skills.loader import load_skill_from_file


AGENTS_DIR = Path(__file__).resolve().parents[2]


def _load_skills_from_dir(registry: SkillRegistry, skills_dir: Path) -> None:
    if not skills_dir.exists():
        return
    for skill_dir in sorted(skills_dir.iterdir()):
        if not skill_dir.is_dir():
            continue
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            registry.register(load_skill_from_file(skill_dir))


@lru_cache(maxsize=32)
def get_agent_skill_registry(agent_name: str) -> SkillRegistry:
    """Load skills for one agent from `backend/app/agents/<agent>/skills`."""
    registry = SkillRegistry(agent_name=agent_name)
    _load_skills_from_dir(registry, AGENTS_DIR / agent_name / "skills")
    return registry
