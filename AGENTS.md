# InterviewBoss — Hermes Agent Context

## Project

InterviewBoss (/home/ubuntu/sj/interview-boss): Vue 3 + FastAPI + SQLite interview prep system.
Full architecture in CLAUDE.md — this file covers Hermes-specific delegation rules.

## What YOU handle directly

- Web search → use web_search (Exa)
- Web content extraction → use web_extract
- General knowledge Q&A → answer directly
- Project status → run git log/status via terminal
- Server status → run df/free/uptime via terminal
- Scheduling/cron → use cronjob tool
- Memory → use memory tool
- Image analysis → use vision_analyze
- File reading → use read_file
- Background tasks → use /background for long-running work

## What you DELEGATE to Claude Code (USE CC BRIDGE, NOT claude -p)

- ALL code writing, editing, generating
- File creation/modification in project directories
- Running tests, builds, linting
- Git commit, push, branch operations
- Code review, refactoring, debugging
- Any task touching /home/ubuntu/sj project files

NEVER write code yourself. NEVER use write_file or patch for code.
NEVER use `terminal(claude -p ...)` — use CC bridge for meaningful progress.

## CC Bridge command template (MANDATORY for code tasks)

```bash
SCRIPT="$HOME/.hermes/skills/claude-code-bridge/scripts/claude-code-bridge.sh"
SID="weixin_o9cq801vgFS6lTjY5oxumNK9Wmwg"

# Step 1: 检查/启动 bridge
STATUS=$("$SCRIPT" "$SID" status 2>&1)
if echo "$STATUS" | grep -q "没有活跃"; then
    "$SCRIPT" "$SID" start /home/ubuntu/sj
    sleep 3
fi

# Step 2: 发送任务（--stream 输出有意义进度，--long 5分钟超时）
"$SCRIPT" "$SID" send "<task>" --stream --long
```

## Workflow for code tasks: Plan → Approve → Code → Review

Step 1 — Plan: `"$SCRIPT" "$SID" send "给出简要实现计划: <task>"` (quick, no --stream)
Step 2 — Present plan to user, wait for approval
Step 3 — Code: `"$SCRIPT" "$SID" send "<task>" --stream --long`
Step 4 — Review: `"$SCRIPT" "$SID" send "review changes, 检查bug和风格" --stream`

For simple tasks (read file, git status, run test), use `send` without --stream.

## Progress reporting (避免长时间沉默)

**STOP 用终端直接跑 claude -p！用 bridge 的 --stream 模式自动推送有意义的进度。**

进度来自 bridge 的 stream 输出（如 "正在编辑 src/api/auth.ts"、"Running pytest"），而不是无意义的 "⏳ Still working... (iteration X/60)"。

如果用户问进度，用：`"$SCRIPT" "$SID" progress`
- 委托后："cc 完成了，结果：（一句话总结）"

对于预期超过 3 分钟的任务，拆成多个阶段，每阶段结束后汇报一次进度。
绝对不要沉默超过 2 分钟不给用户任何反馈。

## Engineering discipline (superpowers skill)

For non-trivial tasks, follow the superpowers workflow:
1. Brainstorm first — don't rush to code
2. Write a failing test before implementation (TDD)
3. Debug systematically when bugs appear — reproduce → minimize → hypothesize → fix
4. Verify the fix actually works before reporting done

## Parallel work

When multiple independent subtasks exist, use delegate_task to run them concurrently.
Example: "check frontend build + run backend tests + review git log" → 3 parallel sub-agents.

## Persistent Claude Code sessions

For multi-step work: "在 /home/ubuntu/sj 打开cc" or "/cc start"

## Key paths

- Backend: /home/ubuntu/sj/interview-boss/backend/
- Frontend: /home/ubuntu/sj/interview-boss/frontend/
- Database: backend/data/interview-boss.db
- Deploy: ./deploy/docker-deploy.sh update
- Tests: uv run pytest backend/tests/ -q
