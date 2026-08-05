# Router — Vue Router 配置

当前项目已使用 Vue Router 4。`App.vue` 是薄壳，挂载 `<router-view />`、`Toaster` 和全局 `TooltipProvider`；认证初始化完成后调用 `markAuthReady()`，路由守卫再判断登录态。

## 当前路由

- `/login` → `BlankLayout.vue` → `LoginView.vue`
- 已登录路由挂在 `AuthenticatedLayout.vue` 下：`/master-bank`, `/chat/:sessionId?`, `/jd`, `/interview`, `/mock-interview`, `/knowledge-graph`, `/import`, `/coding`, `/settings?section=ai?`
- `/` 和未知路径重定向到 `/master-bank`
- `preview=1` 可绕过已登录页面的认证守卫，用于预览

## 核心规则

- 使用 `createRouter` + `createWebHistory`
- 路由组件保持懒加载：`() => import('@/views/XxxView.vue')`
- 认证守卫放 `router/index.js`，登录态来自 `composables/useAuth.js` 的 `currentUser`
- 新增已登录页面时挂在 `AuthenticatedLayout.vue` children 下，并同步侧边栏/路由映射
- views/ 下的页面组件与 business/ 下的业务组件配合使用

## 修改后必做

1. 改路由后运行 `cd frontend && npm run build`
2. 更新根目录 CLAUDE.md 和 `frontend/CLAUDE.md` 的路由表
