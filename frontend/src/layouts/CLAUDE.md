# Layouts — 布局组件

页面布局包装器，负责应用外壳、认证入口和主工作区骨架。

## 文件清单

| 文件 | 职责 |
|------|------|
| `AuthenticatedLayout.vue` | 已登录应用壳：侧边栏、顶栏、路由内容区、共享 appData provide、全局业务弹层 |
| `DefaultLayout.vue` | 默认布局：`min-h-screen` + 背景色（支持 light/dark） |
| `BlankLayout.vue` | 空白布局：纯 `<slot />`，无样式包装 |

## 核心规则

- `AuthenticatedLayout.vue` 是数据层边界，调用 composables 后通过 `provide('appData')` 交给 views 使用
- 顶栏和侧栏保持为主工作区常驻外壳，设置页等工作区页面优先走 Vue Router，而不是全屏覆盖
- 刷题通过 `/practice` 路由进入 `PracticeView.vue`，视图从布局提供的当前题库筛选结果和 `practicedQuestions` 组装闪卡工作台；布局只负责导航和共享数据，不再挂载全屏刷题弹层。
- **设置页统一走 Vue Router**（`/settings` 路由 → `SettingsView.vue` → `SettingsPage.vue`），不再使用覆盖层模式
- `AppSidebar` 的 `sidebarCollapsed` 状态由 `AuthenticatedLayout` 统一管理（通过 prop 传入，emit 回传），避免重复 ref 导致状态不同步
- 新增布局时保持简洁，只做布局框架
- `BlankLayout.vue` 用于登录等无侧栏页面

## 修改后必做

1. 新增布局后更新本文件
