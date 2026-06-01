# 绿灯阶段报告

**日期:** 2026-05-23

## 实现的功能

### useTabScroll composable（T-001, T-004）
- `frontend/src/composables/useTabScroll.js` — singleton 模式，跨组件共享滚动位置
- `saveScroll(tabKey, scrollTop)` — 保存指定 tab 的 scrollTop
- `restoreScroll()` — 在 `requestAnimationFrame` 中恢复滚动位置，避免与动画冲突
- `pendingRestore` 变量跟踪待恢复的 tab，防止重复恢复

### Crossfade 动画（T-002）
- `tab-fade` 过渡从 `opacity + translateY` 改为纯 `opacity` 渐变
- 去掉 `transform: translateY(12px)` 和 `translateY(-6px)`
- 消除动画位移与滚动恢复的视觉冲突

### @after-enter hook（T-003）
- `App.vue` 的 `<Transition>` 添加 `@after-enter="restoreScroll()"`
- 滚动恢复在进场动画完成后触发，确保 DOM 已就绪
- `onTabChange` 在切换前保存当前 tab 的 scrollTop

### useHighlightNav 重构
- 移除内部 `savedScrollTop` 变量，改用 `useTabScroll` 的 `saveScroll`
- `setSavedScrollTop` → `saveScroll(activeTab.value, val)`
- `restoreOuterScroll` → `tabRestoreScroll()`
- 导航到面经的特殊流程也使用统一的滚动管理

## 测试运行结果（预期：✅ 绿色）

```
4 passed (1.6s)
```

## 修改的文件清单

| 文件 | 改动 |
|------|------|
| `frontend/src/composables/useTabScroll.js` | 新建 — 滚动位置管理 composable |
| `frontend/src/App.vue` | +import, +saveScroll in onTabChange, +@after-enter, crossfade CSS |
| `frontend/src/composables/useHighlightNav.js` | 重构为使用 useTabScroll |

## 阶段状态
- [x] 最小实现已编写
- [x] 测试通过（绿色）
- [x] 进入重构阶段
