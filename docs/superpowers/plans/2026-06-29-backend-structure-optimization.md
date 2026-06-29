# Backend Structure Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split 5 oversized backend files (2077, 1760, 1254, 952, 933 lines) into focused modules with clear responsibilities, while preserving all existing import paths via re-exports.

**Architecture:** Physical split only (Phase 1). Each oversized file is broken into smaller files by responsibility. An `__init__.py` re-exports all public symbols so external consumers see zero import path changes. No behavior changes, no architecture boundary fixes.

**Tech Stack:** Python 3.10, FastAPI, SQLite, LangGraph, pytest

---

## Constraints

- **Zero behavior change** — all functions keep identical signatures and logic
- **Zero import path changes** — `__init__.py` re-exports everything; no consumer code changes except submit.py consumers (Task 4)
- **Test after every task** — each task ends with compilation check + targeted tests
- **One commit per task** — clean bisectability

## File Map (Before → After)

| Before | After |
|--------|-------|
| `db/migrations.py` (1760 lines) | `db/migrations/__init__.py` + 9 domain files |
| `services/clustering.py` (1254 lines) | `services/clustering/__init__.py` + 4 files |
| `services/pipeline/batch.py` (933 lines) | `services/pipeline/batch.py` (~400) + `compact.py` (~530) |
| `routers/submit.py` (952 lines) | `routers/submit.py` (~150) + `services/submit_service.py` (~300) |
| `agents/chat/pipeline.py` (2077 lines) | `agents/chat/pipeline.py` (~300) + 5 new files |

---

## Task 1: Split migrations.py

**Files:**
- Create: `backend/app/db/migrations/__init__.py`
- Create: `backend/app/db/migrations/question_bank.py`
- Create: `backend/app/db/migrations/auth.py`
- Create: `backend/app/db/migrations/data_repair.py`
- Create: `backend/app/db/migrations/sources.py`
- Create: `backend/app/db/migrations/chat.py`
- Create: `backend/app/db/migrations/coding.py`
- Create: `backend/app/db/migrations/clustering.py`
- Create: `backend/app/db/migrations/jobs.py`
- Create: `backend/app/db/migrations/view.py`
- Delete: `backend/app/db/migrations.py` (after all functions moved)

- [ ] **Step 1: Create the migrations package directory**

```bash
mkdir -p backend/app/db/migrations
```

- [ ] **Step 2: Create domain files with migration functions**

For each domain file, copy the corresponding migration functions from `migrations.py`. The function bodies are unchanged — only the file location changes.

**`question_bank.py`** — migrations 001, 002, 004, 005, 006, 007, 008:

```python
"""Migrations: question bank schema evolution."""

import sqlite3


def _migration_001_base_tables(conn: sqlite3.Connection):
    # Lines 16-118 from migrations.py — unchanged body
    ...


def _migration_002_question_bank(conn: sqlite3.Connection):
    # Lines 120-174 from migrations.py — unchanged body
    ...


def _migration_004_jd_interview_qd_columns(conn: sqlite3.Connection):
    # Lines 222-343 from migrations.py — unchanged body
    ...


def _migration_005_question_bank_extra_columns(conn: sqlite3.Connection):
    # Lines 345-412 from migrations.py — unchanged body
    ...


def _migration_006_job_positions(conn: sqlite3.Connection):
    # Lines 414-446 from migrations.py — unchanged body
    ...


def _migration_007_taxonomy(conn: sqlite3.Connection):
    # Lines 448-486 from migrations.py — unchanged body
    ...


def _migration_008_user_question_view(conn: sqlite3.Connection):
    # Lines 488-514 from migrations.py — unchanged body
    ...
```

**`auth.py`** — migrations 003, 010, 012, 015:

```python
"""Migrations: authentication and user management."""

import sqlite3


def _migration_003_auth_tables(conn: sqlite3.Connection):
    # Lines 176-220 from migrations.py
    ...


def _migration_010_users_extra_columns(conn: sqlite3.Connection):
    # Lines 546-574 from migrations.py
    ...


def _migration_012_admin_seed(conn: sqlite3.Connection):
    # Lines 653-709 from migrations.py
    ...


def _migration_015_refresh_tokens_extra(conn: sqlite3.Connection):
    # Lines 911-944 from migrations.py
    ...
```

**`data_repair.py`** — migrations 011, 014, 017, 018, 019, 020:

```python
"""Migrations: data backfills and repairs."""

import sqlite3


def _migration_011_data_backfills(conn: sqlite3.Connection):
    # Lines 576-651 from migrations.py
    ...


def _migration_014_data_repairs(conn: sqlite3.Connection):
    # Lines 737-909 from migrations.py (largest migration, ~175 lines)
    ...


def _migration_017_backfill_normalized_sources(conn: sqlite3.Connection):
    # Lines 989-1050 from migrations.py
    ...


def _migration_018_composite_indexes(conn: sqlite3.Connection):
    # Lines 1052-1055 from migrations.py
    ...


def _migration_019_fix_cascades(conn: sqlite3.Connection):
    # Lines 1057-1086 from migrations.py
    ...


def _migration_020_drop_json_columns(conn: sqlite3.Connection):
    # Lines 1088-1107 from migrations.py (commented out in original)
    ...
```

**`sources.py`** — migrations 016, 023:

```python
"""Migrations: question bank source tracking."""

import sqlite3


def _migration_016_normalized_source_tables(conn: sqlite3.Connection):
    # Lines 946-987 from migrations.py
    ...


def _migration_023_duplicate_of(conn: sqlite3.Connection):
    # Lines 1143-1148 from migrations.py
    ...
```

**`chat.py`** — migrations 024, 025, 026, 027, 028, 037, 038:

