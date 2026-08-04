# Skills — Chat Agent 技能模块

Progressive Disclosure 架构的面试官技能系统。每个 skill 是一个标准 Agent Skill package：独立目录 + 必需 `SKILL.md`，可选 `references/`、`scripts/`、`assets/`。

## 架构

```
skills/
├── base.py              ← shared skills 兼容导出
├── loader.py            ← shared loader 兼容导出
├── builder.py           ← chat-specific catalog 包装 + shared prompt builder
├── defaults.py          ← get_default_registry() 扫描所有子目录加载 skill
├── __init__.py          ← 统一导出
├── adaptive-difficulty/ ← 自适应难度调节
│   └── SKILL.md
├── algorithm-coding/    ← 算法/手撕代码面试
│   └── SKILL.md
├── hr-soft-skills/      ← HR 软技能面试
├── interview-rhythm/    ← 面试节奏控制
├── interview-tool-use/  ← MCP 工具调用规范（始终激活，kind=tool-use）
├── project-deep-dive/   ← 项目深挖
├── agent-interview/     ← Agent 开发 profile 专属的私有面试策略
└── theory-qa/           ← 理论问答
```

## 三层渐进加载

| Layer | 内容 | 加载时机 |
|-------|------|---------|
| Layer 1 | 标准 metadata（name, description）+ InterviewBoss runtime metadata | 始终加载 |
| Layer 2 | Instruction（`SKILL.md` body） | `load_skill` 按需加载 |
| Layer 3 | `references/`、`scripts/`、`assets/` 资源 | 默认只索引；当前运行时不自动读取或执行 |

## SKILL.md 格式

```yaml
---
name: skill-name
description: 一句话描述
metadata:
  interview-boss.triggers: [触发词列表]
  interview-boss.priority: 50  # 数值越大优先级越高
  interview-boss.always-active: false
---

指令内容（Markdown 格式，Layer 2）
```

`SKILL.md` 顶层只使用标准 Agent Skill 字段：`name`、`description`，以及可选 `license`、`compatibility`、`metadata`、`allowed-tools`。InterviewBoss 私有策略必须放在 `metadata.interview-boss.*` 命名空间；loader 会映射为运行时字段（`triggers`、`priority`、`always_active`、`strategy_rules` 等）。不要新增 `skill-pack.yaml`。

## 触发规则

- `always_active=true` 的 skill 始终匹配（`interview-rhythm`、`adaptive-difficulty`、`interview-tool-use`）
- 只有 `always_active=true` 且 `metadata.interview-boss.kind: tool-use` 的 skill 会自动注入每次 ReAct system prompt；普通行为类 skill 即使 always active，也只在被 `load_skill` 或 state `active_skills` 明确激活后注入完整 body
- 其他 skill：triggers 中任一关键词出现在用户消息或关键词中
- `hr-soft-skills` 有特殊上下文验证：泛化触发词（如"团队"）需要配合上下文词（合作/协作/文化等）
- 面试后期（12+ 消息）自动激活 `hr-soft-skills`

## 核心规则

- 新增 skill：创建目录 + `SKILL.md`，无需修改 Python 代码（自动扫描加载）
- skill 名称必须与父目录一致，并使用小写字母、数字和单个连字符
- 可选资源目录为 `references/`、`scripts/`、`assets/`；默认只索引不注入 prompt。`references/` 可作为开发者/测试文档；`scripts/` 不得由 Agent 自动执行，除非后续新增受限 runner 和对应测试
- `load_skill` 的公共 enum 只包含普通 skill；`agent-interview` 及其私有工具 schema 仅由 Agent profile 的内部 ReAct 动态注入，不能出现在外部 MCP 工具清单
- `base.py` 中的 `_triggers_match()` 做上下文感知匹配，减少误触发
- `builder.py` 负责 chat-specific Layer 1 catalog 文案；Layer 2 指令合并复用 shared `build_skill_prompt()`
- `interview-rhythm` 负责节奏和表达边界：它可以提醒 Agent 尊重后端 `InterviewLedger`，但不能替代 `question_plan.py` / MCP 工具层的题号和题型去重；同时避免“我抽个题”“来聊一个八股题”“换个方向”这类流程播报式话术
- `interview-rhythm` / `interview-tool-use` 必须与 chat runtime 的中国互联网大厂 + full-loop harness 对齐：覆盖项目深挖、八股基础、场景题/system design、手撕代码/coding/testing、HR/behavioral/STAR、communication 和反问信号；不要把 skill 写成单纯抽题流程

## 修改后必做

1. 新增/修改 skill 后运行 `docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q`
2. 更新本文件
