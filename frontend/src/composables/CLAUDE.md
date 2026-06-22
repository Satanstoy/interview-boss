# Composables — 领域逻辑复用

Vue 3 Composition API 的可复用逻辑，`use*` 命名前缀。

## 文件清单

| 文件 | 职责 |
|------|------|
| `useBatchActions.js` | 批量操作逻辑（选择、删除、移动） |
| `useHighlightNav.js` | 导航高亮 |
| `useMergeDialog.js` | 合并弹窗逻辑 |
| `useMotionPresets.js` | 动画预设 |
| `useNotification.js` | 通知提示 |
| `usePractice.js` | 练习流程逻辑 |
| `useQuestionOps.js` | 题目操作（编辑、拆分、删除） |
| `useSelection.js` | 多选逻辑 |
| `useSidebar.js` | 侧边栏状态 |
| `useTabScroll.js` | Tab 滚动 |
| `useAuth.js` | 认证状态单例；登录成功、自动刷新、统一退出登录（调用后端 logout 清 refresh cookie 后清本地状态） |
| `useTheme.js` | 主题切换 |

## 核心规则

- 纯逻辑复用，不包含模板
- 通过参数和返回值与组件交互
- 命名必须以 `use` 开头

## 修改后必做

1. `cd frontend && npm run build` 确认构建通过
2. 更新本文件（如新增 composable）
