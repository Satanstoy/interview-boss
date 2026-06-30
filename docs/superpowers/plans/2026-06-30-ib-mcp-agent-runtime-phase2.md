# IB MCP Agent Runtime Phase 2 — System Adaptation Plan

> **Goal:** Harden the internal ReAct+MCP boundary (Phase 2A) and make the `/mcp` endpoint stateful for external MCP clients (Phase 2B).

## Global Constraints

- Backend tests run through Docker `test-runtime`.
- Preserve existing SSE event names and ReAct tool schemas where possible.
- All executable interview tools return a stable envelope with `ok`, `tool`, `items`/`selected_question`, `metadata`, `error`.
- Update relevant `CLAUDE.md` files after changes.

---

## Phase 2A: Internal Boundary Hardening

### Task 1: `/mcp` Endpoint Auth & CSRF

**Files:**
- Modify: `backend/app/asgi.py`
- Modify: `backend/app/mcp_server/app.py`
- Test: `backend/tests/chat/test_interview_mcp_tools.py`

**Steps:**
1. Add `/mcp` path prefix to `_CSRF_EXEMPT_PATHS` or wrap `mcp_app` with a small ASGI middleware that injects a synthetic `x-requested-with` header for `/mcp` requests.
2. Add an API-key dependency to `mcp_app` tool calls. Read `MCP_API_KEY` from env; if set, require `X-MCP-API-Key` header or query param. If not set, allow open access (backward compatible for local dev).
3. Write tests that call `/mcp` without key → 403 (when env set) and with key → 200.

**Verification:**
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_interview_mcp_tools.py -q
```

---

### Task 2: Unify `load_skill` Envelope

**Files:**
- Modify: `backend/app/mcp_server/interview_tools.py`
- Modify: `backend/app/agents/chat/tools.py`
- Modify: `backend/app/agents/chat/react_loop.py`
- Test: `backend/tests/chat/test_tools.py`, `backend/tests/chat/test_interview_mcp_tools.py`

**Steps:**
1. Change `load_skill_tool` to return the unified envelope:
   - success: `{"ok": true, "tool": "load_skill", "items": [], "metadata": {"status": "loaded", "skill": skill_name, "summary": ...}, "error": null}`
   - already active: `{"ok": true, "tool": "load_skill", "items": [], "metadata": {"status": "already_active", "skill": skill_name}, "error": null}`
   - unknown skill: `{"ok": false, "tool": "load_skill", "items": [], "metadata": {}, "error": {"error_code": "UNKNOWN_SKILL", "message": ...}}`
2. Keep `state["active_skills"]` and `state["active_skill_instructions"]` updated as before.
3. In `tools.py`, `_execute_load_skill` should detect the envelope and return JSON; no special handling needed if envelope is uniform.
4. In `react_loop.py`, update `_summarize_tool_output` to parse the unified envelope for `load_skill`.

**Verification:**
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_tools.py backend/tests/chat/test_interview_mcp_tools.py -q
```

---

### Task 3: Allow Agent to Call `select_question`

**Files:**
- Modify: `backend/app/agents/chat/tools.py`
- Modify: `backend/app/agents/chat/react_loop.py`
- Test: `backend/tests/chat/test_react_e2e.py`

**Steps:**
1. Add OpenAI function schema for `select_question` to `tools.py` with args: `candidates` (list of question ids), `question_type` optional.
2. Add `_execute_select_question(args, state)` in `tools.py` that calls `interview_tools.select_question_tool(args, state)` and returns JSON envelope.
3. Add `select_question` to `_ALLOWED_TOOL_NAMES` in `react_loop.py`.
4. After `select_question` tool call, also call `_maybe_create_question_plan(state)` if needed, or rely on `select_question_tool` setting `state["next_question_plan"]`.
5. Update ReAct system prompt / tool guidance if needed.

**Verification:**
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_react_e2e.py backend/tests/chat/test_react_loop.py -q
```

---

### Task 4: Exception Hardening

**Files:**
- Modify: `backend/app/mcp_server/interview_tools.py`
- Modify: `backend/app/agents/chat/tools.py`
- Test: `backend/tests/chat/test_tools.py`, `backend/tests/chat/test_interview_mcp_tools.py`

**Steps:**
1. Wrap the entire body of `execute_tool` in a broad `except Exception` (already present) and ensure it logs and returns `{"error": ...}`.
2. In `search_questions_tool`/`draw_questions_tool`, catch `BaseException`? No — keep `Exception`. Add a top-level safety wrapper in `interview_tools.py` if needed.
3. Add timeout guard around `asyncio.to_thread` calls using `asyncio.wait_for` to prevent hung service calls from blocking ReAct forever.

**Verification:**
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_tools.py backend/tests/chat/test_interview_mcp_tools.py -q
```

---

## Phase 2B: Stateful External MCP Sessions

### Task 5: MCP Session State Store

**Files:**
- Create: `backend/app/mcp_server/session.py`
- Test: `backend/tests/chat/test_mcp_session.py`

**Steps:**
1. Implement `get_mcp_session(session_id: str) -> dict` and `set_mcp_session(session_id: str, state: dict, ttl: int = 3600)`.
2. Backing store: Redis if `app.state.redis` pool is available, else SQLite table `mcp_sessions(session_id, data_json, updated_at)`.
3. Session ID generation: `uuid.uuid4().hex` if not provided.
4. Persisted fields: `active_skills`, `active_skill_instructions`, `retrieved_questions`, `candidate_questions`, `session_notes`, `question_source`, `question_source_reason`.

**Verification:**
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_mcp_session.py -q
```

---

### Task 6: Add `session_id` to MCP Endpoint Tools

**Files:**
- Modify: `backend/app/mcp_server/app.py`
- Modify: `backend/app/mcp_server/interview_tools.py` (optional helper)
- Test: `backend/tests/chat/test_interview_mcp_tools.py`

**Steps:**
1. Add `session_id: str = None` parameter to all 4 MCP tool functions in `app.py`.
2. On entry, load existing session state (or create empty state + new session_id).
3. Call `interview_tools.*_tool(args, state)`.
4. Persist updated `state` back to session store.
5. Return result with `session_id` injected into `metadata`.

**Verification:**
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_interview_mcp_tools.py -q
```

---

### Task 7: Stateful MCP Cross-Tool Flow Test

**Files:**
- Test: `backend/tests/chat/test_interview_mcp_tools.py`

**Steps:**
1. Write test: call `load_skill` with `session_id`, then `draw_questions` with same `session_id`, assert active skills persisted and draw sees session state.
2. Write test: `search_questions` then `select_question` with same `session_id`, assert selected question plan persisted.

**Verification:**
```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_interview_mcp_tools.py -q
```

---

### Task 8: Update Documentation

**Files:**
- Modify: `backend/app/mcp_server/CLAUDE.md`
- Modify: `backend/app/agents/chat/CLAUDE.md`
- Modify: `backend/app/CLAUDE.md` (if needed)

**Steps:**
1. Document `/mcp` auth requirements and session_id usage.
2. Document `select_question` as Agent-callable tool.
3. Document session persistence contract.

---

## Phase Gate

Run full chat suite after all tasks:

```bash
./deploy/docker-deploy.sh test backend/tests/chat/ -q
```

Expected: all chat tests pass.
