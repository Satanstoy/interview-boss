# Backend Structure Optimization Design

**Date**: 2026-06-29
**Status**: Approved for implementation
**Scope**: Phase 1 (physical split, zero behavior change) of a two-phase refactor

## Background

The backend has several oversized files that hurt maintainability:

| File | Lines | Problem |
|------|-------|---------|
| `agents/chat/pipeline.py` | 2077 | 50+ functions covering 7 distinct responsibilities |
| `db/migrations.py` | 1760 | 38 migration functions in a single file |
| `services/clustering.py` | 1254 | 6 public entry points + 3 prompt constants + 15 helpers |
| `routers/submit.py` | 952 | Business logic in router layer, 3 versions of same endpoint |
| `services/pipeline/batch.py` | 933 | Two distinct subsystems (incremental clustering + compaction) |

Additionally, `submit.py` has v1 and v1_sse endpoints that are no longer used by the frontend (which already uses v2), creating ~500 lines of dead code duplication.

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Refactor approach | Two-phase (physical split first, architecture fix later) | Lower risk, each step independently verifiable |
| Backward compatibility | `__init__.py` re-exports all public symbols | Zero import path changes for consumers |
| submit.py versions | Keep only v2 (LangGraph) | Frontend already uses `/api/submit-stream-v2` |
| batch.py split | Split into batch.py + compact.py | Two conceptually distinct subsystems |
| clustering.py split | 4 files by responsibility | Each file has a clear single purpose |
| migrations.py split | 9 files by functional domain | Groups related migrations together |
| pipeline.py split | 5 files by responsibility | Balances granularity with file count |

## Target Directory Structure

```
app/
├── agents/chat/
│   ├── pipeline.py          ← ~300 lines (orchestration entry)
│   ├── react_loop.py        ← ~500 lines (ReAct core)
│   ├── answer.py            ← ~400 lines (answer generation + dedup)
│   ├── question_plan.py     ← ~300 lines (question plan + repetition)
│   ├── summary.py           ← ~200 lines (end interview + summary)
│   └── metadata.py          ← ~250 lines (basis tracking + metadata)
│
├── services/
│   ├── clustering/
│   │   ├── __init__.py      ← re-exports all public symbols
│   │   ├── matcher.py       ← ~400 lines (incremental matching)
│   │   ├── clusterer.py     ← ~400 lines (new question clustering)
│   │   ├── full_recluster.py← ~200 lines (full rebuild)
│   │   └── prompts.py       ← ~80 lines (prompt constants)
│   │
│   ├── submit_service.py    ← ~300 lines (business logic from submit.py)
│   │
│   └── pipeline/
│       ├── batch.py         ← ~400 lines (incremental clustering pipeline)
│       └── compact.py       ← ~530 lines (singleton compaction)
│
├── db/
│   ├── migrations/
│   │   ├── __init__.py      ← run_migrations() + _MIGRATIONS list
│   │   ├── question_bank.py ← migrations 001/002/004/005/006/007/008
│   │   ├── auth.py          ← migrations 003/010/012/015
│   │   ├── data_repair.py   ← migrations 011/014/017/018/019/020
│   │   ├── sources.py       ← migrations 016/023
│   │   ├── chat.py          ← migrations 024/025/026/027/028/037/038
│   │   ├── coding.py        ← migrations 029/030/031
│   │   ├── clustering.py    ← migrations 032/033/034/035
│   │   ├── jobs.py          ← migrations 009/022/036
│   │   └── view.py          ← migrations 008/013
│   │
│   ├── operations.py        ← unchanged
│   ├── queries.py           ← unchanged
│   └── connection.py        ← unchanged
│
└── routers/
    └── submit.py            ← ~150 lines (thin router, v2 only)
```

---

## 1. pipeline.py Split (2077 → 5 files + entry)

### pipeline.py (entry, ~300 lines)

