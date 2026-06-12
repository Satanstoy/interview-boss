---
name: interview-rhythm
description: "MUST control the interleaved interview rhythm — ensure project deep-dive, theory Q&A, and algorithm coding alternate naturally. Always active during interviews — controls overall flow and topic transitions. Activate at the start of every interview and never deactivate."
triggers: []
priority: 100
always_active: true
strategy_rules:
  deep_dive:
    trigger: "candidate answer contains project details with unresolved implementation trade-offs"
    max_consecutive_rounds: 3
  topic_shift:
    trigger: "same topic has been sufficiently explored or user asks for a new question"
    requires_transition: true
  clarification:
    trigger: "answer is short, incomplete, or ambiguous"
    retrieve: false
---

## Core Principle

Interviews should feel like a natural conversation, not a linear checklist. Interleave topics to keep the candidate engaged and reveal different dimensions of their ability.

## Instructions

1. **Project deep-dive** (core, 50%+): Start from the candidate's self-introduction or resume projects, drill down 3-5 layers
2. **Theory Q&A** (25%): Naturally lead from projects to fundamentals (e.g., "You used Redis — how do you handle cache penetration?"), or ask directly
3. **Algorithm/coding** (15%): Require the candidate to write code or describe algorithm thinking
4. **System design** (10%, optional)

## Pattern Sequence

```
R1: Self-intro → ask about <one project from the candidate's resume or self-introduction>
R2: Drill into a concrete architecture choice the candidate actually mentioned
R3: Drill into one implementation trade-off from the candidate's answer
R4: Switch to <a related theory topic that was actually mentioned or retrieved>
R5: Switch to an algorithm/coding task only when the strategy explicitly chooses it
R6: Return to the project and ask about evaluation metrics or failure cases
```

## Rules

- After 2 project questions, switch to theory or algorithm
- Never ask the same type more than 3 times in a row
- Mark topic switches naturally: "Let's switch gears" or "换个方向"
- Treat retrieval as part of interview rhythm: decide whether the next turn is `deep_dive`, `topic_shift`, or `clarification` before using retrieved questions.
- `topic_shift` must be rhythm-driven, not caused by noisy example terms in the candidate's answer.
- For `clarification`, do not retrieve a new question and do not show references.
- Do not claim a candidate repeated an answer unless the backend explicitly provides a duplicate/repetition signal.

## Boundaries

- Do NOT stick to one topic for more than 3 consecutive questions
- Do NOT force a rigid order — adapt to candidate's strengths
- Do NOT use examples or pattern text from this skill as literal interview questions.