```python
"""Migrations: chat and interview conversation tables."""

import sqlite3


def _migration_024_chat_tables(conn: sqlite3.Connection):
    # Lines 1150-1214 from migrations.py
    ...


def _migration_025_question_fts(conn: sqlite3.Connection):
    # Lines 1216-1241 from migrations.py
    ...


def _migration_026_populate_fts(conn: sqlite3.Connection):
    # Lines 1243-1268 from migrations.py
    ...


def _migration_027_memory_summary(conn: sqlite3.Connection):
    # Lines 1270-1283 from migrations.py
    ...


def _migration_028_session_notes(conn: sqlite3.Connection):
    # Lines 1285-1292 from migrations.py
    ...


def _migration_037_conversation_metadata(conn: sqlite3.Connection):
    # Lines 1656-1663 from migrations.py
    ...


def _migration_038_chat_conversation_position(conn: sqlite3.Connection):
    # Lines 1665-1736 from migrations.py
    ...
```

**`coding.py`** — migrations 029, 030, 031:

```python
"""Migrations: coding practice module."""

import sqlite3


def _migration_029_user_resumes(conn: sqlite3.Connection):
    # Lines 1294-1312 from migrations.py
    ...


def _migration_030_coding_module(conn: sqlite3.Connection):
    # Lines 1314-1439 from migrations.py
    ...


def _migration_031_coding_scores(conn: sqlite3.Connection):
    # Lines 1441-1455 from migrations.py
    ...
```

**`clustering.py`** — migrations 032, 033, 034, 035 + helper:

```python
"""Migrations: clustering and embedding columns."""

import sqlite3


def _migration_032_embedding_column(conn: sqlite3.Connection):
    # Lines 1457-1465 from migrations.py
    ...


def _migration_033_cluster_id(conn: sqlite3.Connection):
    # Lines 1467-1481 from migrations.py
    ...


def _migration_034_backfill_confidence(conn: sqlite3.Connection):
    # Lines 1483-1588 from migrations.py
    ...


def _classify_e_question(question_text: str) -> str:
    # Lines 1590-1605 from migrations.py — helper for migration 035
    ...


def _migration_035_split_e_category(conn: sqlite3.Connection):
    # Lines 1607-1639 from migrations.py
    ...
```

**`jobs.py`** — migrations 009, 022, 036:

```python
"""Migrations: background job and queue tables."""

import sqlite3


def _migration_009_analysis_queue(conn: sqlite3.Connection):
    # Lines 516-544 from migrations.py
    ...


def _migration_022_jobs_table(conn: sqlite3.Connection):
    # Lines 1121-1141 from migrations.py
    ...


def _migration_036_job_payloads(conn: sqlite3.Connection):
    # Lines 1641-1654 from migrations.py
    ...
```

**`view.py`** — migrations 008, 013 (note: 008 appears in both question_bank.py and view.py — resolve by keeping it in question_bank.py only):

Actually, migration 008 `user_question_view` is a view/analysis table. Move it here instead of question_bank.py:

```python
"""Migrations: user question view and analysis views."""

import sqlite3


def _migration_008_user_question_view(conn: sqlite3.Connection):
    # Lines 488-514 from migrations.py
    ...


def _migration_013_user_question_view_user_answer(conn: sqlite3.Connection):
    # Lines 711-735 from migrations.py
    ...
```

Updated `question_bank.py` — remove `_migration_008` from it (it goes to `view.py`).

- [ ] **Step 3: Create `__init__.py` with run_migrations and re-exports**

```python
"""Database schema migrations.

Each migration function lives in a domain-specific submodule.
This file re-exports all migration functions for backward compatibility
and contains the run_migrations() execution engine.
"""

import sqlite3
import logging

from .question_bank import (
    _migration_001_base_tables,
    _migration_002_question_bank,
    _migration_004_jd_interview_qd_columns,
    _migration_005_question_bank_extra_columns,
    _migration_006_job_positions,
    _migration_007_taxonomy,
)
from .auth import (
    _migration_003_auth_tables,
    _migration_010_users_extra_columns,
    _migration_012_admin_seed,
    _migration_015_refresh_tokens_extra,
)
from .data_repair import (
    _migration_011_data_backfills,
    _migration_014_data_repairs,
    _migration_017_backfill_normalized_sources,
    _migration_018_composite_indexes,
    _migration_019_fix_cascades,
    _migration_020_drop_json_columns,
)
from .sources import (
    _migration_016_normalized_source_tables,
    _migration_023_duplicate_of,
)
from .view import (
    _migration_008_user_question_view,
    _migration_013_user_question_view_user_answer,
)
from .chat import (
    _migration_024_chat_tables,
    _migration_025_question_fts,
    _migration_026_populate_fts,
    _migration_027_memory_summary,
    _migration_028_session_notes,
    _migration_037_conversation_metadata,
    _migration_038_chat_conversation_position,
)
from .coding import (
    _migration_029_user_resumes,
    _migration_030_coding_module,
    _migration_031_coding_scores,
)
from .clustering import (
    _migration_032_embedding_column,
    _migration_033_cluster_id,
    _migration_034_backfill_confidence,
    _classify_e_question,
    _migration_035_split_e_category,
)
from .jobs import (
    _migration_009_analysis_queue,
    _migration_022_jobs_table,
    _migration_036_job_payloads,
)

logger = logging.getLogger("interview-boss")

_MIGRATIONS = [
    (1, "base_tables", _migration_001_base_tables),
    (2, "question_bank", _migration_002_question_bank),
    (3, "auth_tables", _migration_003_auth_tables),
    (4, "jd_interview_qd_columns", _migration_004_jd_interview_qd_columns),
    (5, "question_bank_extra_columns", _migration_005_question_bank_extra_columns),
    (6, "job_positions", _migration_006_job_positions),
    (7, "taxonomy", _migration_007_taxonomy),
    (8, "user_question_view", _migration_008_user_question_view),
    (9, "analysis_queue", _migration_009_analysis_queue),
    (10, "users_extra_columns", _migration_010_users_extra_columns),
    (11, "data_backfills", _migration_011_data_backfills),
    (12, "admin_seed", _migration_012_admin_seed),
    (13, "user_question_view_user_answer", _migration_013_user_question_view_user_answer),
    (14, "data_repairs", _migration_014_data_repairs),
    (15, "refresh_tokens_extra", _migration_015_refresh_tokens_extra),
    (16, "normalized_source_tables", _migration_016_normalized_source_tables),
    (17, "backfill_normalized_sources", _migration_017_backfill_normalized_sources),
    (18, "composite_indexes", _migration_018_composite_indexes),
    (19, "fix_cascades", _migration_019_fix_cascades),
    # (20, "drop_json_columns", _migration_020_drop_json_columns),  # disabled
    (21, "performance_indexes", _migration_021_performance_indexes),
    (22, "jobs_table", _migration_022_jobs_table),
    (23, "duplicate_of", _migration_023_duplicate_of),
    (24, "chat_tables", _migration_024_chat_tables),
    (25, "question_fts", _migration_025_question_fts),
    (26, "populate_fts", _migration_026_populate_fts),
    (27, "memory_summary", _migration_027_memory_summary),
    (28, "session_notes", _migration_028_session_notes),
    (29, "user_resumes", _migration_029_user_resumes),
    (30, "coding_module", _migration_030_coding_module),
    (31, "coding_scores", _migration_031_coding_scores),
    (32, "embedding_column", _migration_032_embedding_column),
    (33, "cluster_id", _migration_033_cluster_id),
    (34, "backfill_confidence", _migration_034_backfill_confidence),
    (35, "split_e_category", _migration_035_split_e_category),
    (36, "job_payloads", _migration_036_job_payloads),
    (37, "conversation_metadata", _migration_037_conversation_metadata),
    (38, "chat_conversation_position", _migration_038_chat_conversation_position),
]


def run_migrations(conn: sqlite3.Connection):
    """Run all pending schema migrations."""
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    cursor.execute("SELECT version FROM schema_version")
    applied = {row[0] for row in cursor.fetchall()}

    for version, name, migration_fn in _MIGRATIONS:
        if version in applied:
            continue
        logger.info(f"Running migration {version}: {name}")
        try:
            migration_fn(conn)
            cursor.execute(
                "INSERT INTO schema_version (version, name) VALUES (?, ?)",
                (version, name),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception(f"Migration {version} ({name}) failed")
            raise
```

