# Agents — LangGraph 状态机

> 位置：`backend/app/agents/` | 上游调用方：`routers/` | 下游依赖：`services/`, `db/`
> 职责：LangGraph StateGraph 实现的异步任务流。每个 agent 有独立子目录。

## 架构

```
agents/
├── submit/         ← JD/面经提交流程（识别→提取→分类→入库）
├── build/          ← 题库构建流程（备份→加载→聚类→生成答案→写入）
├── batch_generate/ ← 批量答案生成
├── chat/           ← 面试 chatbot（纯 async harness：记忆召回 → 上下文构建 → LLM 语义分类 → ReAct 工具证据循环 → TurnPlanner → contract writer/validator → 记忆提取；40+ 文件）
├── candidate/      ← 评测框架候选人 Skill 包（供 scripts/eval_interview_agent.py 加载）
└── shared/         ← submit/build/batch_generate 共享模块（state.py, events.py, quality.py）
```

## 每个 agent 的文件结构

| 文件 | 职责 |
|------|------|
| `graph.py` | StateGraph 定义、节点连接、条件路由 |
| `nodes.py` | 节点实现（每个节点是一个 async 函数） |
| `state.py` | TypedDict 状态定义；submit/build/batch_generate 在 `shared/state.py`，chat 在 `chat/state.py` |
| `prompts.py` | 提示词模板（如有；chat 有独立 prompts/pipeline/tools） |

`candidate/` 当前只提供评测用 `skills/`，不是生产 LangGraph agent；新增候选人行为策略时保持标准 `SKILL.md` 目录结构，并通过 `get_agent_skill_registry("candidate")` 加载。

## 核心规则

- **SSE 流式**：submit 使用 `asyncio.ContextVar` 的 `_event_queue` 实时推送；build/batch_generate 使用 `astream_events()` 读取节点输出事件；chat 在 `pipeline.py` 内组织 ReAct/流式事件
- **状态传递**：节点通过 `state: TypedDict` 读写数据，禁止用全局变量
- **DB 操作**：节点中的 DB 操作必须用 `run_db()` 包装
- **错误处理**：节点失败时 yield `error` 事件，不抛异常到上层

## 共享模块 (`shared/`)

| 文件 | 职责 |
|------|------|
| `state.py` | SubmitState / BuildBankState / BatchGenerateState TypedDict |
| `events.py` | SSE 事件格式化（`format_sse`, `make_*_event`） |
| `quality.py` | 分类质量评估、重试决策 |

## 修改后必做

1. 运行 `docker compose --profile test run --rm test uv run pytest backend/tests/pipeline/ backend/tests/chat/ -q` 确认 agent 测试通过
2. 更新本文件（如新增 agent 或改变架构）
