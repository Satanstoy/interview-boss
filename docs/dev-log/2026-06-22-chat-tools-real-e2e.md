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

Guard 验证：

```bash
docker compose --profile test run --rm --build test uv run python backend/scripts/verify_chat_tools_real_e2e.py
```

预期返回码为 2，并输出：`Refusing to run real LLM E2E. Set RUN_REAL_CHAT_E2E=1.`

真实 E2E 验证（2026-06-22）：

```bash
docker compose exec -e RUN_REAL_CHAT_E2E=1 backend uv run python backend/scripts/verify_chat_tools_real_e2e.py
```

结果：脚本成功通过 internal token 调用真实后端 SSE，但 4 个 case 中 3 个失败，`tool_call_rate=0%`。后端日志显示 LLM provider 返回 `401 Invalid API Key`，随后 ReAct LLM step 失败并进入 fallback，因此工具调用没有机会发生。需要先修复生产 LLM API Key 后再复测工具调用稳定性。

## 观测面补齐复测（2026-06-22）

补齐内容：

- `chat.py` 通过 `_metadata_events_from_done()` 将 done metadata 拆成公开 SSE 事件。
- 新增 `question_plan` SSE 事件，保持最终 `done` 事件不带完整 metadata。
- `verify_chat_tools_real_e2e.py` 解析拆分后的 `selected_question` 和 `question_plan` 事件，并保留旧版 `done.metadata` fallback。

验证命令：

```bash
DEPLOY_MIN_FREE_MB=512 ./deploy/docker-deploy.sh test -k "test_done_metadata_can_emit_question_plan_event or extract_case_result_reads_split_sse_question_events or extract_case_result_keeps_legacy_done_metadata_fallback" -q
DEPLOY_MIN_FREE_MB=512 ./deploy/docker-deploy.sh update
docker compose exec -T -e RUN_REAL_CHAT_E2E=1 backend uv run python backend/scripts/verify_chat_tools_real_e2e.py
```

验证结果：

```text
Summary:
- cases: 4
- passed: 4
- failed: 0
- tool_call_rate: 75%
- selected_question_rate: 75%
- question_plan_rate: 75%
- repair_count: 0
- fallback_count: 0
- leak_count: 0
```

说明：follow-up 负向场景按预期不调用抽题工具，因此整体工具/选题/计划命中率为 75%。部署前自动备份数据库到 `backups/interview-boss_20260622_155041.db`。

## 工具调用稳定性收紧复测（2026-06-22）

收紧内容：

- `question_plan` SSE event 改为显式字段白名单，禁止透传 `question_text`、`strategy`、`allowed_focus`、`forbidden_focus` 等内部 plan 字段。
- `verify_chat_tools_real_e2e.py` 增加 case 期望矩阵：必须调工具的 case 没有 `search_questions`/`draw_questions` step 会直接 FAIL，避免 selected/question_plan 掩盖工具缺失。
- 真实 E2E 首次严格校验暴露 `complete_answer_new_question` 未调工具；根因是 `project-deep-dive + answer_complete=True` 工具策略允许直接追问。
- 修复 `_build_tool_strategy()`：完整回答且无候选题时，即使在 `project-deep-dive` 模式也必须调用 `search_questions`，确保后续 selected_question/question_plan 绑定。

验证命令：

```bash
DEPLOY_MIN_FREE_MB=512 ./deploy/docker-deploy.sh test -k "test_deep_dive_complete_answer_requires_search or test_done_metadata_can_emit_question_plan_event or extract_case_result_fails_required_tool_case_without_tool_step or extract_case_result_reads_split_sse_question_events or extract_case_result_keeps_legacy_done_metadata_fallback" -q
DEPLOY_MIN_FREE_MB=512 ./deploy/docker-deploy.sh update
docker compose exec -T -e RUN_REAL_CHAT_E2E=1 backend uv run python backend/scripts/verify_chat_tools_real_e2e.py
docker compose --profile test run --rm --build test uv run pytest backend/tests/chat/test_interview_rhythm.py -q
```

验证结果：

```text
Chat tools real E2E:
- cases: 4
- passed: 4
- failed: 0
- tool_call_rate: 75%
- selected_question_rate: 75%
- question_plan_rate: 75%
- repair_count: 0
- fallback_count: 0
- leak_count: 0

Mock interview backend E2E:
- 23 passed
- 16 warnings（既有 pytest.mark.asyncio 同步测试警告）
```

说明：follow-up 负向场景按预期不调用工具，因此严格后的工具/选题/计划命中率仍为 75%；其余 3 个必须调工具的 case 均已出现工具 step 和 question_plan。部署备份数据库到 `backups/interview-boss_20260622_174702.db`。