- [ ] **Step 4: Delete the old migrations.py file**

```bash
rm backend/app/db/migrations.py
```

- [ ] **Step 5: Verify compilation**

```bash
docker compose --profile test run --rm test uv run python -m compileall -q backend/app
```

Expected: no output (success).

- [ ] **Step 6: Verify migrations work on empty DB**

```bash
docker compose --profile test run --rm test uv run python -c "
from app.db.migrations import run_migrations, _MIGRATIONS, _migration_033_cluster_id
import sqlite3
conn = sqlite3.connect(':memory:')
run_migrations(conn)
cursor = conn.cursor()
cursor.execute('SELECT count(*) FROM schema_version')
count = cursor.fetchone()[0]
print(f'Applied {count} migrations')
assert count == len([m for m in _MIGRATIONS if m[0] != 20])
print('PASS: all migrations applied successfully')
"
```

Expected: `Applied 37 migrations` and `PASS`.

- [ ] **Step 7: Run targeted tests**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/infra/ -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add backend/app/db/migrations/
git rm backend/app/db/migrations.py
git commit -m "refactor(backend): split migrations.py into domain-specific modules"
```

---

## Task 2: Split clustering.py

**Files:**
- Create: `backend/app/services/clustering/__init__.py`
- Create: `backend/app/services/clustering/matcher.py`
- Create: `backend/app/services/clustering/clusterer.py`
- Create: `backend/app/services/clustering/full_recluster.py`
- Create: `backend/app/services/clustering/prompts.py`
- Delete: `backend/app/services/clustering.py` (after all functions moved)

- [ ] **Step 1: Create the clustering package directory**

```bash
mkdir -p backend/app/services/clustering
```

- [ ] **Step 2: Create `prompts.py` with prompt constants**

```python
"""Clustering prompt constants and thresholds."""

MATCH_EXISTING_PROMPT = """..."""  # Lines 60-99 from clustering.py

CLUSTER_NEW_PROMPT = """..."""  # Lines 101-133 from clustering.py

VALIDATE_MERGES_PROMPT = """..."""  # Lines 135-170 from clustering.py

VALIDATION_CONFIDENCE_THRESHOLD = 0.85
DIRECT_ACCEPT_CONFIDENCE_THRESHOLD = 0.95
```

- [ ] **Step 3: Create `clusterer.py` with clustering engine functions**

```python
"""New question clustering and three-stage clustering engine."""

from __future__ import annotations

import logging
from typing import Dict, List

from app.services.embedding_service import encode_texts, build_index
from app.services.llm import _call_llm_with_retry, _extract_json
from .prompts import CLUSTER_NEW_PROMPT

logger = logging.getLogger("interview-boss")


def _normalize_question_text(text: str) -> str:
    # Lines 30-47 from clustering.py — unchanged
    ...


async def _cluster_unmatched(unmatched_questions: list, user_id=None) -> List[Dict]:
    # Lines 647-754 from clustering.py — unchanged
    # This is the key function imported by pipeline/batch.py
    ...


def _union_find(parent: dict, x):
    # Lines 958-964 from clustering.py — unchanged
    ...


def _union_merge(parent: dict, rank: dict, a, b):
    # Lines 966-976 from clustering.py — unchanged
    ...


async def cluster_three_stage_v2(questions, user_id=None, similarity_threshold=0.60):
    # Lines 978-1180 from clustering.py — unchanged
    ...
```

- [ ] **Step 4: Create `matcher.py` with incremental matching functions**

```python
"""Incremental matching: match new questions to existing clusters."""

from __future__ import annotations

import logging
from typing import Dict, List

