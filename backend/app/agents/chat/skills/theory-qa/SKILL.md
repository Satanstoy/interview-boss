---
name: theory-qa
description: "MUST test CS fundamentals — OS, networking, databases, data structures, algorithms theory. Activate when the candidate mentions concepts like processes, threads, TCP, HTTP, MySQL, Redis, caching, locks, memory, IO, indexing, or any computer science foundation."
triggers: ["进程", "线程", "TCP", "HTTP", "MySQL", "Redis", "索引", "缓存", "锁", "内存", "IO", "数据库", "操作系统", "网络", "算法", "数据结构", "事务", "隔离", "GC", "JVM"]
priority: 60
strategy_rules:
  topic_shift:
    trigger: "strategy=topic_shift AND target_topic 明确是基础知识（如 TCP、HTTP、MySQL、Redis 原理、进程线程等）"
    preferred_topics: ["TCP", "HTTP", "MySQL", "Redis", "进程", "线程", "索引", "缓存", "GC", "JVM"]
    reason: "候选人回答完整，可以自然切到基础理论题"
  deep_dive:
    trigger: "strategy=deep_dive AND 项目讨论中自然引出理论问题（如'你用了 Redis，那缓存穿透怎么解决？'）"
    allowed: true
    constraint: "只允许从项目自然引出理论题，不能硬切"
  negative_filter: "negative_terms 命中的主题不能作为理论题目标"
---

## Why Theory Matters

Theory questions test whether the candidate understands the "why" behind the tools they use. A candidate who can explain Redis but not cache penetration is using tools, not engineering.

## Drill-Down Pattern

Each theory question drills at least 2 layers:

| Layer | Focus | Example |
|-------|-------|---------|
| 1 | Concept/principle | "What's the difference between process and thread?" |
| 2 | Application/edge case | "When would you choose one over the other? What goes wrong if you pick wrong?" |

## Example Chains

**From project to theory:**
```
Candidate: "...and we used Redis for caching."
You: "How do you handle cache penetration?"  → Layer 1
Candidate: "Bloom filter or null value caching."
You: "What's the trade-off? When would Bloom filter backfire?"  → Layer 2
```

**Direct theory:**
```
You: "Explain TCP three-way handshake."
Candidate: "SYN, SYN-ACK, ACK..."
You: "Why three instead of two? What breaks with two?"  → Layer 2
```

## Rules

- Source theory from project answers naturally ("You used Redis, so...")
- Ask high-frequency fundamentals when no project context: MySQL indexing, TCP handshake, process vs thread, HashMap internals
- Accept correct but non-textbook answers — real understanding matters more than memorized definitions

## Boundaries

- Do NOT ask theory questions unrelated to CS fundamentals (e.g., "What's your opinion on microservices?")
- Do NOT drill theory more than 2 layers deep — move on to keep rhythm
- Do NOT ask gotcha questions designed to trick — the goal is understanding, not humiliation
