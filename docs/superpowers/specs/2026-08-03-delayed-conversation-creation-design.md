# 延迟对话创建设计文档

## 问题背景

当前行为：用户点击"新建面试"按钮后，系统立即在数据库中创建对话记录，即使用户从未发送任何消息。这导致 sj 账户下积累了 214 个无效对话（只有 AI 开场白，没有用户消息）。

期望行为：对标 ChatGPT/DeepSeek，用户发送第一条消息后才真正创建对话。

## 设计目标

1. 消除无效对话：只有用户实际参与的对话才会被持久化
2. 保持配置能力：保留难度、面经节奏、JD、简历等配置选项
3. 平滑过渡：用户体验自然，不增加认知负担

## 行为变更

### 当前流程
```
点击"新建面试" → 弹窗配置 → 点击"开始面试" → API创建对话 → 生成开场白 → 显示在侧边栏
```

### 新流程
```
点击"新建面试" → 弹窗配置 → 点击"开始面试" → 保存配置到前端状态 → 显示空聊天界面
                                                                              ↓
用户输入消息并发送 → API创建对话+处理消息 → 显示在侧边栏
```

## 技术设计

### 前端改动

#### ChatView.vue

1. **新增状态**
   ```javascript
   const pendingNewConversation = ref(null)  // 存储待创建对话的配置
   const openingMessage = ref('')  // 开场白文案（用于placeholder）
   ```

2. **修改 handleCreateConversation**
   - 不再调用 `chatApi.createConversation(data)`
   - 保存配置到 `pendingNewConversation`
   - 生成开场白文案到 `openingMessage`（用于输入框placeholder）
   - 设置 `activeConversationId` 为临时状态（如 `'pending'`）

3. **修改 handleSend**
   - 检测 `pendingNewConversation` 是否存在
   - 如果存在：调用新 API `POST /api/chat/conversations` 并附带 `first_message`
   - 成功后：清空 `pendingNewConversation`，更新对话列表

4. **修改输入框 placeholder**
   - 如果有 `openingMessage`：显示开场白
   - 否则：显示默认文案

5. **修改侧边栏显示**
   - `pendingNewConversation` 存在时，侧边栏显示"新对话（未保存）"
   - 不计入对话列表

#### NewChatModal.vue

- 无需修改，仍然用于配置对话选项

### 后端改动

#### routers/chat.py

修改 `POST /api/chat/conversations` 端点：

```python
class CreateConversationRequest(BaseModel):
    mode: str
    title: Optional[str] = None
    jd_id: Optional[int] = None
    resume_text: Optional[str] = None
    difficulty: Optional[str] = "mid"
    experience_id: Optional[int] = None
    distribution_override: Optional[DistributionPreferenceRequest] = None
    first_message: Optional[str] = None  # 新增：第一条消息
```

处理逻辑：
1. 创建对话（现有逻辑）
2. 如果 `first_message` 存在：
   - 处理用户消息（调用 `run_chat`）
   - 返回对话 ID + AI 回复
3. 如果 `first_message` 不存在：
   - 生成开场白
   - 返回对话 ID + 开场白

#### services/chat_service.py

新增函数 `create_conversation_with_first_message`：

```python
def create_conversation_with_first_message(
    user_id: int,
    mode: str,
    first_message: str,
    **kwargs
) -> dict:
    """创建对话并处理第一条消息"""
    # 1. 创建对话
    conversation = create_conversation(user_id, mode, **kwargs)
    
    # 2. 处理第一条消息
    response = process_message(conversation['id'], user_id, first_message)
    
    return {
        'id': conversation['id'],
        'mode': conversation['mode'],
        'title': conversation['title'],
        'response': response  # AI回复
    }
```

### 数据流

```
前端                              后端
  │                                │
  ├─ 用户点击"开始面试"            │
  │  └─ 保存配置到                 │
  │     pendingNewConversation     │
  │  └─ 显示空聊天界面             │
  │                                │
  ├─ 用户输入消息并发送 ──────────►│
  │  └─ POST /api/chat/conversations
  │     {mode, difficulty,         │
  │      first_message: "用户消息"}│
  │                                ├─ 创建对话
  │                                ├─ 处理消息
  │                                ├─ 生成AI回复
  │◄───────────────────────────────┤
  │  └─ 更新对话列表               │
  │  └─ 显示AI回复                 │
```

## 测试策略

### 前端测试
1. 点击"开始面试"后不创建对话
2. 发送第一条消息后对话出现在侧边栏
3. 配置选项正确传递到后端

### 后端测试
1. `first_message` 参数存在时：创建对话+处理消息
2. `first_message` 参数不存在时：保持原行为
3. 错误处理：消息处理失败时回滚对话创建

## 实现步骤

1. **后端**：修改 `CreateConversationRequest` 添加 `first_message` 字段
2. **后端**：修改 `create_conversation` 处理 `first_message`
3. **前端**：修改 `handleCreateConversation` 保存配置而非创建对话
4. **前端**：修改 `handleSend` 检测待创建状态
5. **前端**：修改输入框 placeholder 显示开场白
6. **测试**：验证新流程正常工作
7. **清理**：删除 sj 账户下的无效对话

## 风险与缓解

| 风险 | 缓解措施 |
|------|----------|
| 消息处理失败导致对话创建但无消息 | 后端使用事务，失败时回滚 |
| 用户刷新页面丢失待创建配置 | 配置存储在内存中，刷新后重置（可接受） |
| 并发创建多个对话 | 前端防抖，后端幂等性检查 |