from app.services.embedding_service import prefilter_centroids_batch
from app.services.llm import _call_llm_with_retry, _extract_json
from .prompts import (
    MATCH_EXISTING_PROMPT,
    VALIDATE_MERGES_PROMPT,
    VALIDATION_CONFIDENCE_THRESHOLD,
    DIRECT_ACCEPT_CONFIDENCE_THRESHOLD,
)
from .clusterer import _cluster_unmatched, _normalize_question_text

logger = logging.getLogger("interview-boss")

RECENT_DAYS = 30


def _extract_id(raw) -> str:
    # Lines 22-28 from clustering.py
    ...


def _safe_confidence(match: Dict) -> float | None:
    # Lines 49-58 from clustering.py
    ...


async def _validate_merges(matches, new_questions, existing_clusters, user_id):
    # Lines 172-317 from clustering.py
    ...


async def _load_recent_singletons(cat2: str, days: int = RECENT_DAYS) -> List[Dict]:
    # Lines 319-345 from clustering.py
    ...


def calculate_dynamic_recent_days(cat2: str) -> int:
    # Lines 347-384 from clustering.py
    ...


def _build_matched_item(q: Dict, cluster_id: str, cat2: str) -> Dict:
    # Lines 386-399 from clustering.py
    ...


def _apply_exact_candidate_matches(cat2, questions, candidates, unmatched_ids):
    # Lines 401-427 from clustering.py
    ...


def _extract_raw_matches(result: Dict, unmatched_ids: set) -> List[Dict]:
    # Lines 429-444 from clustering.py
    ...


def _partition_matches_by_risk(matches: List[Dict], cat2: str):
    # Lines 446-461 from clustering.py
    ...


async def process_incremental_batch(new_rows, existing_by_cat2, user_id=None, recent_days=RECENT_DAYS):
    # Lines 463-524 from clustering.py — public entry point
    ...


async def _match_and_cluster_cat2(cat2, new_questions, existing_clusters, user_id, recent_days=RECENT_DAYS):
    # Lines 526-645 from clustering.py
    ...


def _format_existing_clusters(clusters):
    # Lines 756-762 from clustering.py
    ...


def _format_new_questions(questions):
    # Lines 764-768 from clustering.py
    ...


async def generate_unified_question(questions, sources_context=None, user_id=None):
    # Lines 770-775 from clustering.py — public entry point
    ...


async def match_new_questions(new_rows, existing_clusters_by_cat2, user_id=None):
    # Lines 777-850 from clustering.py — public entry point
    ...


async def scan_personal_duplicates(public_qb_id, cat2, job_position):
    # Lines 852-905 from clustering.py — public entry point
    ...
```

- [ ] **Step 5: Create `full_recluster.py` with full rebuild function**

```python
"""Full database reclustering."""

from __future__ import annotations

import logging

from app.db.connection import get_db_connection
from .clusterer import cluster_three_stage_v2

logger = logging.getLogger("interview-boss")


async def full_recluster_hybrid(user_id=None, similarity_threshold=0.60):
    # Lines 1182-1254 from clustering.py — unchanged
    ...
```

- [ ] **Step 6: Create `__init__.py` with re-exports**

```python
"""Clustering service — question deduplication via LLM + embedding.

This package splits the original clustering.py into focused modules:
- matcher.py: incremental matching (match_new_questions, process_incremental_batch)
- clusterer.py: clustering engine (_cluster_unmatched, cluster_three_stage_v2)
- full_recluster.py: full database rebuild (full_recluster_hybrid)
- prompts.py: prompt constants and thresholds
"""

from .matcher import (
    process_incremental_batch,
    match_new_questions,
    scan_personal_duplicates,
    generate_unified_question,
    calculate_dynamic_recent_days,
    _validate_merges,
    _extract_id,
    _format_existing_clusters,
    _format_new_questions,
    _match_and_cluster_cat2,
    _load_recent_singletons,
    _extract_raw_matches,
    _partition_matches_by_risk,
    _build_matched_item,
    _apply_exact_candidate_matches,
    _safe_confidence,
)
from .clusterer import (
    _cluster_unmatched,
    cluster_three_stage_v2,
    _normalize_question_text,
    _union_find,
    _union_merge,
)
from .full_recluster import full_recluster_hybrid
from .prompts import (
    MATCH_EXISTING_PROMPT,
    CLUSTER_NEW_PROMPT,
    VALIDATE_MERGES_PROMPT,
    VALIDATION_CONFIDENCE_THRESHOLD,
    DIRECT_ACCEPT_CONFIDENCE_THRESHOLD,
)

__all__ = [
    # Public entry points
    "process_incremental_batch",
    "match_new_questions",
    "scan_personal_duplicates",
    "generate_unified_question",
    "full_recluster_hybrid",
    "cluster_three_stage_v2",
    "calculate_dynamic_recent_days",
    # Imported by pipeline/batch.py
    "_cluster_unmatched",
    "_validate_merges",
    "_extract_id",
    "_format_existing_clusters",
    "_format_new_questions",
    # Prompts and thresholds
    "MATCH_EXISTING_PROMPT",
    "CLUSTER_NEW_PROMPT",
    "VALIDATE_MERGES_PROMPT",
    "VALIDATION_CONFIDENCE_THRESHOLD",
    "DIRECT_ACCEPT_CONFIDENCE_THRESHOLD",
]
```

- [ ] **Step 7: Delete the old clustering.py file**

```bash
rm backend/app/services/clustering.py
```

- [ ] **Step 8: Verify compilation**

```bash
docker compose --profile test run --rm test uv run python -m compileall -q backend/app
```

Expected: no output (success).

- [ ] **Step 9: Run clustering tests**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/services/clustering/ -q
```

Expected: all tests pass.

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/clustering/
git rm backend/app/services/clustering.py
git commit -m "refactor(backend): split clustering.py into matcher/clusterer/full_recluster/prompts"
```

---

## Task 3: Split batch.py

**Files:**
- Create: `backend/app/services/pipeline/compact.py`
- Modify: `backend/app/services/pipeline/batch.py` (remove compaction functions)
- Modify: `backend/app/services/pipeline/__init__.py` (add compact re-exports)

- [ ] **Step 1: Create `compact.py` with compaction subsystem**

```python
"""Singleton compaction: merge frequency=1 questions into existing clusters."""

