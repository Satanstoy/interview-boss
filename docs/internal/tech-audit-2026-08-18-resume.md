# Resume Analysis — Complete Tech Audit — 2026-08-18

**Repo**: interview-boss · **Stack**: Python 3.12 / FastAPI / SQLite · Vue 3 / Vite
**Scope**: resume analysis surface — upload/extract, CRUD, SSE optimization, chat-resume integration, eval adapter
**HEAD**: ef62c310 · **Findings source**: `.tech-audit/work/2026-08-18/findings.tsv` (16 rows; every 🟡 code path was re-read and verified)

## Executive summary

- **Top risk**: the resume text is *two un-synced copies* — `user_resumes.raw_text` and `chat_memories` (`memory_type='resume'`). Deleting/replacing a resume via `/api/profile/resume` never deactivates the chat-memory copy, so the interview agent keeps recalling stale (and deleted) resume PII.
- **Top strength**: isolation is structurally sound (all queries are `user_id`-scoped from auth, no IDOR surface, verified single-tenant-per-user), upload size guard is double-checked (Content-Length + post-read) and regression-tested, and the SSE optimize flow has genuine adversarial coverage (error events, JSON-degrade path).
- **Biggest gap**: the optimize SSE generator lives in the router (LLM orchestration + Persistence + JSON parsing), violating the project's router layer rule, which also makes the test seams import from a router module.

**Health: ⚠️** — no 🔴; 6 🟡; the 🟡s are 1-day-class fixes, none ship-blocking, all defensible to defer briefly.

## Verified runtime state

- `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_resume_service.py backend/tests/services/test_resume_optimize_endpoint.py backend/tests/security/test_upload_size_guard.py -q` → **27 passed, 2 skipped** (15.64s) under Python 3.12.14 / pytest 9.0.3.
- F4044 prior findings already fixed: upload size guard (2026-08-14 audit item 112 → commit efb376bf), resume text extraction switched pypdf→pdfplumber (b282e2cb).

## Findings by dimension

### D1 — Code essentiality — ⚠️ (1 🟡)

- 🟡 `backend/app/routers/profile_pkg/resume.py:106-168` — `optimize_resume_event_stream` is 60+ lines of business logic (LLM prompt assembly, `_extract_json` parsing, two-phase generation, persistence) inside the router. The router's own CLAUDE.md says "禁止业务逻辑". Fix: move the generator to `resume_service` (e.g. `optimize_resume_stream(user, position)`), keeping the route as request parsing + `StreamingResponse`; update the two tests that import the generator from the router module.

### D2 — Docs integrity — ✅

- Compliance docs cover the resume data path (`docs/compliance/privacy-policy.md` row for 简历数据, `account-deletion.md` row for `user_resumes` with ON DELETE CASCADE, `sub-processors.md` §1 LLM providers); plan doc `docs/superpowers/plans/2026-08-05-resume-optimization.md` matches the implemented migration 061 and endpoints. No drift found in sampled claims.
- Note: privacy policy should explicitly state that resume text persists in chat memory (`chat_memories`) after the profile resume is deleted — currently the policy implies deletion removes resume data (see D9 finding).

### D3 — Tests as adversaries — ⚠️ (1 🟡)

- Good baseline: SSE event ordering, error-path (stream raise → error event + no persist), JSON-degrade to [] continuing the flow, size-guard 413-before-service, non-PDF rejection, real Chinese resume fixture with garbling regression.
- 🟡 Gaps: no HTTP-level happy path for upload/delete/get-metadata endpoints (only direct service calls + size-guard tests); no wrong-type `position` (e.g. list) test; no dict-envelope `{"points": [...]}` branch test (only raw list + invalid string); no duplicate-upload / UNIQUE invariant test; no 50k truncation test; no cross-user isolation test for resume endpoints; no stale chat-memory test (would pin the D9 bug).

### D4 — Security posture — ✅

- No secrets in git for this surface; upload validated as real PDF by pdfplumber before storage (ValueError → 400); size guard is Content-Length-first + len-after-read; output rendered through DOMPurify-sanitized markdown; resume text egress to LLM is user's own configured provider and documented in sub-processors. Chat pipeline wraps resume as untrusted context (`wrap_untrusted_context`, safety hint in prompts). No PII in logs found (`llm.py` logs config/retry events, not message bodies).

### D5 — Multi-tenant isolation — ✅

- Every resume query is `WHERE user_id = ?` from the authenticated session; no resume-id-in-URL/body surface to probe; uploading user A cannot address user B's resume. Single copy per user enforced by app logic; DB-side UNIQUE missing (see D9 hardening note).

### D9 — Data model integrity — ⚠️ (1 🟡 + 2 🟢)

