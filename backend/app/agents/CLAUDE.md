# Agents — LangGraph 状态机

LangGraph StateGraph 实现的异步任务流。每个 agent 有独立子目录。

## 架构

```
agents/
├── submit/         ← JD/面经提交流程（识别→提取→分类→入库）
├── build/          ← 题库构建流程（备份→加载→聚类→生成答案→写入）
├── batch_generate/ ← 批量答案生成
├── chat/           ← 面试 chatbot（记忆召回→上下文构建→LLM 回复）
└── shared/         ← 共享模块（state.py, events.py, quality.py）
```

## 每个 agent 的文件结构

| 文件 | 职责 |
|------|------|
| `graph.py` | StateGraph 定义、节点连接、条件路由 |
| `nodes.py` | 节点实现（每个节点是一个 async 函数） |
| `state.py` | TypedDict 状态定义（在 shared/ 中） |
| `prompts.py` | 提示词模板（如有） |

## 核心规则

- **SSE 流式**：所有 agent 通过 `asyncio.ContextVar` 的 `_event_queue` yield SSE 事件
- **状态传递**：节点通过 `state: TypedDict` 读写数据，禁止用全局变量
- **DB 操作**：节点中的 DB 操作必须用 `run_db()` 包装
- **错误处理**：节点失败时 yield `error` 事件，不抛异常到上层

## 共享模块 (`shared/`)

| 文件 | 职责 |
|------|------|
| `state.py` | SubmitState / BuildState / BatchGenerateState TypedDict |
| `events.py` | SSE 事件格式化（`format_sse`, `make_*_event`） |
| `quality.py` | 分类质量评估、重试决策 |

## 修改后必做

1. 运行 `uv run pytest backend/tests/ -q` 确认 agent 测试通过
2. 更新本文件（如新增 agent 或改变架构）