from __future__ import annotations

import logging
from typing import Dict, List

from app.db.connection import get_db_connection
from app.services.clustering import (
    _cluster_unmatched,
    _validate_merges,
    MATCH_EXISTING_PROMPT,
)
from app.services.llm import _call_llm_with_retry, _extract_json

logger = logging.getLogger("interview-boss")


def _run_db(fn, *args, **kwargs):
    # Lines 27-31 from batch.py — unchanged
    ...


def _compute_merge_confidence(text_a: str, text_b: str) -> float:
    # Lines 33-62 from batch.py — unchanged
    ...


def _record_merge_history(conn, survivor_id, merged_id, confidence, reason):
    # Lines 140-186 from batch.py — unchanged
    ...


def _snapshot_question(conn, question_id):
    # Lines 188-203 from batch.py — unchanged
    ...


def _load_existing_clusters_for_compact(cat2: str):
    # Lines 419-436 from batch.py — unchanged
    ...


async def _do_merge_to_existing(survivor_id, merged_id, confidence, user_id=None):
    # Lines 438-548 from batch.py — unchanged
    ...


async def _match_singletons_to_existing(singletons_by_cat2, user_id=None):
    # Lines 550-727 from batch.py — unchanged
    ...


async def compact_singletons_in_db(user_id=None, dry_run=False):
    # Lines 729-933 from batch.py — unchanged (public entry point)
    ...
```

- [ ] **Step 2: Remove compaction functions from batch.py**

Remove these functions from `batch.py` (they now live in `compact.py`):
- `_compute_merge_confidence` (lines 33-62)
- `_record_merge_history` (lines 140-186)
- `_snapshot_question` (lines 188-203)
- `_load_existing_clusters_for_compact` (lines 419-436)
- `_do_merge_to_existing` (lines 438-548)
- `_match_singletons_to_existing` (lines 550-727)
- `compact_singletons_in_db` (lines 729-933)

Keep in `batch.py`:
- `_run_db` (lines 27-31)
- `_safe_json_list` (lines 64-74)
- `_append_unique_text` (lines 76-82)
- `_ensure_original_source_entry` (lines 84-105)
- `_canonicalize_originals` (lines 107-138)
- `_load_existing_clusters_by_cat2` (lines 205-237)
- `cluster_batch` (lines 239-335)
- `process_interview_tag_then_maybe_cluster` (lines 337-372)
- `force_cluster_all_pending` (lines 374-417)

- [ ] **Step 3: Update `pipeline/__init__.py` to re-export compact symbols**

```python
"""Pipeline package — clustering batch processing and compaction."""

from .batch import (
    cluster_batch,
    process_interview_tag_then_maybe_cluster,
    force_cluster_all_pending,
    enqueue_questions,  # if this exists
    dequeue_batch,      # if this exists
)
from .compact import compact_singletons_in_db

__all__ = [
    "cluster_batch",
    "process_interview_tag_then_maybe_cluster",
    "force_cluster_all_pending",
    "compact_singletons_in_db",
]
```

- [ ] **Step 4: Verify compilation**

```bash
docker compose --profile test run --rm test uv run python -m compileall -q backend/app
```

Expected: no output (success).

- [ ] **Step 5: Run pipeline tests**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/pipeline/ -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/pipeline/
git commit -m "refactor(backend): split batch.py compaction into pipeline/compact.py"
```

---

## Task 4: Move submit.py business logic to services

**Files:**
- Create: `backend/app/services/submit_service.py`
- Modify: `backend/app/routers/submit.py` (remove moved functions)
- Modify: `backend/app/worker.py` (update import)
- Modify: `backend/app/routers/interview.py` (update import)
- Modify: `backend/app/services/pipeline/writer.py` (update import)
- Modify: `backend/app/routers/data.py` (update import)
- Modify: `backend/app/agents/submit/classify.py` (update import)

- [ ] **Step 1: Create `services/submit_service.py`**

```python
"""Submit service — business logic for JD/interview submission."""

from __future__ import annotations

import logging
from typing import List

from app.services.llm import _call_llm_with_retry
from app.core.prompts import TAGGING_PROMPT
from app.services.pipeline import enqueue_questions, cluster_batch

logger = logging.getLogger("interview-boss")


def _get_current_position_for_user(user_id: int) -> str:
    # Lines 34-38 from routers/submit.py — unchanged
    ...


async def background_generate_answer(question_id: int, question_text: str, user_id: int = None):
    # Lines 40-66 from routers/submit.py — unchanged
    # This function is imported by worker.py and routers/interview.py
    ...


async def tag_questions_batch(url: str, company: str, round_: str, questions: List[str],
                              taxonomy_config: dict = None, user_id: int = None) -> List[List[str]]:
    # Lines 68-120 from routers/submit.py — unchanged
    # This function is imported by pipeline/writer.py, routers/data.py, agents/submit/classify.py
    ...


async def incremental_update_master_bank(new_tagged_rows: list, bg_tasks=None,
                                          submitter_is_admin: bool = True, user_id: int = None,
                                          is_personal: bool = False, interview_id: int = None,
                                          job_position: str = None):
    # Lines 122-167 from routers/submit.py — unchanged
    ...
```

- [ ] **Step 2: Update consumers to import from submit_service**

**`backend/app/worker.py`** — change:
```python
# Before:
from app.routers.submit import background_generate_answer

# After:
from app.services.submit_service import background_generate_answer
```

**`backend/app/routers/interview.py`** — change:
```python
# Before:
from app.routers.submit import background_generate_answer

# After:
from app.services.submit_service import background_generate_answer
```

**`backend/app/services/pipeline/writer.py`** — change:
```python
# Before:
from app.routers.submit import tag_questions_batch

# After:
from app.services.submit_service import tag_questions_batch
```

