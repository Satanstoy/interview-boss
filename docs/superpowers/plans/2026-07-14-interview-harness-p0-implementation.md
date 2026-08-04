# Interview Harness P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留现有 turn lifecycle 的前提下，收紧模拟面试 harness 的执行边界、请求幂等、prompt trust boundary 和 assistant regenerate 语义。

**Architecture:** P0 在现有 SQLite/FastAPI/SSE 结构上增量修改。ToolPolicy 在共享 executor 处成为最后授权边界；chat turn 通过 fingerprint 支持冲突识别和 status/replay；revision 复用 turn fence 但不创建新的 user message。P1/P2 的 Outbox、CandidateSet 和 EvidenceBundle 不在本计划实现。

**Tech Stack:** Python 3.10, FastAPI, Pydantic, SQLite WAL migrations, Vue 3, Docker test-runtime, pytest。

## Global Constraints

- 测试必须通过 `docker compose --profile test run --rm test ...` 执行。
- 遵循 TDD：每个行为先写一个会失败的测试，再实现最小代码。
- 不使用新的 Python/JS 依赖。
- 修改 backend/frontend/docs 对应的 `CLAUDE.md`。
- 不修改 P1/P2 未来模型；P0 只新增 request fingerprint、revision linkage 和执行边界。

### Task 1: 写入并审阅 P0/P1/P2 设计规格

**Files:**
- Create: `docs/superpowers/specs/2026-07-14-interview-harness-p0-boundary-hardening-design.md`
- Create: `docs/superpowers/specs/2026-07-14-interview-harness-p1-durable-side-effects-design.md`
- Create: `docs/superpowers/specs/2026-07-14-interview-harness-p2-structured-turn-design.md`
- Create: `docs/superpowers/plans/2026-07-14-interview-harness-p0-implementation.md`

- [x] 明确 P0/P1/P2 边界、数据契约、错误码和验证命令。
- [x] 自审：确保 P0 没有承诺 P1 Outbox 或 P2 CandidateSet。

### Task 2: 统一 tool execution policy

**Files:**
- Modify: `backend/app/agents/chat/tool_policy.py`
- Modify: `backend/app/agents/chat/tools.py:270-297`
- Modify: `backend/app/agents/chat/react_loop.py:108-150`
- Test: `backend/tests/chat/test_tool_policy.py`
- Test: `backend/tests/chat/test_tools.py`

**Interfaces:**
- `enforce_tool_call(tool_call: dict, state: ChatState, policy: ToolPolicy | None = None) -> dict`
- `ToolPolicyViolation.code: str`
- `execute_tool(tool_call: dict, state: ChatState, policy: ToolPolicy | None = None) -> str`

- [x] 写测试：policy 禁止的已知工具在 executor 处被拒绝，且工具实现没有被调用。
- [x] 写测试：非法参数和不允许的 skill 返回稳定错误码。
- [x] 运行 Docker 单测确认 RED。
- [x] 在 `tool_policy.py` 集中调用 `validate_tool_arguments` 并规范化调用参数。
- [x] 让 `execute_tool()` 在 dispatch 前强制调用授权函数；无显式 policy 时从当前 state 构建。
- [x] 让 `react_loop.validate_tool_call()` 委托同一函数，保持 `StopRun` 兼容。
- [x] 运行 tool policy、tool gateway、react loop 测试确认 GREEN。

### Task 3: request fingerprint、status 和 replay

**Files:**
- Modify: `backend/app/db/migrations/chat.py`
- Modify: `backend/app/db/migrations/__init__.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/routers/chat.py`
- Modify: `backend/tests/chat/test_chat_turns.py`
- Modify: `backend/tests/chat/test_chat.py`

**Interfaces:**
- `build_turn_request_fingerprint(content: str, model: str | None = None, revision_of_message_id: int | None = None) -> str`
- `reserve_chat_turn(..., request_fingerprint: str | None = None) -> ChatTurn`
- `get_chat_turn(turn_id: str, conversation_id: str | None = None, user_id: int | None = None) -> dict | None`
- `GET /api/chat/conversations/{conversation_id}/turns/{turn_id}`

- [x] 写测试：同 request ID + 同 fingerprint 不增加 user message。
- [x] 写测试：同 request ID + 不同 content/model 抛出 `TurnIdempotencyConflict`。
- [x] 写测试：status endpoint 只允许 owner 读取并返回 assistant replay data。
- [x] 运行 turn tests 确认 RED。
- [x] 新增 migration 044 的 `request_fingerprint` 和 revision linkage 字段。
- [x] 在 reserve 和 router 中计算并保存 canonical SHA-256 fingerprint。
- [x] 为重复 completed turn 提供只读 replay/status 结果；不重新运行 pipeline。
- [x] 更新错误契约和 SSE `turn_started` metadata。
- [x] Docker 运行 turn/router 测试确认 GREEN。

