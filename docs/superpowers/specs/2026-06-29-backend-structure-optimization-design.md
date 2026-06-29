# Backend Structure Optimization Design

**Date**: 2026-06-29
**Status**: Revised draft, pending implementation plan
**Scope**: Phase 1 only: thin `backend/app/routers/submit.py` with zero endpoint behavior change.

## Background

The backend has several oversized files that hurt maintainability:

| File | Current lines | Problem |
|------|---------------|---------|
| `backend/app/agents/chat/pipeline.py` | 2077 | ReAct loop, answer generation, summary, metadata, and repetition protection live in one file. |
| `backend/app/db/migrations.py` | 1760 | 38 defined migration functions plus one disabled migration in a single file. |
| `backend/app/services/clustering.py` | 1254 | Public clustering entry points, prompt constants, LLM validation, and helpers are tightly coupled. |
| `backend/app/routers/submit.py` | 952 | Router layer contains tagging, answer generation, master-bank update, and endpoint orchestration logic. |
| `backend/app/services/pipeline/batch.py` | 933 | Incremental clustering and singleton compaction share one module. |

The broad structural cleanup is valid, but doing all of it in one implementation pass is too risky. Phase 1 narrows the work to `submit.py`, because it has the clearest router-layer violation and can be improved while preserving every API endpoint and import path.

## Phase 1 Goal

Move submit-related business logic out of `backend/app/routers/submit.py` into a service module while keeping all existing HTTP endpoints, function signatures, import paths, and SSE behavior intact.

Phase 1 is not an endpoint cleanup. The legacy `/api/submit` and `/api/submit-stream` endpoints stay available as compatibility wrappers. Removing them is a future phase after explicit caller and access-log verification.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Phase 1 target | `routers/submit.py` only | Highest architectural value with the smallest blast radius. |
| Behavior policy | Zero endpoint behavior change | Refactor should be deployable without frontend or external-client changes. |
| Backward compatibility | Keep old router exports as wrappers | Existing tests and production code patch/import `app.routers.submit.*`. |
| New business module | `backend/app/services/submit_service.py` | Matches existing router -> service boundary in `backend/CLAUDE.md`. |
| Legacy submit endpoints | Keep `/api/submit` and `/api/submit-stream` | Deletion conflicts with zero behavior change and must be a separate decision. |
| Production import migration | Defer to Phase 2 | Moving imports now breaks monkeypatch paths and makes the refactor harder to verify. |
| Other large-file splits | Defer to separate specs | Migrations, clustering, batch, and chat pipeline have different risks and test strategies. |

## Current Submit Surface

`backend/app/routers/submit.py` currently exposes:

| Surface | Keep in Phase 1 | Notes |
|---------|-----------------|-------|
| `POST /api/submit` -> `submit_data()` | Yes | Legacy JSON endpoint; keep as compatibility wrapper. |
| `POST /api/submit-stream` -> `submit_data_stream()` | Yes | Legacy SSE endpoint; keep as compatibility wrapper. |
| `POST /api/submit-stream-v2` -> `submit_data_stream_v2()` | Yes | Frontend primary path. |
| `POST /api/submit-jobs` -> `create_submit_job()` | Yes | Frontend async submit job path. |
| `GET /api/submit-jobs/active` -> `get_active_submit_jobs()` | Yes | Frontend active-job recovery path. |
| `tag_questions_batch()` | Yes, wrapper | Existing tests and modules import this from `app.routers.submit`. |
| `background_generate_answer()` | Yes, wrapper | Existing worker/interview imports use this path. |
| `incremental_update_master_bank()` | Yes, wrapper | Existing endpoint code depends on this symbol. |

## Target Structure

```text
backend/app/
├── routers/
│   └── submit.py              # HTTP endpoints, auth, request validation, SSE/event wrapping
└── services/
    └── submit_service.py      # tagging, answer generation, master-bank update orchestration
```

`submit.py` remains the compatibility module. It should import the service module and expose thin wrappers:

```python
from app.services import submit_service as _submit_service


async def tag_questions_batch(*args, **kwargs):
    return await _submit_service.tag_questions_batch(*args, **kwargs)


async def background_generate_answer(*args, **kwargs):
    return await _submit_service.background_generate_answer(*args, **kwargs)


async def incremental_update_master_bank(*args, **kwargs):
    return await _submit_service.incremental_update_master_bank(*args, **kwargs)
```

Endpoint functions in `submit.py` should call these wrapper names, not the private service object directly, so existing monkeypatch paths such as `app.routers.submit.tag_questions_batch` still work.

## Service Responsibilities

`backend/app/services/submit_service.py` owns:

- `tag_questions_batch(url, company, round_, questions, taxonomy_config=None, user_id=None)`
- `background_generate_answer(question_id, question_text, user_id=None)`
- `incremental_update_master_bank(new_tagged_rows, bg_tasks, submitter_is_admin=True, user_id=None, is_personal=False, interview_id=None, job_position=None)`

The service may import lower-level dependencies:

- `app.services.llm`
- `app.services.pipeline`
- `app.services.clustering`
- `app.db.operations`
- `app.db.queries`
- `app.core.prompts`

The service must not import FastAPI router objects or request/response classes. `BackgroundTasks` is allowed only as a passed-in scheduling interface because the current public function signature already uses it.

