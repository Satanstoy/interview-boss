# Components — 组件目录

> 位置：`frontend/src/components/` | 上游：`App.vue`, composables | 下游：`services/` 调用 API
> 职责：Vue 组件，分为通用组件和业务组件两个子目录。

## 子目录

- `common/` — 通用 UI 组件（DataTable、TabBar、PaginationBar 等），无业务依赖
- `business/` — 业务组件（MasterBankList、PracticePanel、SettingsPanel 等）

## 规则

- 通用组件禁止导入 `services/` 或 `composables/` 中的业务模块
- 业务组件通过 composables 获取数据，不直接调用 API
- 组件规范见 `.claude/rules/vue-components.md`（编辑 Vue 文件时自动加载）
