---
name: interview-rhythm
description: "MUST control the interleaved interview rhythm — ensure project deep-dive, theory Q&A, and algorithm coding alternate naturally. Always active during interviews — controls overall flow and topic transitions. Activate at the start of every interview and never deactivate."
metadata:
  interview-boss.triggers: []
  interview-boss.priority: 100
  interview-boss.always-active: true
  interview-boss.strategy-rules:
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

Use a big-tech full-loop shape as the runtime harness: each question should collect one clear signal, such as clarification, project ownership, problem solving, coding, testing, system design, trade-off reasoning, behavioral judgment, or communication.

## Instructions

1. **Project deep-dive** (core, 50%+): Start from the candidate's self-introduction or resume projects, drill down 3-5 layers
2. **Theory Q&A** (25%): Naturally lead from projects to fundamentals (e.g., "You used Redis — how do you handle cache penetration?"), or ask directly
3. **Algorithm/coding** (15%): Require the candidate to write code or describe algorithm thinking
4. **System design** (10%, optional)
5. **Behavioral** (at least once in a complete interview): Ask about conflict, ambiguity, failure, ownership, or impact. Expect concrete STAR-style evidence, not generic attitude statements.

### Interview Plan

面试开始时（收到 start_interview 或第一轮对话），生成一个面试计划：
- **目标题量**: 10-15 题（根据岗位复杂度调整）
- **分配比例**:
  - 项目深挖 5-7 题
  - 理论问答 3-4 题
  - 算法/编码 1-2 题
  - 系统设计 0-1 题（可选）
  - behavioral/行为面 1 题（完整面试必须覆盖一次）
- **进度追踪**: 每出一道题，在内心记账（不需要告诉候选人）。面试接近尾声时（已出 >=8 题且候选人信号表示想结束，或已出 >=12 题），自然地收尾。

## Pattern Sequence

```
R1: Self-intro → ask about <one project from the candidate's resume or self-introduction>
R2: Drill into a concrete architecture choice the candidate actually mentioned
R3: Drill into one implementation trade-off from the candidate's answer
R4: Switch to <a related theory topic that was actually mentioned or retrieved>
R5: Switch to an algorithm/coding task only when the strategy explicitly chooses it
R6: Return to the project and ask about evaluation metrics or failure cases
R7: Ask a system design or behavioral question if those full-loop signals are still missing
R7+: Continue the interview — interleave project deep-dive, theory Q&A, and algorithm/coding
     until the target question count (10-15) is reached. Repeat R2-R6 patterns with fresh topics.
     Do NOT stop at R6; the above is a suggested opening sequence, not a hard limit.
```

## Rules

- After 2 project questions, switch to theory or algorithm
- Never ask the same type more than 3 times in a row
- Let topic switches sound like normal interviewing: ask the next concrete question without announcing that you are drawing or switching topics.
- Treat retrieval as part of interview rhythm: decide whether the next turn is `deep_dive`, `topic_shift`, or `clarification` before using retrieved questions.
- `topic_shift` must be rhythm-driven, not caused by noisy example terms in the candidate's answer.
- The backend maintains an interview ledger with asked question IDs, categories, and recent topics. Treat that ledger as authoritative: do not ask the same question ID, do not ask a close paraphrase, and avoid categories that have already reached their quota.
- For `clarification`, do not retrieve a new question and do not show references.
- Do not claim a candidate repeated an answer unless the backend explicitly provides a duplicate/repetition signal.
- 面试必须覆盖至少 8 题才算完整，低于 5 题是不可接受的
- 如果候选人回答简短（<3句话），追问一两个层次再换题，不要一道题就换
- 如果面试即将结束但题量不足，加速节奏：跳过深挖，改为快速问答模式
- 候选人说"换一个"/"下一个"时，计入已完成的题并切换
- For coding, require algorithm idea, edge cases, complexity, and testing; for system design, require requirements, scale assumptions, bottlenecks, reliability, and trade-offs.
- For behavioral, ask one concrete STAR-style question and follow up on the candidate's actual action and measurable result.

## Boundaries

- Do NOT stick to one topic for more than 3 consecutive questions
- Do NOT force a rigid order — adapt to candidate's strengths
- Do NOT use examples or pattern text from this skill as literal interview questions.
- Do NOT use process phrases such as "我抽个题", "换个方向", or "来聊一个八股题" as repeated transitions.