**`backend/app/routers/data.py`** — change:
```python
# Before:
from app.routers.submit import tag_questions_batch

# After:
from app.services.submit_service import tag_questions_batch
```

**`backend/app/agents/submit/classify.py`** — change:
```python
# Before:
from app.routers.submit import tag_questions_batch

# After:
from app.services.submit_service import tag_questions_batch
```

- [ ] **Step 3: Remove moved functions from `routers/submit.py`**

Remove these functions from `submit.py`:
- `_get_current_position_for_user` (lines 34-38)
- `background_generate_answer` (lines 40-66)
- `tag_questions_batch` (lines 68-120)
- `incremental_update_master_bank` (lines 122-167)

Add import at top of `submit.py`:
```python
from app.services.submit_service import (
    tag_questions_batch,
    incremental_update_master_bank,
    background_generate_answer,
)
```

- [ ] **Step 4: Verify compilation**

```bash
docker compose --profile test run --rm test uv run python -m compileall -q backend/app
```

Expected: no output (success).

- [ ] **Step 5: Run submit-related tests**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/pipeline/ backend/tests/services/ -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/submit_service.py backend/app/routers/submit.py \
       backend/app/worker.py backend/app/routers/interview.py \
       backend/app/services/pipeline/writer.py backend/app/routers/data.py \
       backend/app/agents/submit/classify.py
