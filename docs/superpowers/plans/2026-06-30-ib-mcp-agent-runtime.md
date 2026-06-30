# IB MCP Agent Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move InterviewBoss interview tools behind a backend-embedded MCP boundary so tool execution becomes a stable, validated contract.

**Architecture:** Phase 1 keeps the existing chat pipeline running, but extracts interview question tools into a backend MCP-style tool layer with stable envelopes and deterministic fallback. The ReAct executor will call that tool layer instead of directly calling question services, then later phases can swap the transport to full FastMCP without changing tool behavior.

**Tech Stack:** Python 3.10, FastAPI, SQLite, existing `tool_gateway.py` envelopes, Docker test runtime.

## Global Constraints

- Run backend tests through Docker test runtime, not host pytest.
- Do not rewrite the whole chat agent in this phase.
- Preserve existing SSE event names and `search_questions` / `draw_questions` tool schemas.
- Every executable interview tool must return a stable envelope with `ok`, `tool`, `items`, `metadata`, and `error`.
- Update relevant `CLAUDE.md` files after code changes.

---

### Task 1: Question Draw Fallback Contract

**Files:**
- Modify: `backend/tests/services/test_question_draw_service.py`
- Modify: `backend/app/services/question_draw_service.py`

**Interfaces:**
- Consumes: `draw_questions(user, count, question_type, difficulty, ...) -> list[dict]`
- Produces: fallback behavior for `question_type="algorithm_coding"` when the current job-position filter returns no candidates.

- [x] **Step 1: Write the failing test**

Add a test that seeds an algorithm question under a default position and configures the user to a different position. Call `draw_questions(question_type="algorithm_coding")` and assert it returns the algorithm question with fallback metadata.

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_question_draw_service.py::test_algorithm_draw_falls_back_to_default_position_when_current_position_empty -q
```

Expected: FAIL because current `draw_questions` returns `[]`.

- [x] **Step 3: Implement minimal fallback**

When `question_type="algorithm_coding"` and filtered candidates are empty, retry against approved public questions matching the same type filter without the current-position join. Mark returned rows with `_fallback_used=True` and `_fallback_reason="position_filter_empty"`.

- [x] **Step 4: Run test to verify it passes**

Run the same targeted Docker pytest command and confirm it passes.

### Task 2: Backend MCP Tool Layer

**Files:**
- Create: `backend/app/mcp_server/__init__.py`
- Create: `backend/app/mcp_server/interview_tools.py`
- Modify: `backend/app/agents/chat/tools.py`
- Test: `backend/tests/chat/test_interview_mcp_tools.py`

**Interfaces:**
- Produces: `load_skill_tool(args: dict, state: dict) -> dict`
- Produces: `async search_questions_tool(args: dict, state: dict) -> dict`
- Produces: `async draw_questions_tool(args: dict, state: dict) -> dict`
- Produces: `select_question_tool(args: dict, state: dict) -> dict`

- [x] **Step 1: Write failing MCP tool tests**

Test that `draw_questions_tool` returns the same stable envelope shape as `tool_gateway.py`, updates `state["candidate_questions"]`, and marks fallback metadata when service rows carry fallback markers.

- [x] **Step 2: Run test to verify it fails**

Run:

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_interview_mcp_tools.py -q
```

Expected: FAIL because the module does not exist.

- [x] **Step 3: Implement the MCP tool layer**

Move the service-calling code currently in `backend/app/agents/chat/tools.py` into `backend/app/mcp_server/interview_tools.py`. Keep OpenAI tool schemas in `agents/chat/tools.py`; make `execute_tool()` delegate to the MCP tool layer. Include `load_skill` so every current ReAct tool has the same backend execution boundary.

- [x] **Step 4: Run targeted tests**

Run:

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_interview_mcp_tools.py backend/tests/chat/test_tools.py -q
```

### Task 3: Embedded MCP App Skeleton

**Files:**
- Create: `backend/app/mcp_server/app.py`
- Modify: `backend/app/asgi.py`
- Modify: `backend/app/CLAUDE.md`
- Modify: `backend/app/agents/chat/CLAUDE.md`

**Interfaces:**
- Produces: `mcp_app` or a documented no-op compatibility app mounted under `/mcp` when the MCP package is available.

- [x] **Step 1: Add import-safe app tests**

Test that `backend.app.mcp_server.app` imports and exposes the interview tool registry without requiring an external process.

- [x] **Step 2: Implement app skeleton**

Create an import-safe module that defines the embedded MCP boundary and leaves transport wiring isolated from tool behavior.

- [x] **Step 3: Update docs**

Document that interview executable tools now live behind `backend/app/mcp_server/interview_tools.py`, and the chat agent should not directly call question services.

### Task 4: Verification

**Files:**
- No new files expected.

- [x] **Step 1: Run service and chat tests**

Run:

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_question_draw_service.py backend/tests/chat/test_interview_mcp_tools.py backend/tests/chat/test_tools.py -q
```

- [ ] **Step 2: Run real E2E if API limits permit**

Run:

```bash
docker compose exec -T -e RUN_REAL_CHAT_E2E=1 backend uv run python backend/scripts/verify_chat_tools_real_e2e.py
```

Record whether failures are code failures or provider rate-limit failures.
