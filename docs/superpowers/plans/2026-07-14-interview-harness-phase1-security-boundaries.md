# Interview Harness Phase One Security Boundaries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将模拟面试第一阶段的工具授权、题目候选来源、MCP session 身份和 archived conversation 写入边界升级为服务端硬约束。

**Architecture:** 保留现有 `ToolStrategy` 作为 prompt guidance，在其旁边新增不可变 `ToolPolicy`，由 ReAct 每次工具执行前重新计算并强制校验。题目选择继续使用当前 state/session，但只允许索引并按 question ID 从权威题库重载。MCP HTTP 入口使用现有 JWT/API key 能力做 fail-closed 和 session namespace 隔离；Chat 写入口新增 SQLite 原子 active 检查，不在本计划中引入 turn 表。

**Tech Stack:** Python 3.10, FastAPI, Pydantic 2, SQLite WAL, FastMCP, Redis/SQLite MCP session, pytest in Docker test-runtime。

## Global Constraints

- 遵守 `/home/ubuntu/sj/interview-boss/CLAUDE.md`、`backend/app/agents/chat/CLAUDE.md`、`backend/app/mcp_server/CLAUDE.md` 和 `backend/app/db/CLAUDE.md`。
- 测试必须通过 Docker test-runtime 执行，不能在宿主机直接运行 pytest。
- 先写失败测试，确认失败后再写生产代码；每个逻辑批次单独提交。
- 不新增 `chat_turns`、candidate_sets、coverage events 表，不引入 ORM 或 PostgreSQL。
- `ToolStrategy` 仍保留给 prompt；任何安全约束必须在 executor/tool boundary 再验证一次。
- 不使用模型提供的 `user_id`、`bank_mode`、question text、dimension、tags 覆盖服务端事实。
- 不增加机械题目 fallback；被拒绝的工具继续走现有 contract/error 路径。

---

### Task 1: Add strict ToolPolicy and tool input validation

**Files:**
- Create: `backend/app/agents/chat/tool_policy.py`
- Modify: `backend/app/agents/chat/tool_gateway.py`
- Modify: `backend/app/agents/chat/react_loop.py:124-154,775-853`
- Modify: `backend/app/agents/chat/tools.py:267-297`
- Test: `backend/tests/chat/test_tool_strategy.py`
- Test: `backend/tests/chat/test_tool_strategy_limit.py`
- Test: `backend/tests/chat/test_react_loop.py`
- Update: `backend/app/agents/chat/CLAUDE.md`

**Interfaces:**
- Consumes: `ChatState`, `compute_tool_strategy(state)`, `ToolStrategy`, existing four tool names.
- Produces: `ToolPolicy`, `build_tool_policy(state)`, `validate_tool_call(tool_call, policy)`, and normalized strict args used by the existing executor.

- [ ] **Step 1: Write failing policy tests**

Add focused tests with the existing state helpers:

```python
def test_end_interview_policy_denies_all_tools():
    state = {"user_id": 7, "conversation_id": "c1", "intent": "end_interview"}
    policy = build_tool_policy(state)
    assert policy.allowed_tools == frozenset()


def test_retrieval_policy_allows_draw_but_not_search():
    state = {
        "user_id": 7,
        "conversation_id": "c1",
        "intent": "interview_question",
        "requires_bank_question": True,
        "distribution_primary_required": True,
        "distribution_control": {"preferred_type": "knowledge_probe"},
    }
    policy = build_tool_policy(state)
    assert "draw_questions" in policy.allowed_tools
    assert "search_questions" not in policy.allowed_tools


def test_select_question_is_not_allowed_without_server_candidates():
    state = {"user_id": 7, "conversation_id": "c1", "intent": "chat"}
    assert "select_question" not in build_tool_policy(state).allowed_tools
```

Add validation tests:

