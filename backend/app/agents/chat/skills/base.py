"""Skills 系统基类 — Skill + SkillRegistry

Progressive Disclosure 架构：
- Layer 1: Metadata（name, description, triggers, priority）→ 始终加载
- Layer 2: Instruction（instruction_template）→ 按需加载
- Layer 3: Resources → 条件触发
"""
from dataclasses import dataclass, field


@dataclass
class Skill:
    """面试官技能定义"""
    name: str
    description: str
    triggers: list[str] = field(default_factory=list)
    priority: int = 50
    instruction_template: str | None = None
    always_active: bool = False

    @property
    def metadata_line(self) -> str:
        """Layer 1: 单行 metadata 格式化"""
        return f"- [{self.name}] {self.description}"

    def get_instruction(self, context: dict | None = None) -> str:
        """加载 Layer 2: 返回格式化的指令文本"""
        if not self.instruction_template:
            return ""
        if not context:
            return self.instruction_template
        try:
            return self.instruction_template.format(**context)
        except (KeyError, IndexError):
            return self.instruction_template


class SkillRegistry:
    """技能注册表 — 管理所有可用 skill"""

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        """注册一个 skill（同名覆盖）"""
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill | None:
        """按名称检索 skill"""
        return self._skills.get(name)

    def get_all_metadata(self) -> str:
        """Layer 1: 返回所有 skill 的 metadata，按优先级降序排列"""
        if not self._skills:
            return ""
        sorted_skills = sorted(self._skills.values(), key=lambda s: s.priority, reverse=True)
        return "\n".join(s.metadata_line for s in sorted_skills)

    def match_skills(self, state: dict) -> list[Skill]:
        """根据对话状态匹配触发的 skill

        匹配规则：
        - always_active=True 的 skill 始终包含
        - 其他 skill：triggers 中任一关键词出现在 user_message 或 keywords 中
        """
        if not self._skills:
            return []

        user_message = state.get("user_message", "")
        keywords = state.get("keywords", [])
        search_text = user_message + " " + " ".join(keywords)

        matched = []
        for skill in self._skills.values():
            if skill.always_active or any(t in search_text for t in skill.triggers):
                matched.append(skill)
        return matched
