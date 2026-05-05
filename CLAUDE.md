# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

InterviewBoss is a Chinese-language AI-powered interview prep platform. It ingests job descriptions and interview experiences (text + images), classifies them with an LLM, builds a deduplicated question bank via embedding similarity, and supports quiz/practice with LLM-generated answers, mock interviews, and knowledge graphs. Multi-user with JWT auth, three bank modes, and admin review.

## Commands

### Backend (Python / FastAPI)
```bash
cd /root/sj/multimodal-parser
uv run uvicorn app.asgi:app --host 0.0.0.0 --port 8000
```

### Frontend (Vue 3 / Vite)
```bash
cd frontend
npm install
npm run dev      # Dev server at http://localhost:3000
npm run build    # Production build → /var/www/interview-boss/dist/
```

### Python 依赖管理（必须使用 uv）
```bash
# uv 二进制绝对路径: /root/.local/bin/uv（不在 PATH 中）
uv sync                    # 从 pyproject.toml 安装所有依赖
uv add <package>           # 添加新依赖
# 安装后需要重启后端服务才能生效
```

**重要：本项目所有 Python 依赖操作必须使用 uv，不要用 pip/pip3。**

## Architecture

### Backend (`backend/app/`)

Layered design with 4 tiers:

1. **Routers** (`routers/`) — 8 FastAPI APIRouters registered in `asgi.py`. Key routes: `/api/auth/*`, `/api/submit`, `/api/data/*`, `/api/master-bank/*`, `/api/analytics`, `/api/profile`.
2. **Services** (`services/`) — Business logic. `llm.py` wraps AsyncOpenAI with tenacity retries; `clustering.py` provides LLM-based question deduplication via cat2 pre-grouping + two-pass clustering; `utils.py` handles image encoding and URL-signature dedup for Chinese platforms.
3. **Core** (`core/`) — `config.py` hot-reloads settings from DB and syncs back to `.env`; `auth.py` implements JWT access (15min) + refresh token (HttpOnly cookie, server-side JTI tracking, rotation); `prompts.py` holds 4 LLM prompt templates.
4. **DB** (`db/`) — `connection.py` manages thread-local SQLite connections (WAL mode), `run_db()` wraps sync calls in `asyncio.to_thread()`. `operations.py` has reusable CRUD. Schema migrations are inline in `init_db()`.

**Database:** SQLite at `backend/data/multimodal.db`. Tables: `jd`, `interview`, `questions_detail`, `question_bank`, `users`, `refresh_tokens`, `user_profile`, `user_practice_history` (plus legacy `master_question_bank`, `practice_history` being migrated).

### Frontend (`frontend/src/`)

- **`App.vue`** — Monolithic orchestrator (~750 lines) holding all state (data, auth, filters, selections). Components are children that receive props and emit events.
- **`api/index.js`** — Typed API client function wrappers.
- **`utils/http.js`** — Custom Fetch wrapper with auto JWT injection, 401-triggered token refresh, retry on 5xx/network, timeout, SSE streaming, and request cancellation.
- **`composables/`** — `useSelection` (multi-select checkboxes), `useNotification` (toast + confirm dialog).
- **`components/`** — 16 Vue SFCs using `<script setup>` Composition API style.

### Auth Flow
Access token stored in memory (not localStorage). Refresh token in HttpOnly cookie. On 401, `http.js` automatically calls `/api/auth/refresh` and retries the original request.

### LLM Integration
Uses OpenAI Python SDK (`AsyncOpenAI`) against any OpenAI-compatible API. Endpoint, model, and API key are configurable via `/api/profile` and persisted in `user_profile` table + `.env` file. Four prompt templates in `core/prompts.py`: content extraction, question tagging, answer generation, answer evaluation. Question deduplication uses LLM-based clustering instead of embedding similarity.

## Key Patterns

- **Question deduplication:** LLM-based clustering with cat2 pre-grouping, two-pass clustering, and verification step.
- **Batch operations:** SSE streaming for progress updates on answer generation.
- **Admin system:** `users.is_admin` flag; admin review flow for uploaded questions.
- **Bank mode:** Three modes (public/personal/mixed) controlling question visibility per user.
- **DB auto-backup:** Before destructive operations (clear, rebuild), SQLite database is backed up.

## Configuration

Backend env vars (in `backend/.env`, see `.env.example`):
- `OPENAI_API_KEY`, `OPENAI_BASE_URL` — LLM API connection
- `LLM_MODEL_NAME` — Model selection
- `JWT_SECRET` — JWT signing key (auto-generated if not set)
- `ADMIN_USERNAME` — 种子管理员用户名（默认 sj）
- `ADMIN_PASSWORD` — 种子管理员密码（首次启动必填，之后可改）
- `DEBUG` — 设为 true 开启热重载和 Swagger 文档
- `ALLOWED_ORIGINS` — CORS 允许的来源（逗号分隔，开发时设 http://localhost:3000）

Production: nginx at `/etc/nginx/conf.d/interview-boss.conf` reverse-proxies `/api/` to uvicorn on port 8000 with 180s timeout; serves frontend static files from `/var/www/interview-boss/dist/`.

## README.md 更新规则

每当完成以下类型的工作后，**必须**同步检查并更新 README.md：
- 新增功能模块
- 项目结构发生变化（新增、删除或重命名目录/重要文件）
- API 路由发生变更
- 技术栈发生变化（新增依赖、框架升级等）
- 部署方式发生变更

更新时遵循以下原则：
- 只做最小化修改：更新项目结构展示、补充新功能的简要说明
- 禁止大幅重写或重新组织 README 的整体结构
- 保持原有的文档风格和排版不变

## 阶段性工作流

每完成一个开发阶段后，按顺序执行：
1. 运行测试，确认功能正常
2. 如涉及上述变更，更新 README.md
3. 提交代码并推送到远程仓库

## Language

The application UI, prompts, and documentation are in Chinese (Simplified). Code identifiers, comments, and commit messages mix Chinese and English.
