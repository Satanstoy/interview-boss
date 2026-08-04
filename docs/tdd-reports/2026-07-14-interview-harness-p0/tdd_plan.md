# 模拟面试 Harness P0 TDD 计划

## 目标

在不改动 P1 Outbox 或 P2 结构化 turn ledger 的前提下，修复 P0 的四类正确性边界：

1. tool executor 不能绕过服务端 ToolPolicy、严格参数和 skill scope。
2. chat turn 使用 `client_request_id + request_fingerprint` 提供可重试、可冲突检测的幂等语义。
3. JD、简历、memory、session notes 和历史摘要进入 prompt 时必须标记为不可执行的外部数据。
4. assistant regenerate 复用原 user message，创建可审计的 revision，而不是追加 user turn。
5. evaluator 必须把 SSE terminal 和持久化 turn status 对账，契约失败不得被评分器掩盖。

## 测试分组

- `test_tool_policy.py`：executor 级授权、skill scope、严格参数。
- `test_chat_turns.py`：fingerprint、status owner boundary、取消、revision 和 metadata。
- `test_prompt_trust_boundary.py`：标签转义、截断和 prompt trust instruction。
- `test_eval_harness_contract.py`：request ID、terminal/status 对账和评分阻断。
- 既有 chat/reAct/MCP/distribution 测试：验证增量改动没有破坏现有行为。

## 验收命令

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q
cd frontend && npm run build
```
