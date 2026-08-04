# MCP Server — Interview Tool Boundary（单轨双入口架构）

后端内嵌 MCP 工具服务。这里承载模拟面试 agent 的可执行动作，agent 只决定"调用什么工具"和"如何对用户表达"，不在提示词里自由执行搜索、抽题或选题逻辑。

**架构说明**：这是**单轨双入口**架构——`interview_tools.py` 是唯一的工具执行层，被两个入口共享：
- **内部 ReAct**（`pipeline.py` → `agents/chat/tools.py`）：直接函数调用，低延迟
- **外部 MCP**（`/mcp` 端点）：通过 MCP 协议调用，支持外部 agent

两个入口共享同一个执行层和 session 基础设施，不是"双轨"。

## 文件职责

| 文件 | 职责 |
|------|------|
| `app.py` | FastMCP app 定义，导出 `mcp` 与可挂载的 `mcp_app`；处理 `/mcp` 的账户级 MCP Token 认证、旧 API key + JWT 兼容、CSRF 豁免、session 加载/持久化 |
| `interview_tools.py` | 加载 skill、搜索、抽题、选题工具的稳定执行层；更新 chat state 并返回统一 envelope |
| `session.py` | MCP session 状态存储：Redis 优先，SQLite 兜底，支持 sync/async API，按 user_id 隔离 session key，跨调用保留 active_skills / retrieved_questions |
| `principal.py` | 外部 MCP 请求级账户 principal 的 ContextVar，供工具初始化和 session 命名空间读取 |
| `__init__.py` | 包初始化 |

## 契约

- 所有工具返回统一 `ok/tool/items|selected_question/metadata/error` envelope，包括 `load_skill`。所有 envelope 经过 `build_success_envelope` / `build_error_envelope` 构造，包含 `metadata.metrics`（ToolMetrics）和 `debug_reason`。
- `select_question_tool` 只接受服务端 session 中的候选集和 `candidate_index`，拒绝 `candidates` 客户端参数；内部做空候选（`NO_CANDIDATES`）、越界（`INDEX_OUT_OF_RANGE`）和用户缺失检查，并按 `user_id` / `bank_mode` / 当前岗位从题库重新加载选中题目。题目不可见或已失效时返回 `QUESTION_NOT_AVAILABLE`，不能信任候选 payload 中的题干和分类。双入口（内部 ReAct via `tools.py` / 外部 MCP via `app.py`）共享同一执行层。
- `interview_tools.py` 可以调用 service 层；`agents/chat/tools.py` 不应直接组装搜索或抽题 envelope（纯转发）。
- MCP 对外函数参数注解保持朴素类型（如 `str`、`int`、`list`、`dict`），避免 FastMCP 对 `str | None`、`list[str]` 等注解解析失败。生产环境外部 HTTP 请求必须通过用户设置页生成的账户级 MCP Bearer Token；旧部署也可继续使用 API key + Bearer access token。只有显式设置 `MCP_ALLOW_ANONYMOUS=true` 才允许开发/测试匿名请求。
- 每个 MCP 工具都接受 `session_id: str`；不传则自动生成。同一 session 内的 state 会持久化。MCP 初始化 instructions 和每个 session 会自动加载 `interview-tool-use`；外部 agent 只需按需调用领域 skill 的 `load_skill`，再分步调用 `search_questions` / `draw_questions` → `select_question`。
- `search_questions_tool()` / `draw_questions_tool()` 必须通过 `question_plan._collect_question_exclusion_ids()` 合并本轮和历史 metadata 中已问/已展示候选题号，并始终从 `interview_asked_questions` 合并当前会话已问题号到 service 层 `exclude_ids`。正常抽题还要排除同用户跨会话历史；分布控制的兜底重用只可放开后者，绝不能重问当前会话题目。防重题属于工具执行边界，不能只靠模型 prompt 自觉。
- `/mcp` 端点已豁免 CSRF；默认要求 `Authorization: Bearer <account-mcp-token>`。Token 与账户一一对应，轮换后旧 Token 立即失效；账户 Token 中的 user_id 与数据库策略组成请求 principal，客户端传入的 user_id / bank_mode 不能覆盖它；Redis/SQLite session key 使用 `mcp:{user_id}:{session_id}` 命名空间。
- `draw_questions` 支持 `job_position` 覆盖当前账户岗位；未传时使用账户当前岗位，岗位过滤仍走统一题库可见性查询。
- 匿名开发模式只允许 public、无 user identity 的 session；`user_id`/`bank_mode` 请求参数和 anonymous session 中残留的身份字段必须被清空/覆盖，不能借匿名模式读取个人题库或用户级 asked-question 事实。
- 新增可执行工具时，先在本目录落工具函数，再由 agent executor 或 FastMCP app 转发调用；同时更新 `session.py` 的持久化字段白名单。

## 双入口 Session 持久化策略

| 入口 | state 来源 | session 持久化 |
|---|---|---|
| 内部 ReAct (`pipeline.py`) | `ChatState` TypedDict，pipeline 内存流转 | ReAct 循环结束后调用 `await save_mcp_session_async(session_id, state)` |
| 外部 MCP (`app.py`) | `_init_tool_state_async` 从 `load_mcp_session_async` 加载 | `save_mcp_session_async` 持久化到 Redis/SQLite |

两个入口共享同一个 session 基础设施。ASGI / FastMCP / pipeline 路径必须使用 async 变体（`load_mcp_session_async` / `save_mcp_session_async`），因为运行时 Redis pool 的 `get` / `setex` 可能返回 coroutine；同步 `load_mcp_session` / `save_mcp_session` 只保留给同步测试或非 ASGI 调用，遇到 awaitable Redis 会关闭 coroutine 并降级 SQLite，避免 `Redis.execute_command was never awaited` warning。内部 ReAct 路径的 `session_id` 默认等于 `conversation_id`（存入 `ChatState.session_id`），保存时显式传入 `user_id` 做隔离。持久化白名单见 `session.py:_PERSISTED_STATE_KEYS`。内部路径只在 ReAct 循环结束时持久化，不在每次工具执行后（避免性能开销）。

## 修改后必做

1. 更新 `backend/tests/chat/test_interview_mcp_tools.py`
2. 更新 `backend/tests/chat/test_mcp_session.py`（如涉及 session 字段变更）
3. 运行 `docker compose --profile test run --rm --build test uv run pytest backend/tests/chat/test_interview_mcp_tools.py backend/tests/chat/test_tools.py backend/tests/chat/test_mcp_session.py -q`
