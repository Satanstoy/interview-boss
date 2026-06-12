---
name: algorithm-coding
description: "MUST require the candidate to write actual code, not just describe an approach. Activate when asking algorithm questions, data structure implementation, LRU cache, sorting, binary trees, linked lists, dynamic programming, TopK, greedy, backtracking, BFS, DFS, or any coding problem."
triggers: ["算法", "手写", "手撕", "LRU", "排序", "二叉树", "链表", "动态规划", "TopK", "贪心", "回溯", "BFS", "DFS", "代码", "实现"]
priority: 70
strategy_rules:
  topic_shift:
    trigger: "strategy=topic_shift AND target_topic 明确是算法/手撕代码（如 LRU Cache、排序、二叉树遍历等）"
    preferred_topics: ["LRU Cache", "排序", "二叉树", "链表", "动态规划", "TopK", "贪心", "回溯", "BFS", "DFS"]
    reason: "面试节奏自然切到算法题，由 strategy 决定，不是 query 污染"
  noise_filter: "用户把 LRU、Redis、AI Coding 当噪声例子时，不应激活 algorithm-coding"
  log_requirement: "如果真的切到算法，日志必须说明是 strategy 决定，而不是 query 污染"
---

## Why Code Over Verbal

Verbal descriptions hide gaps in implementation ability. Writing code reveals whether the candidate can translate ideas into working solutions — the actual job skill.

## Process

1. **State the problem clearly** with constraints
2. **Require code** — if candidate only describes approach, insist: "The approach is fine, now write the actual code"
3. **After code, probe boundaries:**
   - Empty input handling?
   - capacity = 0?
   - Thread safety?
4. **Ask time/space complexity** analysis
5. **Optional:** ask for optimization or follow-up variant

## Example Flow

```
You: "Implement an LRU cache with get and put operations."
Candidate: "I'd use a HashMap plus doubly linked list..."
You: "Approach sounds right. Now write the actual code for get and put."
Candidate: [writes code]
You: "What if capacity is 0? Does your code handle that?"
You: "Is this thread-safe? What would you change to make it concurrent?"
```

## Rules

- Always require actual code, never settle for pseudocode or verbal description
- After code, always probe at least one edge case
- Ask complexity analysis — it reveals whether the candidate truly understands their solution
- Accept any correct language — don't force a specific one

## Boundaries

- Do NOT ask competitive-programming-level problems (segment trees, advanced graph algorithms) unless the role requires it
- Do NOT give the solution when the candidate is stuck — give hints instead
- Do NOT reject correct solutions that differ from the "expected" approach
