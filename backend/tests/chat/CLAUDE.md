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
| `test_tool_policy.py` | executor 级 ToolPolicy、严格参数和 skill scope 边界 |
| `test_react_loop.py` | ReAct 主循环、tool governance、question plan 绑定与 repair |
| `test_chat_turns.py` | turn fence、取消、幂等 fingerprint、status、assistant revision |
| `test_prompt_trust_boundary.py` | 动态上下文标签和 prompt injection 防护边界 |
| `test_eval_harness_contract.py` | evaluator request ID 与 SSE terminal/status 对账 |
| `test_basis_parser.py` / `test_basis_tracking.py` | basis 解析与追踪 |
| `test_rag_quality.py` / `test_heuristic_rerank.py` / `test_skill_guided_rerank.py` | RAG 质量与重排 |
| `test_chat_tools_real_e2e_verifier.py` | 真实 chat tools E2E verifier 的事件解析和 case 期望矩阵 |
| `test_interview_agent_real_e2e_verifier.py` | 真实多轮模拟面试 verifier 的 opt-in guard、候选人 profile、SSE 轮次解析和质量判定 |
| `test_interview_distribution_plan.py` | 分布计划快照、整数目标分配和事件派生执行状态；包含 50 题计划不受 100 条 chat 上下文窗口截断的回归 |
| `test_interview_distribution_e2e.py` / `test_interview_distribution_e2e_verifier.py` | 题库事实到统计、计划、控制器事件的确定性对齐、显式“下一道技术题”继续/否定指令、HR 独立词边界、50 题计划越过通用上下文与 stop/候选人反问收尾阈值，以及真实 verifier 的 opt-in guard |

## 运行

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q
```
