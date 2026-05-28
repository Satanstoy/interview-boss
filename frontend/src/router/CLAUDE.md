# Router — Vue Router 配置（占位）

当前项目使用 `App.vue` 内的 TabBar 组件切换视图（activeTab ref），未使用 Vue Router。

## 当前状态

`index.js` 为占位文件，导出 `null`。如需引入路由，在此文件中配置。

## 核心规则

- 启用路由时：使用 `createRouter` + `createWebHistory`
- 路由懒加载：`() => import('@/views/XxxView.vue')`
- 路由守卫放 `router/index.js`，认证逻辑复用 `services/http.js`
- views/ 下的页面组件与 business/ 下的业务组件配合使用

## 修改后必做

1. 启用路由后更新根目录 CLAUDE.md 和 `frontend/CLAUDE.md` 的目录结构