```python
def test_validate_tool_call_rejects_unknown_arguments():
    policy = ToolPolicy(
        user_id=7,
        conversation_id="c1",
        bank_mode="public",
        allowed_tools=frozenset({"select_question"}),
        allowed_skills=None,
        policy_version="test",
    )
    with pytest.raises(StopRun, match="invalid_args:select_question"):
        validate_tool_call(
            {"function": {"name": "select_question", "arguments": '{"candidates": []}'}},
            policy,
        )
```

- [ ] **Step 2: Run the new tests and verify they fail for the missing policy contract**

Run:

```bash
docker compose --profile test run --rm --build test uv run pytest \
  backend/tests/chat/test_tool_strategy.py \
  backend/tests/chat/test_tool_strategy_limit.py \
  backend/tests/chat/test_react_loop.py -q
```

Expected: FAIL because `tool_policy.py` and the policy argument to `validate_tool_call()` do not exist yet, while existing tests unrelated to the new behavior may remain green.

- [ ] **Step 3: Implement `ToolPolicy` and strict schemas**

Create a frozen policy that derives the allowlist from `ToolStrategy`. Use `None` for unrestricted registered skills and a non-empty frozenset for strategy-specific skills. Add strict Pydantic input models in `tool_gateway.py` with `ConfigDict(extra="forbid")`:

```python
class LoadSkillInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    skill_name: Literal[
        "adaptive-difficulty", "algorithm-coding", "hr-soft-skills",
        "interview-rhythm", "project-deep-dive", "theory-qa",
    ]


class SelectQuestionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    candidate_index: int = Field(default=0, ge=0, le=4)
```

Make the existing search/draw models strict as well, preserving their current field limits. Add a single `validate_tool_arguments(name, raw_args, policy)` helper that returns a normalized dict or raises the existing `StopRun` error shape.

- [ ] **Step 4: Enforce policy before executor dispatch**

Change `validate_tool_call(tool_call, policy)` so it validates global tool name, policy membership, strict schema, and skill scope. In `_react_loop`, call `build_tool_policy(state)` immediately before each validation and pass the policy in. A denied call must append the existing tool-result error, stop that invalid tool batch, and never call `chat_tools.execute_tool()`.

Keep `execute_tool()` as a defensive boundary: parse only normalized arguments and return a structured `INVALID_TOOL_ARGUMENTS` error if it is called directly with malformed input. Do not silently drop unknown fields.

- [ ] **Step 5: Run targeted tests and commit**

Run:

```bash
docker compose --profile test run --rm --build test uv run pytest \
  backend/tests/chat/test_tool_strategy.py \
  backend/tests/chat/test_tool_strategy_limit.py \
  backend/tests/chat/test_react_loop.py \
  backend/tests/chat/test_tools.py -q
```

Expected: PASS. Update the tool section in `backend/app/agents/chat/CLAUDE.md`, then commit:

```bash
git add backend/app/agents/chat/tool_policy.py \
  backend/app/agents/chat/tool_gateway.py \
  backend/app/agents/chat/react_loop.py \
  backend/app/agents/chat/tools.py \
  backend/tests/chat/test_tool_strategy.py \
  backend/tests/chat/test_tool_strategy_limit.py \
  backend/tests/chat/test_react_loop.py \
  backend/tests/chat/test_tools.py \
  backend/app/agents/chat/CLAUDE.md
git commit -m "fix(chat): enforce tool policy at execution boundary"
```

### Task 2: Make `select_question` use authoritative server candidates

**Files:**
- Modify: `backend/app/mcp_server/interview_tools.py:354-448`
- Modify: `backend/app/agents/chat/tools.py:422-428`
- Modify: `backend/app/mcp_server/app.py:168-188`
- Modify: `backend/app/agents/chat/tool_gateway.py`
- Test: `backend/tests/chat/test_interview_mcp_tools.py`
- Test: `backend/tests/chat/test_tools.py`
- Update: `backend/app/mcp_server/CLAUDE.md`

