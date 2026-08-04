"""
TDD 测试 — Skills 系统

Progressive Disclosure 架构：
- Layer 1: Metadata（始终加载到 system prompt）
- Layer 2: Instruction（LLM 按需加载）
- Layer 3: Resources（条件触发）

测试清单：
- T-001: Skill 基类 — metadata 属性
- T-002: SkillRegistry — 注册检索
- T-003: SkillRegistry — 全部 metadata
- T-004: SkillRegistry — 触发条件匹配
- T-005: Skill — instruction 按需加载
- T-006: 集成 — 构建 skill-aware prompt
- T-007: SkillRegistry — 空注册表兼容
- T-008: SkillRegistry — 优先级排序
"""

import pytest


# ═══════════════════════════════════════════════════
#  T-001: Skill 基类 — metadata 属性
# ═══════════════════════════════════════════════════
class TestSkillMetadata:
    """Skill 基类的 metadata 属性测试"""

    def test_skill_creation_with_all_fields(self):
        """创建 skill 时所有属性应正确设置"""
        from app.agents.chat.skills.base import Skill

        skill = Skill(
            name="project_deep_dive",
            description="项目深挖：从简历项目出发，3-5层追问",
            triggers=["项目", "GLEAR", "实习"],
            priority=80,
            instruction_template="从候选人的项目出发，连续追问{layers}层。",
        )
        assert skill.name == "project_deep_dive"
        assert skill.description == "项目深挖：从简历项目出发，3-5层追问"
        assert skill.triggers == ["项目", "GLEAR", "实习"]
        assert skill.priority == 80
        assert skill.instruction_template == "从候选人的项目出发，连续追问{layers}层。"

    def test_skill_creation_minimal_fields(self):
        """只提供必填字段时，可选字段应有默认值"""
        from app.agents.chat.skills.base import Skill

        skill = Skill(name="test", description="测试技能")
        assert skill.name == "test"
        assert skill.description == "测试技能"
        assert skill.triggers == []
        assert skill.priority == 50
        assert skill.instruction_template is None
        assert skill.always_active is False


# ═══════════════════════════════════════════════════
#  T-002: SkillRegistry — 注册检索
# ═══════════════════════════════════════════════════
class TestSkillRegistryRegister:
    """SkillRegistry 注册和检索测试"""

    def test_register_and_get(self):
        """注册 skill 后应能按名称检索"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        skill = Skill(name="test", description="desc")
        registry.register(skill)

        assert registry.get("test") is skill

    def test_get_nonexistent_returns_none(self):
        """检索不存在的 skill 应返回 None"""
        from app.agents.chat.skills.base import SkillRegistry

        registry = SkillRegistry()
        assert registry.get("nonexistent") is None

    def test_register_multiple_skills(self):
        """注册多个 skill 后各自独立"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        s1 = Skill(name="a", description="A")
        s2 = Skill(name="b", description="B")
        registry.register(s1)
        registry.register(s2)

        assert registry.get("a") is s1
        assert registry.get("b") is s2

    def test_register_overwrites_existing(self):
        """重复注册同名 skill 应覆盖旧的"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        s1 = Skill(name="test", description="old")
        s2 = Skill(name="test", description="new")
        registry.register(s1)
        registry.register(s2)

        assert registry.get("test").description == "new"


# ═══════════════════════════════════════════════════
#  T-007: SkillRegistry — 空注册表兼容
# ═══════════════════════════════════════════════════
class TestSkillRegistryEmpty:
    """空注册表应安全返回空值，不抛异常"""

    def test_empty_registry_metadata(self):
        """空注册表 get_all_metadata() 应返回空字符串"""
        from app.agents.chat.skills.base import SkillRegistry

        registry = SkillRegistry()
        assert registry.get_all_metadata() == ""

    def test_empty_registry_match(self):
        """空注册表 match_skills() 应返回空列表"""
        from app.agents.chat.skills.base import SkillRegistry

        registry = SkillRegistry()
        assert registry.match_skills({}) == []

    def test_empty_registry_get(self):
        """空注册表 get() 应返回 None"""
        from app.agents.chat.skills.base import SkillRegistry

        registry = SkillRegistry()
        assert registry.get("any") is None


# ═══════════════════════════════════════════════════
#  T-003: SkillRegistry — 全部 metadata 输出
# ═══════════════════════════════════════════════════
class TestSkillRegistryMetadata:
    """SkillRegistry 的 metadata 输出测试"""

    def test_get_all_metadata_contains_all_skills(self):
        """get_all_metadata() 应包含所有已注册 skill 的描述"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        registry.register(Skill(name="a", description="项目深挖", priority=80))
        registry.register(Skill(name="b", description="八股问答", priority=60))

        metadata = registry.get_all_metadata()
        assert "项目深挖" in metadata
        assert "八股问答" in metadata

    def test_get_all_metadata_format(self):
        """metadata 应包含 skill 名称和描述的格式化文本"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        registry.register(
            Skill(name="project", description="项目深挖技能", priority=80)
        )

        metadata = registry.get_all_metadata()
        assert "project" in metadata
        assert "项目深挖技能" in metadata


# ═══════════════════════════════════════════════════
#  T-008: SkillRegistry — 优先级排序
# ═══════════════════════════════════════════════════
class TestSkillRegistryPriority:
    """SkillRegistry 按优先级排序测试"""

    def test_metadata_ordered_by_priority_desc(self):
        """metadata 应按优先级从高到低排列"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        registry.register(Skill(name="low", description="低优先级", priority=10))
        registry.register(Skill(name="high", description="高优先级", priority=100))
        registry.register(Skill(name="mid", description="中优先级", priority=50))

        metadata = registry.get_all_metadata()
        pos_high = metadata.index("高优先级")
        pos_mid = metadata.index("中优先级")
        pos_low = metadata.index("低优先级")

        assert pos_high < pos_mid < pos_low


