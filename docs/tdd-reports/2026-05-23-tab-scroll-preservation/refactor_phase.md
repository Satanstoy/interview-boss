# 重构阶段报告

**日期:** 2026-05-23

## 重构前

`useHighlightNav.js` 内部维护独立的 `savedScrollTop` 变量，与 `useTabScroll` 的 `scrollPositions` Map 重复。

## 重构后

- `useHighlightNav` 导入 `useTabScroll`，通过 `saveScroll` / `restoreScroll` 统一管理
- `setSavedScrollTop(val)` → `saveScroll(activeTab.value, val)`
- `restoreOuterScroll()` → `tabRestoreScroll()`
- 消除了两套滚动管理的重复

## 重构验证

```
4 passed (1.6s)
✓ built in 20.85s
```

## 阶段状态
- [x] 重构完成
- [x] 测试仍然通过