- 🟡 `resume_service.py` (`save_resume`/`delete_resume`) + `chat_memory_service.py:200` — stale chat-memory resume copy. Repro trace: upload via ResumeView → `user_resumes` updated, `chat_memories.resume` untouched; delete → same. `agents/chat/nodes.py:189` (`recall_memories`) reads `get_resume_memory` and free_practice mode injects `resume_summary` (old copy) into the prompt; jd_resume mode prefers `resume_summary or state.resume_text` — the stale copy wins. Fix: on `save_resume`/`delete_resume`, also deactivate `memory_type='resume'` rows in `chat_memories` (or make the agent read `user_resumes` as the single source). This is also an erasure-completeness gap (deleted resume PII remains recallable).
- 🟢 No `UNIQUE(user_id)` on `user_resumes`; current delete+insert is a single implicit transaction (race-safe today), but the invariant is app-enforced only — add a UNIQUE index as schema-level guard.
- 🟢 `updated_at` column never written (dead schema weight).

### D10 — Performance & cost — ✅ (1 🟢)

- 🟢 `resume_service.get_resume` selects `raw_text` (up to 50KB) for the metadata endpoint that discards it; add a lean meta query.
- (Cross-ref) pdfplumber parsing is synchronous CPU work inside async handlers — flagged in D14.

### D11 — Legal / compliance — ⚠️

- Compliance docs exist and are current for the resume path. The stale chat-memory copy after resume deletion (D9) is the one compliance-relevant gap: erasure of "简历" is incomplete until `chat_memories` resume rows are deactivated; must be honored by the account-deletion flow too (cascade exists for full account deletion, but item-level resume delete is separate).

### D14 — Correctness & robustness — ⚠️ (3 🟡 + 3 🟢)

- 🟡 `resume.py:42` + `chat.py:706` — synchronous pdfplumber parse blocks the event loop in two async handlers; a 10MB adversarial/scan-heavy PDF stalls all requests. Fix: `await asyncio.to_thread(resume_service.extract_pdf_text, content)` (or `run_db`-style threadpool).
- 🟡 `resume.py:119-129` — text-phase `stream_llm_messages` call omits `max_tokens`; the OpenAI-compatible streaming path in `llm.py` does not inject a default (`kwargs` pass-through), so the provider's server default applies and can silently truncate the optimized resume mid-sentence. Fix: pass `max_tokens=4096` per the project convention.
- 🟢 `resume.py:107-108` — `body: dict` untyped; non-string `position` (number/list/object) raises AttributeError → 500. Fix: Pydantic body `position: str = Field(max_length=100)`.
- 🟢 `resume.py:150-154` — `save_optimization` return value ignored; deleting the resume mid-stream yields `done` "已保存" while nothing was persisted. Fix: check the boolean, yield `error` on False.
- 🟢 `resume.py:38-45` — `points` items not coerced to str; a dict item renders `[object Object]` in the badge list. Fix: `str()` coercion before yielding.
- 🟢 `resume_service.py:38-45` — `except Exception: raise ValueError` swallows the pdfplumber root cause with no log line; log the original exception first.

### D15 — UX & interaction — ⚠️ (1 🟡 + 2 🟢)

- 🟡 `ResumeView.vue` `handleDelete` — destructive action (resume + optimization history irreversibly removed) with no confirmation gate; project convention is ConfirmDialog. Add a confirm step.
- 🟢 Icon-only Trash2 button lacks `aria-label`/AppTooltip (WCAG 4.1.2 per frontend CLAUDE convention).
- 🟢 In-flight optimize SSE is not aborted on component unmount; stream keeps running after navigation. Pass an AbortController via `postSSE` options and abort in `onUnmounted`.
- UX otherwise complete: loading/empty/error states all present; upload→replace→preview→delete loop is reachable; copy/download have fallbacks; model guard pre-checks LLM config.

### D16 — UI & design-system craft — ✅ (1 🟢)

- 🟢 Native `<select>`/`<input type=checkbox>`/`<input type=file>` instead of shadcn Select/Checkbox components — deviates from the design-system mandate; coordinates with the rest of the surface which does use shadcn.

## Triage — proposed milestones (devplan M<N> scheme)

| Finding | Suggested milestone | Effort |
|---|---|---|
| 🟡 D9 stale chat-memory resume | M39-resume-memory-sync | 2-4 h |
| 🟡 D14 event-loop PDF parse | M40-pdf-parse-offload | 30 min |
| 🟡 D14 missing max_tokens | M41-resume-max-tokens | 30 min |
| 🟡 D1 generator in router | M42-resume-service-move | 2-4 h |
| 🟡 D3 adversarial gaps | M43-resume-test-gaps | 4 h |
| 🟡 D15 delete confirmation | M44-resume-delete-confirm | 30 min |
| 🟢 batch (UNIQUE index, meta query, points str(), body pydantic, save_optimization check, a11y, abort-unmount, updated_at) | M45-resume-hardening | 4 h |

## Verdict

**Ship / Hold** — Ship. No 🔴; the 6 🟡 are bounded (resume surface only) and none block a release. The two worth scheduling first: M39 (stale PII recall after delete) and M41 (silent truncation risk on user-configured OpenAI-compatible endpoints).
