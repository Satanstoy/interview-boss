# MCP Server — Interview Tool Boundary

后端内嵌 MCP 工具服务。这里承载模拟面试 agent 的可执行动作，agent 只决定“调用什么工具”和“如何对用户表达”，不在提示词里自由执行搜索、抽题或选题逻辑。

## 文件职责

| 文件 | 职责 |
|------|------|
| `app.py` | FastMCP app 定义，导出 `mcp` 与可挂载的 `mcp_app` |
| `interview_tools.py` | 加载 skill、搜索、抽题、选题工具的稳定执行层；更新 chat state 并返回统一结果 |
| `__init__.py` | 包初始化 |

## 契约

- 题目类工具返回统一 `ok/tool/items/metadata/error` envelope；`load_skill` 保持 legacy `status/skill/summary` 形状，避免打破 ReAct loop 兼容性。
- `interview_tools.py` 可以调用 service 层；`agents/chat/tools.py` 不应直接组装搜索或抽题 envelope。
- MCP 对外函数参数注解保持朴素类型（如 `str`、`int`、`list`、`dict`），避免 FastMCP 对 `str | None`、`list[str]` 等注解解析失败。
- 新增可执行工具时，先在本目录落工具函数，再由 agent executor 或 FastMCP app 转发调用。

## 修改后必做

1. 更新 `backend/tests/chat/test_interview_mcp_tools.py`
2. 运行 `docker compose --profile test run --rm --build test uv run pytest backend/tests/chat/test_interview_mcp_tools.py backend/tests/chat/test_tools.py -q`