git commit -m "refactor(backend): move submit business logic to services/submit_service.py"
```

---

## Task 5: Split pipeline.py

**Files:**
- Create: `backend/app/agents/chat/react_loop.py`
- Create: `backend/app/agents/chat/answer.py`
- Create: `backend/app/agents/chat/question_plan.py`
- Create: `backend/app/agents/chat/summary.py`
- Create: `backend/app/agents/chat/metadata.py`
- Modify: `backend/app/agents/chat/pipeline.py` (slim down to entry + re-exports)

- [ ] **Step 1: Create `react_loop.py`**

```python
"""ReAct loop — autonomous tool-calling core."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import AsyncGenerator

from app.agents.chat.tools import ALL_TOOLS, execute_tool, tool_progress_message
from app.agents.chat.nodes import build_react_system_prompt, _build_next_question_plan_prompt
from app.services.llm import llm_with_tools, make_tool_result_message
from app.agents.shared.events import _event_queue_var

logger = logging.getLogger("interview-boss")


# --- Constants ---
MAX_REACT_STEPS = 5

@dataclass
class REACT_BUDGET:
    max_tool_calls: int = 10
    max_seconds: float = 30.0


STEP_REASONS = {
    "max_tool_calls": "reached tool call limit",
    "max_seconds": "time budget exhausted",
    "loop_detected": "repeated tool call pattern",
    "max_steps": "reached max ReAct steps",
    "validation_failure": "tool call validation failed",
}

_ALLOWED_TOOL_NAMES = frozenset({"load_skill", "search_questions", "draw_questions"})
_INTERNAL_REACT_MARKERS = frozenset({
    "load_skill", "search_questions", "draw_questions",
    # plus SKILL_NAMES from tools
})
_SAFE_TOOL_ARG_KEYS = {
    "cat1", "count", "difficulty", "keywords",
    "question_type", "skill_name", "topic",
}
_TRACE_STRING_LIMIT = 120
_TRACE_LIST_LIMIT = 5


# --- Budget and exceptions ---
@dataclass
class Budget:
    tool_calls: int = 0
    start_time: float = 0.0


class StopRun(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


# --- Event helpers ---
def _emit(event: dict) -> None:
    # Lines 289-293 from pipeline.py
    ...


def _step(step: str, message: str, reason: str = "", insight: str = "") -> None:
    # Lines 295-316 from pipeline.py
    ...


# --- Logging ---
def _log_react_llm_step(response_text, tool_calls, step_count, budget):
    # Lines 980-997 from pipeline.py
    ...


def _log_react_tool_call(tool_call, result_preview, step_count):
    # Lines 999-1018 from pipeline.py
    ...


def _summarize_tool_output(tool_name: str, output: str, state) -> dict:
    # Lines 929-978 from pipeline.py
    ...


def _sanitize_tool_args(tool_call: dict) -> dict:
    # Lines 910-927 from pipeline.py
    ...


def _trace_safe_value(value):
    # Lines 894-908 from pipeline.py
    ...


def _basis_event_payload(meta: dict) -> dict:
    # Lines 882-892 from pipeline.py
    ...


# --- Tool validation ---
def validate_tool_call(tool_call: dict) -> dict:
    # Lines 235-268 from pipeline.py
    ...


# --- The ReAct loop ---
async def _react_loop(state) -> AsyncGenerator[dict, None]:
    # Lines 1607-1949 from pipeline.py — the main ReAct loop
    # Imports from answer.py, question_plan.py, metadata.py as needed
    ...
```

- [ ] **Step 2: Create `answer.py`**

```python
"""Answer generation — streaming, deduplication, quality checks."""

from __future__ import annotations

import hashlib
import re
from typing import AsyncGenerator

from app.services.llm import stream_llm_messages
from app.agents.chat.nodes import _question_plan_adherence, _repair_response_to_question_plan


class OutputDeduplicator:
    """Two-level dedup: hash exact match + Jaccard fuzzy match."""
    # Lines 86-121 from pipeline.py — unchanged
    ...


async def _stream_final_answer(state, messages) -> AsyncGenerator[dict, None]:
    # Lines 1081-1184 from pipeline.py — unchanged
    ...


async def _final_answer_events_from_text(text: str, state) -> AsyncGenerator[dict, None]:
    # Lines 1186-1202 from pipeline.py — unchanged
    ...


async def _regenerate_after_dup(state, messages, dup_type: str) -> AsyncGenerator[dict, None]:
    # Lines 1059-1079 from pipeline.py — unchanged
    ...


async def _enforce_question_plan_on_text(text: str, state) -> str:
    # Lines 630-679 from pipeline.py — unchanged
    ...


def _ensure_final_answer_quality(text: str, state) -> str:
    # Lines 620-628 from pipeline.py — unchanged
    ...


def _fallback_react_answer(state, reason: str) -> str:
    # Lines 681-704 from pipeline.py — unchanged
    ...


def _fallback_interviewer_response(marker: str, state) -> str:
    # Lines 1031-1057 from pipeline.py — unchanged
    ...


def _fallback_coding_question(state) -> str:
    # Lines 589-618 from pipeline.py — unchanged
    ...


def _is_internal_react_marker(text: str) -> bool:
    # Lines 1024-1029 from pipeline.py — unchanged
    ...


def _normalize_react_marker(text: str) -> str:
    # Lines 1020-1022 from pipeline.py — unchanged
    ...


def _looks_like_candidate_question(text: str) -> bool:
    # Lines 807-814 from pipeline.py — unchanged
    ...


def _last_assistant_message(state) -> str:
    # Lines 706-716 from pipeline.py — unchanged
    ...
```

- [ ] **Step 3: Create `question_plan.py`**

```python
"""Question plan management and repetition protection."""

from __future__ import annotations

import re


def _should_create_question_plan(state) -> bool:
    # Lines 419-430 from pipeline.py
    ...


def _select_question_for_plan(candidates, state) -> dict | None:
    # Lines 468-491 from pipeline.py
    ...


def _maybe_create_question_plan(state) -> dict | None:
    # Lines 493-519 from pipeline.py
    ...


def _candidate_contains_negative_term(candidate: dict, negative_terms: list) -> bool:
    # Lines 432-440 from pipeline.py
    ...


def _is_algorithm_candidate(candidate: dict) -> bool:
    # Lines 442-448 from pipeline.py
    ...


def _allowed_focus_from_question(question: dict) -> list:
    # Lines 450-466 from pipeline.py
    ...


def _build_previously_asked_section(state) -> str:
    # Lines 535-587 from pipeline.py
    ...


def _count_consecutive_similar_questions(state) -> tuple[int, str]:
    # Lines 718-776 from pipeline.py
    ...


def _build_repetition_protection_note(state) -> str:
    # Lines 777-805 from pipeline.py
    ...


def _tokenize_for_overlap(text: str) -> set[str]:
    # Lines 359-364 from pipeline.py
    ...


def _normalize_question_text(text: str) -> str:
    # Lines 366-370 from pipeline.py
    ...


def _is_bare_coding_prompt(text: str, state) -> bool:
    # Lines 521-533 from pipeline.py
    ...
```

- [ ] **Step 4: Create `summary.py`**

```python
"""Interview ending and summary generation."""

from __future__ import annotations

import json
import logging

from pydantic import BaseModel
from app.services.llm import _call_llm_with_retry_messages

logger = logging.getLogger("interview-boss")


class InterviewSummary(BaseModel):
    overall_comment: str
    strongest_topic: str
    weakest_topic: str
    key_suggestions: list[str]
    score_estimate: int


def _build_interview_transcript(state) -> str:
    # Lines 157-169 from pipeline.py
    ...


def _render_interview_summary_markdown(summary: InterviewSummary) -> str:
    # Lines 171-182 from pipeline.py
    ...


async def _generate_structured_summary(state) -> str:
    # Lines 184-233 from pipeline.py
    ...


async def _forced_closing_response(state) -> str:
    # Lines 816-841 from pipeline.py
    ...


async def _generate_end_interview_response(state) -> str:
    # Lines 843-873 from pipeline.py
    ...


def _sanitize_error_message(e: Exception) -> str:
    # Lines 875-880 from pipeline.py
    ...
```

- [ ] **Step 5: Create `metadata.py`**

```python
"""Basis tracking and metadata extraction."""

from __future__ import annotations

import logging
import re

from app.db.connection import get_db_connection
from app.agents.chat.nodes import (
    _parse_basis_from_response,
    validate_basis,
    _filter_basis_ids_by_response,
    _extract_company_from_sources,
    _extract_round_from_sources,
    _response_references_resume,
    _response_references_jd,
    _get_resume_name,
    _get_jd_title,
)

logger = logging.getLogger("interview-boss")


def _build_react_metadata(state, response_text: str) -> tuple[dict, str]:
    # Lines 1204-1376 from pipeline.py — the largest function (172 lines)
    ...


def _infer_selected_question(state) -> dict | None:
    # Lines 372-417 from pipeline.py
    ...


def _public_question(question: dict | None) -> dict | None:
    # Lines 346-357 from pipeline.py
    ...


def _extract_company(question: dict) -> str:
    # Lines 318-330 from pipeline.py
    ...


def _extract_round(question: dict) -> str:
    # Lines 332-344 from pipeline.py
    ...
```

- [ ] **Step 6: Slim down `pipeline.py` to entry + re-exports**

```python
"""Chat Pipeline — orchestration entry point.

This module is the sole public entry point for the chat agent.
Internal implementation is split across:
- react_loop.py: ReAct loop core
- answer.py: answer generation and dedup
- question_plan.py: question plan management
- summary.py: end interview and summary
- metadata.py: basis tracking and metadata
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

from app.agents.chat.context_builder import build_interview_context
from app.agents.chat.nodes import (
    build_react_system_prompt,
    extract_memory,
    load_history,
    recall_memories,
    summarize_context,
    check_round_limit,
    _restore_active_skills_from_metadata,
)
from app.agents.chat.state import ChatState
from app.agents.shared.events import _event_queue_var
from app.services import chat_service
from app.services.memory_recall_service import classify_and_recall, classify_and_recall_fast

# Internal modules
from app.agents.chat.react_loop import _react_loop, _emit, _step, Budget, StopRun
from app.agents.chat.summary import (
    _generate_end_interview_response,
    _sanitize_error_message,
    _forced_closing_response,
)
from app.agents.chat.metadata import _build_react_metadata, _basis_event_payload

logger = logging.getLogger("interview-boss")