**Interfaces:**
- Consumes: `candidate_index`, current state/session candidate list, current user/bank mode/job position.
- Produces: `select_question_tool(args, state, candidate_index)` that rejects supplied candidate objects and binds only a database-reloaded question.

- [ ] **Step 1: Write failing candidate-integrity tests**

Add tests demonstrating that a forged candidate is rejected and a tampered in-memory question is not authoritative:

```python
def test_select_question_rejects_candidates_argument():
    state = {"candidate_questions": [{"id": 1, "question": "server question"}], "user_id": 7}
    result = select_question_tool(
        {"candidates": [{"id": 999, "question": "forged question"}]},
        state,
        candidate_index=0,
    )
    assert result["ok"] is False
    assert result["error"]["error_code"] == "INVALID_TOOL_ARGUMENTS"


def test_select_question_uses_database_question_after_candidate_text_tampering(monkeypatch):
    state = {
        "user_id": 7,
        "bank_mode": "public",
        "job_position": "后端开发",
        "candidate_questions": [{"id": 1, "question": "tampered"}],
    }
    monkeypatch.setattr(
        question_service,
        "get_authoritative_question",
        lambda **_: {"id": 1, "question": "database question", "cat1": "B"},
    )
    result = select_question_tool({}, state, candidate_index=0)
    assert result["selected_question"]["question"] == "database question"
```

- [ ] **Step 2: Run the candidate tests and verify the old implementation fails**

Run:

```bash
docker compose --profile test run --rm test uv run pytest \
  backend/tests/chat/test_interview_mcp_tools.py \
  backend/tests/chat/test_tools.py -q
```

Expected: the forged candidate test fails because the current shared executor accepts `candidates` and trusts the object in state.

- [ ] **Step 3: Remove candidate payloads and add authoritative reload**

Make the internal `select_question` path pass only normalized `candidate_index`. In the shared MCP executor:

1. Reject any `candidates` key in `args`.
2. Read the candidate list from state/session.
3. Extract only the candidate ID and source.
4. Query the approved, non-deleted question for the current user/bank mode/job position.
5. Build `selected_question`, plan, asked record, and coverage facts from the returned row.
6. Return a stable error for missing, out-of-range, deleted, or unauthorized candidates.

Change the external FastMCP signature to accept `candidate_index` and `session_id`, not `candidates`. Update the public tool description to require a preceding search/draw call in the same user-bound session.

- [ ] **Step 4: Run targeted tests and commit**

Run:

```bash
docker compose --profile test run --rm --build test uv run pytest \
  backend/tests/chat/test_interview_mcp_tools.py \
  backend/tests/chat/test_tools.py \
  backend/tests/chat/test_react_loop.py -q
```

Expected: PASS. Update `backend/app/mcp_server/CLAUDE.md`, then commit:

```bash
git add backend/app/mcp_server/interview_tools.py \
  backend/app/agents/chat/tools.py \
  backend/app/agents/chat/tool_gateway.py \
  backend/app/mcp_server/app.py \
  backend/tests/chat/test_interview_mcp_tools.py \
  backend/tests/chat/test_tools.py \
  backend/tests/chat/test_react_loop.py \
  backend/app/mcp_server/CLAUDE.md
git commit -m "fix(chat): bind question selection to server candidates"
```

### Task 3: Bind external MCP authentication and session state

**Files:**
- Modify: `backend/app/mcp_server/app.py:18-43,58-188`
- Modify: `backend/app/mcp_server/session.py:47-65,77-239`
- Test: `backend/tests/chat/test_mcp_session.py`
- Test: `backend/tests/chat/test_interview_mcp_tools.py`
- Modify: `backend/tests/chat/test_interview_mcp_tools.py`
- Update: `backend/app/mcp_server/CLAUDE.md`

