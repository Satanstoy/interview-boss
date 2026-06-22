# Docs — 历史经验库

Bug 修复记录和 TDD 开发记录，供后续开发参考。

## 目录结构

```
docs/
├── bug-reports/       ← 后端 bug 修复记录（按日期+描述命名）
├── tdd-reports/       ← 后端 TDD 开发记录
├── dev-log/           ← 每次开发/设计活动的简要记录
├── superpowers/
│   ├── specs/         ← Superpowers brainstorming 产出的设计规格
│   └── plans/         ← Superpowers writing-plans 产出的实施计划
├── frontend/
│   ├── bug-reports/   ← 前端 bug 修复记录
│   └── tdd-reports/   ← 前端 TDD 开发记录
├── logo.png
└── test-page.png
```

## 使用规则

- **修 Bug 前**：先搜 `bug-reports/` 是否有类似问题，避免重复踩坑
- **开发新功能前**：先搜 `tdd-reports/` 了解相关模块的历史设计决策
- **修 Bug 后**：在对应目录创建 `YYYY-MM-DD-描述/` 文件夹，包含 `bug.md`、`fix_bug_plan.md`、`test_report.md`
- **新功能后**：在对应目录创建 `YYYY-MM-DD-描述/` 文件夹，包含 `tdd_plan.md`、`tdd_report.md`
- **后端相关** → 放 `bug-reports/` 或 `tdd-reports/`
- **前端相关** → 放 `frontend/bug-reports/` 或 `frontend/tdd-reports/`
- **设计规格** → 放 `superpowers/specs/`
- **实施计划** → 放 `superpowers/plans/`
- **开发活动记录** → 放 `dev-log/`

## 命名规范

- 目录名：`YYYY-MM-DD-kebab-case描述`
- 文件名：`bug.md`、`bug_preview.md`、`fix_bug_plan.md`、`bug_verification.md`、`test_report.md`
- TDD 文件名：`tdd_plan.md`、`red_phase.md`、`green_phase.md`、`refactor_phase.md`、`tdd_report.md`
