# Stores — 状态目录（空）

当前项目未启用 Pinia。跨组件共享状态主要在 `composables/` 中用模块级 ref/函数封装，页面级共享数据由 `AuthenticatedLayout.vue` 调用 composables 后通过 `provide('appData')` 给 views 使用。

## 当前状态

目录为空。如需引入 store，先确认是否能继续放在现有 composable；只有确实需要统一 store 层时再新增。

## 核心规则

- 不要为了单个页面状态引入 Pinia
- 如新增 store，文件命名 `use<Domain>Store.js`，并通过 `services/` 调 API
- 新增状态层后同步 `frontend/CLAUDE.md` 的目录结构和数据流说明

## 修改后必做

1. 新增 store 后更新根目录 CLAUDE.md 和 `frontend/CLAUDE.md`
