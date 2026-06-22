# 2026-06-22 Chat Tools Real E2E 验证脚本

## 变更摘要

- 新增 `backend/scripts/verify_chat_tools_real_e2e.py`，用于手动验证真实后端 + 真实 LLM + SSE 下的 chat tools 稳定性。
- 脚本覆盖 RAG 主动练习、算法题、完整回答后出新题、follow-up 负向场景。
- 报告工具调用率、selected_question 绑定率、question_plan 命中率、repair/fallback 和内部标记泄露。

## 运行方式

```bash
RUN_REAL_CHAT_E2E=1 \
  docker compose exec backend uv run python backend/scripts/verify_chat_tools_real_e2e.py
```

脚本默认在 backend 容器内创建/复用临时 E2E 用户并签发短期 access token，不需要账号密码。也支持显式传 `--token` 或 `E2E_ACCESS_TOKEN`。

## 安全说明

- 默认不运行真实 LLM；必须设置 `RUN_REAL_CHAT_E2E=1`。
- 不硬编码账号、密码、token 或 API key。
- 不直接修改题库或用户配置。
- 默认清理测试会话；传 `--keep-conversation` 才保留。

## 验证

```bash
docker compose --profile test run --rm --build test uv run python backend/scripts/verify_chat_tools_real_e2e.py
```

预期返回码为 2，并输出：`Refusing to run real LLM E2E. Set RUN_REAL_CHAT_E2E=1.`
