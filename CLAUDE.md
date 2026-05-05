# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

InterviewBoss is a Chinese-language AI-powered interview prep platform. It ingests job descriptions and interview experiences (text + images), classifies them with an LLM, builds a deduplicated question bank via embedding similarity, and supports quiz/practice with LLM-generated answers, mock interviews, and knowledge graphs. Multi-user with JWT auth, three bank modes, and admin review.

## Commands

### Backend (Python / FastAPI)
```bash
cd backend
uv run uvicorn app.asgi:app --host 0.0.0.0 --port 8000
```

### Frontend (Vue 3 / Vite)
```bash
cd frontend
npm install
npm run dev      # Dev server at http://localhost:3000
npm run build    # Production build → /var/www/interview-boss/dist/
```

### Running with uv (root level)
```bash
uv sync          # Install from pyproject.toml
```

## Architecture

### Backend (`backend/app/`)

Layered design with 4 tiers:

1. **Routers** (`routers/`) — 8 FastAPI APIRouters registered in `asgi.py`. Key routes: `/api/auth/*`, `/api/submit`, `/api/data/*`, `/api/master-bank/*`, `/api/analytics`, `/api/profile`.
2. **Services** (`services/`) — Business logic. `llm.py` wraps AsyncOpenAI with tenacity retries; `embedding.py` provides cosine-similarity dedup; `utils.py` handles image encoding and URL-signature dedup for Chinese platforms.
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
Uses OpenAI Python SDK (`AsyncOpenAI`) against any OpenAI-compatible API. Endpoint, model, and API key are configurable via `/api/profile` and persisted in `user_profile` table + `.env` file. Four prompt templates in `core/prompts.py`: content extraction, question tagging, answer generation, answer evaluation.

## Key Patterns

- **Question deduplication:** Embedding cosine similarity with configurable threshold (default 0.85).
- **Batch operations:** SSE streaming for progress updates on answer generation.
- **Admin system:** `users.is_admin` flag; admin review flow for uploaded questions.
- **Bank mode:** Three modes (public/personal/mixed) controlling question visibility per user.
- **DB auto-backup:** Before destructive operations (clear, rebuild), SQLite database is backed up.

## Configuration

Backend env vars (in `backend/.env`, see `.env.example`):
- `OPENAI_API_KEY`, `OPENAI_BASE_URL` — LLM API connection
- `LLM_MODEL_NAME`, `EMBEDDING_MODEL_NAME` — Model selection
- `JWT_SECRET` — JWT signing key (auto-generated if not set)

Production: nginx at `/etc/nginx/conf.d/interview-boss.conf` reverse-proxies `/api/` to uvicorn on port 8000 with 180s timeout; serves frontend static files from `/var/www/interview-boss/dist/`.

## Language

The application UI, prompts, and documentation are in Chinese (Simplified). Code identifiers, comments, and commit messages mix Chinese and English.