Functions:
- `run_chat()` — sole public entry point
- `_initial_state()` — state factory
- `_step_load_context()` — context loading step
- `_step_classify()` — intent classification step
- `_step_extract_memory()` — background memory extraction
- `_persist_active_skills()` — skill persistence
- Constants: `_SENTINEL`, `_FRIENDLY_ERROR`

Imports from: `react_loop`, `answer`, `summary`, `metadata` (internal)

### react_loop.py (ReAct core, ~500 lines)

Functions:
- `_react_loop()` — main autonomous tool-calling loop
- `Budget` (dataclass) / `StopRun` (exception) — budget and termination
- `validate_tool_call()` — tool call validation
- `_log_react_llm_step()` / `_log_react_tool_call()` — trace logging
- `_summarize_tool_output()` / `_sanitize_tool_args()` — tool output processing
- `_emit()` / `_step()` — SSE event emission
- `_trace_safe_value()` / `_basis_event_payload()` — tracing helpers
- Constants: `MAX_REACT_STEPS`, `REACT_BUDGET`, `STEP_REASONS`, `_ALLOWED_TOOL_NAMES`, `_INTERNAL_REACT_MARKERS`, `_SAFE_TOOL_ARG_KEYS`, `_TRACE_STRING_LIMIT`, `_TRACE_LIST_LIMIT`

### answer.py (answer generation, ~400 lines)

Functions:
- `OutputDeduplicator` (class) — two-level dedup (hash + Jaccard)
- `_stream_final_answer()` — streaming final answer with dedup
- `_final_answer_events_from_text()` — direct-answer path
- `_regenerate_after_dup()` — regenerate on duplicate
- `_enforce_question_plan_on_text()` — plan adherence check
- `_ensure_final_answer_quality()` — quality guard
- `_fallback_react_answer()` / `_fallback_interviewer_response()` — degradation
- `_fallback_coding_question()` — coding question fallback
- `_is_internal_react_marker()` / `_normalize_react_marker()` — marker detection
- `_looks_like_candidate_question()` / `_last_assistant_message()` — helpers

### question_plan.py (question plan + repetition, ~300 lines)

Functions:
- `_should_create_question_plan()` — gate check
- `_select_question_for_plan()` — candidate selection
- `_maybe_create_question_plan()` — plan creation orchestrator
- `_candidate_contains_negative_term()` — negative filter
- `_is_algorithm_candidate()` — algorithm detection
- `_allowed_focus_from_question()` — focus extraction
- `_build_previously_asked_section()` — asked-questions list builder
- `_count_consecutive_similar_questions()` — streak counter
- `_build_repetition_protection_note()` — anti-repetition injection
- `_tokenize_for_overlap()` / `_normalize_question_text()` — text utilities

### summary.py (end interview + summary, ~200 lines)

Functions:
- `InterviewSummary` (Pydantic model) — structured summary schema
- `_generate_structured_summary()` — LLM-based summary generation
- `_build_interview_transcript()` — transcript extraction
- `_render_interview_summary_markdown()` — markdown rendering
- `_forced_closing_response()` — hard-stop overlong interviews
- `_generate_end_interview_response()` — explicit end_interview handler
- `_sanitize_error_message()` — user-friendly error messages

### metadata.py (basis tracking + metadata, ~250 lines)

Functions:
- `_build_react_metadata()` — build done-event metadata (172 lines, the largest function)
- `_infer_selected_question()` — infer which question was asked
- `_public_question()` — sanitize question for public API
- `_extract_company()` / `_extract_round()` — metadata extraction

### Backward Compatibility

`pipeline.py` re-exports all symbols imported by tests:
```python
from .react_loop import _react_loop, MAX_REACT_STEPS, Budget, StopRun, validate_tool_call, _emit, _step, ...
from .answer import OutputDeduplicator, _stream_final_answer, _final_answer_events_from_text, ...
from .question_plan import _should_create_question_plan, _select_question_for_plan, _maybe_create_question_plan, ...
from .summary import _forced_closing_response, _generate_end_interview_response, ...
from .metadata import _build_react_metadata, _infer_selected_question, ...
```

---

## 2. clustering.py Split (1254 → 4 files + __init__.py)

