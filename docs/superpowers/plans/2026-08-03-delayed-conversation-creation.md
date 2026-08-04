# 延迟对话创建实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修改对话创建流程，用户发送第一条消息后才创建对话，消除无效空对话

**Architecture:** 前端保存配置到内存状态，后端新增 `first_message` 参数支持原子创建对话+处理消息

**Tech Stack:** Vue 3 Composition API / FastAPI / SQLite

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/app/models/schemas.py:110-117` | 修改 | `CreateConversationRequest` 添加 `first_message` 字段 |
| `backend/app/routers/chat.py:49-96` | 修改 | `create_conversation` 端点处理 `first_message` |
| `backend/app/services/chat_service.py:695-796` | 修改 | `create_conversation` 支持 `first_message` 参数 |
| `frontend/src/components/business/ChatView.vue:703-740` | 修改 | `handleCreateConversation` 延迟创建 |
| `frontend/src/components/business/ChatView.vue:748-800` | 修改 | `handleSend` 检测待创建状态 |

---

### Task 1: 后端 Schema 修改

**Files:**
- Modify: `backend/app/models/schemas.py:110-117`
- Test: `backend/tests/chat/test_chat.py`

- [ ] **Step 1: 添加 first_message 字段到 CreateConversationRequest**

```python
# backend/app/models/schemas.py:110-117
class CreateConversationRequest(BaseModel):
    mode: str = Field(..., pattern="^(jd_resume|free_practice)$")
    title: Optional[str] = None
    jd_id: Optional[int] = None
    resume_text: Optional[str] = None
    difficulty: Optional[str] = Field(None, pattern="^(junior|mid|senior|staff_plus)$")
    experience_id: Optional[int] = None
    distribution_override: Optional[DistributionPreferenceRequest] = None
    first_message: Optional[str] = Field(None, min_length=1, max_length=10000)  # 新增
```

- [ ] **Step 2: 运行测试验证 schema 修改**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_chat.py -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/schemas.py
git commit -m "feat(backend): add first_message field to CreateConversationRequest"
```

---

### Task 2: 后端 Service 修改

**Files:**
- Modify: `backend/app/services/chat_service.py:695-796`

- [ ] **Step 1: 修改 create_conversation 函数签名**

在 `create_conversation` 函数中添加 `first_message` 参数：

```python
def create_conversation(
    user_id: int,
    mode: str,
    title: Optional[str] = None,
    jd_id: Optional[int] = None,
    resume_text: Optional[str] = None,
    job_position: str = "",
    difficulty: str = "mid",
    experience_id: Optional[int] = None,
    distribution_override: Optional[dict] = None,
    first_message: Optional[str] = None,  # 新增
) -> dict:
```

- [ ] **Step 2: 在函数末尾处理 first_message**

在 `return` 语句之前添加：

```python
    # 如果有 first_message，保存用户消息并处理
    if first_message:
        save_message(conv_id, "user", first_message)
        # 注意：这里不处理AI回复，由前端调用消息发送API处理
```

- [ ] **Step 3: 运行测试**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_chat.py -q`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/chat_service.py
git commit -m "feat(backend): support first_message in create_conversation"
```

---

### Task 3: 后端 Router 修改

**Files:**
- Modify: `backend/app/routers/chat.py:49-96`

- [ ] **Step 1: 修改 create_conversation 端点**

修改 `create_conversation` 函数，当有 `first_message` 时：
1. 创建对话
2. 保存用户消息
3. 不生成开场白
4. 返回对话 ID（前端会调用消息发送 API 处理）

