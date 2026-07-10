# Interview Agent Harness Contract Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the two high-risk contracts in the approved harness spec control production output rather than operate as sidecar metadata or generic post-processing.

**Architecture:** Calculate the `TurnContract` before the output path is selected. `ask_selected_question` alone invokes the semantic adherence validator and may retry once; every other contract bypasses that validator. Every explicit or policy-driven close runs one natural-closing writer and one structured-summary writer, and either missing stage is a generation failure rather than a legacy farewell or summary-only fallback.

**Tech Stack:** Python 3.10, FastAPI async SSE pipeline, Pydantic, pytest in Docker.

## Global Constraints

- Keep ReAct as the tool/evidence loop; do not add regex intent routing.
- `semantic_question_adherence` is online blocking only for `ask_selected_question`.
- `close_with_summary` always produces natural closing text followed by a structured summary.
- Do not reintroduce a template question or farewell fallback.
- Run all pytest through `docker compose --profile test run --rm test`.

---

### Task 1: Gate Validation by the Actual Turn Contract

**Files:**
- Modify: `backend/tests/chat/test_validator_blocks_drift.py`
- Modify: `backend/app/agents/chat/react_loop.py`

**Interfaces:**
- Consumes: `state["turn_contract"]` with `action` and a selected question.
- Produces: `semantic_validation_failed` only for an `ask_selected_question` output whose retry is absent or fails.

- [ ] Write a failing test where the retry text is empty. Assert that the original drifted text is absent and the SSE error code is `semantic_validation_failed`.
- [ ] Write a failing counter-question test with a stale `selected_question`. Assert that the semantic validator was never called.
- [ ] Run `docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_validator_blocks_drift.py -q` and confirm both new tests fail for the expected contracts.
- [ ] Change `react_loop.py` so it reads a precomputed contract, validates only when the action is `ask_selected_question`, and returns `error` plus `done` for an empty retry, exception, or failed retry.
- [ ] Persist a validator trace on state and expose it in the `done` metadata.
- [ ] Rerun `docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_validator_blocks_drift.py backend/tests/chat/test_contract_e2e.py -q` and confirm PASS.

### Task 2: Make Closing Contract Atomic

**Files:**
- Modify: `backend/tests/chat/test_closing_writer.py`
- Modify: `backend/tests/chat/test_react_loop.py`
- Modify: `backend/app/agents/chat/react_loop.py`
- Modify: `backend/app/agents/chat/pipeline.py`
- Modify: `backend/app/agents/chat/summary.py`
- Modify: `backend/app/agents/chat/CLAUDE.md`

**Interfaces:**
- Consumes: `closing_reason`, recent context, and a structured-summary writer result.
- Produces: natural closing text followed by the structured summary, or one explicit generation error with no legacy fallback text.

- [ ] Write a failing test where a short explicit `end_interview` produces a structured summary, not the old generic farewell.
- [ ] Write a failing test where the closing writer errors. Assert that it emits no summary-only chunk and instead reports `closing_generation_failed`.
- [ ] Run `docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_closing_writer.py backend/tests/chat/test_react_loop.py -q` and confirm each fails for the stated reason.
- [ ] Extract one async helper that generates the closing utterance, then `_generate_structured_summary()`, and joins both only on success. Use it for both explicit `end_interview` and stop-policy close.
- [ ] Delete the generic-farewell branch from `_generate_end_interview_response()` and remove the hard-coded counter-question answer from `_forced_closing_response()`.
- [ ] Update `backend/app/agents/chat/CLAUDE.md` with the now-active output ownership and failure behavior.
- [ ] Run `docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_closing_writer.py backend/tests/chat/test_react_loop.py backend/tests/chat/test_error_recovery.py -q`.
- [ ] Run `docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q`; separately record exact unrelated eval-split failures if any remain.
