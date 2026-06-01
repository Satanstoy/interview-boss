# Bug 详细分析报告

**Bug ID:** BUG-001
**发现日期:** 2026-05-25
**状态:** 已确认

## 问题概述
点击模拟面试侧边栏的历史对话记录时，前端完全冻结。根因是 `marked.use()` 被 3 个文件重复注册 highlight 扩展，导致每个代码块执行 3 次 `hljs.highlightAuto()`，且 ChatMessage.vue 绕过了已有的 LRU 缓存。

## 根本原因分析

### BUG-001a: marked.use() 重复注册（Critical）
- **位置:** `ChatMessage.vue:61-62`, `ChatView.vue:167-168`, `utils/markdown.js:5-6`
- **症状:** 每个代码块被 highlight 3 次
- **根因:** `marked.use()` 是 additive 的全局修改器，3 个文件各调用一次导致扩展叠加
- **影响:** 渲染耗时 ×3
- **严重程度:** P0

### BUG-001b: ChatMessage.vue 绕过 LRU 缓存（Critical）
- **位置:** `ChatMessage.vue:72-76`
- **症状:** 相同内容重复解析
- **根因:** 直接调用 `marked.parse()` 而非 `renderSafeMarkdown()`
- **影响:** 50+ 条消息全部重新解析
- **严重程度:** P0

### BUG-001c: DOMPurify 无 restrictive config（Medium）
- **位置:** `ChatMessage.vue:75`
- **症状:** DOMPurify 使用默认宽松配置扫描所有标签
- **根因:** 未传入 `purifyConfig`
- **影响:** 大 HTML 字符串的清理耗时增加
- **严重程度:** P1

### BUG-001d: 无虚拟滚动（Medium）
- **位置:** `ChatView.vue:78-79`
- **症状:** 50+ 消息全部渲染到 DOM
- **根因:** 未使用已安装的 `vue-virtual-scroller`
- **影响:** DOM 节点过多阻塞主线程
- **严重程度:** P1

## 复现步骤
1. 登录应用
2. 进入"模拟面试"页面
3. 在左侧对话列表中，点击一条有 10+ 轮对话的历史记录
4. 预期：正常加载并显示对话
5. 实际：浏览器完全冻结数秒

## 修复建议
- 统一使用 `renderSafeMarkdown()` 替代直接 `marked.parse()`
- 从 `ChatMessage.vue` 和 `ChatView.vue` 删除 `marked.use()` 重复调用
- 长远考虑为消息列表添加虚拟滚动
