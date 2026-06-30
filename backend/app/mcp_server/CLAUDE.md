# MCP Server — Interview Tool Boundary

后端内嵌 MCP 工具服务。这里承载模拟面试 agent 的可执行动作，agent 只决定“调用什么工具”和“如何对用户表达”，不在提示词里自由执行搜索、抽题或选题逻辑。

## 文件职责

| 文件 | 职责 |
|------|------|
| `app.py` | FastMCP app 定义，导出 `mcp` 与可挂载的 `mcp_app`；处理 `/mcp` 认证、CSRF 豁免、session 加载/持久化 |
| `interview_tools.py` | 加载 skill、搜索、抽题、选题工具的稳定执行层；更新 chat state 并返回统一 envelope |
| `session.py` | MCP session 状态存储：Redis 优先，SQLite 兜底，支持跨调用保留 active_skills / retrieved_questions |
| `__init__.py` | 包初始化 |

## 契约

- 所有工具返回统一 `ok/tool/items|selected_question/metadata/error` envelope，包括 `load_skill`。
- `interview_tools.py` 可以调用 service 层；`agents/chat/tools.py` 不应直接组装搜索或抽题 envelope。
- MCP 对外函数参数注解保持朴素类型（如 `str`、`int`、`list`、`dict`），避免 FastMCP 对 `str | None`、`list[str]` 等注解解析失败。
- 每个 MCP 工具都接受 `session_id: str`；不传则自动生成。同一 session 内的 state 会持久化，外部 agent 可以分步调用 `load_skill` → `draw_questions` → `select_question`。
- `/mcp` 端点已豁免 CSRF；若环境变量 `MCP_API_KEY` 设置，则要求请求头 `X-MCP-API-Key` 或查询参数 `mcp_api_key` 匹配，否则返回 401。
- 新增可执行工具时，先在本目录落工具函数，再由 agent executor 或 FastMCP app 转发调用；同时更新 `session.py` 的持久化字段白名单。

## 修改后必做

1. 更新 `backend/tests/chat/test_interview_mcp_tools.py`
2. 更新 `backend/tests/chat/test_mcp_session.py`（如涉及 session 字段变更）
3. 运行 `docker compose --profile test run --rm --build test uv run pytest backend/tests/chat/test_interview_mcp_tools.py backend/tests/chat/test_tools.py backend/tests/chat/test_mcp_session.py -q`
