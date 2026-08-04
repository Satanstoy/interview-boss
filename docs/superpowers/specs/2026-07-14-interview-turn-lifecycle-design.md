# 模拟面试 Turn 生命周期与并发取消设计

**日期：** 2026-07-14  
**状态：** 已获用户确认，进入实现  
**范围：** 单会话单 active turn、幂等发送、服务端取消、条件 finalize

## 问题

当前发送接口在保存 user message 后直接启动 SSE/LLM 流程。前端的
`isSending` 只能限制同一个组件实例，不能阻止重复标签页、网络重试或重复
HTTP 请求。assistant 消息在 SSE `done` 事件中按 conversation/status 写入，
没有回合身份，因此旧 worker 可能在新回合或取消之后继续提交结果。

前端已有停止按钮，但它只中断浏览器的 SSE 请求；服务端没有持久化的取消
状态，也没有 request idempotency key。现有 regenerate 只修改前端数组，重新
提交后会在数据库追加重复 user message；本设计不在本次修复中实现编辑分支。

## 目标

1. 同一个 conversation 同时最多有一个 `running` turn。
2. 同一个 `client_request_id` 只能创建一个 turn 和一条 user message。
3. cancel 后旧 turn 不能再写 assistant message、coverage 相关事实、active
   skills 或 MCP session。
4. finalize 必须同时验证 `turn_id`、conversation、user 和 `running` 状态。
5. 客户端停止只影响当前 chat stream，不影响全局其他 HTTP 请求。
6. 保持现有 SSE 事件和旧客户端兼容；旧客户端未提供 request id 时由服务端
   生成随机 id，因此仍能发送，但无法获得跨重试幂等性。

## 非目标

- 本次不实现用户消息编辑、分支树、历史截断或 regenerate UI 重构。
- 本次不实现完整 worker/provider 级 token cancellation；服务端先保证取消
  后不产生新的持久化副作用，底层 LLM 调用在当前进程中通过 SSE disconnect
  的 task cancellation 尽快停止。
- 本次不引入 coverage event sourcing、完整审计事件或多设备消息队列。
- 本次不改变已有消息内容和历史数据。

## 数据模型

新增 migration 043，建立 `chat_turns`：

```sql
CREATE TABLE chat_turns (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    client_request_id TEXT NOT NULL,
    fence INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',
    user_message_id INTEGER,
    assistant_message_id INTEGER,
    cancel_reason TEXT,
    error_code TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    FOREIGN KEY (conversation_id) REFERENCES chat_conversations(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
```

索引和约束：

- `UNIQUE(conversation_id, client_request_id)` 防止同一个客户端请求重复创建。
- partial unique index：同一个 conversation 的 `running` turn 最多一条。
- `fence` 在 conversation 内递增，finalize 使用 `turn_id + fence`，避免旧
  worker 仅凭 conversation/status 越权提交。

turn 状态只有四种：`running`、`cancelled`、`completed`、`failed`。cancel
采用立即失效语义：数据库状态先变为 `cancelled`，随后旧 pipeline 即使继续
运行，所有持久化入口都会拒绝它。

## 服务端数据流

### Reserve

`POST /api/chat/conversations/{id}/messages` 首先调用服务层
`reserve_chat_turn(conversation_id, user_id, client_request_id, content)`，在
一个 SQLite `BEGIN IMMEDIATE` 事务中完成：

1. 校验 conversation 归属和 active 状态。
2. 查询相同 `client_request_id`；已存在则返回幂等冲突/已有状态，不新增消息。
3. 查询 running turn；存在则返回 `TURN_IN_PROGRESS`。
4. 生成 `turn_id` 和递增 `fence`。
5. 同一事务插入 `chat_turns` 和 user message，并把 `user_message_id` 写回 turn。

路由把 `turn_id` 放进首个 SSE `turn_started` 事件，并将它传给
`run_chat(turn_id=...)`。

### Cancel

新增：

```text
POST /api/chat/conversations/{conversation_id}/turns/{turn_id}/cancel
```

服务端按 user/conversation/turn 校验后，把 `running` 更新为 `cancelled`。
重复 cancel 是幂等的，返回当前状态。前端先调用 cancel，再 abort 当前 SSE
controller；如果服务端已经因连接断开进入 finally，也按同样的状态转换处理。

### Finalize

assistant 持久化不再调用普通的 active conversation 检查，而调用
`finalize_chat_turn(turn_id, fence, conversation_id, user_id, content, metadata)`。
该函数在一个事务中：

1. 只允许 `chat_turns.status = 'running'` 且身份/fence 全部匹配。
2. 插入 assistant message（如果有内容）。
3. 更新 turn 为 `completed`，记录 assistant message id 和 finished_at。
4. 更新 conversation.updated_at。

如果没有匹配行，抛出 `TurnCancelled`/`TurnNotFound`，绝不写 assistant message。
pipeline 在 asked-question、active skills、MCP session 和 memory 后台任务等
副作用前调用同一个 `assert_chat_turn_active()`，取消后的旧 worker 不再产生
这些事实。

### Failure / disconnect

- 正常生成异常：turn 标记 `failed`，SSE 返回现有 error 事件。
- 客户端断开：SSE generator finally 尝试将仍为 running 的 turn 标记为
  `cancelled`；正常 completed turn 不被覆盖。
- 取消后新消息可以马上 reserve 新 turn；旧 turn 的 finalize 因状态不匹配
  失败。

## 前端行为

- `sendMessage()` 每次生成一个 UUID `client_request_id`。
- `postSSE()` 支持传出当前请求专属 `AbortController`。
- ChatView 只保存当前 turn 的 controller/id，不再调用全局
  `cancelAllRequests()` 作为停止手段。
- 收到 `turn_started` 后记录 `turn_id`。
- 点击停止时调用 cancel API；取消完成后 abort 当前 stream，清理临时流式
  内容，并重新加载当前 conversation 消息以消除本地 optimistic 状态。
- `TURN_IN_PROGRESS`、`TURN_ALREADY_EXISTS` 显示明确提示，不追加错误 assistant
  消息。

## 错误契约

- `409 TURN_IN_PROGRESS`：当前 conversation 已有进行中的 turn。
- `409 TURN_IDEMPOTENCY_CONFLICT`：同一 client request 已创建过 turn。
- `409 TURN_NOT_ACTIVE`：取消或 finalize 时 turn 已失效。
- `404 TURN_NOT_FOUND`：turn 不属于当前用户或不存在。

## 测试

后端新增 turn service/router 测试：

- 同一个 request id 不重复插入 user message。
- 两个不同 request 并发 reserve 只有一个成功。
- cancel 后 finalize 不插入 assistant message。
- 正常 finalize 只提交一次，重复 finalize 被拒绝。
- 非本人不能 cancel 或 finalize。
- SSE 首事件包含 turn_id，cancel endpoint 返回幂等状态。

前端至少验证：

- stop 使用当前 controller 和 cancel API，不调用全局取消。
- `client_request_id` 在一次发送生命周期内保持不变。
- cancel/error 后不会追加伪造 assistant 错误消息。

验证命令：

```bash
docker compose --profile test run --rm test uv run pytest \
  backend/tests/chat/test_chat_turns.py \
  backend/tests/chat/test_chat.py -q
cd frontend && npm run build
```
