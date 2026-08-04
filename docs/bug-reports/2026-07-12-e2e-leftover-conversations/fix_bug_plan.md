# 修复计划

**Bug ID:** BUG-001, BUG-002, BUG-003
**日期:** 2026-07-12
**优先级:** P2

## 修复步骤

### 步骤 1: 完善 chat-thinking-timer.spec.js 的 mock
**文件:** `frontend/tests/e2e/chat-thinking-timer.spec.js`
**行号:** 50-153
**修改类型:** 修正

**修改前:**
```javascript
async function mockChatThinkingStream(page) {
  await page.route('**/api/chat/conversations?status=active', async route => {
    // ...
  })
  await page.route('**/api/chat/conversations/conv-1/messages', async route => {
    // ...
  })
}
```

**修改后:**
```javascript
async function mockChatThinkingStream(page) {
  // Mock all chat API requests to prevent leaking to real backend
  await page.route('**/api/chat**', async route => {
    const url = route.request().url()
    const method = route.request().method()

    if (url.includes('/conversations?status=active') && method === 'GET') {
      // Return conversation list
      await route.fulfill({
        json: {
          status: 'success',
          data: [{ id: 'conv-1', title: '模拟面试', mode: 'free_practice', updated_at: new Date().toISOString() }],
        },
      })
    } else if (url.includes('/conversations/conv-1/messages') && method === 'GET') {
      // Return messages
      // ... existing mock
    } else if (url.includes('/conversations/conv-1/messages') && method === 'POST') {
      // Handle send message SSE
      // ... existing mock
    } else if (method === 'POST') {
      // Mock conversation creation
      await route.fulfill({
        json: { status: 'success', data: { id: 'mock-new-conv', title: '新对话' } },
      })
    } else {
      // Default: return empty success
      await route.fulfill({ json: { status: 'success', data: [] } })
    }
  })
}
```

### 步骤 2: 增强 E2E 脚本的清理逻辑
**文件:** `backend/scripts/verify_interview_agent_real_e2e.py`
**行号:** 486-492
**修改类型:** 修正

**修改前:**
```python
finally:
    if args.keep_conversation:
        print(f"\nConversation kept: {conversation_id}")
    else:
        try:
            _delete_conversation(args.base_url, token, conversation_id)
        except Exception as exc:
            print(f"Warning: failed to delete conversation {conversation_id}: {exc}", file=sys.stderr)
```

**修改后:**
```python
finally:
    if args.keep_conversation:
        print(f"\nConversation kept: {conversation_id}")
    else:
        max_retries = 3
        for attempt in range(max_retries):
            try:
                _delete_conversation(args.base_url, token, conversation_id)
                print(f"Conversation deleted: {conversation_id}")
                break
            except Exception as exc:
                if attempt == max_retries - 1:
                    print(f"ERROR: Failed to delete conversation {conversation_id} after {max_retries} attempts: {exc}", file=sys.stderr)
                    raise
                else:
                    print(f"Warning: attempt {attempt + 1} failed to delete conversation {conversation_id}: {exc}", file=sys.stderr)
                    time.sleep(1)
```

### 步骤 3: 增强 eval_framework/runner.py 的清理逻辑
**文件:** `backend/scripts/eval_framework/runner.py`
**行号:** 50-54, 142-149
**修改类型:** 修正

**修改前:**
```python
def _delete_conversation(base_url: str, token: str, conversation_id: str) -> None:
    try:
        _json_request("DELETE", f"{base_url}/api/chat/conversations/{conversation_id}", token=token)
    except Exception:
        pass
```

**修改后:**
```python
def _delete_conversation(base_url: str, token: str, conversation_id: str) -> None:
    _json_request("DELETE", f"{base_url}/api/chat/conversations/{conversation_id}", token=token)
```

### 步骤 4: 在 ChatView 中完善 preview 模式检查
**文件:** `frontend/src/components/business/ChatView.vue`
**行号:** 689-710, 718-826
**修改类型:** 修正

**修改前:**
```javascript
async function handleCreateConversation(data) {
  if (creatingConversation.value) return
  creatingConversation.value = true
  try {
    const res = await chatApi.createConversation(data)
    // ...
  }
}
```

**修改后:**
```javascript
async function handleCreateConversation(data) {
  if (creatingConversation.value) return
  creatingConversation.value = true
  try {
    if (props.preview) {
      // In preview mode, simulate conversation creation
      const newConv = {
        id: `preview-${Date.now()}`,
        title: data.title || '新对话',
        mode: data.mode || 'free_practice',
        updated_at: new Date().toISOString(),
      }
      conversations.value.unshift(newConv)
      activeConversationId.value = newConv.id
      showNewChat.value = false
      return
    }
    const res = await chatApi.createConversation(data)
    // ...
  }
}
```

## 验证方法
1. 运行 Playwright E2E 测试：`cd frontend && npx playwright test`
2. 检查数据库中对话数量没有增加
3. 运行真实 E2E 脚本并验证对话被正确清理

## 回滚方案
如果修复导致测试失败，可以回滚到原始代码并手动清理数据库中的测试对话。
