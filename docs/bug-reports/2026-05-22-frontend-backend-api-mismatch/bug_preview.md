# Bug 预览报告

**日期:** 2026-05-22
**问题:** 前后端接口对接存在多处问题，导致部分前端功能点击无反应
**严重程度:** High

## 初步诊断

### 问题现象

1. **"模拟面试" Tab 中新建面试会话后上传 PDF 简历无反应** — 选择 PDF 文件后，后端返回 401 未授权，但前端无任何错误提示，用户以为功能不可用。
2. **对话中 AI 检索到的相关题目信息丢失** — 用户发送面试回答后，AI 检索到了题库相关题目（SSE `retrieved` 事件），但这些信息未被正确保存到消息元数据中，用户看不到 AI 参考了哪些题目。
3. **`api/index.js` 未导出 chat 模块** — 虽然 `ChatView.vue` 直接导入 `chatApi.js` 不受影响，但其他组件无法通过统一入口使用 chat 功能，违反项目代码规范。

### 根本原因

1. **BUG-001**: `NewChatModal.vue` 的 `extractPdfText()` 使用原生 `fetch()` 发送请求，**未附加 `Authorization: Bearer <token>` 头**。后端 `/api/chat/extract-pdf` 端点需要 `get_current_user` 认证，因此返回 401。前端未正确处理该错误，导致用户无感知。
2. **BUG-002**: `ChatView.vue` 的 `handleSend()` 在收到 SSE `retrieved` 事件时，尝试在字符串上附加属性 `streamingContent.value._retrieved = retrievedQuestions`。JavaScript 中字符串是原始类型，不能附加属性，该赋值**静默失败**。导致 `metadata` 始终为空。
3. **BUG-003**: `api/index.js` 缺少 chat 模块的 re-export。

### 影响范围

- **功能:**
  - JD+简历定制面试模式下的 PDF 简历上传功能完全不可用
  - AI 对话中"检索到的相关题目"功能不工作
  - Chat 模块未纳入统一 API 导出
- **用户:** 所有使用模拟面试功能的用户
- **数据:** 不影响数据完整性（PDF 提取和题目信息仅用于上下文展示）

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | High | PDF 简历上传完全不可用 |
| 功能降级 | Medium | 检索题目信息丢失，影响用户理解 AI 回复 |
| 数据完整性 | Low | 不影响核心数据 |
| 安全风险 | Low | 缺少 auth header 会被正确拒绝，不会泄露数据 |
