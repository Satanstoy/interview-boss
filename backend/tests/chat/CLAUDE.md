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
| `test_langgraph_pipeline.py` | LangGraph chat pipeline |
| `test_react_prompt.py` / `test_react_e2e.py` | ReAct prompt 与端到端行为 |
| `test_tools.py` | ReAct tools、Tool Gateway envelope、工具执行副作用 |
| `test_react_loop.py` | ReAct 主循环、tool governance、question plan 绑定与 repair |
| `test_basis_parser.py` / `test_basis_tracking.py` | basis 解析与追踪 |
| `test_rag_quality.py` / `test_heuristic_rerank.py` / `test_skill_guided_rerank.py` | RAG 质量与重排 |
| `test_chat_tools_real_e2e_verifier.py` | 真实 chat tools E2E verifier 的事件解析和 case 期望矩阵 |

## 运行

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q
```
