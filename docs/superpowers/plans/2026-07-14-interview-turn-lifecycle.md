# Interview Chat Turn Lifecycle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为模拟面试增加服务端 turn fence，保证单会话单 active turn、取消失效、幂等发送和条件 finalize。

**Architecture:** 新增 `chat_turns` 表作为回合事实源。发送入口在一个 SQLite `BEGIN IMMEDIATE` 事务中 reserve turn 与 user message；取消将 turn 立即标记为 cancelled；assistant、asked-question、active skills、MCP session 等持久化入口都必须验证 turn 身份和 running 状态。前端为每条 chat SSE 保存独立 AbortController，并在 abort 前调用 cancel API。

**Tech Stack:** Python 3.10, FastAPI, SQLite WAL, Vue 3, SSE, Docker test-runtime。

## Global Constraints

- 测试必须通过 Docker `test-runtime` 执行；前端使用 `cd frontend && npm run build`。
- 先写失败测试并确认失败，再写最少生产代码；每个逻辑批次单独提交。
- 不实现编辑分支、coverage event sourcing、OAuth 或 provider 级完整 token cancellation。
- 不修改已有历史消息；旧客户端不传 `client_request_id` 时由服务端生成随机值。
- assistant finalize 必须使用 `turn_id + fence + conversation_id + user_id + status=running` 条件。
- 取消后的旧 pipeline 不能写 assistant、asked question、active skill metadata 或 MCP session。
- 修改后更新相关 `CLAUDE.md`；逻辑批次完成后立即使用 Conventional Commit。

---

### Task 1: Add chat turn schema and service state machine

**Files:**
- Modify: `backend/app/db/migrations/chat.py`
- Modify: `backend/app/db/migrations/__init__.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/services/CLAUDE.md`
- Test: `backend/tests/chat/test_chat_turns.py`

**Interfaces:**
- `reserve_chat_turn(conversation_id, user_id, client_request_id, content) -> ChatTurn`
- `cancel_chat_turn(turn_id, conversation_id, user_id, reason) -> ChatTurn`
- `assert_chat_turn_active(turn_id, fence, conversation_id, user_id) -> None`
- `finalize_chat_turn(turn_id, fence, conversation_id, user_id, content, metadata) -> int | None`
- `fail_chat_turn(turn_id, fence, conversation_id, user_id, error_code) -> None`

- [ ] **Step 1: Write failing service tests**

Add tests covering:

```python
def test_reserve_turn_is_idempotent_and_does_not_duplicate_user_message(test_db):
    first = chat_service.reserve_chat_turn("c1", user_id, "req-1", "你好")
    second = chat_service.reserve_chat_turn("c1", user_id, "req-1", "你好")
    assert second.id == first.id
    assert chat_service.get_messages("c1")[-1]["role"] == "user"
    assert len(chat_service.get_messages("c1")) == 1


def test_second_running_turn_is_rejected(test_db):
    chat_service.reserve_chat_turn("c1", user_id, "req-1", "第一条")
    with pytest.raises(chat_service.TurnInProgress):
        chat_service.reserve_chat_turn("c1", user_id, "req-2", "第二条")


def test_cancelled_turn_cannot_finalize_assistant_message(test_db):
    turn = chat_service.reserve_chat_turn("c1", user_id, "req-1", "你好")
    chat_service.cancel_chat_turn(turn.id, "c1", user_id, "client_stop")
    with pytest.raises(chat_service.TurnCancelled):
        chat_service.finalize_chat_turn(
            turn.id, turn.fence, "c1", user_id, "不应落库", {}
        )
    assert chat_service.get_messages("c1")[-1]["role"] == "user"
```

Use a real in-memory SQLite fixture and create an active conversation; do not mock
the service SQL.

- [ ] **Step 2: Run tests and verify the missing state machine fails**

Run:

```bash
docker compose --profile test run --rm test uv run pytest \
  backend/tests/chat/test_chat_turns.py -q
```

Expected: FAIL because migration 043 and turn service interfaces do not exist.

- [ ] **Step 3: Add migration 043**

