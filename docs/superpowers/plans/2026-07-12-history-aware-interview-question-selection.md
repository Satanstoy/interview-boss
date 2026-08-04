# History-Aware Interview Question Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Lower, rather than eliminate, the chance of questions used in prior interview conversations while retaining strict within-conversation deduplication.

**Architecture:** `operations.py` aggregates interview and practice history per candidate. `question_draw_service.py` applies a deterministic reuse multiplier during weighted sampling and exposes trace fields. `interview_tools.py` only excludes current-conversation items, then applies the same history ordering to search results.

**Tech Stack:** Python 3.10, SQLite, FastAPI embedded MCP tools, pytest.

## Global Constraints

- Keep current-conversation question IDs in `exclude_ids`.
- Do not add a schema migration or external dependency.
- Run pytest only through the Docker test profile.
- Update affected `CLAUDE.md` files and commit logical changes before deployment.

---

### Task 1: Aggregate history and calculate reusable selection weights

**Files:**
- Modify: `backend/app/db/operations.py`
- Modify: `backend/app/services/question_draw_service.py`
- Test: `backend/tests/services/test_question_draw_service.py`

**Interfaces:**
- Produces `get_interview_question_history(conn, user_id, question_ids) -> dict[int, dict[str, object]]`.
- Produces `_history_reuse_weight(history: dict[str, object]) -> float` and history-aware weighted sampling.

- [ ] **Step 1: Write failing service tests** for recent repeated questions being less likely, 30-day recovery, and weak-practice compensation.
- [ ] **Step 2: Run** `docker compose --profile test run --rm -v "$PWD/backend:/app/backend" test /app/.venv/bin/python -m pytest backend/tests/services/test_question_draw_service.py -q` **and verify failure** because no interview-history weighting exists.
- [ ] **Step 3: Implement** the aggregate query and deterministic multiplier, then attach non-sensitive selection trace fields to drawn questions.
- [ ] **Step 4: Re-run** the targeted service test and verify it passes.

### Task 2: Replace cross-conversation exclusion at the MCP boundary

**Files:**
- Modify: `backend/app/mcp_server/interview_tools.py`
- Test: `backend/tests/chat/test_interview_mcp_tools.py`

**Interfaces:**
- Consumes `get_interview_question_history` and `rerank_questions_by_history(results, history)`.
- Produces search/draw requests that exclude only current-conversation IDs and ordered candidates annotated with reuse metadata.

- [ ] **Step 1: Write failing MCP tests** proving historical IDs are omitted from `exclude_ids`, but current-conversation IDs remain, and lower-history-weight results rank first.
- [ ] **Step 2: Run** `docker compose --profile test run --rm -v "$PWD/backend:/app/backend" test /app/.venv/bin/python -m pytest backend/tests/chat/test_interview_mcp_tools.py -q` **and verify failure** under the old hard-exclusion policy.
- [ ] **Step 3: Implement** shared history lookup/re-ranking and remove distribution-specific cross-conversation retry state.
- [ ] **Step 4: Re-run** the targeted MCP test and verify it passes.

### Task 3: Document, verify, commit, and deploy

**Files:**
- Modify: `backend/app/services/CLAUDE.md`
- Modify: `backend/app/mcp_server/CLAUDE.md`
- Modify: `backend/app/agents/chat/CLAUDE.md`

- [ ] **Step 1: Document** the current-session hard exclusion and cross-session weighted reuse contract.
- [ ] **Step 2: Run** `docker compose --profile test run --rm -v "$PWD/backend:/app/backend" test /app/.venv/bin/python -m pytest backend/tests/services/test_question_draw_service.py backend/tests/chat/test_interview_mcp_tools.py backend/tests/chat/test_interview_distribution_e2e.py -q`.
- [ ] **Step 3: Run** `cd frontend && npm run build` only if frontend files change; this plan has none.
- [ ] **Step 4: Commit** the implementation using `feat(backend): weight reused interview questions`.
- [ ] **Step 5: Deploy** with `./deploy/docker-deploy.sh update` and inspect `./deploy/docker-deploy.sh status`.