```python
@router.post("/conversations")
async def create_conversation(
    req: CreateConversationRequest, user: dict = Depends(get_current_user)
):
    """创建新对话会话"""
    try:
        resume_text = req.resume_text
        if resume_text == "__saved__":
            from app.services import resume_service
            saved = await run_db(lambda: resume_service.get_resume_text(user["id"]))
            resume_text = saved if saved else None

        result = await run_db(
            lambda: chat_service.create_conversation(
                user_id=user["id"],
                mode=req.mode,
                title=req.title,
                jd_id=req.jd_id,
                resume_text=resume_text,
                job_position=_current_position_name(user["id"]),
                difficulty=req.difficulty or "mid",
                experience_id=req.experience_id,
                distribution_override=req.distribution_override.model_dump() if req.distribution_override else None,
                first_message=req.first_message,  # 新增
            )
        )

        if resume_text and resume_text != "__saved__":
            await run_db(
                lambda: chat_service.save_resume_memory(user["id"], resume_text)
            )

        # 只有没有 first_message 时才生成开场白
        if not req.first_message:
            opening = chat_service.generate_opening_message(req.mode)
            await run_db(
                lambda: chat_service.save_message(result["id"], "assistant", opening)
            )
            result["opening_message"] = opening
        else:
            result["opening_message"] = None

        return {"status": "success", "data": result}
    except ValueError as e:
        logger.warning(f"创建对话参数无效: {e}")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"创建对话失败: {e}")
        raise HTTPException(status_code=500, detail="创建对话失败")
```

- [ ] **Step 2: 运行测试**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_chat.py -q`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/routers/chat.py
git commit -m "feat(backend): handle first_message in create_conversation endpoint"
```

---

### Task 4: 前端 ChatView 修改 - 延迟创建

**Files:**
- Modify: `frontend/src/components/business/ChatView.vue:430-450` (添加状态)
- Modify: `frontend/src/components/business/ChatView.vue:703-740` (handleCreateConversation)
- Modify: `frontend/src/components/business/ChatView.vue:748-800` (handleSend)

- [ ] **Step 1: 添加 pendingNewConversation 状态**

在 `ChatView.vue` 的 `script setup` 中添加：

```javascript
// 在 line 450 附近添加
const pendingNewConversation = ref(null)
const openingMessageText = ref('')
```

- [ ] **Step 2: 修改 handleCreateConversation 函数**

将 `handleCreateConversation` 改为不调用 API，只保存配置：

```javascript
async function handleCreateConversation(data) {
  if (creatingConversation.value) return
  creatingConversation.value = true
  try {
    if (props.preview) {
      // Preview mode: simulate
      const newConv = {
        id: `preview-${Date.now()}`,
        title: data.title || (data.mode === 'free_practice' ? '新对话' : 'JD定制面试'),
        mode: data.mode || 'free_practice',
        updated_at: new Date().toISOString(),
      }
      conversations.value.unshift(newConv)
      activeConversationId.value = newConv.id
      messages.value = []
      showNewChat.value = false
      pendingInitialMessage.value = ''
      return
    }

    // 延迟创建：保存配置到前端状态，不调用API
    pendingNewConversation.value = {
      mode: data.mode || 'free_practice',
      title: data.title || null,
      jd_id: data.jd_id || null,
      resume_text: data.resume_text || null,
      difficulty: data.difficulty || 'mid',
      experience_id: data.experience_id || null,
      initial_message: data.initial_message || null,
    }

    // 生成开场白用于placeholder
    openingMessageText.value = data.mode === 'jd_resume'
      ? '请先简单做一下自我介绍吧。'
      : '请先简单做一下自我介绍吧。'

    // 设置临时active状态，显示空聊天界面
    activeConversationId.value = 'pending'
    messages.value = []
    showNewChat.value = false
    pendingInitialMessage.value = ''
  } catch (e) {
    console.error('准备对话失败:', e)
  } finally {
    creatingConversation.value = false
  }
}
```

- [ ] **Step 3: 修改 handleSend 函数**

在 `handleSend` 开头添加待创建对话的处理逻辑：

