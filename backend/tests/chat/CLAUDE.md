# Tests — Chat 测试

Chatbot 功能测试：agent 流程、记忆、预算、路由。

## 测试文件

| 文件 | 测试对象 |
|------|---------|
| `test_chat.py` | 对话基础功能 |
| `test_chat_agent_bugs.py` | Agent bug 回归 |
| `test_chat_budget.py` | Token 预算管理 |
| `test_chat_fast_path.py` | 快速路径（无需 LLM） |
| `test_chat_memory_recall.py` | 记忆召回 |
| `test_chat_routing.py` | 条件路由 |
| `test_chat_session_notes.py` | 会话笔记 |
| `test_chat_skills.py` | Skills 系统（Skill 基类、Registry、匹配、prompt 构建） |

## 运行

```bash
docker compose exec backend uv run pytest backend/tests/chat/ -q
```