**Interfaces:**
- Consumes: existing `decode_token(token, expected_type="access")`, `MCP_API_KEY`, MCP session id.
- Produces: authenticated MCP principal in request scope, user-namespaced `load_mcp_session_async(session_id, user_id)` and `save_mcp_session_async(session_id, state, user_id)`.

- [ ] **Step 1: Write failing auth/session isolation tests**

Add tests that use two user identities and assert that session storage is isolated:

```python
async def test_mcp_session_is_namespaced_by_user(monkeypatch):
    await save_mcp_session_async("same-session", {"candidate_questions": [{"id": 1}]}, user_id=7)
    assert await load_mcp_session_async("same-session", user_id=7)
    assert await load_mcp_session_async("same-session", user_id=8) is None
```

Add middleware tests for production/no-key rejection and body identity mismatch. Existing anonymous-development compatibility tests must explicitly set the development opt-in environment variable.

- [ ] **Step 2: Run the new tests and verify they fail**

Run:

```bash
docker compose --profile test run --rm test uv run pytest \
  backend/tests/chat/test_mcp_session.py \
  backend/tests/chat/test_interview_mcp_tools.py -q
```

Expected: FAIL because session keys currently contain only the opaque session id and MCP middleware skips authentication when the API key is absent.

- [ ] **Step 3: Implement user-bound MCP principal and session namespace**

Add a small request-principal helper in `app.py` that:

1. Enforces `MCP_API_KEY` in production, with an explicit development/test anonymous opt-in.
2. Prefers `X-MCP-API-Key` over query parameters and records whether authentication came from the header.
3. Decodes a Bearer access JWT using the existing auth helper.
4. Stores `user_id` and `bank_mode` in `scope["state"]["mcp_principal"]`.
5. Rejects user-scoped tool calls without a principal.
6. Rejects a request-body `user_id` that differs from the principal; derive bank mode from principal instead.

Change every external MCP tool to pass the principal-derived user id/bank mode into `_init_tool_state_async`. Add a `user_id` parameter to session load/save and namespace both Redis and SQLite keys as `mcp:{user_id}:{session_id}`. Keep the internal ReAct path passing its already-authenticated user id.

Do not add tenant claims, OAuth, or an independent auth provider in this task.

- [ ] **Step 4: Run targeted auth/session tests and commit**

Run:

```bash
docker compose --profile test run --rm --build test uv run pytest \
  backend/tests/chat/test_mcp_session.py \
  backend/tests/chat/test_interview_mcp_tools.py \
  backend/tests/security/ -q
```

Expected: PASS. Update MCP contract documentation and commit:

```bash
git add backend/app/mcp_server/app.py \
  backend/app/mcp_server/session.py \
  backend/tests/chat/test_mcp_session.py \
  backend/tests/chat/test_interview_mcp_tools.py \
  backend/tests/security \
  backend/app/mcp_server/CLAUDE.md
git commit -m "fix(mcp): bind sessions to authenticated users"
```

### Task 4: Make archived conversation writes atomic

**Files:**
- Modify: `backend/app/services/chat_service.py:320-340`
- Modify: `backend/app/routers/chat.py:218-242,338-345`
- Test: `backend/tests/chat/test_chat.py`
- Update: `backend/app/agents/chat/CLAUDE.md` if persistence behavior changes

**Interfaces:**
- Consumes: conversation id, authenticated user id, content, current active/archive status.
- Produces: `save_user_message_if_writable()` and `save_assistant_message_if_active()` with explicit status errors.

- [ ] **Step 1: Write failing archive-write tests**

Add service-level tests for read/write separation:

```python
def test_save_user_message_if_writable_rejects_archived_conversation(db):
    conversation = chat_service.create_conversation(user_id=1, mode="free_practice")
    chat_service.archive_conversation(conversation["id"], user_id=1)
    with pytest.raises(ConversationNotWritable):
        chat_service.save_user_message_if_writable(conversation["id"], 1, "继续")


def test_archived_conversation_remains_readable(db):
    conversation = chat_service.create_conversation(user_id=1, mode="free_practice")
    chat_service.archive_conversation(conversation["id"], user_id=1)
    assert chat_service.get_conversation(conversation["id"], 1)["status"] == "archived"
```