# ═══════════════════════════════════════════════════
#  T-004: SkillRegistry — 触发条件匹配
# ═══════════════════════════════════════════════════
class TestSkillRegistryMatch:
    """SkillRegistry 按触发条件匹配测试"""

    def test_match_by_user_message_keyword(self):
        """用户消息中的关键词应触发匹配的 skill"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        registry.register(
            Skill(
                name="project",
                description="项目深挖",
                triggers=["项目", "GLEAR"],
            )
        )

        state = {"user_message": "我做了GLEAR这个项目", "keywords": []}
        matched = registry.match_skills(state)
        assert any(s.name == "project" for s in matched)

    def test_match_by_keywords(self):
        """state 中的 keywords 应触发匹配的 skill"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        registry.register(
            Skill(
                name="algorithm",
                description="算法手撕",
                triggers=["LRU", "排序", "算法"],
            )
        )

        state = {"user_message": "", "keywords": ["LRU", "缓存"]}
        matched = registry.match_skills(state)
        assert any(s.name == "algorithm" for s in matched)

    def test_no_match_returns_empty(self):
        """没有匹配时应返回空列表"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        registry.register(
            Skill(name="project", description="项目深挖", triggers=["项目"])
        )

        state = {"user_message": "你好", "keywords": []}
        matched = registry.match_skills(state)
        assert matched == []

    def test_multiple_skills_can_match(self):
        """多个 skill 可以同时匹配"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        registry.register(
            Skill(name="project", description="项目深挖", triggers=["项目"])
        )
        registry.register(
            Skill(name="theory", description="八股问答", triggers=["Redis"])
        )

        state = {"user_message": "项目中用了Redis", "keywords": ["Redis"]}
        matched = registry.match_skills(state)
        names = [s.name for s in matched]
        assert "project" in names
        assert "theory" in names

    def test_match_uses_both_message_and_keywords(self):
        """匹配应同时检查 user_message 和 keywords"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        registry.register(Skill(name="a", description="A", triggers=["alpha"]))
        registry.register(Skill(name="b", description="B", triggers=["beta"]))

        state = {"user_message": "alpha问题", "keywords": ["beta"]}
        matched = registry.match_skills(state)
        names = [s.name for s in matched]
        assert "a" in names
        assert "b" in names

    def test_always_active_skill_matches_without_triggers(self):
        """always_active=True 的 skill 应始终匹配，即使没有触发关键词"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        registry.register(
            Skill(
                name="rhythm",
                description="节奏控制",
                triggers=["面试", "开始"],
                always_active=True,
            )
        )

        state = {"user_message": "你好，我叫施杰", "keywords": []}
        matched = registry.match_skills(state)
        assert any(s.name == "rhythm" for s in matched)

    def test_always_active_included_with_other_matches(self):
        """always_active skill 应与其他触发匹配的 skill 一起返回"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        registry.register(
            Skill(
                name="rhythm", description="节奏", triggers=["面试"], always_active=True
            )
        )
        registry.register(Skill(name="project", description="项目", triggers=["项目"]))

        state = {"user_message": "我做了个项目", "keywords": []}
        matched = registry.match_skills(state)
        names = [s.name for s in matched]
        assert "rhythm" in names
        assert "project" in names

    def test_always_active_false_requires_trigger(self):
        """always_active=False（默认）的 skill 必须命中 triggers 才匹配"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        registry.register(Skill(name="project", description="项目", triggers=["项目"]))

        state = {"user_message": "你好", "keywords": []}
        matched = registry.match_skills(state)
        assert not any(s.name == "project" for s in matched)

    def test_hr_soft_skills_auto_activated_after_12_messages(self):
        """面试后期（12+ 消息）应自动激活 hr-soft-skills"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        registry.register(
            Skill(
                name="hr-soft-skills",
                description="HR 软素质",
                triggers=["职业规划", "团队"],
                priority=30,
            )
        )

        # 11 条消息 → 不自动激活
        state = {"user_message": "技术问题", "keywords": [], "message_count": 11}
        matched = registry.match_skills(state)
        assert not any(s.name == "hr-soft-skills" for s in matched)

        # 12 条消息 → 自动激活
        state = {"user_message": "技术问题", "keywords": [], "message_count": 12}
        matched = registry.match_skills(state)
        assert any(s.name == "hr-soft-skills" for s in matched)

    def test_hr_soft_skills_not_duplicated_when_triggered(self):
        """hr-soft-skills 同时被关键词触发和自动激活时不应重复"""
        from app.agents.chat.skills.base import Skill, SkillRegistry

        registry = SkillRegistry()
        registry.register(
            Skill(
                name="hr-soft-skills",
                description="HR 软素质",
                triggers=["职业规划"],
                priority=30,
            )
        )

        state = {
            "user_message": "我想聊聊职业规划",
            "keywords": [],
            "message_count": 14,
        }
        matched = registry.match_skills(state)
        hr_matches = [s for s in matched if s.name == "hr-soft-skills"]
        assert len(hr_matches) == 1


# ═══════════════════════════════════════════════════
#  T-009: adaptive-difficulty skill 基本验证
# ═══════════════════════════════════════════════════
class TestAdaptiveDifficultySkill:
    """adaptive-difficulty skill 的注册和属性验证"""

    def test_default_registry_contains_adaptive_difficulty(self):
        """默认注册表应包含 adaptive-difficulty skill"""
        from app.agents.chat.skills.defaults import get_default_registry

        registry = get_default_registry()
        skill = registry.get("adaptive-difficulty")
        assert skill is not None

    def test_adaptive_difficulty_is_always_active(self):
        """adaptive-difficulty 应该是 always_active，因为它是跨话题的元规则"""
        from app.agents.chat.skills.defaults import get_default_registry

        registry = get_default_registry()
        skill = registry.get("adaptive-difficulty")
        assert skill.always_active is True

    def test_adaptive_difficulty_has_instruction(self):
        """adaptive-difficulty 应该有 instruction_template"""
        from app.agents.chat.skills.defaults import get_default_registry

        registry = get_default_registry()
        skill = registry.get("adaptive-difficulty")
        assert skill.instruction_template is not None
        assert (
            "Funnel" in skill.instruction_template
            or "funnel" in skill.instruction_template
        )

    def test_adaptive_difficulty_always_in_matched(self):
        """adaptive-difficulty 应该始终出现在匹配结果中"""
        from app.agents.chat.skills.defaults import get_default_registry

        registry = get_default_registry()
        state = {"user_message": "你好", "keywords": []}
        matched = registry.match_skills(state)
        assert any(s.name == "adaptive-difficulty" for s in matched)


# ═══════════════════════════════════════════════════
#  T-005: Skill — instruction 按需加载
# ═══════════════════════════════════════════════════
class TestSkillInstruction:
    """Skill instruction 按需加载测试"""

    def test_get_instruction_with_template(self):
        """有 instruction_template 时应返回格式化文本"""
        from app.agents.chat.skills.base import Skill

        skill = Skill(
            name="project",
            description="项目深挖",
            instruction_template="从候选人的项目出发，连续追问{layers}层。",
        )
        result = skill.get_instruction({"layers": "3-5"})
        assert "追问3-5层" in result

    def test_get_instruction_without_template(self):
        """没有 instruction_template 时应返回空字符串"""
        from app.agents.chat.skills.base import Skill

        skill = Skill(name="test", description="desc")
        result = skill.get_instruction({})
        assert result == ""

    def test_get_instruction_with_missing_vars(self):
        """模板变量缺失时应原样返回（不抛异常）"""
        from app.agents.chat.skills.base import Skill

        skill = Skill(
            name="test",
            description="desc",
            instruction_template="追问{layers}层，考察{topic}。",
        )
        # 不传 layers 和 topic，应不抛异常
        result = skill.get_instruction({})
        assert isinstance(result, str)

    def test_get_instruction_returns_raw_when_no_context(self):
        """无 context 时模板变量保持原样"""
        from app.agents.chat.skills.base import Skill

        skill = Skill(
            name="test",
            description="desc",
            instruction_template="固定指令文本。",
        )
        result = skill.get_instruction()
        assert result == "固定指令文本。"


# ═══════════════════════════════════════════════════
#  T-006: 集成 — 构建 skill-aware prompt
# ═══════════════════════════════════════════════════
class TestBuildSkillPrompt:
    """集成测试：构建 skill-aware 的 prompt"""

    def test_build_prompt_with_active_skills(self):
        """active skills 的 instruction 应合并到 prompt 中"""
        from app.agents.chat.skills.base import Skill, SkillRegistry
        from app.agents.chat.skills.builder import build_skill_prompt

        registry = SkillRegistry()
        registry.register(
            Skill(
                name="rhythm",
                description="节奏控制",
                priority=100,
                instruction_template="采用穿插式节奏提问。",
            )
        )
        registry.register(
            Skill(
                name="project",
                description="项目深挖",
                priority=80,
                instruction_template="连续追问3-5层。",
            )
        )

        prompt = build_skill_prompt(registry, active_skills=["rhythm", "project"])
        assert "穿插式节奏提问" in prompt
        assert "连续追问3-5层" in prompt

    def test_build_prompt_with_no_active_skills(self):
        """没有 active skills 时应返回空字符串"""
        from app.agents.chat.skills.base import Skill, SkillRegistry
        from app.agents.chat.skills.builder import build_skill_prompt

        registry = SkillRegistry()
        registry.register(
            Skill(name="test", description="desc", instruction_template="指令")
        )

        prompt = build_skill_prompt(registry, active_skills=[])
        assert prompt == ""

    def test_build_prompt_ignores_nonexistent_skills(self):
        """active_skills 中不存在的 skill 名应被忽略"""
        from app.agents.chat.skills.base import Skill, SkillRegistry
        from app.agents.chat.skills.builder import build_skill_prompt

        registry = SkillRegistry()
        registry.register(
            Skill(name="real", description="真实", instruction_template="真实指令")
        )

        prompt = build_skill_prompt(registry, active_skills=["real", "fake"])
        assert "真实指令" in prompt
        assert "fake" not in prompt

    def test_build_prompt_empty_registry(self):
        """空注册表应返回空字符串"""
        from app.agents.chat.skills.base import SkillRegistry
        from app.agents.chat.skills.builder import build_skill_prompt

        registry = SkillRegistry()
        prompt = build_skill_prompt(registry, active_skills=["any"])
        assert prompt == ""

    def test_build_prompt_wraps_examples_as_illustrative(self):
        """few-shot 应保留，但必须被结构化标记为示例而非当前事实。"""
        from app.agents.chat.skills.base import Skill, SkillRegistry
        from app.agents.chat.skills.builder import build_skill_prompt

        registry = SkillRegistry()
        registry.register(
            Skill(
                name="rhythm",
                description="节奏控制",
                instruction_template=(
                    "## Instructions\n"
                    "- 根据候选人的真实回答追问。\n\n"
                    "## Example Sequence\n"
                    'R4: Switch — "You mentioned HNSW, explain efConstruction"\n\n'
                    "## Rules\n"
                    "- 不要使用示例作为真实题目。"
                ),
            )
        )

        prompt = build_skill_prompt(registry, active_skills=["rhythm"])

        assert "根据候选人的真实回答追问" in prompt
        assert "不要使用示例作为真实题目" in prompt
        assert "HNSW" in prompt
        assert "efConstruction" in prompt
        assert "<skill_instructions>" in prompt
        assert '<skill_instruction name="rhythm">' in prompt
        assert "illustrative few-shot examples, not facts" in prompt

    def test_build_prompt_preserves_sequence_sections(self):
        """Pattern/Sequence few-shot 应保留，用结构化边界降低误读。"""
        from app.agents.chat.skills.base import Skill, SkillRegistry
        from app.agents.chat.skills.builder import build_skill_prompt

        registry = SkillRegistry()
        registry.register(
            Skill(
                name="rhythm",
                description="节奏控制",
                instruction_template=(
                    "## Instructions\n"
                    "- 根据当前上下文发问。\n\n"
                    "## Pattern Sequence\n"
                    "R1: Self-intro -> ask about GLEAR project\n\n"
                    "## Boundaries\n"
                    "- 不要使用模式序列作为真实题目。"
                ),
            )
        )

        prompt = build_skill_prompt(registry, active_skills=["rhythm"])

        assert "根据当前上下文发问" in prompt
        assert "不要使用模式序列作为真实题目" in prompt
        assert "GLEAR" in prompt
        assert "illustrative few-shot examples, not facts" in prompt

    def test_default_interview_rhythm_prompt_uses_generic_examples(self):
        """默认节奏 skill 的 few-shot 应保留结构，但不含具体硬编码题目。"""
        from app.agents.chat.skills import build_skill_prompt, get_default_registry

        prompt = build_skill_prompt(get_default_registry(), ["interview-rhythm"])

        assert "Pattern Sequence" in prompt
        assert (
            "<one project from the candidate's resume or self-introduction>" in prompt
        )
        assert "HNSW" not in prompt
        assert "efConstruction" not in prompt
        assert "GLEAR" not in prompt


# ═══════════════════════════════════════════════════
#  T-010: SKILL.md 文件加载器
# ═══════════════════════════════════════════════════
class TestSkillLoader:
    """SKILL.md 文件加载器测试"""

    def test_load_skill_from_file_parses_frontmatter(self, tmp_path):
        """应正确解析 YAML frontmatter 字段"""
        from app.agents.chat.skills.loader import load_skill_from_file

        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\nname: test-skill\ndescription: "测试技能"\ntriggers: ["测试"]\npriority: 80\nalways_active: true\n---\n\n指令内容。',
            encoding="utf-8",
        )

        skill = load_skill_from_file(skill_dir)
        assert skill.name == "test-skill"
        assert skill.description == "测试技能"
        assert skill.triggers == ["测试"]
        assert skill.priority == 80
        assert skill.always_active is True

    def test_load_skill_from_file_extracts_body(self, tmp_path):
        """Markdown body 应作为 instruction_template"""
        from app.agents.chat.skills.loader import load_skill_from_file

        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\nname: test-skill\ndescription: "desc"\n---\n\n## Instructions\n\n这是指令内容。\n\n## Rules\n\n规则内容。',
            encoding="utf-8",
        )

        skill = load_skill_from_file(skill_dir)
        assert "这是指令内容" in skill.instruction_template
        assert "规则内容" in skill.instruction_template

    def test_load_skill_from_file_defaults(self, tmp_path):
        """缺少可选字段时应使用默认值"""
        from app.agents.chat.skills.loader import load_skill_from_file

        skill_dir = tmp_path / "minimal"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\nname: minimal\ndescription: "最小定义"\n---\n\n指令。',
            encoding="utf-8",
        )

        skill = load_skill_from_file(skill_dir)
        assert skill.triggers == []
        assert skill.priority == 50
        assert skill.always_active is False

    def test_load_skill_from_file_parses_standard_optional_fields(self, tmp_path):
        """标准 Agent Skill 可选字段应被保留，不要求项目私有顶层字段。"""
        from app.agents.chat.skills.loader import load_skill_from_file

        skill_dir = tmp_path / "standard-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: standard-skill\n"
            'description: "标准 skill"\n'
            "license: Apache-2.0\n"
            "compatibility: Requires python3\n"
            "allowed-tools: search_questions draw_questions\n"
            "metadata:\n"
            "  author: interview-boss\n"
            '  version: "1.0"\n'
            "---\n\n标准指令。",
            encoding="utf-8",
        )

        skill = load_skill_from_file(skill_dir)

        assert skill.license == "Apache-2.0"
        assert skill.compatibility == "Requires python3"
        assert skill.allowed_tools == ["search_questions", "draw_questions"]
        assert skill.metadata == {"author": "interview-boss", "version": "1.0"}

    def test_load_skill_from_file_rejects_name_that_does_not_match_directory(
        self, tmp_path
    ):
        """标准 Agent Skill 要求 name 与父目录名一致。"""
        from app.agents.chat.skills.loader import load_skill_from_file

        skill_dir = tmp_path / "actual-name"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\nname: other-name\ndescription: "名称不一致"\n---\n\n指令。',
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="must match parent directory"):
            load_skill_from_file(skill_dir)

    def test_load_skill_from_file_rejects_invalid_standard_name(self, tmp_path):
        """标准 Agent Skill name 只允许小写字母、数字和单个连字符。"""
        from app.agents.chat.skills.loader import load_skill_from_file

        skill_dir = tmp_path / "Bad--Name"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\nname: Bad--Name\ndescription: "非法名称"\n---\n\n指令。',
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="invalid skill name"):
            load_skill_from_file(skill_dir)

    def test_load_skill_from_file_indexes_standard_resource_directories(self, tmp_path):
        """references/scripts/assets 应被索引，但不自动并入 instruction。"""
        from app.agents.chat.skills.loader import load_skill_from_file

        skill_dir = tmp_path / "resourceful-skill"
        (skill_dir / "references").mkdir(parents=True)
        (skill_dir / "scripts").mkdir()
        (skill_dir / "assets").mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\nname: resourceful-skill\ndescription: "资源 skill"\n---\n\n核心指令。',
            encoding="utf-8",
        )
        (skill_dir / "references" / "mcp-tool-envelope.md").write_text(
            "Envelope details", encoding="utf-8"
        )
        (skill_dir / "scripts" / "validate_tool_envelope.py").write_text(
            "print('ok')", encoding="utf-8"
        )
        (skill_dir / "assets" / "template.txt").write_text("template", encoding="utf-8")

        skill = load_skill_from_file(skill_dir)

        assert skill.resources.references == ["references/mcp-tool-envelope.md"]
        assert skill.resources.scripts == ["scripts/validate_tool_envelope.py"]
        assert skill.resources.assets == ["assets/template.txt"]
        assert "Envelope details" not in skill.instruction_template

    def test_skill_resource_reader_blocks_path_traversal(self, tmp_path):
        """资源读取必须限制在 skill 目录内，禁止 ../ 跳出。"""
        from app.agents.chat.skills.loader import load_skill_from_file

        skill_dir = tmp_path / "safe-skill"
        (skill_dir / "references").mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            '---\nname: safe-skill\ndescription: "安全 skill"\n---\n\n核心指令。',
            encoding="utf-8",
        )
        (skill_dir / "references" / "guide.md").write_text(
            "safe guide", encoding="utf-8"
        )
        (tmp_path / "secret.md").write_text("secret", encoding="utf-8")

        skill = load_skill_from_file(skill_dir)

        assert skill.read_resource("references/guide.md") == "safe guide"
        with pytest.raises(ValueError, match="outside skill directory"):
            skill.read_resource("../secret.md")

    def test_loader_maps_interview_boss_metadata_to_runtime_fields(self, tmp_path):
        """InterviewBoss 扩展策略放在 metadata 命名空间时仍可驱动现有运行时。"""
        from app.agents.chat.skills.loader import load_skill_from_file

        skill_dir = tmp_path / "metadata-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: metadata-skill\n"
            'description: "metadata 驱动 skill"\n'
            "metadata:\n"
            "  interview-boss.triggers: [项目, RAG]\n"
            "  interview-boss.priority: 88\n"
            "  interview-boss.always-active: true\n"
            "  interview-boss.allowed-agents: [chat]\n"
            "  interview-boss.prompt-role: system-skill\n"
            "  interview-boss.strategy-rules:\n"
            "    deep_dive:\n"
            "      max_depth: 3\n"
            "---\n\n指令。",
            encoding="utf-8",
        )

        skill = load_skill_from_file(skill_dir)

        assert skill.triggers == ["项目", "RAG"]
        assert skill.priority == 88
        assert skill.always_active is True
        assert skill.allowed_agents == ["chat"]
        assert skill.prompt_role == "system-skill"
        assert skill.strategy_rules == {"deep_dive": {"max_depth": 3}}

    def test_loader_parses_interview_boss_metadata_scalar_strings(self, tmp_path):
        """字符串形式的私有策略标量应被安全解析，避免 bool('false') 误判。"""
        from app.agents.chat.skills.loader import load_skill_from_file

        skill_dir = tmp_path / "string-policy-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: string-policy-skill\n"
            'description: "字符串策略 skill"\n'
            "metadata:\n"
            '  interview-boss.priority: "77"\n'
            '  interview-boss.always-active: "false"\n'
            "---\n\n指令。",
            encoding="utf-8",
        )

        skill = load_skill_from_file(skill_dir)

        assert skill.priority == 77
        assert skill.always_active is False

    def test_load_skill_from_file_missing_file(self, tmp_path):
        """SKILL.md 不存在时应抛出 FileNotFoundError"""
        from app.agents.chat.skills.loader import load_skill_from_file

        skill_dir = tmp_path / "empty"
        skill_dir.mkdir()

        import pytest

        with pytest.raises(FileNotFoundError):
            load_skill_from_file(skill_dir)

    def test_load_skill_from_file_missing_required_fields(self, tmp_path):
        """缺少必填字段时应抛出 ValueError"""
        from app.agents.chat.skills.loader import load_skill_from_file
        import pytest

        skill_dir = tmp_path / "bad"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\ntriggers: ["test"]\n---\n\n内容。',
            encoding="utf-8",
        )

        with pytest.raises(ValueError, match="missing required fields"):
            load_skill_from_file(skill_dir)

    def test_get_default_registry_loads_from_files(self):
        """默认注册表应从 SKILL.md 文件加载所有 6 个 skill"""
        from app.agents.chat.skills.defaults import get_default_registry

        registry = get_default_registry()
        expected_skills = [
            "interview-rhythm",
            "adaptive-difficulty",
            "project-deep-dive",
            "theory-qa",
            "algorithm-coding",
            "hr-soft-skills",
        ]
        for name in expected_skills:
            assert registry.get(name) is not None, (
                f"Skill '{name}' not found in registry"
            )

    def test_get_default_registry_skills_have_instructions(self):
        """所有从文件加载的 skill 都应有 instruction_template"""
        from app.agents.chat.skills.defaults import get_default_registry

        registry = get_default_registry()
        for name in [
            "interview-rhythm",
            "adaptive-difficulty",
            "project-deep-dive",
            "theory-qa",
            "algorithm-coding",
            "hr-soft-skills",
        ]:
            skill = registry.get(name)
            assert skill.instruction_template is not None, (
                f"Skill '{name}' has no instruction"
            )


# ═══════════════════════════════════════════════════
#  T-011: Skill — strategy_rules 字段
# ═══════════════════════════════════════════════════
class TestSkillStrategyRules:
    """Skill 的 strategy_rules 字段和 get_strategy_rules() 方法测试"""

    def test_skill_with_strategy_rules(self):
        """创建 skill 时传入 strategy_rules 应正确存储"""
        from app.agents.chat.skills.base import Skill

        rules = {
            "deep_dive": {"max_depth": 5, "signal": "candidate elaborates"},
            "topic_shift": {"trigger": "silence > 10s"},
        }
        skill = Skill(
            name="test",
            description="desc",
            strategy_rules=rules,
        )
        assert skill.strategy_rules == rules

    def test_skill_strategy_rules_default_none(self):
        """不传 strategy_rules 时默认为 None"""
        from app.agents.chat.skills.base import Skill

        skill = Skill(name="test", description="desc")
        assert skill.strategy_rules is None

    def test_get_strategy_rules_returns_dict(self):
        """有 strategy_rules 时 get_strategy_rules() 返回 dict"""
        from app.agents.chat.skills.base import Skill

        rules = {"deep_dive": {"max_depth": 5}}
        skill = Skill(name="test", description="desc", strategy_rules=rules)
        assert skill.get_strategy_rules() == rules

    def test_get_strategy_rules_returns_empty_dict_when_none(self):
        """strategy_rules 为 None 时 get_strategy_rules() 返回空 dict"""
        from app.agents.chat.skills.base import Skill

        skill = Skill(name="test", description="desc")
        assert skill.get_strategy_rules() == {}

    def test_get_strategy_rules_returns_empty_dict_when_empty(self):
        """strategy_rules 为空 dict 时 get_strategy_rules() 返回空 dict"""
        from app.agents.chat.skills.base import Skill

        skill = Skill(name="test", description="desc", strategy_rules={})
        assert skill.get_strategy_rules() == {}


# ═══════════════════════════════════════════════════
#  T-012: Loader — 解析 strategy_rules
# ═══════════════════════════════════════════════════
class TestSkillLoaderStrategyRules:
    """SKILL.md 加载器对 strategy_rules 的解析测试"""

    def test_loader_parses_strategy_rules_from_yaml(self, tmp_path):
        """应从 YAML frontmatter 解析 strategy_rules"""
        from app.agents.chat.skills.loader import load_skill_from_file

        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\n"
            "name: test-skill\n"
            'description: "测试技能"\n'
            "strategy_rules:\n"
            "  deep_dive:\n"
            "    max_depth: 5\n"
            '    signal: "candidate elaborates"\n'
            "  clarification:\n"
            '    trigger: "ambiguous answer"\n'
            "---\n\n指令内容。",
            encoding="utf-8",
        )

        skill = load_skill_from_file(skill_dir)
        assert skill.strategy_rules is not None
        assert skill.strategy_rules["deep_dive"]["max_depth"] == 5
        assert skill.strategy_rules["clarification"]["trigger"] == "ambiguous answer"

    def test_loader_handles_missing_strategy_rules(self, tmp_path):
        """没有 strategy_rules 时应向后兼容（默认 None）"""
        from app.agents.chat.skills.loader import load_skill_from_file

        skill_dir = tmp_path / "no-rules"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\nname: no-rules\ndescription: "无规则"\n---\n\n指令。',
            encoding="utf-8",
        )

        skill = load_skill_from_file(skill_dir)
        assert skill.strategy_rules is None
        assert skill.get_strategy_rules() == {}

    def test_loader_strategy_rules_with_empty_dict(self, tmp_path):
        """空 strategy_rules 字段应解析为空 dict"""
        from app.agents.chat.skills.loader import load_skill_from_file

        skill_dir = tmp_path / "empty-rules"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\nname: empty-rules\ndescription: "空规则"\nstrategy_rules: {}\n---\n\n指令。',
            encoding="utf-8",
        )

        skill = load_skill_from_file(skill_dir)
        assert skill.strategy_rules == {}


# ═══════════════════════════════════════════════════
#  T-013: interview-tool-use skill — 注册与元数据
# ═══════════════════════════════════════════════════
class TestInterviewToolUseSkill:
    """interview-tool-use skill 的注册、元数据和 catalog 输出验证"""

    def test_default_registry_has_eight_skills(self):
        """默认注册表包含普通 skills、常驻 tool-use 和 profile-gated Agent skill。"""
        from app.agents.chat.skills.defaults import get_default_registry

        registry = get_default_registry()
        expected_skills = [
            "interview-rhythm",
            "adaptive-difficulty",
            "project-deep-dive",
            "theory-qa",
            "algorithm-coding",
            "hr-soft-skills",
            "interview-tool-use",
            "agent-interview",
        ]
        for name in expected_skills:
            assert registry.get(name) is not None, (
                f"Skill '{name}' not found in registry"
            )
        assert len(registry._skills) == 8

    def test_interview_tool_use_metadata_from_interview_boss_namespace(self):
        """interview-tool-use 应从 metadata.interview-boss.* 读取运行时字段"""
        from app.agents.chat.skills.defaults import get_default_registry

        registry = get_default_registry()
        skill = registry.get("interview-tool-use")
        assert skill is not None
        assert skill.always_active is True
        assert skill.priority == 100
        assert skill.kind == "tool-use"

    def test_build_skill_catalog_includes_tool_use_but_not_internal_markers(self):
        """build_skill_catalog 输出应包含 interview-tool-use 名称和描述，
        且 skill 自身的 description 不包含内部 marker 字符串"""
        from app.agents.chat.skills.defaults import get_default_registry
        from app.agents.chat.skills.builder import build_skill_catalog

        registry = get_default_registry()
        catalog = build_skill_catalog(registry)

        assert "interview-tool-use" in catalog

        skill = registry.get("interview-tool-use")
        desc_lower = skill.description.lower()
        internal_markers = [
            "search_questions",
            "draw_questions",
            "select_question",
            "project-deep-dive",
        ]
        for marker in internal_markers:
            assert marker not in desc_lower, (
                f"Internal marker '{marker}' leaked into skill description"
            )

    def test_load_skill_enum_matches_non_tool_use_registry_skills(self):
        """load_skill exposes only user-loadable skills and excludes tool-use policy."""
        from app.agents.chat.skills.defaults import get_default_registry
        from app.agents.chat.tools import SKILL_NAMES

        registry = get_default_registry()
        expected = sorted(
            skill.name
            for skill in registry._skills.values()
            if skill.kind != "tool-use" and not skill.job_profiles
        )

        assert sorted(SKILL_NAMES) == expected
        assert "interview-tool-use" not in SKILL_NAMES