### matcher.py (incremental matching, ~400 lines)

Public functions:
- `process_incremental_batch()` — incremental clustering entry point
- `match_new_questions()` — lightweight matching for personal bank
- `scan_personal_duplicates()` — post-approval reverse scan
- `generate_unified_question()` — unified question text generation
- `calculate_dynamic_recent_days()` — dynamic days calculation

Private helpers:
- `_match_and_cluster_cat2()` — per-cat2 processing core
- `_extract_id()`, `_normalize_question_text()`, `_safe_confidence()`
- `_build_matched_item()`, `_apply_exact_candidate_matches()`
- `_extract_raw_matches()`, `_partition_matches_by_risk()`
- `_validate_merges()`, `_load_recent_singletons()`
- `_format_existing_clusters()`, `_format_new_questions()`

### clusterer.py (clustering engine, ~400 lines)

Public functions:
- `_cluster_unmatched()` — new question clustering (imported by batch.py)
- `cluster_three_stage_v2()` — three-stage clustering (exact + FAISS + LLM)

Private helpers:
- `_union_find()`, `_union_merge()` — union-find data structure

### full_recluster.py (full rebuild, ~200 lines)

Public functions:
- `full_recluster_hybrid()` — full database reclustering

### prompts.py (prompt constants, ~80 lines)

Constants:
- `MATCH_EXISTING_PROMPT`
- `CLUSTER_NEW_PROMPT`
- `VALIDATE_MERGES_PROMPT`
- `VALIDATION_CONFIDENCE_THRESHOLD`
- `DIRECT_ACCEPT_CONFIDENCE_THRESHOLD`

### Internal Dependencies

`matcher.py` calls `_cluster_unmatched` from `clusterer.py` for unmatched questions after incremental matching. This is the only cross-file dependency within the clustering package.

### Backward Compatibility

`services/clustering/__init__.py` re-exports everything:
```python
from .matcher import (
    process_incremental_batch, match_new_questions,
    scan_personal_duplicates, generate_unified_question,
    calculate_dynamic_recent_days,
    _validate_merges, _extract_id, _format_existing_clusters,
    _format_new_questions,
)
from .clusterer import _cluster_unmatched, cluster_three_stage_v2
from .full_recluster import full_recluster_hybrid
from .prompts import (
    MATCH_EXISTING_PROMPT, CLUSTER_NEW_PROMPT, VALIDATE_MERGES_PROMPT,
    VALIDATION_CONFIDENCE_THRESHOLD, DIRECT_ACCEPT_CONFIDENCE_THRESHOLD,
)
```

---

## 3. submit.py Refactor (952 → ~150 lines thin router)

### Functions to move to services/submit_service.py

- `tag_questions_batch()` — LLM tagging logic (imported by pipeline/writer.py, routers/data.py, agents/submit/classify.py)
- `background_generate_answer()` — background answer generation (imported by worker.py, routers/interview.py)
- `incremental_update_master_bank()` — incremental update orchestration

### Functions to delete

- `submit_data()` — v1 JSON endpoint (no production callers, only test imports)
- `submit_data_stream()` — v1 SSE endpoint (frontend uses v2)

### Functions to keep in router

- `submit_data_stream_v2()` — LangGraph SSE endpoint (thin, delegates to agent graph)
- `create_submit_job()` — async job creation
- `get_active_submit_jobs()` — query endpoint
- `_get_current_position_for_user()` — helper

### Import Path Updates

Production code that imports from `submit.py`:
- `app/worker.py`: `from app.routers.submit import background_generate_answer` → `from app.services.submit_service import background_generate_answer`
- `app/routers/interview.py`: same change
- `app/services/pipeline/writer.py`: `from app.routers.submit import tag_questions_batch` → `from app.services.submit_service import tag_questions_batch`
- `app/routers/data.py`: same change
- `app/agents/submit/classify.py`: same change

---

## 4. batch.py Split (933 → ~400 + ~530)

### batch.py (incremental clustering pipeline, ~400 lines)

