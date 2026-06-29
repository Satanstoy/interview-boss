# Shared — Agent 共享模块

submit、build、batch_generate 共用的状态定义、事件格式化、质量评估。chat agent 有独立 `backend/app/agents/chat/state.py`，但也复用 `events.py` 的 SSE 格式化。

## 文件职责

| 文件 | 职责 |
|------|------|
| `state.py` | TypedDict 状态定义（SubmitState / BuildBankState / BatchGenerateState） |
| `events.py` | SSE 事件格式化（`format_sse`, `make_progress_event`, `make_error_event`, `make_done_event`） |
| `quality.py` | 分类质量评估（`evaluate_tagging_quality`）、重试决策（`should_retry`） |

## 核心规则

- 新增非 chat 的 LangGraph agent 时，在 `state.py` 中定义对应 TypedDict；chat 状态继续放 `backend/app/agents/chat/state.py`
- SSE 事件必须通过 `format_sse()` 格式化，前端依赖此格式
- `_event_queue_var` 是 `asyncio.ContextVar`，每个请求独立

## 修改后必做

1. 修改 `state.py` 后确认所有引用该状态的 agent 仍然兼容
2. 修改 `events.py` 后确认前端 SSE 解析逻辑兼容
3. 更新本文件