In `backend/app/db/migrations/chat.py`, add `_migration_043_chat_turns` with
the columns from the design spec, a unique `(conversation_id, client_request_id)`
index, a partial unique index for `status = 'running'`, and an index on
`(conversation_id, fence)`. Re-export and register it as migration 43 in
`backend/app/db/migrations/__init__.py`.

- [ ] **Step 4: Implement atomic reserve/cancel/finalize service functions**

Use `BEGIN IMMEDIATE` in `reserve_chat_turn` to serialize the active-turn check,
fence allocation, turn insert, and user-message insert. Map duplicate request IDs
to the existing turn without inserting a second user message. Map a different
running turn to `TurnInProgress`. Make finalize insert the assistant row and mark
the turn completed in one transaction, with all identity/fence/status predicates
in the same write path. Keep existing generic message helpers for conversation
opening and backward-compatible tests.

- [ ] **Step 5: Run service tests and commit**

```bash
docker compose --profile test run --rm test uv run pytest \
  backend/tests/chat/test_chat_turns.py -q
git add backend/app/db/migrations/chat.py \
  backend/app/db/migrations/__init__.py \
  backend/app/services/chat_service.py \
  backend/app/services/CLAUDE.md \
  backend/tests/chat/test_chat_turns.py
git commit -m "fix(chat): add durable turn lifecycle state"
```

### Task 2: Bind the chat router to turn reserve/finalize/cancel

**Files:**
- Modify: `backend/app/routers/chat.py`
- Modify: `backend/tests/chat/test_chat.py`
- Modify: `backend/tests/chat/test_chat_turns.py`

**Interfaces:**
- Request field: `SendMessageRequest.client_request_id: str | None`
- Endpoint: `POST /api/chat/conversations/{conversation_id}/turns/{turn_id}/cancel`
- SSE event: first event `turn_started`; cancellation event `cancelled`.

- [ ] **Step 1: Write failing router tests**

Add tests that post two messages to the same conversation while the first turn is
running and assert HTTP 409 `TURN_IN_PROGRESS`. Add a test that calls cancel with
the authenticated user, then asserts a later finalize cannot create an assistant
message. Add a test that an unauthenticated/other user cannot cancel the turn.

- [ ] **Step 2: Run router tests and verify they fail**

```bash
docker compose --profile test run --rm test uv run pytest \
  backend/tests/chat/test_chat.py \
  backend/tests/chat/test_chat_turns.py -q
```

- [ ] **Step 3: Reserve before streaming and finalize by turn fence**

Replace the direct `save_user_message_if_writable` call in `send_message` with
`reserve_chat_turn`. Map conflicts to stable 409 details. Emit `turn_started`
before invoking `run_chat(turn_id=..., fence=...)`. Replace assistant persistence
on `done` with `finalize_chat_turn`; mark failed on ordinary exceptions and mark
cancelled in the stream `finally` when the turn is still running.

- [ ] **Step 4: Add the cancel endpoint and error mapping**

Implement the cancel endpoint with the existing JWT dependency and user ownership
checks. Cancellation must be idempotent and must not turn a completed/failed turn
back into cancelled. Preserve archived conversation 409 behavior.

- [ ] **Step 5: Run router tests and commit**

```bash
docker compose --profile test run --rm test uv run pytest \
  backend/tests/chat/test_chat.py \
  backend/tests/chat/test_chat_turns.py -q
git add backend/app/routers/chat.py \
  backend/tests/chat/test_chat.py \
  backend/tests/chat/test_chat_turns.py
git commit -m "fix(chat): fence streaming turns at the router"
```

### Task 3: Prevent cancelled pipeline side effects

**Files:**
- Modify: `backend/app/agents/chat/state.py`
- Modify: `backend/app/agents/chat/pipeline.py`
- Modify: `backend/app/agents/chat/CLAUDE.md`
- Test: `backend/tests/chat/test_chat_turns.py`

**Interfaces:**
- `run_chat(..., turn_id: str | None = None, turn_fence: int | None = None)`
- Internal `assert_chat_turn_active(state)` guard for persistence boundaries.

