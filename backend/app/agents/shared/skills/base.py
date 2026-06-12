"""Shared skill primitives used by agent-specific skill directories."""

from dataclasses import dataclass, field


def _triggers_match(triggers: list[str], search_text: str, skill_name: str) -> bool:
    """Context-aware trigger matching to reduce obvious false positives."""
    for trigger in triggers:
        if trigger not in search_text:
            continue
        if skill_name == "hr-soft-skills" and trigger in ("团队",):
            hr_context = ["合作", "协作", "氛围", "文化", "管理", "角色", "选择"]
            if not any(ctx in search_text for ctx in hr_context):
                continue
        return True
    return False


@dataclass
class Skill:
    """Agent skill loaded from a SKILL.md directory."""

    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    priority: int = 50
    instruction_template: str | None = None
    always_active: bool = False
    strategy_rules: dict | None = None
    allowed_agents: list[str] = field(default_factory=list)
    prompt_role: str | None = None

    def get_strategy_rules(self) -> dict:
        return self.strategy_rules if self.strategy_rules is not None else {}

    @property
    def metadata_line(self) -> str:
        return f"- [{self.name}] {self.description}"

    def get_instruction(self, context: dict | None = None) -> str:
        if not self.instruction_template:
            return ""
        if not context:
            return self.instruction_template
        try:
            return self.instruction_template.format(**context)
        except (KeyError, IndexError):
            return self.instruction_template


class SkillRegistry:
    """Registry for skills available to one agent."""

    def __init__(self, agent_name: str | None = None) -> None:
        self.agent_name = agent_name
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if self.agent_name and skill.allowed_agents:
            if self.agent_name not in skill.allowed_agents:
                return
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def get_all_metadata(self) -> str:
        if not self._skills:
            return ""
        sorted_skills = sorted(
            self._skills.values(), key=lambda s: s.priority, reverse=True
        )
        return "\n".join(s.metadata_line for s in sorted_skills)

    def match_skills(self, state: dict) -> list[Skill]:
        if not self._skills:
            return []

        user_message = state.get("user_message", "")
        keywords = state.get("keywords", [])
        search_text = user_message + " " + " ".join(keywords)
        message_count = state.get("message_count", 0)

        matched = []
        for skill in self._skills.values():
            if skill.always_active:
                matched.append(skill)
                continue
            if _triggers_match(skill.triggers, search_text, skill.name):
                matched.append(skill)

        if message_count >= 12:
            hr_skill = self._skills.get("hr-soft-skills")
            if hr_skill and hr_skill not in matched:
                matched.append(hr_skill)

        return matched
