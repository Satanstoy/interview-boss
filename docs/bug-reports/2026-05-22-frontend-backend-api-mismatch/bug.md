# Bug 详细分析报告

**Bug ID:** BUG-001, BUG-002, BUG-003
**发现日期:** 2026-05-22
**状态:** 已确认

## 问题概述

新增的 Chat（模拟面试）模块在前后端对接中存在三处接口/逻辑问题，导致用户在使用模拟面试功能时遇到无响应或功能缺失。

---

## BUG-001: NewChatModal.vue PDF 提取缺少 Authorization 头

- **位置:** `frontend/src/components/business/NewChatModal.vue:125-131`
- **症状:** 用户在"JD+简历定制"模式下上传 PDF 简历后，无任何反馈，简历文本为空
- **根因:** 使用原生 `fetch()` 而非 `http.js` 的 `upload()` 函数，导致缺少 `Authorization` header。后端 `chat.py:218` 的 `extract_pdf` 端点要求 `Depends(get_current_user)` 认证，因此返回 HTTP 401。前端的 `if (res.ok)` 判断后直接跳过，`resumeText` 保持为空字符串。
- **影响:** JD+简历定制面试模式完全不可用（无简历则 AI 无法定制化提问）
- **严重程度:** P1

## BUG-002: ChatView.vue SSE retrieved 事件静默失败

- **位置:** `frontend/src/components/business/ChatView.vue:198-201`
- **症状:** AI 回复中"检索到的相关题目"信息丢失，用户无法看到 AI 参考了哪些题库题目
- **根因:**
  ```javascript
  // streamingContent.value 是 string 类型
  const streamingContent = ref('')  // string
  // ...
  streamingContent.value._retrieved = retrievedQuestions  // 静默失败！
  ```
  JavaScript 的字符串是原始类型（primitive），不能像对象一样附加属性。在严格模式下，`str.prop = value` 是一个 no-op，不报错也不生效。后续 `if (streamingContent.value._retrieved)` 始终为 falsy，`metadata` 始终为空。
- **影响:** 消息元数据中缺失 `retrieved_questions`，用户无法查看 AI 参考了哪些题目
- **严重程度:** P2

## BUG-003: api/index.js 缺少 chat 模块 re-export

- **位置:** `frontend/src/api/index.js`
- **症状:** 其他组件无法通过 `import * as api from '@/api/index.js'` 使用 chat 功能
- **根因:** 新增 `chatApi.js` 后未在 `api/index.js` 中添加 re-export
- **影响:** 不符合项目统一 API 导出规范，目前 `ChatView.vue` 直接导入不受影响，但未来维护可能遗漏
- **严重程度:** P3

## 复现步骤

### BUG-001 复现
1. 登录后进入"模拟面试" Tab
2. 点击"新建面试"
3. 选择"JD + 简历定制"模式
4. 上传 PDF 简历
5. **预期:** 简历文本被提取并显示文件名
6. **实际:** 文件名显示但无文本提取（后端 401），创建对话后 AI 无简历上下文

### BUG-002 复现
1. 进入已有对话
2. 发送一个面试答案（如"请介绍一下 Redis 的数据结构"）
3. **预期:** 消息元数据包含 AI 参考的题目列表
4. **实际:** 元数据中 `retrieved_questions` 为空

## 修复建议

- **BUG-001:** 使用 `http.js` 的 `upload()` 函数替代原生 `fetch()`，自动获得 Authorization header
- **BUG-002:** 使用独立的 `ref` 变量存储 retrieved 信息，不依赖字符串属性
- **BUG-003:** 在 `api/index.js` 中添加 chat 模块的 re-export
