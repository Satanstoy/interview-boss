# 修复计划

**Bug ID:** BUG-001
**日期:** 2026-05-25
**优先级:** P0

## 修复步骤

### 步骤 1: 统一 marked.use() 初始化
**文件:** `frontend/src/utils/highlight.js`
**修改类型:** 修改
**说明:** 在 highlight.js 中执行 `marked.use()` 初始化，确保全局只注册一次

### 步骤 2: ChatMessage.vue 使用 renderSafeMarkdown
**文件:** `frontend/src/components/business/ChatMessage.vue`
**修改类型:** 修改
**说明:** 删除本地 marked.use() 和直接 marked.parse()，改用带缓存的 renderSafeMarkdown()

### 步骤 3: ChatView.vue 使用 renderSafeMarkdown
**文件:** `frontend/src/components/business/ChatView.vue`
**修改类型:** 修改
**说明:** 删除本地 marked.use()，流式渲染也使用 renderSafeMarkdown()

### 步骤 4: utils/markdown.js 已有 highlight 集成（无需改动）
**文件:** `frontend/src/utils/markdown.js`
**说明:** 已在之前的修改中正确添加了 highlightExtension

## 验证方法
1. `cd frontend && npm run build`
2. 打开浏览器，点击历史对话记录，验证不卡顿
3. 验证代码块有语法高亮
