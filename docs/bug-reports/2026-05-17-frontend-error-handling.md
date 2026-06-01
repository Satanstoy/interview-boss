# 前端错误处理完善

**日期：** 2026-05-17
**类型：** Bug 修复
**状态：** 完成

## 问题描述

审计发现前端 13 个错误处理缺口：8 个静默失败（catch 无用户反馈）、2 个不一致、3 个缺失提示。

## 修复内容

### HIGH（3 项）
1. `uploadSSE` error 事件缺少 fallback — 改为 `data.message || data.detail || '操作失败'`
2. `fetchAnalytics` 静默失败 — 改为 `console.warn`
3. `fetchPracticeStats` 静默失败 — 改为 `console.warn`

### MEDIUM（6 项）
4. `loadActiveSeason` 完全静默 — 添加 `console.warn`
5. `loadHistory` 静默 — 添加 `_historyError` 标记
6. `PracticePanel` 历史加载静默 — 改为 `console.warn`
7. SSE 重建中断显示"完成 0 题" — 添加 null 检查，显示"连接中断"
8. `QuestionCard` 答案详情加载静默 — 添加 `detailError` + "答案加载失败" 提示 + 重试按钮
9. 新增 HTTP 423 状态码提示："账号已锁定，请稍后重试或联系管理员"

## 涉及文件
- `frontend/src/utils/http.js` — uploadSSE error fallback + 423 状态码
- `frontend/src/App.vue` — analytics/practice/season/重建中断错误处理
- `frontend/src/composables/usePractice.js` — 历史加载错误标记
- `frontend/src/components/PracticePanel.vue` — 历史加载警告
- `frontend/src/components/QuestionCard.vue` — 答案加载失败 UI
