# MiMo Interviewer Reasoning Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show MiMo `reasoning_content` in Chat as the interviewer reasoning process while preserving existing step/tool/skill observability.

**Architecture:** MiMo exposes reasoning through OpenAI-compatible `reasoning_content`: non-streaming responses use `choices[0].message.reasoning_content`, streaming responses use `choices[0].delta.reasoning_content`. The backend should propagate tool-calling reasoning into the existing `thinking`/`reasoning_trace` metadata path, and the frontend should label that content as interviewer reasoning instead of generic thinking.

**Tech Stack:** Python 3.10, FastAPI, OpenAI Python SDK, Vue 3, Playwright, Docker pytest test-runtime.

## Global Constraints

- Do not print or persist API keys.
- Preserve existing `thinking`, `thinking_duration`, `steps`, `tool_steps`, `reasoning_trace`, `tool_calls_trace`, and `skill_trace` compatibility fields.
- Store at most `_MAX_THINKING_CHUNKS` thinking chunks in metadata.
- Run backend tests through Docker test-runtime.
- Update touched `CLAUDE.md` files.

---

### Task 1: Propagate MiMo Tool-Calling Reasoning

**Files:**
- Modify: `backend/app/services/llm.py`
- Modify: `backend/app/agents/chat/react_loop.py`
- Test: `backend/tests/chat/test_react_loop.py`

**Interfaces:**
- Consumes: `llm_service.llm_with_tools(...) -> dict`
- Produces: optional `reasoning_content: str` in the returned dict; `_react_loop()` emits `thinking_start`, `thinking`, and `thinking_done` around non-empty tool-calling reasoning.

- [ ] **Step 1: Write the failing tests**

Add tests that mock `llm_with_tools()` returning `reasoning_content` and assert `_react_loop()` emits thinking events before the final answer.

- [ ] **Step 2: Run the targeted backend test and confirm failure**

Run: `docker compose --profile test run --rm -v "$PWD/backend:/app/backend" test /app/.venv/bin/python -m pytest backend/tests/chat/test_react_loop.py -q`

Expected: FAIL because `_react_loop()` does not emit tool-calling reasoning yet.

- [ ] **Step 3: Implement minimal backend propagation**

In `llm.py`, include `reasoning_content` in OpenAI tool-calling responses with `getattr(msg, "reasoning_content", None)`. In `react_loop.py`, when a tool-calling LLM result includes reasoning, emit `thinking_start`, `thinking`, and `thinking_done` once per result.

- [ ] **Step 4: Run the targeted backend test and confirm pass**

Run the same pytest command.

### Task 2: Label and Prioritize Interviewer Reasoning in the Frontend

**Files:**
- Modify: `frontend/src/components/business/ChatMessage.vue`
- Modify: `frontend/src/components/business/ReasoningTimeline.vue`
- Modify: `frontend/src/components/business/CLAUDE.md`
- Test: `frontend/tests/e2e/chat-thinking-timer.spec.js`

**Interfaces:**
- Consumes: message metadata `thinking` plus `reasoning_trace.source === "model_reasoning"`.
- Produces: visible label text beginning with `面试官推理...`; raw model reasoning is displayed before fallback summary when available.

- [ ] **Step 1: Write/update the failing frontend test**

Update the existing reasoning timeline test to expect `面试官推理了 2.4 秒` and raw reasoning text from `metadata.thinking` even when `reasoning_trace.summary` exists.

- [ ] **Step 2: Run the targeted frontend test and confirm failure**

Run: `cd frontend && npm run test -- chat-thinking-timer.spec.js`

Expected: FAIL because the UI still says `思考了...` and prioritizes `reasoning_trace.summary`.

- [ ] **Step 3: Implement frontend display changes**

Change `ChatMessage.vue` to prefer `metadata.thinking` when `reasoning_trace.source === "model_reasoning"`. Change `ReasoningTimeline.vue` labels from generic thinking to interviewer reasoning.

- [ ] **Step 4: Run the targeted frontend test and confirm pass**

Run the same npm command, then `cd frontend && npm run build`.

### Task 3: Documentation and Final Verification

**Files:**
- Modify: `backend/app/agents/chat/CLAUDE.md`
- Modify: `frontend/src/components/business/CLAUDE.md`

**Interfaces:**
- Produces: updated local guidance that MiMo reasoning uses `reasoning_content`.

- [ ] **Step 1: Update CLAUDE guidance**

Document that OpenAI-compatible MiMo reasoning is read from `reasoning_content` and displayed as interviewer reasoning.

- [ ] **Step 2: Run final targeted verification**

Run:

```bash
docker compose --profile test run --rm -v "$PWD/backend:/app/backend" test /app/.venv/bin/python -m pytest backend/tests/chat/test_react_loop.py backend/tests/chat/test_chat.py -q
cd frontend && npm run build
```

- [ ] **Step 3: Review diff**

Run: `git diff --stat` and inspect touched files.