_SENTINEL = object()
_FRIENDLY_ERROR = "AI 服务配置错误，请在系统设置中配置有效的 API Key"


async def _step_load_context(state: ChatState) -> ChatState:
    # Lines 1439-1477 from original pipeline.py
    ...


async def _step_classify(state: ChatState) -> ChatState:
    # Lines 1479-1562 from original pipeline.py
    ...


async def _step_extract_memory(state: ChatState) -> None:
    # Lines 1564-1577 from original pipeline.py
    ...


async def _persist_active_skills(state: ChatState) -> None:
    # Lines 1579-1605 from original pipeline.py
    ...


def _initial_state(**kwargs) -> ChatState:
    # Lines 1378-1437 from original pipeline.py
    ...


async def run_chat(
    user_id: int,
    conversation_id: int,
    user_message: str,
    *,
    jd_text: str = "",
    resume_summary: str = "",
    job_position: str = "",
    selected_difficulty: str = "",
    **kwargs,
) -> AsyncGenerator[dict, None]:
    """Sole public entry point for the chat agent."""
    # Lines 1957-2077 from original pipeline.py — unchanged
    ...


# --- Re-exports for test backward compatibility ---
from app.agents.chat.react_loop import (  # noqa: E402
    _react_loop,
    MAX_REACT_STEPS,
    REACT_BUDGET,
    validate_tool_call,
    _log_react_llm_step,
    _log_react_tool_call,
    _summarize_tool_output,
    _sanitize_tool_args,
    _trace_safe_value,
    _emit,
    _step,
    Budget,
    StopRun,
    _INTERNAL_REACT_MARKERS,
    _ALLOWED_TOOL_NAMES,
    _SAFE_TOOL_ARG_KEYS,
    _TRACE_STRING_LIMIT,
    _TRACE_LIST_LIMIT,
    STEP_REASONS,
)
from app.agents.chat.answer import (  # noqa: E402
    OutputDeduplicator,
    _stream_final_answer,
    _final_answer_events_from_text,
    _regenerate_after_dup,
    _enforce_question_plan_on_text,
    _ensure_final_answer_quality,
    _fallback_react_answer,
    _fallback_interviewer_response,
    _fallback_coding_question,
    _is_internal_react_marker,
    _normalize_react_marker,
    _looks_like_candidate_question,
    _last_assistant_message,
)
from app.agents.chat.question_plan import (  # noqa: E402
    _should_create_question_plan,
    _select_question_for_plan,
    _maybe_create_question_plan,
    _candidate_contains_negative_term,
    _is_algorithm_candidate,
    _allowed_focus_from_question,
    _build_previously_asked_section,
    _count_consecutive_similar_questions,
    _build_repetition_protection_note,
    _tokenize_for_overlap,
    _normalize_question_text,
    _is_bare_coding_prompt,
)
from app.agents.chat.summary import (  # noqa: E402
    InterviewSummary,
    _generate_structured_summary,
    _build_interview_transcript,
    _render_interview_summary_markdown,
    _forced_closing_response,
    _generate_end_interview_response,
    _sanitize_error_message,
)
from app.agents.chat.metadata import (  # noqa: E402
    _build_react_metadata,
    _infer_selected_question,
    _public_question,
    _extract_company,
    _extract_round,
    _basis_event_payload,
)
```

- [ ] **Step 7: Verify compilation**

```bash
docker compose --profile test run --rm test uv run python -m compileall -q backend/app
```

Expected: no output (success).

- [ ] **Step 8: Run chat tests**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q
```

Expected: all tests pass.

- [ ] **Step 9: Commit**

```bash
git add backend/app/agents/chat/
git commit -m "refactor(backend): split pipeline.py into react_loop/answer/question_plan/summary/metadata"
```

---

## Task 6: Delete submit v1 and v1_sse endpoints

**Files:**
- Modify: `backend/app/routers/submit.py` (remove v1 functions)
- Modify: `backend/app/asgi.py` (remove v1 router registrations if separate)

- [ ] **Step 1: Remove v1 functions from submit.py**

Remove these functions:
- `submit_data()` (lines 169-452 in original, ~280 lines)
- `submit_data_stream()` (lines 454-739 in original, ~285 lines)

Remove any router decorators (`@router.post(...)`) associated with these functions.

Keep:
- `submit_data_stream_v2()` — the LangGraph SSE endpoint
- `create_submit_job()` — async job creation
- `get_active_submit_jobs()` — query endpoint

- [ ] **Step 2: Check if asgi.py registers separate routers for v1**

```bash
grep -n "submit" backend/app/asgi.py
```

If v1 endpoints have separate router registrations, remove them.

- [ ] **Step 3: Verify compilation**

```bash
docker compose --profile test run --rm test uv run python -m compileall -q backend/app
```

Expected: no output (success).

- [ ] **Step 4: Run full test suite**

```bash
./deploy/docker-deploy.sh test -q
```

Expected: all tests pass (or only pre-existing failures unrelated to this change).

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/submit.py backend/app/asgi.py
git commit -m "refactor(backend): remove unused submit v1 and v1_sse endpoints"
```

---

## Final Verification

After all 6 tasks are complete:

- [ ] **Step 1: Run backend daily gate**

```bash
./deploy/docker-deploy.sh check backend
```

Expected: blocking checks PASS.

- [ ] **Step 2: Run full test suite**

```bash
./deploy/docker-deploy.sh test -q
```

Expected: no new failures compared to baseline.

- [ ] **Step 3: Verify file sizes are reduced**

```bash
wc -l backend/app/agents/chat/pipeline.py \
      backend/app/db/migrations/__init__.py \
      backend/app/services/clustering/__init__.py \
      backend/app/services/pipeline/batch.py \
      backend/app/routers/submit.py
```

Expected:
- `pipeline.py` < 400 lines
- `migrations/__init__.py` < 100 lines
- `clustering/__init__.py` < 80 lines
- `batch.py` < 450 lines
- `submit.py` < 200 lines
