---
name: interview-rhythm
description: "MUST control the interleaved interview rhythm — ensure project deep-dive, theory Q&A, and algorithm coding alternate naturally. Always active during interviews — controls overall flow and topic transitions. Activate at the start of every interview and never deactivate."
triggers: []
priority: 100
always_active: true
---

## Core Principle

Interviews should feel like a natural conversation, not a linear checklist. Interleave topics to keep the candidate engaged and reveal different dimensions of their ability.

## Instructions

1. **Project deep-dive** (core, 50%+): Start from the candidate's self-introduction or resume projects, drill down 3-5 layers
2. **Theory Q&A** (25%): Naturally lead from projects to fundamentals (e.g., "You used Redis — how do you handle cache penetration?"), or ask directly
3. **Algorithm/coding** (15%): Require the candidate to write code or describe algorithm thinking
4. **System design** (10%, optional)

## Example Sequence

```
R1: Self-intro → ask about GLEAR project
R2: Drill into hybrid retrieval architecture
R3: Drill into RRF implementation details
R4: Switch — "You mentioned HNSW, explain efConstruction" (theory)
R5: Switch — "Now implement an LRU cache" (algorithm)
R6: Back to project — ask about evaluation metrics
```

## Rules

- After 2 project questions, switch to theory or algorithm
- Never ask the same type more than 3 times in a row
- Mark topic switches naturally: "Let's switch gears" or "换个方向"

## Boundaries

- Do NOT stick to one topic for more than 3 consecutive questions
- Do NOT force a rigid order — adapt to candidate's strengths
