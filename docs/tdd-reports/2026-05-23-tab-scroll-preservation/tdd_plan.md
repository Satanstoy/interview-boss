# TDD 开发计划

**功能名称:** Tab 切换滚动位置保持 + 动画无冲突
**日期:** 2026-05-23
**TDD 状态:** 🔴 红灯阶段准备

## 需求描述

切换 JD库/面经库/高频题库 tab 时，保持各 tab 的滚动位置不丢失，同时动画不能因滚动恢复而产生"抽搐"。

## 问题根因分析

1. **滚动丢失** — `<Transition mode="out-in">` 销毁旧组件后创建新组件，scrollTop 重置为 0
2. **动画抽搐** — `translateY(12px)` 进场动画 + 滚动恢复 = 视觉跳动
3. **MasterBankList** — 使用 virtual scroller + visibility 切换，不受 Transition 影响

## 解决方案

1. **`useTabScroll` composable** — 在 `onTabChange` 前保存 scrollTop，`@after-enter` 后恢复
2. **Crossfade 动画** — 去掉 translateY，只用 opacity 渐变，消除动画与滚动的冲突
3. **延迟恢复** — 滚动恢复在 `requestAnimationFrame` 中执行，确保 DOM 已就绪

## 验收标准

- [ ] 切换 tab 后回到之前的 tab，滚动位置保持不变
- [ ] 切换动画无 translateY 变形，只有 opacity 渐变
- [ ] 滚动恢复在动画结束后执行，不产生视觉跳动
- [ ] useTabScroll composable 正确导出

## 测试清单

| ID | 测试场景 | 验证方式 | 状态 |
|----|---------|---------|------|
| T-001 | useTabScroll composable 可用 | Playwright: 检查打包 | ⏳ |
| T-002 | tab-fade 使用 opacity-only | Playwright: CSS 规则检查 | ⏳ |
| T-003 | @after-enter hook 存在 | Playwright: 模板检查 | ⏳ |
| T-004 | 滚动恢复用 requestAnimationFrame | Playwright: composable 逻辑检查 | ⏳ |

## 红-绿-重构循环计划

- [ ] 循环 1: T-001 — useTabScroll composable 存在
- [ ] 循环 2: T-002 — crossfade 动画
- [ ] 循环 3: T-003 — after-enter hook
- [ ] 循环 4: T-004 — 延迟恢复逻辑