## Router Responsibilities

`backend/app/routers/submit.py` owns:

- FastAPI route decorators and dependency injection.
- Auth and user context extraction.
- Form/file parsing and input validation.
- SSE event formatting for the legacy and v2 streaming endpoints.
- Compatibility wrappers for old import paths.
- Job endpoint request handling.

The router should not contain LLM prompt construction, DB update orchestration, clustering trigger logic, or answer-generation implementation details.

## Compatibility Rules

Phase 1 must preserve these contracts:

1. No endpoint is removed.
2. No endpoint path, method, status-code shape, or SSE event name changes.
3. Existing imports from `app.routers.submit` remain callable.
4. Existing tests that patch `app.routers.submit.tag_questions_batch` continue to patch the call path used by submit endpoints and submit agents.
5. Frontend calls remain unchanged:
   - `frontend/src/services/dataApi.js` uses `/api/submit-stream-v2`.
   - `frontend/src/services/dataApi.js` uses `/api/submit-jobs`.
   - `frontend/src/services/dataApi.js` uses `/api/submit-jobs/active`.
6. Text plus image/file combined uploads remain supported. Do not make input sources mutually exclusive.

## Implementation Order

| Step | Task | Risk | Verification |
|------|------|------|--------------|
| 0 | Ensure unrelated test migration work is committed or intentionally left untouched | Medium | `git status --short` shows only known unrelated files plus this spec before code changes. |
| 1 | Add/confirm characterization tests for submit exports and endpoints | Low | `backend/tests/services/test_router_refactor.py` and submit-related tests identify current behavior. |
| 2 | Create `services/submit_service.py` and move pure business functions | Medium | Old `app.routers.submit.*` imports still resolve and delegate. |
| 3 | Thin `submit.py` endpoint bodies without changing endpoint behavior | Medium | Submit pipeline tests and router-refactor tests pass. |
| 4 | Run backend gate and document remaining large-file follow-up specs | Low | `./deploy/docker-deploy.sh check backend` passes. |

## Verification

Targeted verification:

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/test_router_refactor.py -q
docker compose --profile test run --rm test uv run pytest backend/tests/pipeline/ -q
docker compose --profile test run --rm test uv run python -m compileall -q backend/app
./deploy/docker-deploy.sh check backend
```

Full verification after the separate test-directory migration is clean:

```bash
./deploy/docker-deploy.sh test -q
```

## Acceptance Criteria

- `backend/app/routers/submit.py` is primarily HTTP orchestration and compatibility wrappers.
- `backend/app/services/submit_service.py` contains submit business logic.
- `/api/submit`, `/api/submit-stream`, `/api/submit-stream-v2`, `/api/submit-jobs`, and `/api/submit-jobs/active` still exist.
- `from app.routers.submit import tag_questions_batch` still works.
- `from app.routers.submit import background_generate_answer` still works.
- Existing frontend API code does not change.
- Docker backend daily gate passes after code changes.

## Explicitly Out of Scope for Phase 1

- Deleting `/api/submit` or `/api/submit-stream`.
- Updating frontend submit APIs.
- Moving existing production imports away from `app.routers.submit`.
- Splitting `backend/app/agents/chat/pipeline.py`.
- Splitting `backend/app/services/clustering.py`.
- Splitting `backend/app/services/pipeline/batch.py`.
- Splitting `backend/app/db/migrations.py`.
- Changing DB schema, migration behavior, or migration order.
- Changing chat agent behavior, question planning, ReAct tool behavior, or interview summary behavior.
- Changing test directory layout. That work is currently being handled separately.

## Follow-Up Specs

The earlier broad design is preserved as a roadmap, but each item needs its own spec and implementation plan.

| Future spec | Scope | Important constraints |
|-------------|-------|-----------------------|
| Pipeline batch/compact split | Split `services/pipeline/batch.py` into incremental clustering and singleton compaction modules. | Preserve `app.services.pipeline` exports and worker imports. |
| Clustering package split | Split `services/clustering.py` into matcher, clusterer, full-recluster, and prompt modules. | Decide whether tests keep patching `app.services.clustering.*` or move to new module paths. |
| Chat pipeline modularization | Split `agents/chat/pipeline.py` into ReAct loop, answer, question plan, summary, and metadata modules. | Existing tests heavily patch `app.agents.chat.pipeline.*`; compatibility shim strategy must be explicit. |
| Migration package split | Split `db/migrations.py` into migration domain files. | Preserve `_MIGRATIONS` order exactly. Migration 020 is currently disabled; migration 021 is active. Migration 008 must appear once only. Verify empty DB, upgraded DB, and idempotent re-run. |

## Migration Split Notes for Future Spec

The previous version of this document contained a migration grouping draft with two issues:

- Migration `008` was listed in both `question_bank.py` and `view.py`; it should only appear once.
- Migration `020` is defined but disabled in `_MIGRATIONS`; it must not be accidentally enabled during a physical split.

Any future migration split must start from the current `_MIGRATIONS` list in `backend/app/db/migrations.py`, not from a hand-written grouping table.

## References

- `backend/CLAUDE.md`
- `backend/tests/services/test_router_refactor.py`
- `frontend/src/services/dataApi.js`
- `backend/app/routers/submit.py`
