# Bug 预览报告

**日期:** 2026-05-25
**问题:** 点击历史模拟面试记录时前端卡死崩溃
**严重程度:** Critical (P0)

## 初步诊断

### 问题现象
用户在模拟面试侧边栏点击过去的一条对话记录时，浏览器标签页完全冻结，需要强制关闭。无任何错误提示。

### 根本原因
多个性能问题叠加导致主线程阻塞超过数秒：

1. **`marked.use()` 重复注册 3 次** — `ChatMessage.vue`、`ChatView.vue`、`utils/markdown.js` 各调用一次 `marked.use(highlightExtension)`，导致 `hljs.highlightAuto()` 对每个代码块执行 3 次
2. **绕过 LRU 缓存** — `ChatMessage.vue` 直接调用 `marked.parse()` + `DOMPurify.sanitize()`，没有使用已有的 `renderSafeMarkdown()` 带 200 条 LRU 缓存
3. **无虚拟滚动** — 50+ 条消息全部同时渲染到 DOM，`vue-virtual-scroller` 已安装但未在此使用
4. **`hljs.highlightAuto()` 无语言标签时极慢** — 对无语言标注的代码块尝试全部 13 种语言检测，每个代码块 50-200ms

### 影响范围
- **功能:** 模拟面试历史对话查看完全不可用
- **用户:** 所有用户
- **数据:** 不影响数据完整性

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | Critical | 历史对话查看完全不可用 |
| 数据完整性 | Low | 不影响数据 |
| 安全风险 | Low | DOMPurify 无 restrictive config，但非此 bug 根因 |