### Task 4: assistant revision API

**Files:**
- Modify: `backend/app/db/migrations/chat.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/routers/chat.py`
- Modify: `frontend/src/services/chatApi.js`
- Modify: `frontend/src/components/business/ChatView.vue`
- Modify: `backend/tests/chat/test_chat_turns.py`
- Create or modify: `frontend/tests/e2e/chat-revision.spec.js`

**Interfaces:**
- `reserve_chat_revision(conversation_id: str, user_id: int, assistant_message_id: int, client_request_id: str, model: str | None = None) -> tuple[ChatTurn, str]`
- `POST /api/chat/conversations/{conversation_id}/messages/{assistant_message_id}/regenerate`
- `chatApi.regenerateMessage(conversationId, assistantMessageId, onEvent, model, options)`

- [x] 写测试：revision turn 复用原 user message，不新增 role=user 消息。
- [x] 写测试：非本人、非 assistant、无父 turn 的目标被拒绝。
- [x] 运行 backend revision test 确认 RED。
- [x] 创建 revision turn，记录 `revision_of_message_id`、revision number 和 fingerprint。
- [x] 普通发送和 revision 共用现有 finalize/fence SSE streaming。
- [x] 前端 regenerate 调用 revision API，删除本地截断重发逻辑。
- [x] 前端 build 和 backend revision contract tests 确认 GREEN；前端 E2E 未新增，依赖现有构建与 backend contract 覆盖。

### Task 5: prompt trust boundary

**Files:**
- Modify: `backend/app/agents/chat/prompts.py`
- Modify: `backend/app/agents/chat/nodes.py:1028-1059,1834-1894`
- Modify: `backend/tests/chat/test_multi_turn_e2e.py`
- Create or modify: `backend/tests/chat/test_prompt_trust_boundary.py`

**Interfaces:**
- `wrap_untrusted_context(source: str, value: object, max_chars: int | None = None) -> str`

- [x] 写测试：JD/resume/memory/session notes 中的伪指令仍被包在 untrusted tags 内。
- [x] 写测试：helper 截断长度并保留 source 标签。
- [x] 运行 prompt tests 确认 RED。
- [x] 在 prompt helper 中加入统一 trust instruction 和 XML-like context wrapper。
- [x] 替换 JD、resume、interview_context、memory、session notes、compressed history 的直接拼接。
- [x] 保留现有内容可见性，避免改变正常面试语义。
- [x] Docker 运行 chat prompt/e2e 测试确认 GREEN。

### Task 6: evaluator contract

**Files:**
- Modify: `backend/scripts/eval_framework/http_client.py`
- Modify: `backend/scripts/eval_framework/runner.py`
- Modify: `backend/scripts/eval_framework/metrics.py`
- Modify: `backend/tests/chat/test_eval_interview_agent.py`

**Interfaces:**
- `_iter_sse_events(..., client_request_id: str | None = None) -> list[dict]`
- `send_message_and_collect(...) -> dict` with `client_request_id`, `turn_id`, `terminal_status`

- [x] 写测试：eval POST body 含 client_request_id，且同一 send lifecycle 不变。
- [x] 写测试：terminal SSE 与 turn status 不一致时结果标记为 harness error。
- [x] 运行 eval unit tests 确认 RED。
- [x] 给每个 runner turn 生成 UUID，记录 `turn_started.turn_id`。
- [x] 增加 status reconciliation 请求；保留真实 eval 不调用时的可测试注入点。
- [x] 将 mismatch 计入 metrics 并阻止误评分为通过。
- [x] Docker 运行 eval/chat tests 确认 GREEN。

### Task 7: 文档与全量验证

**Files:**
- Modify: `backend/app/agents/chat/CLAUDE.md`
- Modify: `backend/app/routers/CLAUDE.md`
- Modify: `backend/app/mcp_server/CLAUDE.md`
- Modify: `backend/tests/chat/CLAUDE.md`
- Modify: `frontend/src/services/CLAUDE.md`
- Modify: `frontend/src/components/business/CLAUDE.md`

- [x] 更新 live flow、revision endpoint、fingerprint 和 prompt trust boundary。
- [x] 运行 `docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q`。
- [x] 运行 `cd frontend && npm run build`。
- [x] 运行 `git diff --check` 和相关静态检查。
- [x] 按逻辑批次提交 P0 代码与文档。
