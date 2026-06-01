# Stores — Pinia 状态管理（占位）

当前项目状态管理在 `App.vue` 中通过 `ref` 实现，此目录为 Pinia store 预留。

## 当前状态

目录为空。如需引入 Pinia store，在此目录创建 `use*Store.js` 文件。

## 核心规则

- Store 文件命名：`use<Domain>Store.js`（如 `useAuthStore.js`）
- 只放跨组件共享的状态，组件内状态用 `ref`/`reactive`
- Store 中禁止直接 fetch，通过 `services/` 调用 API
- 配合 `composables/` 使用，composable 负责业务逻辑，store 负责状态

## 修改后必做

1. 新增 store 后更新根目录 CLAUDE.md 和 `frontend/CLAUDE.md`
