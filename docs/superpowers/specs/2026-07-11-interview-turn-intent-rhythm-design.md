# Interview Turn Intent and Rhythm Design

Date: 2026-07-11
Status: approved design, awaiting implementation-plan review

## Problem

The current chat harness correctly separates ReAct tool execution from final
user-visible writers, but it leaves rhythm control split across three places:

- `interview-rhythm` and domain skills influence the ReAct prompt.
- `rhythm_profile`, coverage, and stop policy influence thresholds and closing.
- Contract writers receive only a small `next_focus` string and recreate the
  next question from scratch.

This means a skill can be loaded and its tool instructions can be followed,
while the final writer still asks a generic or rhythm-inappropriate question.
The system has no single, observable decision that says why this turn is a
deep-dive, clarification, topic shift, counter-question response, or close.

## Goals

- Keep the async harness. Do not reintroduce LangGraph state edges.
- Keep ReAct as evidence and tool execution only.
- Make `rhythm_profile`, `interview-rhythm`, and focused skills such as
  `project-deep-dive` jointly affect the final user-visible turn.
- Avoid enumerating candidate phrasings or maintaining conversational keyword
  states. Use LLM semantic interpretation and structured interview facts.
- Preserve the five existing `TurnContract` actions.
- Make the executed pacing decision observable in API done metadata and E2E.

## Non-goals

- Do not generate a fixed 10-15 question script at conversation start.
- Do not let one LLM prompt select tools, change policy, and write the final
  question without a structured boundary.
- Do not turn skill examples into literal questions.
- Do not make every turn require a blocking LLM validator.

## Architecture

```text
Semantic Interpreter
  -> Interview Strategy Engine
  -> TurnIntent
  -> TurnContract
  -> ReAct evidence collection when required
  -> Contract writer
  -> validator / metadata
```

### Semantic Interpreter

The existing structured classifier continues to interpret the current user
turn. It reports facts such as answer quality, candidate act, counter-question
status, request to end, clarification need, and confidence. It does not pick
the final question or transition policy.

### Interview Strategy Engine

This is the single pacing authority. It combines:

- semantic facts from the interpreter;
- question coverage and repeated-topic facts from `InterviewLedger`;
- macro coverage preferences from `rhythm_profile`;
- `interview-rhythm` rules, including excessive consecutive depth and missing
  dimensions;
- the active focused skill's local tactic, for example the next project
  deep-dive layer.

The engine uses a hybrid decision model:

- semantic interpretation may say whether the current project still contains
  unresolved, useful material;
- deterministic ledger and coverage rules prevent excessive consecutive topic
  depth, repeated questions, missing dimensions, and premature completion.

### TurnIntent

`TurnIntent` is a short-lived decision record for one turn. It is not a
conversation state machine and it does not classify candidate wording.

Suggested shape:

```python
class TurnIntent(BaseModel):
    strategy: Literal[
        "deep_dive", "clarification", "topic_shift",
        "counter_response", "close",
    ]
    assessment_goal: str
    target_dimension: str | None
    drill_layer: str | None
    tool_intent: ToolIntent
    writer_brief: WriterBrief
    source_facts: dict
    reason: str
```

Examples:

- `deep_dive` plus `drill_layer=decision_rationale` asks why a candidate made
  an already-mentioned architecture choice.
- `topic_shift` plus `target_dimension=algorithm_coding` requires question
  selection from the corresponding bank category.
- `clarification` stays on the same assessed signal and does not retrieve a
  new bank question.

`writer_brief` contains the evidence anchor, what signal to collect, and
semantic boundaries. It is an output brief, not a literal question template.

### Skill roles

`rhythm_profile` is macro policy: coverage proportions, missing dimensions,
and stop readiness.

`interview-rhythm` is the policy rule set that translates macro facts into a
turn strategy: remain in a deep dive, clarify, or shift dimensions.

Focused skills provide local tactics only after the strategy is chosen:

- `project-deep-dive`: architecture, rationale, failure recovery, pressure
  test, personal contribution, or measured impact;
- `theory-qa`: the allowed depth and evidence expected for fundamentals;
- `algorithm-coding`: algorithm-specific evidence and question-bank usage.

Skills no longer rely on a final writer re-reading their prose from an
unstructured ReAct prompt.

### TurnContract, ReAct, and writers

The current five `TurnContract` actions stay in place. `TurnIntent` is created
before final output and explains how that action must be carried out.

ReAct receives the intent's tool requirements and may collect candidates,
load skills, and explicitly select a question. It cannot change the chosen
strategy or final contract.

Writers receive both `TurnContract` and `TurnIntent`:

- a follow-up writer renders the selected deep-dive layer or topic shift;
- a question writer renders the selected bank question while preserving the
  intent's assessment goal;
- counter and close writers preserve the current interview intent in metadata
  so later summary/coverage can distinguish a normal counter-question from a
  missing answer.

## Assessment evidence follow-up

The same intent records the expected signal for an interviewer question.
Subsequent semantic interpretation records whether that signal was observed,
partially observed, or not assessed. A counter-question after an unanswered
technical question creates `not_assessed`; it does not create a weakness or
avoidance conclusion.

This evidence will become the input to the practice-feedback summary path.
It is deliberately separate from rhythm selection, but shares the same
question and turn identity.

## Observability

Done metadata will include:

```json
{
  "turn_intent": {
    "strategy": "deep_dive",
    "assessment_goal": "decision_rationale",
    "target_dimension": "project_followup"
  },
  "turn_contract": {"action": "continue_natural_followup"},
  "writer_trace": {"writer": "followup_writer"},
  "tool_contract_trace": {}
}
```

The metadata must describe the executed intent, not a later sidecar decision.

## TDD acceptance scenarios

1. After two sufficiently answered project layers, with theory coverage
   missing, the engine emits `topic_shift` to theory. The writer cannot continue
   project deep-dive.
2. With an unresolved project trade-off, the engine emits `deep_dive` with
   `decision_rationale`. It cannot retrieve or ask an algorithm question.
3. A candidate counter-question receives `answer_counter_question`; the
   outstanding technical signal remains `not_assessed`, not negative evidence.
4. A candidate requesting close receives `close_with_summary`; summary input
   marks unobserved signals as `not_assessed` rather than weak or avoided.
5. API E2E asserts the done event exposes the executed `turn_intent`, contract,
   tool trace, and writer trace for each relevant turn.

## Migration

1. Introduce `TurnIntent` and its strategy engine in observation mode with
   focused pure-function tests.
2. Feed the intent into contract execution and writers, then make it the only
   source for the final writer brief.
3. Persist executed intent and assessment evidence in metadata.
4. Add the real `sj` journey as a mocked API E2E fixture and retain a manual
   real-model acceptance run for naturalness.
