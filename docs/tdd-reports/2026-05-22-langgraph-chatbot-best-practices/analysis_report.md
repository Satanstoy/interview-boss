# LangGraph Chatbot 最佳实践研究报告

**日期:** 2026-05-22
**状态:** 分析完成，待决策

## 研究摘要

搜索了 15+ 篇 LangGraph chatbot 生产实践文章/代码库，提炼出 6 个核心模式。

## 我们的现状 vs LangGraph 最佳实践

| LangGraph 模式 | 我们的实现 | 差距 |
|---------------|-----------|------|
| 两节点摘要模式 (call_model → should_continue → summarize) | ✅ 三级渐进压缩 (budget.py) | **已超越** — LangGraph 官方只有单级摘要 |
| 分离状态键 (messages vs summary) | ✅ message_history vs compressed_context | **已对齐** |
| 增量后响应索引 (Librarian 模式) | ✅ extract_memory 异步提取 | **已对齐** |
| 三层记忆 (短期/长期/摘要) | ✅ 消息历史 + chat_memories + session_notes | **已对齐** |
| Checkpoint 容错 | ❌ 状态为每次请求临时对象 | **缺失** |
| 无限消息增长控制 | ⚠️ 有 trim 但无 reducer 防护 | **部分缺失** |

## 核心发现

### 1. 两节点摘要模式 (LangGraph 官方推荐)

```
START → call_model → should_continue
                        ├── messages > 6 → summarize_conversation → END
                        └── messages ≤ 6 → END
```

**关键实现:**
- `should_continue` 检查消息数量，条件路由到摘要节点
- 摘要节点将旧消息压缩为 running summary，仅保留最近 2 条
- LLM 接收两层上下文：dense summary + recent turns

**我们的情况:** 我们的 `budget.py` 五级级联已经覆盖且超越了这个模式。但我们可以借鉴"条件路由"的思路，让压缩决策更显式。

### 2. 无限消息增长控制 (`Annotated[list, add]` reducer)

```python
class State(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]  # 自动追加，不覆盖
```

**关键教训:** "Without the `add_messages` reducer, LangGraph replaces the entire `messages` list on every node return. With it, new messages are appended."

**我们的情况:** 我们的 `chat_service.get_messages()` 每次从 DB 加载全量消息（limit=100），不存在无限增长问题。但 `message_history` 在 state 中没有 reducer 保护。

### 3. Librarian 模式 (LLM 选择性记忆召回)

```
1. Index (post-response): 每条消息摘要为 ≤3 句 (~104 tokens vs ~328 tokens)
2. Select (online): LLM 推理摘要索引，选出相关消息
3. Hydrate (online): 获取选中消息的完整内容 + 最近 N 轮
```

**关键数据:** 短消息 (<200 chars) 跳过摘要直接使用，节省 LLM 调用。

**我们的情况:** 我们的 `classify_and_recall` 已经实现了类似模式（LLM 选择相关记忆）。但消息索引部分我们用的是 session_notes（手动维护），不是自动索引。

### 4. Checkpoint 容错 (生产必备)

```
MemorySaver (开发) → SqliteSaver (单机) → PostgresSaver (生产)
```

**关键教训:**
- "MemorySaver is for tutorials. PostgresSaver is for production."
- "thread_id is the unit of persistence. Without it, the checkpointer cannot save state."
- "The checkpointer is a write-after-every-node abstraction."

**我们的情况:** 我们用 SQLite 存储消息和记忆（chat_service），但没有 checkpoint 机制。如果服务器重启，进行中的对话会丢失。不过我们的对话是单次请求-响应模式（SSE 流式），不涉及长时间暂停，所以 checkpoint 的价值有限。

### 5. FastAPI + LangGraph 生产模式

```
graph = builder.compile(checkpointer=checkpointer)  # 启动时编译一次
# 请求处理：
config = {"configurable": {"thread_id": f"{user_id}:{conversation_id}"}}
async for event in graph.astream(state, config=config, stream_mode="messages"):
    yield f"data: {json.dumps(event)}\n\n"
```

**关键决策:**
- 图在启动时编译一次，不是每次请求
- thread_id 编码 tenant + user + session
- `X-Accel-Buffering: no` 禁用 Nginx 缓冲
- `astream_events(version="v2")` 获取细粒度流式事件

**我们的情况:** 我们的 `run_chat` 是 async generator，直接 yield SSE 事件。模式类似但没有用 LangGraph 框架。SSE 头部已设置 `X-Accel-Buffering: no`。

### 6. 条件路由防止越界

```python
# 结构性阻止：agent 只能去显式定义的节点
builder.add_conditional_edges("agent", tools_condition)
# 循环控制：max_attempts 防止无限执行
if state["attempt_count"] > MAX_ATTEMPTS:
    return END
```

**我们的情况:** 我们的 intent 路由已经有条件分支（interview/practice → RAG，chat/follow_up → direct）。但没有最大尝试次数限制。

## 值得借鉴的改进点

### 改进 1: 条件路由显式化 (中优先级)

将 `graph.py` 中的 `if/else` 路由改为更显式的路由函数，便于测试和维护。

**现状:**
```python
if intent in ("practice_request", "interview_question"):
    # RAG path
else:
    # direct path
```

**改进:**
```python
def route_after_classify(state: ChatState) -> str:
    intent = state.get("intent", "interview_question")
    if intent in ("practice_request", "interview_question"):
        return "rag_retrieve"
    return "direct_respond"
```

### 改进 2: 增量消息索引 (低优先级，高价值)

借鉴 Librarian 模式，在 `extract_memory` 后自动为新消息建立摘要索引。

**现状:** session_notes 手动维护，依赖 LLM 提取。

**改进:** 每条用户消息自动生成 ≤3 句摘要，存入 `chat_memories`，供下次 `classify_and_recall` 使用。

### 改进 3: 最大轮次限制 (低优先级，安全防护)

防止异常情况下对话无限进行。

```python
MAX_ROUNDS = 50
if len(state.get("message_history", [])) > MAX_ROUNDS * 2:
    yield {"type": "error", "message": "对话已达最大轮次限制，请新建对话"}
    return
```

## 不需要改的

| 模式 | 原因 |
|------|------|
| 引入 LangGraph 框架 | 我们的 async generator 模式更轻量，适合 SSE 流式输出 |
| Postgres checkpoint | 我们的对话是单次请求-响应，SQLite 已够用 |
| add_messages reducer | 我们从 DB 加载消息，不存在 state 中的无限增长 |
| MemorySaver | 我们已有 SQLite 持久化（chat_messages 表） |

## 结论

**我们的 chat agent 已经实现了 LangGraph chatbot 的大部分最佳实践**，甚至在某些方面（五级渐进压缩、LLM 语义召回）超越了标准 LangGraph 模式。主要差距在 checkpoint 宥错（但对我们的场景影响有限）和增量消息索引（可选优化）。

建议下一步：
1. 实现改进 1（条件路由显式化）— 代码可读性提升
2. 实现改进 3（最大轮次限制）— 安全防护
3. 改进 2（增量消息索引）作为未来优化
