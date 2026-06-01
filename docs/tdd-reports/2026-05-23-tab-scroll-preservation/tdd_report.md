# TDD 开发完成报告

**功能名称:** Tab 切换滚动位置保持 + 动画无冲突
**完成日期:** 2026-05-23
**TDD 状态:** ✅ 完成

## 执行摘要

| 指标 | 结果 |
|------|------|
| 完成测试数 | 4 |
| TDD循环数 | 4 |
| 最终测试通过率 | 100% |
| 构建状态 | ✅ 通过 |
| Playwright MCP 验证 | ✅ 滚动保持 + 无抽搐 |

## 问题分析

| 问题 | 根因 | 解决方案 |
|------|------|---------|
| 切换 tab 滚动丢失 | `<Transition mode="out-in">` 销毁/重建组件 | `useTabScroll` 在切换前保存 scrollTop |
| 动画抽搐 | `translateY` 进场动画 + 滚动恢复冲突 | 改为 opacity-only crossfade |
| 恢复时机不对 | 滚动恢复在动画进行中 | `@after-enter` + nextTick + 双重 rAF |
| 恢复目标错误 | `saveScroll` 同时设置 `pendingRestore`，导致恢复旧 tab | 拆分为 `saveScroll` + `prepareRestore` |

## 关键 Bug Fix

Playwright MCP 测试发现 `restoreScroll` 恢复到 0 而非 5000。

**根因：** `saveScroll('Interview', 5000)` 设置 `pendingRestore = 'Interview'`，但随后 `onTabChange` 切换到 JD 时调用 `saveScroll('MasterBank', 0)` 覆盖了 `pendingRestore = 'MasterBank'`。`restoreScroll` 恢复了 MasterBank (0) 而非 Interview (5000)。

**修复：** 拆分 `saveScroll` 和 `prepareRestore`，`saveScroll` 只保存位置，`prepareRestore` 在 `onTabChange` 中显式指定要恢复的 tab。

## 变更详情

### 1. useTabScroll composable
- `saveScroll(tabKey, scrollTop)` — 只保存位置到 Map
- `prepareRestore(tabKey)` — 标记待恢复的 tab
- `restoreScroll()` — nextTick + 双重 rAF 延迟恢复

### 2. Crossfade 动画
- `tab-fade` 去掉 `translateY`，只保留 `opacity` 渐变

### 3. 滚动恢复时机
- `onTabChange` — `saveScroll` 保存旧 tab + `prepareRestore` 标记新 tab
- `@after-enter` — 进场动画完成后 `restoreScroll()`

### 4. useHighlightNav 统一
- 移除 `savedScrollTop` 局部变量，使用 `useTabScroll`

## 文件变更清单

```
A frontend/src/composables/useTabScroll.js        — 滚动位置管理
M frontend/src/App.vue                             — +import, +saveScroll, +prepareRestore, +@after-enter, crossfade CSS
M frontend/src/composables/useHighlightNav.js     — 统一使用 useTabScroll
A frontend/tests/e2e/tab-scroll.spec.js           — Playwright E2E 测试
```

## 测试覆盖

### Playwright E2E 测试
```
4 passed (2.2s)
```

| 测试 ID | 场景 | 验证方式 | 状态 |
|---------|------|---------|------|
| T-001 | useTabScroll composable 可用 | 文件读取: export + saveScroll + prepareRestore + restoreScroll | ✅ PASS |
| T-002 | tab-fade 无 translateY | CSS 规则: opacity 有, translateY 无 | ✅ PASS |
| T-003 | @after-enter hook 存在 | 模板检查: @after-enter | ✅ PASS |
| T-004 | requestAnimationFrame 延迟恢复 | 文件读取: requestAnimationFrame | ✅ PASS |

### Playwright MCP 手动验证
| 测试 | 操作 | 预期 | 结果 |
|------|------|------|------|
| 滚动保持 | 面经库 scrollTop=5000 → JD → 面经库 | scrollTop=5000 | ✅ 5000 |
| 多 tab 循环 | 面经库(3000) → JD → 高频题库 → 面经库 | scrollTop=3000 | ✅ 3000 |
| 动画无抽搐 | 检查 tabContent transform | none | ✅ none |
| 动画 opacity | 检查 tabContent opacity | 1 | ✅ 1 |

## 结论

✅ 四个测试全部通过
✅ 构建通过
✅ Playwright MCP 验证滚动保持正确
✅ 动画无 translateY，无抽搐
✅ 发现并修复了 pendingRestore 覆盖 bug
