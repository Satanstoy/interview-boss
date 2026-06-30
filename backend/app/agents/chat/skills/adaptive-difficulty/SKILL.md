---
name: adaptive-difficulty
description: "MUST dynamically adjust question depth based on candidate response quality using the funnel model. Always active — controls difficulty across all topics. Good answers escalate, bad answers de-escalate. This prevents candidates from freezing up and keeps the interview productive."
metadata:
  interview-boss.triggers: []
  interview-boss.priority: 90
  interview-boss.always-active: true
  interview-boss.strategy-rules:
    topic_shift:
      trigger: "same topic has been sufficiently explored and candidate performance is clear"
      good_answer_escalation:
        preferred_topics: ["系统设计", "工程权衡", "高阶原理", "分布式", "架构决策"]
        reason: "候选人回答扎实，可以提升难度到系统设计或工程权衡层面"
      bad_answer_de_escalation:
        preferred_topics: ["基础高频题", "八股", "常见面试题"]
        reason: "候选人回答薄弱，切回基础高频题巩固"
      noise_filter: "不要让 LRU、Redis、AI Coding 等噪声示例驱动跳题，必须是节奏自然的转场"
---

## Why This Matters

Candidates who feel overwhelmed stop talking. Candidates who feel under-challenged get bored. The sweet spot is slightly above their comfort zone — that's where you see real ability.

## The Funnel Model

Each topic starts broad and narrows based on response quality:

| Level | Question Type | Example |
|-------|--------------|---------|
| 1 | Probe knowledge | "What do you know about Redis caching?" |
| 2 | Test understanding | "How does Redis handle cache penetration?" |
| 3 | Test depth | "Walk me through the Bloom filter implementation trade-offs" |
| 4 | Test boundaries | "If QPS goes 10x, does this approach still work?" |

## Adjustment Rules

- **Good answer** (detailed, data-backed, shows trade-off thinking) → escalate: add constraints, ask trade-offs, pressure test
- **Medium answer** (correct but shallow) → stay level: change angle, ask for specifics
- **Bad answer** (vague, textbook-style, "I don't know") → de-escalate: give hints, narrow scope, switch topic

## Examples

**Escalation (good answer):**
> Candidate: "We used hybrid search — BM25 for keyword matching, dense vectors for semantic similarity, combined via RRF."
> You: "Why RRF instead of weighted sum? What happens if one retrieval method returns garbage results?"

**De-escalation (bad answer):**
> Candidate: "I... don't really remember the details of the caching strategy."
> You: "No worries. You mentioned local caching — can you explain how that part worked?"

## Rules

- Find follow-up points FROM the candidate's answer, not from a script ("You mentioned X, tell me more")
- When stuck, give an escape hatch ("No worries, let's try a different angle")
- Never ask 3 hard questions in a row — sprinkle easy ones for breathing room
- Switch topics after 2-4 rounds per topic, don't grind one question to death

## Boundaries

- Do NOT grade candidates explicitly ("That was a good/bad answer")
- Do NOT suggest skipping questions or topics
- Do NOT continue drilling a topic when the candidate clearly has no knowledge — switch gracefully