- [ ] **Step 1: Write failing pipeline guard tests**

Patch the turn activity assertion to raise `TurnCancelled` after the ReAct result,
then verify `_record_asked_question_if_any`, active-skill persistence, and MCP
session persistence are not called. Keep tests focused on the guard boundary and
do not invoke a real LLM.

- [ ] **Step 2: Run tests and verify they fail**

```bash
docker compose --profile test run --rm test uv run pytest \
  backend/tests/chat/test_chat_turns.py backend/tests/chat/test_react_loop.py -q
```

- [ ] **Step 3: Add turn identity to ChatState and guard side effects**

Pass `turn_id` and `turn_fence` from the router into `_initial_state` and
`run_chat`. Check the turn before asked-question recording, before active-skill
metadata and MCP session saves, and before scheduling memory extraction. The guard
must be a no-op for existing synthetic/internal tests that do not provide a turn.

- [ ] **Step 4: Run focused chat tests and commit**

```bash
docker compose --profile test run --rm test uv run pytest \
  backend/tests/chat/test_chat_turns.py \
  backend/tests/chat/test_react_loop.py \
  backend/tests/chat/test_chat_session_notes.py -q
git add backend/app/agents/chat/state.py \
  backend/app/agents/chat/pipeline.py \
  backend/app/agents/chat/CLAUDE.md \
  backend/tests/chat/test_chat_turns.py
git commit -m "fix(chat): block cancelled turn side effects"
```

### Task 4: Add scoped frontend cancel and request identity

**Files:**
- Modify: `frontend/src/services/http.js`
- Modify: `frontend/src/services/chatApi.js`
- Modify: `frontend/src/components/business/ChatView.vue`
- Modify: `frontend/CLAUDE.md`

**Interfaces:**
- `postSSE(url, body, onEvent, retry, { onController })`
- `chatApi.cancelTurn(conversationId, turnId)`
- `sendMessage` sends `client_request_id` and exposes the current controller.

- [ ] **Step 1: Add frontend test or static contract fixture for scoped cancel**

If the repository has no Vue unit test runner for `ChatView`, add a small service
test/contract assertion for `postSSE` controller exposure and run the existing
frontend build as the behavioral gate. Do not add a new frontend test framework.

- [ ] **Step 2: Implement per-stream controller ownership**

Add an optional `onController` callback to `postSSE`, preserve it across the 401
retry path, and keep existing callers unchanged. `ChatView` stores the controller,
client request id, and server turn id for only the active message.

- [ ] **Step 3: Wire cancel API and reconcile UI state**

Send a UUID `client_request_id`, consume `turn_started`, and make `handleStop`
call `cancelTurn` before aborting the current controller. Treat AbortError,
`cancelled`, `TURN_IN_PROGRESS`, and `TURN_NOT_ACTIVE` as control flow rather than
creating a fake assistant error message. Reload messages after cancellation so the
optimistic local user message matches the server.

- [ ] **Step 4: Build frontend and commit**

```bash
cd frontend && npm run build
git add frontend/src/services/http.js \
  frontend/src/services/chatApi.js \
  frontend/src/components/business/ChatView.vue \
  frontend/CLAUDE.md
git commit -m "fix(chat): scope frontend turn cancellation"
```

### Task 5: Full verification and documentation gate

- [ ] **Step 1: Run targeted phase tests**

```bash
docker compose --profile test run --rm test uv run pytest \
  backend/tests/chat/test_chat_turns.py \
  backend/tests/chat/test_chat.py \
  backend/tests/chat/test_react_loop.py \
  backend/tests/chat/test_chat_session_notes.py -q
```

- [ ] **Step 2: Run complete chat suite**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q
```

- [ ] **Step 3: Run frontend build and final diff review**

```bash
cd frontend && npm run build
git diff --check HEAD~5..HEAD
git status --short
git log -6 --oneline
```

Confirm that user identity, conversation identity, turn id, fence and status are
all checked at finalize; no global cancel remains in ChatView; cancelled turns do
not create assistant messages or background state writes.
