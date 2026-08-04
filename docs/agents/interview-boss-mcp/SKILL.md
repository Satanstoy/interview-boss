---
name: interview-boss-mcp
description: "Use the InterviewBoss MCP as a stateful interview-question source: load the right interview skill, search or draw questions for a job position, select a server-owned candidate, and ask it naturally."
compatibility: "Requires an InterviewBoss Streamable HTTP MCP server configured in the agent client."
metadata:
  interview-boss.mcp: true
  interview-boss.session-state: true
---

# InterviewBoss MCP Agent Skill

Use this skill whenever the user asks to practise an interview, generate interview questions, search the InterviewBoss question bank, or run a role-specific mock interview.

## Core distinction

The MCP server provides tools and server-side skill instructions. This file is the canonical source for the MCP tool-use policy and is automatically included in the server's MCP initialization instructions. The server also activates it in each MCP `session_id`; a client-side copy is only a fallback for clients that ignore server instructions.

## Session rule

Create one stable opaque `session_id` for each interview. Pass the same value to every MCP call in that interview. After the first call, persist the `metadata.session_id` returned by the server and use that value if one was generated. Do not reuse a session across unrelated users or interviews.

## Account and privacy rule

- The MCP Bearer Token identifies the account. Treat all returned questions as belonging to that account's authorized view.
- Do not use or expose `user_id` or `bank_mode` from the client request. The server overrides them from the authenticated account.
- Never put the Token in a URL query parameter or in the conversation transcript.
- Do not reveal tool names, session IDs, candidate indexes, debug fields, or raw metadata to the interview candidate.

## Recommended workflow

1. Infer the target role from the user's request. Keep the exact role in `job_position`, such as `后端开发` or `Java 工程师`.
2. Load only the specialized server skills needed for the current interview. Do not reload a skill already active in this session.
3. Use `search_questions` when the user gives a topic or specific technology. Extract 2–5 concrete keywords.
4. Use `draw_questions` when the user requests a random question, a fresh question, or a filtered question by difficulty/type.
5. Read the returned `items`. If there are multiple candidates, choose by relevance to the current interview signal, then call `select_question` with its zero-based `candidate_index`.
6. After `select_question` returns `selected_question`, ask that question directly in a natural interviewer voice. Do not add process commentary first.
7. Continue the conversation without another tool call when the candidate is still answering the current question. Retrieve or draw the next question only when a new question is needed.

## Server skills

Use `load_skill` with one of these names when its specialized behavior is needed:

- `project-deep-dive`: drill into project architecture, personal contribution, trade-offs, metrics, and failure cases.
- `theory-qa`: test OS, networking, database, cache, JVM, and other CS fundamentals.
- `algorithm-coding`: require real code, then probe edge cases, complexity, and testing.
- `adaptive-difficulty`: escalate strong answers and de-escalate or change direction when the candidate is stuck.
- `interview-rhythm`: maintain a balanced full-loop interview across projects, fundamentals, system design, coding, and behavioral signals.
- `hr-soft-skills`: use for behavioral, career, collaboration, closing, and candidate-question phases.

The `interview-tool-use` policy is loaded automatically by the MCP server. Do not spend a tool call loading it again; load only the domain skill needed for the current interview.

## Tool policy

### `load_skill`

Call once per required skill per session:

```text
load_skill(
  skill_name="project-deep-dive",
  session_id="<stable-session-id>"
)
```

Read the returned instruction text and follow it. If the tool says the skill is already active, continue without calling it again.

### `search_questions`

Use concrete keywords and pass the role when known:

```text
search_questions(
  keywords=["Redis", "缓存穿透", "布隆过滤器"],
  job_position="后端开发",
  question_type="knowledge_probe",
  session_id="<stable-session-id>"
)
```

Check both `ok` and whether `items` is non-empty. A successful call may still return no questions.

### `draw_questions`

Use for fresh or random questions:

```text
draw_questions(
  count=3,
  job_position="Java 工程师",
  difficulty="medium",
  question_type="algorithm_coding",
  session_id="<stable-session-id>"
)
```

Supported filters include `difficulty`, `cat1`, `cat2`, `topic`, `question_type`, and `job_position`. Do not invent a candidate list; the server owns the candidates.

### `select_question`

Call after search/draw when you want to bind a specific candidate:

```text
select_question(
  candidate_index=1,
  session_id="<stable-session-id>"
)
```

The index is zero-based and refers only to the most recent server-owned candidate list in this session. If selection fails because candidates are missing or stale, retrieve or draw again.

## Empty-result fallback

1. Empty search → try `draw_questions` with the same role and topic.
2. Empty draw → try `search_questions` with different concrete keywords.
3. Both empty → state briefly that the question bank has no suitable item and ask a clearly labeled fallback question yourself.
4. Never silently skip the requested interview signal.

## Response handling

The tools return a stable envelope:

- `ok`: whether the operation succeeded.
- `items`: candidate questions from search/draw.
- `selected_question`: the question bound for the next turn.
- `question_plan`: the server's next-question binding information.
- `metadata.session_id`: the session value to persist.

Treat `items=[]` as an empty result even when `ok=true`. Internal fields such as `debug_reason`, candidate indexes, and session state are for agent control only and must not be shown to the candidate.

## Interview output style

After a question is selected, ask it directly. Do not say “I am calling draw_questions”, “the tool selected”, or “candidate index 1”. For coding questions, require actual code, edge cases, complexity, and testing. For system-design questions, ask about requirements, scale, bottlenecks, reliability, and trade-offs. For behavioral questions, ask for concrete STAR evidence.
