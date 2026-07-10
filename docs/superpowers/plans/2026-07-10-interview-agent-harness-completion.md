# Interview Agent Harness Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the approved harness spec so every final user-visible interview turn is selected by `TurnPlanner`, rendered by its contract writer, and recorded with contract and validator evidence.

**Architecture:** Preserve ReAct as the evidence collector and tool executor. After tools finish, normalize classifier signals into structured state, compute one `TurnContract`, then execute it through an explicit contract executor. The executor owns all five final-output actions; it invokes the existing question and close writers or dedicated clarify/counter/follow-up writers. A ReAct text draft may be retained for observability only and never becomes user-visible output.

**Tech Stack:** Python 3.10, FastAPI async SSE, Pydantic, pytest in Docker.

## Global Constraints

- No regex or keyword routing for current-user semantic intent; planner consumes classifier facts and ledger/tool facts only.
- `semantic_question_adherence` remains the only blocking LLM semantic validator in this phase, and only for `ask_selected_question`.
- `close_with_summary` emits a natural LLM closing followed by a schema-valid LLM summary, or one error event.
- No mechanical question/farewell fallback; failed writer output is an observable generation error.
- ReAct, skills, and MCP tools collect evidence only; writers own user-visible wording.
- Docker is the only pytest runtime.

---

### Task 1: Normalize Semantic Facts and Tighten Planner Eligibility

**Files:**
- Modify: `backend/app/agents/chat/pipeline.py`
- Modify: `backend/app/agents/chat/turn_contract.py`
- Modify: `backend/tests/chat/test_turn_planner.py`
- Modify: `backend/tests/chat/test_contract_e2e.py`

**Interfaces:**
- Consumes: `ClassifyResult` fields including `asked_counter_question`, `requested_end`, `needs_clarification`, `needs_new_dimension`, `confidence`, and `suggested_question_type`.
- Produces: a `TurnContract` whose `source_facts` reports the facts used for the decision.

- [ ] Add failing integration tests proving classifier `asked_counter_question=True` yields `answer_counter_question`, and `needs_new_dimension=False` prevents a selected question from becoming `ask_selected_question`.
- [ ] Run the tests in Docker and confirm the current state bridge/eligibility fails.
- [ ] Write all semantic fields from `ClassifyResult` to `ChatState`, derive the compatibility `counter_question` fields from them, and require a coverage/new-dimension plus confidence-qualified selection for `ask_selected_question`.
- [ ] Include the consumed semantic facts and selected-question confidence in contract metadata.
- [ ] Rerun the focused planner and pipeline tests to PASS.

### Task 2: Execute Every Turn Contract Without a ReAct Draft Dependency

**Files:**
- Create: `backend/app/agents/chat/writers/clarify_writer.py`
- Create: `backend/app/agents/chat/writers/counter_writer.py`
- Create: `backend/app/agents/chat/writers/followup_writer.py`
- Create: `backend/app/agents/chat/contract_executor.py`
- Modify: `backend/app/agents/chat/react_loop.py`
- Modify: `backend/app/agents/chat/writers/__init__.py`
- Modify: `backend/tests/chat/test_contract_e2e.py`
- Modify: `backend/tests/chat/test_react_loop.py`

**Interfaces:**
- Consumes: `state`, a validated `TurnContract`, and `llm_call`.
- Produces: `{status, text|error_code, writer_trace, validator_trace}`; no action returns a synthetic fallback.

- [ ] Add failing tests for blank ReAct completion after `select_question`, a classifier-driven counter question, a vague-answer clarification, and natural follow-up. Assert the correct writer owns each chunk.
- [ ] Run the tests and confirm current code either errors on an empty ReAct draft or emits the draft directly.
- [ ] Add one focused writer per contract and a `execute_turn_contract()` dispatcher. Each writer builds its own prompt from structured state, returns a non-empty natural response, and returns an error result on LLM failure.
- [ ] Move final-output dispatch out of the `final_answer_text` branch: after a successful ReAct tool loop, compute and execute exactly one contract even when its final content is empty. Keep the discarded ReAct text only in non-public trace metadata.
- [ ] Rerun focused contract E2E tests to PASS.

### Task 3: Persist Contract, Writer, and Validator Evidence

**Files:**
- Modify: `backend/app/agents/chat/metadata.py`
- Modify: `backend/app/agents/chat/pipeline.py`
- Modify: `backend/app/agents/chat/CLAUDE.md`
- Modify: `backend/tests/chat/test_contract_e2e.py`

**Interfaces:**
- Consumes: contract-executor result and tool facts.
- Produces: `turn_contract`, `writer_trace`, `validator_trace`, and `tool_contract_trace` in done metadata.

- [ ] Add failing metadata tests for `ask_selected_question` writer/validator traces and every contract's writer trace.
- [ ] Run the tests and confirm writer traces are absent or contract metadata is recomputed as a sidecar.
- [ ] Preserve the actual executed contract; remove the post-output sidecar re-planning. Emit tool source/id, writer attempt, blocking status, score, and validator issues in stable metadata.
- [ ] Update the chat module documentation to describe all active writers and the evidence contract.
- [ ] Run focused tests to PASS.

### Task 4: Full Harness Verification

**Files:**
- Modify: relevant chat tests only when their assertions encode superseded ReAct-output ownership.

- [ ] Run the writer, planner, contract, metadata, stop-policy, ReAct, and multi-turn chat suites in Docker.
- [ ] Run `compileall` and `git diff --check`.
- [ ] Run the full chat suite; separately document failures from the in-progress eval split or independent direct-stream regression, without weakening the harness tests.
- [ ] Commit the implementation and documentation as one logical harness-completion change.