- [ ] **Step 2: Run the tests and verify the old write path fails the new behavior**

Run:

```bash
docker compose --profile test run --rm test uv run pytest \
  backend/tests/chat/test_chat.py \
  backend/tests/chat/test_chat_session_notes.py -q
```

Expected: the new archived-write test fails because the route calls unrestricted `save_message()` after a read-only conversation lookup.

- [ ] **Step 3: Implement atomic conditional inserts**

Add a typed `ConversationNotWritable` service exception and implement the user insert with one SQLite statement equivalent to:

```sql
INSERT INTO chat_messages (conversation_id, role, content, metadata)
SELECT ?, 'user', ?, '{}'
WHERE EXISTS (
    SELECT 1 FROM chat_conversations
    WHERE id = ? AND user_id = ? AND status = 'active'
)
```

If `rowcount` is zero, distinguish missing/foreign conversation from archived status using a read query and raise the correct service exception. Keep `get_conversation()` readable for archived rows.

Add an assistant conditional insert that verifies the conversation is still active before persisting the generated response. Map `ConversationNotWritable` to HTTP 409 in the route. Do not claim this solves concurrent turns; that remains Task 2 of the next phase.

- [ ] **Step 4: Run targeted tests and commit**

Run:

```bash
docker compose --profile test run --rm --build test uv run pytest \
  backend/tests/chat/test_chat.py \
  backend/tests/chat/test_chat_session_notes.py \
  backend/tests/chat/test_interview_distribution_e2e.py -q
```

Expected: PASS. Update the persistence notes in `backend/app/agents/chat/CLAUDE.md`, then commit:

```bash
git add backend/app/services/chat_service.py \
  backend/app/routers/chat.py \
  backend/tests/chat/test_chat.py \
  backend/tests/chat/test_chat_session_notes.py \
  backend/tests/chat/test_interview_distribution_e2e.py \
  backend/app/agents/chat/CLAUDE.md
git commit -m "fix(chat): reject writes to archived conversations"
```

### Task 5: Full phase verification and documentation gate

**Files:**
- Modify: `backend/app/agents/chat/CLAUDE.md`
- Modify: `backend/app/mcp_server/CLAUDE.md`
- Test: all changed chat/security tests

- [ ] **Step 1: Run the focused phase suite**

```bash
docker compose --profile test run --rm --build test uv run pytest \
  backend/tests/chat/test_tool_strategy.py \
  backend/tests/chat/test_tool_strategy_limit.py \
  backend/tests/chat/test_react_loop.py \
  backend/tests/chat/test_tools.py \
  backend/tests/chat/test_interview_mcp_tools.py \
  backend/tests/chat/test_mcp_session.py \
  backend/tests/chat/test_chat.py \
  backend/tests/chat/test_chat_session_notes.py \
  backend/tests/security/ -q
```

Expected: PASS with no new warnings or unhandled coroutine errors.

- [ ] **Step 2: Run the complete chat suite**

```bash
docker compose --profile test run --rm --build test uv run pytest backend/tests/chat/ -q
```

Expected: all collected chat tests pass, or any pre-existing unrelated failure is recorded with its exact test name and output.

- [ ] **Step 3: Perform final diff and documentation review**

```bash
git diff --check HEAD~4..HEAD
git status --short
git log -5 --oneline
```

Confirm no user-controlled identity fields are trusted, no `select_question.candidates` parameter remains, policy denial happens before executor dispatch, and archived reads remain available.

- [ ] **Step 4: Commit documentation-only corrections if needed**

```bash
git add backend/app/agents/chat/CLAUDE.md backend/app/mcp_server/CLAUDE.md
git commit -m "docs(chat): record phase one security boundaries"
```
