# Skills — Chat Agent 技能模块

Progressive Disclosure 架构的面试官技能系统。每个 skill 是一个独立目录，包含 `SKILL.md` 定义文件。

## 架构

```
skills/
├── base.py              ← Skill + SkillRegistry 基类（Layer 1/2/3 渐进加载）
├── loader.py            ← SKILL.md 文件加载器（YAML frontmatter + Markdown body）
├── builder.py           ← build_skill_prompt() 合并 active skills 为 prompt 片段
├── defaults.py          ← get_default_registry() 扫描所有子目录加载 skill
├── __init__.py          ← 统一导出
├── adaptive-difficulty/ ← 自适应难度调节
├── algorithm-coding/    ← 算法/手撕代码面试
├── hr-soft-skills/      ← HR 软技能面试
├── interview-rhythm/    ← 面试节奏控制
├── project-deep-dive/   ← 项目深挖
└── theory-qa/           ← 理论问答
```

## 三层渐进加载

| Layer | 内容 | 加载时机 |
|-------|------|---------|
| Layer 1 | Metadata（name, description, triggers, priority） | 始终加载 |
| Layer 2 | Instruction（instruction_template） | 按需加载 |
| Layer 3 | Resources | 条件触发 |

## SKILL.md 格式

```yaml
---
name: skill-name
description: 一句话描述
triggers: [触发词列表]
priority: 50  # 数值越大优先级越高
always_active: false
---

指令内容（Markdown 格式，Layer 2）
```

## 触发规则

- `always_active=true` 的 skill 始终匹配
- 其他 skill：triggers 中任一关键词出现在用户消息或关键词中
- `hr-soft-skills` 有特殊上下文验证：泛化触发词（如"团队"）需要配合上下文词（合作/协作/文化等）
- 面试后期（12+ 消息）自动激活 `hr-soft-skills`

## 核心规则

- 新增 skill：创建目录 + `SKILL.md`，无需修改 Python 代码（自动扫描加载）
- `base.py` 中的 `_triggers_match()` 做上下文感知匹配，减少误触发
- `builder.py` 合并多个 active skill 的 Layer 2 指令为一个 prompt 片段

## 修改后必做

1. 新增/修改 skill 后运行 `docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q`
2. 更新本文件
