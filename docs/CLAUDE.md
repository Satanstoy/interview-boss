# Docs — 历史经验库

Bug 修复记录和 TDD 开发记录，供后续开发参考。

## 目录结构

```
docs/
├── agents/            ← agent/子代理相关说明
├── analysis/          ← 分析材料和审计记录
├── bug-reports/       ← 后端 bug 修复记录（按日期+描述命名）
├── tdd-reports/       ← 后端 TDD 开发记录
├── dev-log/           ← 每次开发/设计活动的简要记录
├── superpowers/
│   ├── specs/         ← Superpowers brainstorming 产出的设计规格
│   └── plans/         ← Superpowers writing-plans 产出的实施计划
├── frontend/
│   ├── bug-reports/   ← 前端 bug 修复记录
│   └── tdd-reports/   ← 前端 TDD 开发记录
└── test-page.png
```

## 使用规则

- **修 Bug 前**：先搜 `bug-reports/` 是否有类似问题，避免重复踩坑
- **开发新功能前**：先搜 `tdd-reports/` 了解相关模块的历史设计决策
- **修 Bug 后**：在对应目录创建 `YYYY-MM-DD-描述/` 文件夹，包含 `bug.md`、`fix_bug_plan.md`、`test_report.md`
- **新功能后**：在对应目录创建 `YYYY-MM-DD-描述/` 文件夹，包含 `tdd_plan.md`、`tdd_report.md`
- 本次洞察工作台 TDD 记录位于 `tdd-reports/2026-08-04-insights-dashboard/`，包含 RED、GREEN、REFACTOR 和汇总报告。
- **后端相关** → 放 `bug-reports/` 或 `tdd-reports/`
- **前端相关** → 放 `frontend/bug-reports/` 或 `frontend/tdd-reports/`
- **设计规格** → 放 `superpowers/specs/`
- `docs/specs/` 也存放项目内临时/产品 spec；修改这类 spec 时要先对齐当前代码事实，避免把已存在的 pipeline、metadata 或 ledger 能力写成“尚不存在”。
- **实施计划** → 放 `superpowers/plans/`
- MiMo/DeepSeek reasoning 相关实施计划需明确区分 `reasoning_content` 原始模型推理、公开摘要 fallback、以及前端“面试官推理”展示语义。
- **开发活动记录** → 放 `dev-log/`
- **agent 协作/分析材料** → 放 `agents/` 或 `analysis/`

## 命名规范

- 目录名：`YYYY-MM-DD-kebab-case描述`
- 文件名：`bug.md`、`bug_preview.md`、`fix_bug_plan.md`、`bug_verification.md`、`test_report.md`
- TDD 文件名：`tdd_plan.md`、`red_phase.md`、`green_phase.md`、`refactor_phase.md`、`tdd_report.md`
