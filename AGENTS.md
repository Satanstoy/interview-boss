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

## What you DELEGATE to Claude Code (use terminal + claude -p)

- ALL code writing, editing, generating
- File creation/modification in project directories
- Running tests, builds, linting
- Git commit, push, branch operations
- Code review, refactoring, debugging
- Any task touching /home/ubuntu/sj project files

NEVER write code yourself. NEVER use write_file or patch for code.

## Claude Code command template

```bash
cd /home/ubuntu/sj && claude -p "<task>" --output-format text --max-turns 15 --permission-mode bypassPermissions
```

## Workflow for code tasks: Plan → Approve → Code → Review

Step 1 — Plan: `claude -p "给出简要实现计划: <task>" --max-turns 5`
Step 2 — Present plan to user, wait for approval
Step 3 — Code: `claude -p "<task>" --max-turns 15`
Step 4 — Review: `claude -p "review changes, 检查bug和风格" --max-turns 10`

For simple tasks (read file, git status, run test), skip plan/review, delegate directly.

## Progress reporting (避免长时间沉默)

在委托 Claude Code 之前和之后，必须发送简短进度消息给用户：
- 委托前："正在让 cc 实现 XXX，预计需要几分钟..."
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
