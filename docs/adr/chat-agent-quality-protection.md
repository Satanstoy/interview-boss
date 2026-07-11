# ADR-001: Chat Agent Quality Protection Mechanisms

**Date:** 2025-05-22 → 2026-07-11 (iterative)  
**Status:** Active  
**Context:** `backend/app/agents/chat/` module

## Decision

The chat agent uses a layered quality protection architecture: code-level state machines own routing decisions (not prompt prose), contract writers own final wording (not ReAct drafts), and validators block drift before user-visible output.

## Architecture Layers

```
classify(LLM) → build_turn_intent → stop_policy(code) → plan_turn(code)
  → ReAct loop (tools/evidence only, never user-visible)
  → contract_executor → writer(LLM) → validator → SSE output
```

### Layer 1: Stop Policy (code-level)

| Gate | Threshold | Action |
|------|-----------|--------|
| Coverage complete + soft close | ≥32 msgs | Ask candidate reverse question |
| Strong close | ≥44 msgs | Only fill last gap or HR/反问/收尾 |
| Hard stop | >56 msgs | Force summary regardless of coverage |
| Candidate repeat | 3× similar | Degraded: switch dimension |
| Candidate repeat | 5× similar | Force close interview |

Thresholds scale with difficulty: easy ×0.75, hard ×1.25 (via `DecisionConfig`).

### Layer 2: Turn Contract (deterministic planner)

`plan_turn()` reads only structured facts and produces one of 5 contract actions:

| Priority | Action | When |
|----------|--------|------|
| 1 | `close_with_summary` | explicit end / stop_policy says close |
| 2 | `answer_counter_question` | candidate asked a counter question (dict evidence required) |
| 3 | `clarify_candidate_answer` | answer vague/incomplete |
| 4 | `ask_selected_question` | selected_question exists with high confidence |
| 5 | `continue_natural_followup` | default |

### Layer 3: Turn Intent (rhythm strategy)

`build_turn_intent()` runs every turn, independent of ReAct `load_skill`:

| Strategy | Condition |
|----------|-----------|
| CLOSE | `requested_end` or `intent=end_interview` |
| COUNTER_RESPONSE | `classify_result.counter_question` is dict |
| CLARIFICATION | answer_quality vague/incomplete/off_topic |
| TOPIC_SHIFT | consecutive deep_dives ≥2 + missing dimension |
| DEEP_DIVE | default or `project-deep-dive` active skill |

### Layer 4: Contract Writers

Each contract action maps to a dedicated writer that produces only the user-visible text:

| Writer | Contract | Notes |
|--------|----------|-------|
| `question_writer` | ask_selected_question | LLM rewrite + semantic_question_adherence validator (0.75 threshold) + fallback swap |
| `clarify_writer` | clarify_candidate_answer | — |
| `counter_writer` | answer_counter_question | — |
| `followup_writer` | continue_natural_followup | — |
| `closing_writer` + `summary_writer` | close_with_summary | Two-stage: natural utterance + structured practice recap |

**Critical rule:** ReAct text is evidence only. The contract writer owns all user-visible output. Writer/validator failure → error event (no mechanical fallback).

### Layer 5: Output Guardrails

- **Context Grounding:** `output_guardrails.check_context_grounding()` rejects entities not mentioned by candidate
- **Unauthorized Summary Protection:** non-close turns cannot output "面试总结/综合评分"
- **Mechanical Rewrite Guard:** forbidden patterns like "好，XXX？" or restating question stem

## Key Invariants

1. `end_interview` hard-routes through pipeline (skips ReAct entirely)
2. Counter question requires `{text, topic}` dict evidence, not bare boolean
3. `turn_intent` and `plan_turn` must stay aligned (invariant-tested)
4. InterviewLedger (not prompt) is source of truth for asked questions
5. coverage_events in assistant metadata (not snapshot) drive next turn's stop_policy
6. `recent_decisions` restored from historical turn_intent metadata, not inferred from prose

## Consequences

- **Positive:** Deterministic routing prevents LLM drift; contract separation enables per-writer validation
- **Negative:** 4-7 LLM calls per turn; writer failure has no graceful degradation (error to user)
- **Trade-off:** Speed vs. quality — every user-visible sentence passes through writer + validator

## References

- `turn_contract.py` — TurnContract + plan_turn
- `turn_intent.py` — TurnIntent + build_turn_intent
- `contract_executor.py` — execute_turn_contract + _run_question_writer_with_fallback
- `stop_policy.py` — evaluate_interview_stop
- `decision_config.py` — DecisionConfig + difficulty scaling
- `validators/semantic_question_adherence.py` — validate_question_adherence
- `output_guardrails.py` — check_context_grounding
