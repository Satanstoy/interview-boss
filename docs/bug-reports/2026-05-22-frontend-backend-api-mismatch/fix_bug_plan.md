# 修复计划

**Bug ID:** BUG-001, BUG-002, BUG-003
**日期:** 2026-05-22
**优先级:** P1/P2/P3

## 修复步骤

### 步骤 1: 修复 BUG-001 — NewChatModal.vue PDF 提取认证

**文件:** `frontend/src/components/business/NewChatModal.vue`
**行号:** 119-139
**修改类型:** 修正

**修改前:**
```javascript
async function extractPdfText(file) {
  const formData = new FormData()
  formData.append('file', file)
  try {
    const res = await fetch('/api/chat/extract-pdf', {
      method: 'POST',
      headers: { 'X-Requested-With': 'XMLHttpRequest' },
      body: formData,
      credentials: 'same-origin',
    })
    if (res.ok) {
      const data = await res.json()
      return data.text || ''
    }
  } catch (e) {
    console.error('PDF extraction failed:', e)
  }
  return ''
}
```

**修改后:**
```javascript
async function extractPdfText(file) {
  const formData = new FormData()
  formData.append('file', file)
  try {
    const data = await upload('/api/chat/extract-pdf', formData)
    return data.text || ''
  } catch (e) {
    console.error('PDF extraction failed:', e)
    throw e
  }
}
```

需要在文件顶部添加 import:
```javascript
import { upload } from '@/services/http.js'
```

### 步骤 2: 修复 BUG-002 — ChatView.vue SSE retrieved 事件

**文件:** `frontend/src/components/business/ChatView.vue`
**行号:** 119, 193-209
**修改类型:** 修正

在 state 定义处添加独立变量:
```javascript
const pendingRetrievedQuestions = ref(null)
```

修改 SSE 事件处理:
```javascript
if (event.type === 'retrieved') {
  const retrievedQuestions = event.questions || []
  pendingRetrievedQuestions.value = retrievedQuestions
}
```

修改 finalResult 构建:
```javascript
if (streamingContent.value) {
  const metadata = {}
  if (pendingRetrievedQuestions.value?.length > 0) {
    metadata.retrieved_questions = pendingRetrievedQuestions.value
  }
  messages.value.push({
    id: Date.now() + 1,
    role: 'assistant',
    content: streamingContent.value,
    metadata,
    created_at: new Date().toISOString(),
  })
  pendingRetrievedQuestions.value = null
}
```

### 步骤 3: 修复 BUG-003 — api/index.js 添加 chat 模块导出

**文件:** `frontend/src/api/index.js`
**行号:** 111 之后
**修改类型:** 新增

```javascript
// ── Chat ──
export {
  createConversation,
  getConversations,
  getConversation,
  updateTitle,
  archiveConversation,
  deleteConversation,
  getMessages,
  sendMessage,
  getMemories,
  deleteMemory,
} from '../services/chatApi.js'
```

## 验证方法

1. **BUG-001:** 上传 PDF 后检查浏览器 Network 面板，确认 `/api/chat/extract-pdf` 请求包含 Authorization header 且返回 200
2. **BUG-002:** 发送面试答案后，在 Vue DevTools 中检查 messages 数组，确认最新 assistant message 的 metadata.retrieved_questions 非空
3. **BUG-003:** 运行 `grep -r 'chatApi' frontend/src/` 确认无遗漏

## 回滚方案

各修复点独立，可通过 git revert 单个 commit 回滚。
