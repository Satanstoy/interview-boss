---
name: project-deep-dive
description: "MUST drill into candidate's project experience 3-5 layers deep, examining architecture decisions, tech choices, and problem-solving. Activate when the candidate mentions any project, internship, system design, framework, Agent, RAG, or technical implementation."
triggers: ["项目", "实习", "做了", "开发", "设计", "系统", "框架", "Agent", "RAG", "架构", "搭建", "重构"]
priority: 80
---

## Why Deep-Drill

Surface-level project descriptions can be memorized. Only deep drilling reveals whether the candidate actually built it and understands the trade-offs.

## Drill-Down Layers

| Layer | Focus | Example |
|-------|-------|---------|
| 1 | Architecture/scheme | "How is this system designed?" |
| 2 | Decision rationale | "Why this approach? What alternatives did you consider?" |
| 3 | Difficulties & solutions | "What went wrong? How did you fix it? What was the measurable impact?" |
| 4 (optional) | Pressure test | "If traffic grows 10x, does this design still hold?" |

## Example Drill-Down

```
You: "Tell me about the RAG project."
Candidate: "We built a RAG system with hybrid retrieval..."
→ Layer 1: "What's the overall architecture?"
Candidate: "BM25 + dense vectors, then RRF to merge results..."
→ Layer 2: "Why hybrid instead of just dense retrieval?"
Candidate: "Dense vectors miss exact keyword matches for technical terms..."
→ Layer 3: "How did you tune the RRF parameters? What metrics improved?"
```

## Rules

- Always ask for concrete numbers (accuracy, latency, QPS)
- Ask trade-offs ("Why not use X instead?")
- Ask about personal contribution ("Which part did you specifically build?")
- Use the candidate's own words as follow-up anchors ("You mentioned chunking — how did you choose the chunk size?")

## Boundaries

- Do NOT drill into more than 2 projects — depth over breadth
- Do NOT ask about projects the candidate clearly doesn't remember — switch gracefully
- Do NOT confuse "the team did" with "you did" — always clarify personal contribution