Functions:
- `cluster_batch()` — core pipeline
- `process_interview_tag_then_maybe_cluster()` — full pipeline
- `force_cluster_all_pending()` — admin function
- Helpers: `_run_db`, `_compute_merge_confidence`, `_safe_json_list`, `_append_unique_text`, `_ensure_original_source_entry`, `_canonicalize_originals`, `_load_existing_clusters_by_cat2`

### compact.py (singleton compaction, ~530 lines)

Functions:
- `compact_singletons_in_db()` — compaction entry point
- `_match_singletons_to_existing()` — LLM matching
- `_do_merge_to_existing()` — merge execution
- Helpers: `_record_merge_history`, `_snapshot_question`, `_load_existing_clusters_for_compact`

### Backward Compatibility

`services/pipeline/__init__.py` re-exports `compact_singletons_in_db` and other public symbols from `compact.py`.

---

## 5. migrations.py Split (1760 → 9 domain files + __init__.py)

### Domain Grouping

| File | Migrations | Lines (est) |
|------|-----------|-------------|
| question_bank.py | 001/002/004/005/006/007/008 | ~400 |
| auth.py | 003/010/012/015 | ~200 |
| data_repair.py | 011/014/017/018/019/020 | ~400 |
| sources.py | 016/023 | ~150 |
| chat.py | 024/025/026/027/028/037/038 | ~350 |
| coding.py | 029/030/031 | ~200 |
| clustering.py | 032/033/034/035 | ~200 |
| jobs.py | 009/022/036 | ~100 |
| view.py | 008/013 | ~100 |

### __init__.py Structure

```python
from .question_bank import _migration_001_base_tables, _migration_002_question_bank, ...
from .auth import _migration_003_auth_tables, ...
# ... all domain files

_MIGRATIONS = [
    (1, "base_tables", _migration_001_base_tables),
    (2, "question_bank", _migration_002_question_bank),
    # ... all 38 migrations
]

def run_migrations(conn):
    # unchanged logic
```

### Special Case

`_classify_e_question` helper (used only by `_migration_035_split_e_category`) moves to `clustering.py` alongside its migration.

---

## Implementation Order

| Step | Task | Risk | Verification |
|------|------|------|-------------|
| 1 | Split migrations.py | Very low | `run_migrations()` on empty DB succeeds |
| 2 | Split clustering.py | Low | Clustering tests pass |
| 3 | Split batch.py | Low | Pipeline tests pass |
| 4 | Move submit.py business logic | Low | Submit-related tests pass |
| 5 | Split pipeline.py | Medium | Chat tests pass |
| 6 | Delete submit v1/v1_sse | Medium | Frontend submit flow works |

### Verification per Step

1. Execute the split/migration
2. `docker compose --profile test run --rm test uv run pytest backend/tests/<related>/ -q`
3. `docker compose --profile test run --rm test uv run python -m compileall -q backend/app`
4. Confirm no import errors

### Final Verification

- `./deploy/docker-deploy.sh check backend` — backend daily gate
- `./deploy/docker-deploy.sh test -q` — full test suite

## What We Explicitly Do NOT Change in Phase 1

- **Architecture boundaries** — `db/operations.py → services/utils.py` reverse dependency stays
- **Agent DB access patterns** — agents still access DB directly in some places
- **Skills infrastructure** — two parallel implementations (`agents/shared/skills/` and `agents/chat/skills/`) stay
- **Function signatures** — all public APIs remain identical
- **Test code** — no test file changes needed (import paths preserved via re-exports)

## Phase 2 Preview (Future)

Phase 2 will address architecture boundary violations:
- Move `tag_questions_batch` from router to service layer (already done in Phase 1)
- Fix `db/operations.py → services/utils.py` reverse dependency
- Unify skills infrastructure
- Consider dependency injection for DB access

## References

- Test audit report: `docs/dev-log/2026-06-29-test-audit-report.md`
- Backend CLAUDE.md: `backend/CLAUDE.md`
- Codex conversation analysis: `.plan` file in codex turn-diffs
