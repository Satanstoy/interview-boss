"""Skills 系统基类 — Skill + SkillRegistry

Progressive Disclosure 架构：
- Layer 1: Metadata（name, description, triggers, priority）→ 始终加载
- Layer 2: Instruction（instruction_template）→ 按需加载
- Layer 3: Resources → 条件触发
"""
from dataclasses import dataclass, field


def _triggers_match(triggers: list[str], search_text: str, skill_name: str) -> bool:
    """上下文感知的触发词匹配，减少误触发"""
    for trigger in triggers:
        if trigger not in search_text:
            continue
        # hr-soft-skills 特殊处理：泛化触发词需要上下文验证
        if skill_name == "hr-soft-skills" and trigger in ("团队",):
            hr_context = ["合作", "协作", "氛围", "文化", "管理", "角色", "选择"]
            if not any(ctx in search_text for ctx in hr_context):
                continue
        return True
    return False


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
        - 面试后期（12+ 消息）自动激活 hr-soft-skills
        """
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

        # 面试后期（12+ 消息 = 6+ 轮问答）自动激活 hr-soft-skills
        if message_count >= 12:
            hr_skill = self._skills.get("hr-soft-skills")
            if hr_skill and hr_skill not in matched:
                matched.append(hr_skill)

        return matched
