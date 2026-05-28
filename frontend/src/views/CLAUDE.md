# Views — 页面视图（占位）

当前项目使用 `App.vue` 内的 TabBar 切换视图，页面组件直接放在 `App.vue` 中渲染。此目录为 Vue Router 页面视图预留。

## 当前状态

目录为空。如需引入路由，在此目录创建 `*View.vue` 页面组件。

## 核心规则

- 页面组件命名：`<Domain>View.vue`（如 `PracticeView.vue`、`AnalyticsView.vue`）
- View 组件负责页面编排（组合 business 组件），不直接调用 API
- API 调用通过 `services/` + `composables/` 封装
- 使用 `<script setup>` 语法
- 路径导入使用 `@/` 绝对路径

## 修改后必做

1. 新增 view 后更新根目录 CLAUDE.md 和 `frontend/CLAUDE.md`
