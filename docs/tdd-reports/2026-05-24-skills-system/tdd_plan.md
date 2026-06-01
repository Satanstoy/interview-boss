# TDD 开发计划

**功能名称:** Skills 系统 — 面试官技能模块化架构
**日期:** 2026-05-24
**TDD 状态:** 🔴 红灯阶段准备

## 需求描述

为 InterviewBoss 面试 chatbot 引入 Skills 系统，将面试官行为拆分为可组合的技能模块（节奏控制、项目深挖、八股问答、算法手撕、HR/软素质），采用 Progressive Disclosure 架构：metadata 始终加载 → instruction 按需注入 → resources 条件触发。

## 验收标准

- [ ] Skill 基类定义清晰，包含 name/description/triggers/priority
- [ ] SkillRegistry 支持注册、检索、按触发条件匹配
- [ ] 所有 skill 的 metadata 可合并为 system prompt 片段
- [ ] 单个 skill 的 instruction 可按需加载
- [ ] 与现有 prompts.py 的 system prompt 无缝集成
- [ ] 空 registry 不影响现有流程（向后兼容）

## 测试清单（按优先级排序）

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| T-001 | Skill 基类 — 创建带 metadata 的 skill | name, description, triggers, priority | 属性正确设置 | ⏳ 待写 |
| T-002 | SkillRegistry — 注册并检索 skill | register(skill), get("name") | 返回正确的 skill | ⏳ 待写 |
| T-003 | SkillRegistry — 获取全部 metadata | register 3 skills, get_all_metadata() | 返回所有 skill 的 metadata 字符串 | ⏳ 待写 |
| T-004 | SkillRegistry — 按触发条件匹配 | state 含 intent/keywords | 返回匹配的 skill 列表 | ⏳ 待写 |
| T-005 | Skill — instruction 按需加载 | skill.get_instruction(context) | 返回格式化的指令文本 | ⏳ 待写 |
| T-006 | 集成 — 构建 skill-aware prompt | registry + state | system prompt 包含 active skill 指令 | ⏳ 待写 |
| T-007 | SkillRegistry — 空注册表 | 空 registry | get_all_metadata() 返回空字符串 | ⏳ 待写 |
| T-008 | SkillRegistry — 优先级排序 | skills 有不同 priority | metadata 按 priority 排序 | ⏳ 待写 |

## 测试用例详细设计

### T-001: Skill 基类
```python
def test_skill_metadata_properties():
    skill = Skill(name="test", description="desc", triggers=["keyword"], priority=10)
    assert skill.name == "test"
    assert skill.description == "desc"
    assert skill.triggers == ["keyword"]
    assert skill.priority == 10
```

### T-002: SkillRegistry 注册检索
```python
def test_registry_register_and_get():
    registry = SkillRegistry()
    skill = Skill(name="test", description="desc")
    registry.register(skill)
    assert registry.get("test") is skill
    assert registry.get("nonexistent") is None
```

### T-003: 全部 metadata
```python
def test_registry_get_all_metadata():
    registry = SkillRegistry()
    registry.register(Skill(name="a", description="A skill", priority=10))
    registry.register(Skill(name="b", description="B skill", priority=5))
    metadata = registry.get_all_metadata()
    assert "A skill" in metadata
    assert "B skill" in metadata
```

### T-004: 按触发条件匹配
```python
def test_registry_match_by_trigger():
    registry = SkillRegistry()
    registry.register(Skill(name="project", description="项目深挖", triggers=["项目", "GLEAR"]))
    state = {"user_message": "我做了GLEAR项目", "keywords": ["GLEAR"]}
    matched = registry.match_skills(state)
    assert any(s.name == "project" for s in matched)
```

### T-005: instruction 按需加载
```python
def test_skill_get_instruction():
    skill = Skill(name="test", description="desc", instruction_template="请追问{topic}层")
    result = skill.get_instruction({"topic": "项目架构"})
    assert "追问项目架构" in result
```

### T-006: 集成构建 prompt
```python
def test_build_skill_prompt():
    registry = SkillRegistry()
    registry.register(Skill(name="rhythm", description="节奏控制", priority=100, instruction_template="穿插式提问"))
    prompt = build_skill_prompt(registry, active_skills=["rhythm"])
    assert "穿插式提问" in prompt
```

### T-007: 空注册表
```python
def test_empty_registry():
    registry = SkillRegistry()
    assert registry.get_all_metadata() == ""
    assert registry.match_skills({}) == []
    assert registry.get("any") is None
```

### T-008: 优先级排序
```python
def test_registry_priority_ordering():
    registry = SkillRegistry()
    registry.register(Skill(name="low", description="低优先级", priority=10))
    registry.register(Skill(name="high", description="高优先级", priority=100))
    metadata = registry.get_all_metadata()
    assert metadata.index("高优先级") < metadata.index("低优先级")
```

## 红-绿-重构循环计划

- [ ] 循环 1: T-001 — Skill 基类
- [ ] 循环 2: T-002 — SkillRegistry 注册检索
- [ ] 循环 3: T-007 — 空注册表兼容
- [ ] 循环 4: T-003 — 全部 metadata 输出
- [ ] 循环 5: T-008 — 优先级排序
- [ ] 循环 6: T-004 — 触发条件匹配
- [ ] 循环 7: T-005 — instruction 按需加载
- [ ] 循环 8: T-006 — 集成构建 prompt

## 文件结构

```
backend/app/agents/chat/
├── skills/
│   ├── __init__.py          # Skill, SkillRegistry 导出
│   ├── base.py              # Skill 基类 + SkillRegistry
│   └── builder.py           # build_skill_prompt() 集成函数
└── tests/
    └── test_chat_skills.py  # TDD 测试
```