```javascript
async function handleSend({ regenerateMessageId = null } = {}) {
  let text = inputText.value.trim()
  if (regenerateMessageId) {
    const targetIndex = messages.value.findIndex(m => m.id === regenerateMessageId)
    for (let i = targetIndex - 1; i >= 0; i--) {
      if (messages.value[i].role === 'user') {
        text = String(messages.value[i].content || '').trim()
        break
      }
    }
  }
  if (!text || isSending.value) return

  // 如果有待创建的对话，先创建对话
  if (pendingNewConversation.value && activeConversationId.value === 'pending') {
    try {
      const createData = {
        ...pendingNewConversation.value,
        first_message: text,
      }
      const res = await chatApi.createConversation(createData)
      if (res.data?.id) {
        // 创建成功，更新状态
        pendingNewConversation.value = null
        openingMessageText.value = ''
        activeConversationId.value = res.data.id
        
        // 刷新对话列表
        await loadConversations()
        
        // 添加用户消息到显示
        messages.value.push({
          id: Date.now(),
          role: 'user',
          content: text,
          created_at: new Date().toISOString(),
        })
        inputText.value = ''
        resetInputHeight()
      }
    } catch (e) {
      console.error('创建对话失败:', e)
      return
    }
  }

  if (!activeConversationId.value || activeConversationId.value === 'pending') return

  // ... 后续原有的发送逻辑
```

- [ ] **Step 4: 运行前端构建**

Run: `cd frontend && npm run build`
Expected: Build successful

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/business/ChatView.vue
git commit -m "feat(frontend): delay conversation creation until first message"
```

---

### Task 5: 前端输入框 Placeholder 修改

**Files:**
- Modify: `frontend/src/components/business/ChatView.vue` (input placeholder)

- [ ] **Step 1: 修改 inputPlaceholder computed**

```javascript
const inputPlaceholder = computed(() => {
  if (pendingNewConversation.value) {
    return openingMessageText.value || '回答面试问题，或输入你想练习的内容...'
  }
  return '回答面试问题，或输入你想练习的内容...'
})
```

- [ ] **Step 2: 修改空状态显示**

在模板中，当 `activeConversationId === 'pending'` 时，显示空聊天界面（不显示"开始模拟面试"大标题）：

```vue
<!-- Empty state: 只在没有active对话且没有pending对话时显示 -->
<div v-if="!activeConversationId || activeConversationId === 'pending'" class="flex-1 flex flex-col">
  <!-- 有待创建对话时，显示简洁界面 -->
  <template v-if="pendingNewConversation">
    <div class="flex-1 flex items-center justify-center">
      <div class="text-center text-muted-foreground">
        <MessageSquare :size="48" class="mx-auto mb-4 text-primary/30" />
        <p class="text-sm">输入你的回答开始面试</p>
      </div>
    </div>
  </template>
  
  <!-- 没有待创建对话时，显示原始空状态 -->
  <template v-else>
    <!-- 原有的空状态内容 -->
  </template>
</div>
```

- [ ] **Step 3: 运行前端构建**

Run: `cd frontend && npm run build`
Expected: Build successful

- [ ] **Step 4: Commit**

```bash
git add frontend/src/components/business/ChatView.vue
git commit -m "feat(frontend): show placeholder for pending conversation"
```

---

### Task 6: 测试验证

- [ ] **Step 1: 运行后端测试**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q`
Expected: PASS

- [ ] **Step 2: 运行前端构建**

Run: `cd frontend && npm run build`
Expected: Build successful

- [ ] **Step 3: 运行前端测试**

Run: `cd frontend && npm run test`
Expected: PASS

- [ ] **Step 4: 手动测试流程**

1. 打开浏览器访问 `/chat`
2. 点击"新建面试"
3. 配置选项，点击"开始面试"
4. 验证：侧边栏不显示新对话
5. 输入消息并发送
6. 验证：对话出现在侧边栏，AI回复正常

- [ ] **Step 5: Final Commit**

```bash
git add -A
git commit -m "feat: implement delayed conversation creation"
```

---

## 测试策略

### 单元测试
- 后端：测试 `first_message` 参数处理
- 后端：测试无 `first_message` 时保持原行为

### E2E 测试
- 前端：测试延迟创建流程
- 前端：测试对话列表更新

### 边界情况
- 用户刷新页面时 pending 状态丢失（可接受）
- 并发创建多个对话（前端防抖）
- 消息发送失败时的错误处理
