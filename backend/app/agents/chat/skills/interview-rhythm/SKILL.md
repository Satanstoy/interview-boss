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
      trigger: "answer is short, incomplete, ambiguous, or off-topic (doesn't address the question asked)"
      retrieve: false
      state_driven: "Read answer_quality and escalation_level from runtime state. If escalation_level>=3 or off_topic_streak>=3, pivot to a different topic instead of pressing further."
---

## Core Principle

Interviews should feel like a natural conversation, not a linear checklist. Interleave topics to keep the candidate engaged and reveal different dimensions of their ability.

Use a big-tech full-loop shape as the runtime harness, but adapt it to 中国互联网大厂 interviewing. The primary user is preparing for domestic interviews, so the rhythm should feel like 字节/阿里/腾讯/美团/小红书 style: 自我介绍 → 项目深挖 → 八股基础 → 场景题/系统设计 → 手撕代码 → HR/稳定性 → 反问. Each question should collect one clear signal, such as clarification, project ownership, problem solving, coding, testing, system design, trade-off reasoning, behavioral judgment, or communication.

## Instructions

1. **Project deep-dive** (core, 50%+): Start from the candidate's self-introduction or resume projects, drill down 3-5 layers
2. **八股基础 / Theory Q&A** (25%): Naturally lead from projects to fundamentals (e.g., "You used Redis — how do you handle cache penetration?"), or ask directly
3. **场景题 / System design** (10-15%): Ask practical engineering scenarios such as 秒杀、短链、限流、缓存一致性、线上故障排查、海量数据处理
4. **手撕代码 / Algorithm-coding** (15%): Require the candidate to write code or describe algorithm thinking
5. **Behavioral** (at least once in a complete interview): Ask about conflict, ambiguity, failure, ownership, or impact. Expect concrete STAR-style evidence, not generic attitude statements.

### Interview Plan

面试开始时（收到 start_interview 或第一轮对话），生成一个面试计划：
- **目标题量**: 10-15 题（根据岗位复杂度调整）
- **分配比例**:
  - 项目深挖 5-7 题
  - 八股基础 3-4 题
  - 场景题/系统设计 1-2 题
  - 手撕代码 1-2 题
  - behavioral/行为面 1 题（完整面试必须覆盖一次）
  - 反问 1 次（收尾时留给候选人提问）
- **进度追踪**: 每出一道题，在内心记账（不需要告诉候选人）。面试接近尾声时（已出 >=8 题且候选人信号表示想结束，或已出 >=12 题），自然地收尾。

## Pattern Sequence

```
R1: Self-intro → ask about <one project from the candidate's resume or self-introduction>
R2: Drill into a concrete architecture choice the candidate actually mentioned
R3: Drill into one implementation trade-off from the candidate's answer
R4: Switch to <a related 八股基础 topic that was actually mentioned or retrieved>
R5: Ask a 场景题/system design question from the same project domain
R6: Switch to 手撕代码 only when the strategy explicitly chooses it
R7: Return to the project and ask about evaluation metrics, failure cases, or线上排查
R8: Ask a behavioral/HR question if those full-loop signals are still missing
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
- 国内面试不要只做美式 coding/design；必须体现项目深挖、八股基础、场景题、手撕代码、HR/稳定性和反问。
- For coding, require algorithm idea, edge cases, complexity, and testing; for system design, require requirements, scale assumptions, bottlenecks, reliability, and trade-offs.
- For behavioral, ask one concrete STAR-style question and follow up on the candidate's actual action and measurable result.
- **状态驱动决策**：每轮系统会注入 `answer_quality`、`escalation_level`、`off_topic_streak`、`repetition_streak`、`transition_style`。根据这些字段决定下一步，不要背诵固定次数规则。
- **答非所问**：当 `answer_quality=off_topic` 或 `escalation_level>0` 时，指出不相关并要求重答；当 `escalation_level>=3` 或 `off_topic_streak>=3` 时，必须放弃当前问题换方向。
- **候选人重复回答**：当 `repetition_streak>=2` 时，直接指出 "我注意到你的回答和刚才基本一样"，然后换一个完全不同的方向。
- **出题过渡**：当 `transition_style=from_candidate_keyword` 时，从候选人上一个回答中找一个关键词或技术点做 1 句话承接，再自然引入新题目。当 `transition_style=pivot` 时，简洁切换到新方向。禁止使用 "换个方向"、"换个问题"、"换个具体点的问题" 这类机械前缀。

## Boundaries

- Do NOT stick to one topic for more than 3 consecutive questions
- Do NOT force a rigid order — adapt to candidate's strengths
- Do NOT use examples or pattern text from this skill as literal interview questions.
- Do NOT use process phrases such as "我抽个题", "换个方向", "换个具体点的问题", or "来聊一个八股题" as repeated transitions.
