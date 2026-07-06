# MCP Server — Interview Tool Boundary

后端内嵌 MCP 工具服务。这里承载模拟面试 agent 的可执行动作，agent 只决定“调用什么工具”和“如何对用户表达”，不在提示词里自由执行搜索、抽题或选题逻辑。

## 文件职责

| 文件 | 职责 |
|------|------|
| `app.py` | FastMCP app 定义，导出 `mcp` 与可挂载的 `mcp_app`；处理 `/mcp` 认证、CSRF 豁免、session 加载/持久化 |
| `interview_tools.py` | 加载 skill、搜索、抽题、选题工具的稳定执行层；更新 chat state 并返回统一 envelope |
| `session.py` | MCP session 状态存储：Redis 优先，SQLite 兜底，支持 sync/async API，跨调用保留 active_skills / retrieved_questions |
| `__init__.py` | 包初始化 |

## 契约

- 所有工具返回统一 `ok/tool/items|selected_question/metadata/error` envelope，包括 `load_skill`。所有 envelope 经过 `build_success_envelope` / `build_error_envelope` 构造，包含 `metadata.metrics`（ToolMetrics）和 `debug_reason`。
- `select_question_tool` 支持 `candidate_index` 参数，内部做空候选（`NO_CANDIDATES`）和越界（`INDEX_OUT_OF_RANGE`）检查；双入口（内部 ReAct via `tools.py` / 外部 MCP via `app.py`）错误码一致。
- `interview_tools.py` 可以调用 service 层；`agents/chat/tools.py` 不应直接组装搜索或抽题 envelope（纯转发）。
- MCP 对外函数参数注解保持朴素类型（如 `str`、`int`、`list`、`dict`），避免 FastMCP 对 `str | None`、`list[str]` 等注解解析失败。
- 每个 MCP 工具都接受 `session_id: str`；不传则自动生成。同一 session 内的 state 会持久化，外部 agent 可以分步调用 `load_skill` → `draw_questions` → `select_question`。
- `search_questions_tool()` / `draw_questions_tool()` 必须通过 `question_plan._collect_question_exclusion_ids()` 合并本轮和历史 metadata 中已问/已展示候选题号，并从 `interview_asked_questions` 合并跨对话历史已问题号到 service 层 `exclude_ids`；防重题属于工具执行边界，不能只靠模型 prompt 自觉。
- `/mcp` 端点已豁免 CSRF；若环境变量 `MCP_API_KEY` 设置，则要求请求头 `X-MCP-API-Key` 或查询参数 `mcp_api_key` 匹配，否则返回 401。
- 新增可执行工具时，先在本目录落工具函数，再由 agent executor 或 FastMCP app 转发调用；同时更新 `session.py` 的持久化字段白名单。

## 双入口 Session 持久化策略

| 入口 | state 来源 | session 持久化 |
|---|---|---|
| 内部 ReAct (`pipeline.py`) | `ChatState` TypedDict，pipeline 内存流转 | ReAct 循环结束后调用 `await save_mcp_session_async(session_id, state)` |
| 外部 MCP (`app.py`) | `_init_tool_state_async` 从 `load_mcp_session_async` 加载 | `save_mcp_session_async` 持久化到 Redis/SQLite |

两个入口共享同一个 session 基础设施。ASGI / FastMCP / pipeline 路径必须使用 async 变体（`load_mcp_session_async` / `save_mcp_session_async`），因为运行时 Redis pool 的 `get` / `setex` 可能返回 coroutine；同步 `load_mcp_session` / `save_mcp_session` 只保留给同步测试或非 ASGI 调用，遇到 awaitable Redis 会关闭 coroutine 并降级 SQLite，避免 `Redis.execute_command was never awaited` warning。内部 ReAct 路径的 `session_id` 默认等于 `conversation_id`（存入 `ChatState.session_id`）。持久化白名单见 `session.py:_PERSISTED_STATE_KEYS`。内部路径只在 ReAct 循环结束时持久化，不在每次工具执行后（避免性能开销）。

## 修改后必做

1. 更新 `backend/tests/chat/test_interview_mcp_tools.py`
2. 更新 `backend/tests/chat/test_mcp_session.py`（如涉及 session 字段变更）
3. 运行 `docker compose --profile test run --rm --build test uv run pytest backend/tests/chat/test_interview_mcp_tools.py backend/tests/chat/test_tools.py backend/tests/chat/test_mcp_session.py -q`
