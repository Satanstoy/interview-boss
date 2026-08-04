# Interview Distribution Quality Control Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a user-configurable, real-interview-data-driven mock-interview controller whose statistics, session plan, tool selection, prompt, recorded events, frontend controls, and E2E evidence all agree.

**Architecture:** `questions_detail` becomes the linked, typed fact table; a versioned materialized statistics table derives defaults by job position. A session snapshots one immutable `distribution_plan`; an append-only event ledger derives execution state. The chat controller, Gateway, search/draw tools, and stop policy enforce that plan programmatically, while the system prompt exposes the same state to the LLM.

**Tech Stack:** Python 3.10, FastAPI, SQLite/WAL, Pydantic, ARQ, LangGraph-style chat harness, Vue 3 Composition API, shadcn-vue/reka-ui, Playwright, pytest in Docker, SSE.

## Global Constraints

- Use migration **042** and register it in `backend/app/db/migrations/__init__.py`; migrations 040 and 041 already exist.
- The only new canonical configurable types are `project_followup`, `knowledge_probe`, `algorithm_coding`, `system_design`, and `behavioral`; their ratios always sum to 1.
- Treat `new_question` as an intent, not a question type. Normalize legacy tool input `hr` to `behavioral` only at an explicit compatibility boundary.
- System defaults use only `interview.owner_id IS NULL`, `status = 'approved'`, undeleted interviews, and linked undeleted typed details. Private data can only affect its owner's selected-experience plan.
- Default total questions are the median of valid interviews' effective primary-question count. Default ratios are the posterior mean from the documented Dirichlet/empirical-Bayes estimator.
- `distribution_plan` is immutable after conversation creation. Counts, final status, and deviation reasons derive from append-only assistant-message events keyed by `plan_id`.
- Every backend test runs through Docker. Do not run host pytest or pytest in the production backend container.
- Frontend components must use shadcn-vue/reka-ui primitives, API calls must live in `frontend/src/services/`, and Vue components must not call `fetch` directly.
- Default tests must not call a real LLM. The manual verifier must refuse to run unless `RUN_REAL_INTERVIEW_DISTRIBUTION_E2E=1` is set.
- Each task ends with its focused Docker test/build command, an update to the affected `CLAUDE.md`, and one logical Conventional Commit.

---

## File and Interface Map

| Path | Responsibility after this plan |
|---|---|
| `backend/app/db/migrations/interview_distribution.py` | Migration 042: typed detail fields, statistics, refresh jobs, and user preferences tables; safe historical backfill. |
| `backend/app/services/interview_distribution.py` | Canonical enum/mapping, fact aggregation, posterior default estimation, refresh queue, immutable plan compilation, and runtime feasibility decisions. |
| `backend/app/db/operations.py` | Writes `interview_id/question_type/dimension` for all new/replaced details and marks the affected public scope stale in the same transaction. |
| `backend/app/worker.py` | Durable refresh-job worker entrypoint and ARQ enqueue helper. |
| `backend/app/routers/interview_distribution.py` | Public system-default statistics endpoint. |
| `backend/app/routers/profile_pkg/interview_distribution.py` | Current user's distribution-preference GET/PUT endpoints. |
| `backend/app/services/chat_service.py` | Resolves profile/default/selected-experience input into the session's immutable plan. |
| `backend/app/agents/chat/distribution_controller.py` | Pure feasibility and priority calculation from plan, existing events, and candidate signals. |
| `backend/app/agents/chat/{question_plan,tool_strategy,coverage_events,metadata,nodes,stop_policy}.py` | Uses the controller, records events, presents the same plan to the prompt, and closes by total primary-question count. |
| `backend/app/agents/chat/{tool_gateway,tools}.py`, `backend/app/mcp_server/{app,interview_tools}.py`, `backend/app/services/{fts_service,question_draw_service}.py` | Uses one canonical tool enum, Gateway enforcement, and candidate type validation. |
| `frontend/src/services/interviewDistributionApi.js` | System-default and user-preference API wrapper. |
| `frontend/src/components/business/{InterviewDistributionSettings,DistributionPlanProgress}.vue` | Settings sliders and in-conversation plan/progress view. |
| `frontend/src/components/business/{SettingsInterview,NewChatModal,ChatView}.vue` | Embeds settings, offers one-time override, and displays SSE/metadata progress. |
| `backend/scripts/verify_interview_distribution_e2e.py` | Opt-in real HTTP/SSE verifier and JSON report. |

## Task 1: Add the linked facts, canonical types, and migration 042

**Files:**
- Create: `backend/app/db/migrations/interview_distribution.py`
- Create: `backend/app/services/interview_distribution.py`
- Modify: `backend/app/db/migrations/__init__.py`
- Modify: `backend/tests/conftest.py`
- Create: `backend/tests/interview/test_interview_distribution_storage.py`
- Modify: `backend/app/db/CLAUDE.md`, `backend/tests/interview/CLAUDE.md`

**Interfaces:**
- Produces `QuestionType`, `QUESTION_TYPES`, `map_question_type()`, `map_dimension()`, and migration `_migration_042_interview_distribution(conn)`.
- Later tasks may import only these names for type validation and mapping; do not duplicate regex/type lists.

- [ ] **Step 1: Write RED storage and mapping tests**

```python
def test_migration_adds_linked_typed_question_detail_fields(test_db):
    columns = {row["name"] for row in test_db.execute("PRAGMA table_info(questions_detail)")}
    assert {"interview_id", "question_type", "dimension"} <= columns
    assert test_db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'interview_distribution_stats'").fetchone()
    assert test_db.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'interview_distribution_refresh_jobs'").fetchone()

def test_question_type_mapper_returns_only_canonical_values():
    from app.services.interview_distribution import QuestionType, map_question_type

    assert map_question_type("E.算法与数据结构", "", "", "") is QuestionType.ALGORITHM_CODING
    assert map_question_type("A.项目经验与设计", "A3.难点攻关与优化", "", "") is QuestionType.PROJECT_FOLLOWUP
    assert map_question_type("", "", "", "") is QuestionType.UNCLASSIFIED
```

- [ ] **Step 2: Run RED in Docker**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/interview/test_interview_distribution_storage.py -q
```

Expected: collection/import failure because the module and migration do not exist.

- [ ] **Step 3: Implement the shared enum, mapper, and idempotent migration**

```python
# backend/app/services/interview_distribution.py
class QuestionType(str, Enum):
    PROJECT_FOLLOWUP = "project_followup"
    KNOWLEDGE_PROBE = "knowledge_probe"
    ALGORITHM_CODING = "algorithm_coding"
    SYSTEM_DESIGN = "system_design"
    BEHAVIORAL = "behavioral"
    UNCLASSIFIED = "unclassified"

QUESTION_TYPES = tuple(item for item in QuestionType if item is not QuestionType.UNCLASSIFIED)

def map_dimension(question_type: QuestionType) -> str:
    if question_type is QuestionType.PROJECT_FOLLOWUP:
        return "project_deep_dive"
    if question_type is QuestionType.BEHAVIORAL:
        return "behavioral"
    return "knowledge_probe" if question_type is not QuestionType.UNCLASSIFIED else "unclassified"
```

```python
# backend/app/db/migrations/interview_distribution.py
def _migration_042_interview_distribution(conn):
    columns = {row[1] for row in conn.execute("PRAGMA table_info(questions_detail)")}
    if "interview_id" not in columns:
        conn.execute("ALTER TABLE questions_detail ADD COLUMN interview_id INTEGER")
    if "question_type" not in columns:
        conn.execute("ALTER TABLE questions_detail ADD COLUMN question_type TEXT NOT NULL DEFAULT 'unclassified'")
    if "dimension" not in columns:
        conn.execute("ALTER TABLE questions_detail ADD COLUMN dimension TEXT NOT NULL DEFAULT 'unclassified'")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_qd_interview_question_type ON questions_detail(interview_id, question_type)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS user_interview_distribution_preferences (
          user_id INTEGER NOT NULL, job_position TEXT NOT NULL,
          mode TEXT NOT NULL DEFAULT 'system_default', target_question_count INTEGER,
          custom_distribution TEXT, selected_experience_id INTEGER,
          style_strength TEXT NOT NULL DEFAULT 'normal', updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (user_id, job_position)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS interview_distribution_stats (
          scope TEXT NOT NULL, job_position TEXT NOT NULL, question_type TEXT NOT NULL,
          stats_version INTEGER NOT NULL, posterior_mean_ratio REAL NOT NULL,
          posterior_alpha REAL NOT NULL, raw_question_count INTEGER NOT NULL,
          sample_interview_count INTEGER NOT NULL, sample_question_count INTEGER NOT NULL,
          recommended_total_count INTEGER NOT NULL, dispersion REAL NOT NULL,
          confidence TEXT NOT NULL, calculated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (scope, job_position, question_type, stats_version)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS interview_distribution_refresh_jobs (
          scope TEXT NOT NULL, job_position TEXT NOT NULL, requested_source_version TEXT NOT NULL,
          published_source_version TEXT, status TEXT NOT NULL DEFAULT 'pending', attempt_count INTEGER NOT NULL DEFAULT 0,
          claimed_by TEXT, claimed_at TIMESTAMP, last_error TEXT, next_retry_at TIMESTAMP,
          updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (scope, job_position)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS interview_distribution_stat_exclusions (
          stats_version INTEGER NOT NULL, scope TEXT NOT NULL, job_position TEXT NOT NULL,
          interview_id INTEGER NOT NULL, exclusion_reason TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
          PRIMARY KEY (stats_version, scope, job_position, interview_id)
        )
    """)
```

Backfill `interview_id` only where one active interview has the same URL. Map every linked active detail with the shared mapper; record ambiguous URLs in the migration logger and leave their `interview_id` null. Add the migration import and `(42, 'interview_distribution', _migration_042_interview_distribution)` registry row.

- [ ] **Step 4: Run GREEN and migration collection tests**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/interview/test_interview_distribution_storage.py backend/tests/infra/ -q
```

Expected: all selected tests pass; existing migration and worker configuration tests remain green.

- [ ] **Step 5: Update directory guidance and commit**

```bash
git add backend/app/db/migrations/interview_distribution.py backend/app/db/migrations/__init__.py backend/app/services/interview_distribution.py backend/tests/conftest.py backend/tests/interview/test_interview_distribution_storage.py backend/app/db/CLAUDE.md backend/tests/interview/CLAUDE.md
git commit -m "feat(backend): add interview distribution facts"
```

## Task 2: Build versioned public statistics and durable refresh jobs

**Files:**
- Modify: `backend/app/services/interview_distribution.py`
- Create: `backend/app/core/interview_distribution_config.py`
- Modify: `backend/app/worker.py`
- Create: `backend/tests/interview/test_interview_distribution_stats.py`
- Modify: `backend/tests/infra/test_worker.py`, `backend/app/CLAUDE.md`

**Interfaces:**
- Produces `mark_distribution_refresh(cursor, job_position)`, `refresh_distribution_scope(conn, scope, job_position)`, `get_distribution_default(conn, job_position)`, and async `refresh_interview_distribution_task(ctx, scope, job_position)`.
- `get_distribution_default()` returns one complete stats version or raises a typed `DistributionStatsUnavailable`; it never returns partial rows.

- [ ] **Step 1: Write RED tests for public-only facts, posterior totals, and job coalescing**

```python
def test_refresh_uses_only_public_approved_linked_details(test_db):
    # Insert one public approved interview and one private approved interview.
    # Only the public record may contribute to the produced stats version.
    result = refresh_distribution_scope(test_db, "public_job_position", "agent_llm")
    assert result["sample_interview_count"] == 1
    assert result["raw_counts"]["algorithm_coding"] == 1

def test_mark_refresh_coalesces_one_scope_job(test_db):
    mark_distribution_refresh(test_db.cursor(), "agent_llm")
    mark_distribution_refresh(test_db.cursor(), "agent_llm")
    assert test_db.execute("SELECT COUNT(*) FROM interview_distribution_refresh_jobs").fetchone()[0] == 1

def test_recommended_total_is_median_and_ratio_sum_is_one(test_db):
    result = refresh_distribution_scope(test_db, "public_job_position", "agent_llm")
    assert result["recommended_total_count"] == 10
    assert sum(result["posterior_mean_ratio"].values()) == pytest.approx(1.0)

def test_sparse_position_uses_job_family_parent_and_records_excluded_interviews(test_db):
    result = refresh_distribution_scope(test_db, "public_job_position", "agent_llm_sparse")
    assert result["parent_scope"] == "job_family"
    assert result["confidence"] in {"low", "medium"}
    reasons = {row["exclusion_reason"] for row in test_db.execute("SELECT exclusion_reason FROM interview_distribution_stat_exclusions")}
    assert {"too_few_effective_questions", "unclassified_ratio_exceeded"} <= reasons

def test_interview_with_more_than_twenty_percent_unclassified_is_excluded(test_db):
    result = refresh_distribution_scope(test_db, "public_job_position", "agent_llm")
    assert result["sample_interview_count"] == 1
    reason = test_db.execute(
        "SELECT exclusion_reason FROM interview_distribution_stat_exclusions WHERE interview_id = ?",
        (mostly_typed_but_over_threshold_interview_id,),
    ).fetchone()["exclusion_reason"]
    assert reason == "unclassified_ratio_exceeded"

def test_related_positions_share_a_family_but_unknown_positions_do_not_merge():
    assert derive_job_family("Agent开发") == derive_job_family("大模型开发") == "agent_llm"
    assert derive_job_family("冷门岗位") == "position:冷门岗位"
```

- [ ] **Step 2: Run RED**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/interview/test_interview_distribution_stats.py -q
```

Expected: FAIL because the refresh, scoped aggregation, quality-gate, and posterior-estimation functions are absent.

- [ ] **Step 3: Implement estimator, quality gates, hierarchy, and worker**

All 042 DDL is already created in Task 1 before any database can record migration version 42. Define the initial immutable quality gates in `interview_distribution.py`:

```python
# backend/app/core/interview_distribution_config.py
JOB_FAMILY_BY_POSITION = {
    "Agent开发": "agent_llm",
    "大模型应用开发": "agent_llm",
    "大模型开发": "agent_llm",
    "Agent开发/大模型应用开发/大模型开发": "agent_llm",
    "后端开发": "backend",
}

def derive_job_family(job_position: str) -> str:
    normalized = (job_position or "").strip()
    return JOB_FAMILY_BY_POSITION.get(normalized, f"position:{normalized or 'system'}")
```

`interview_distribution.py` imports that mapping and defines `MIN_EFFECTIVE_PRIMARY_QUESTIONS = 5` and `MAX_UNCLASSIFIED_RATIO = 0.20`. For a known family, the aggregation query selects every mapped position in that family; an unknown `position:<name>` family contains only that exact position and therefore falls back directly to `system_baseline` rather than silently merging unrelated roles. The stats test fixture must insert qualifying facts for two known `agent_llm` positions and prove they aggregate into one family.

Compute and publish the three scopes in this order: `system_baseline` from all qualifying public facts, `job_family` with `system_baseline` as its prior, then `public_job_position` with its job-family posterior as prior. Run aggregation in two explicit phases. First query every linked, undeleted detail for the public/approved interview set (including `unclassified`) to calculate per-interview total, effective-primary count, and unclassified ratio. Reject an interview below `MIN_EFFECTIVE_PRIMARY_QUESTIONS` or above `MAX_UNCLASSIFIED_RATIO`, writing its exact reason to `interview_distribution_stat_exclusions`. Then aggregate only the five typed details belonging to the accepted interview IDs. The typed second-phase predicate is:

```sql
FROM interview i JOIN questions_detail qd ON qd.interview_id = i.id
WHERE i.owner_id IS NULL AND i.status = 'approved' AND i.deleted_at IS NULL
  AND qd.deleted_at IS NULL AND qd.question_type != 'unclassified' AND i.job_position = ?
```

For each scope, use `alpha_t = raw_count_t + prior_strength * parent_ratio_t`, `ratio_t = alpha_t / sum(alpha)`, retain valid per-interview count vectors for median/dispersion, and publish all five rows plus exclusions in one transaction only after ratios sum to one. Add a worker function and enqueue helper; update the existing worker-count test rather than leaving a stale fixed count assertion.

- [ ] **Step 4: Run GREEN and worker tests**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/interview/test_interview_distribution_stats.py backend/tests/infra/test_worker.py -q
```

Expected: all pass; private, deleted, pending, and unlinked details do not change public stats.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/migrations/interview_distribution.py backend/app/services/interview_distribution.py backend/app/core/interview_distribution_config.py backend/app/worker.py backend/tests/interview/test_interview_distribution_stats.py backend/tests/infra/test_worker.py backend/app/CLAUDE.md backend/app/core/CLAUDE.md
git commit -m "feat(backend): materialize interview distribution defaults"
```

## Task 3: Make every interview write path preserve the fact/statistics contract

**Files:**
- Modify: `backend/app/db/operations.py`
- Modify: `backend/app/services/pipeline/batch.py`
- Modify: `backend/app/services/pipeline/writer.py`
- Modify: `backend/app/routers/data.py`
- Modify: `backend/app/routers/interview.py`
- Modify: `backend/app/routers/questions.py`
- Modify: `backend/app/routers/questions_pkg/bulk.py`
- Modify: `backend/app/routers/questions_pkg/mutations.py`
- Modify: `backend/app/routers/analytics.py`
- Create: `backend/tests/pipeline/test_interview_distribution_write_paths.py`
- Modify: `backend/app/db/CLAUDE.md`, `backend/app/services/pipeline/CLAUDE.md`, `backend/app/routers/CLAUDE.md`

**Interfaces:**
- `_insert_details_txn(cursor, interview_id, tagged_rows, job_position)` and `_replace_details_txn(cursor, interview_id, url, tagged_rows, job_position)` must write canonical types and call `mark_distribution_refresh()` before commit.
- `tag_and_write_details(interview_id, url, company, round_, questions_list, job_position, user_id)` must use the same replacement primitive; it may not delete/reinsert URL-only details.
- All callers must supply the known `interview.id`; no path may reconstruct ownership by ambiguous URL.

- [ ] **Step 1: Write RED regression tests for new upload, reprocess, and editing**

```python
def _refresh_status(conn, job_position):
    return conn.execute(
        "SELECT status FROM interview_distribution_refresh_jobs WHERE scope = 'public_job_position' AND job_position = ?",
        (job_position,),
    ).fetchone()["status"]

def _details_for_interview(conn, interview_id):
    return [row["question_type"] for row in conn.execute(
        "SELECT question_type FROM questions_detail WHERE interview_id = ? ORDER BY id", (interview_id,)
    )]

def test_submit_interview_links_details_and_marks_public_scope_stale(test_db, monkeypatch):
    interview_id = submit_interview_txn_tag_only(
        "https://example.test/interview-1",
        {"公司": "测试公司", "面试轮次": "一面", "考察重点": "算法", "难易程度": "中等"},
        "手撕 LRU Cache",
        "2026Q3", None, "approved", "agent_llm",
        [["https://example.test/interview-1", "测试公司", "一面", "手撕 LRU Cache", "E.算法与数据结构", "E1.算法手撕", "", "L2"]],
    )
    detail = test_db.execute("SELECT interview_id, question_type FROM questions_detail").fetchone()
    assert detail["interview_id"] == interview_id
    assert detail["question_type"] == "algorithm_coding"
    assert _refresh_status(test_db, "agent_llm") == "pending"

def test_editing_questions_list_replaces_only_same_interview_and_requeues_stats(test_db, client):
    response = client.put("/api/data/update", json={
        "table_name": "interview", "record_id": interview_id,
        "update_data": {"questions_list": "请介绍一个你负责过的项目"},
    })
    assert response.status_code == 200
    assert _details_for_interview(test_db, interview_id) == ["project_followup"]

async def test_pipeline_writer_and_delete_restore_requeue_distribution_stats(test_db, client):
    await tag_and_write_details("https://example.test/interview-2", "测试公司", "一面", "二分查找", "agent_llm", user_id=None)
    client.delete(f"/api/data/interview/{interview_id}")
    client.post(f"/api/data/restore/interview/{interview_id}")
    assert _refresh_status(test_db, "agent_llm") == "pending"

def test_question_edit_and_bulk_delete_mark_linked_public_distribution_stale(test_db, client):
    response = client.put(f"/api/master-bank/{question_id}", json={"question": "解释 Redis 缓存穿透"})
    assert response.status_code == 200
    response = client.post("/api/master-bank/batch-delete", json={"ids": [question_id]})
    assert response.status_code == 200
    assert _refresh_status(test_db, "agent_llm") == "pending"

def test_category_mutation_and_analytics_normalization_retype_and_requeue(test_db, client):
    # Mock raw_llm_call so the real re-tag endpoint deterministically returns an E-category.
    response = client.post(f"/api/master-bank/re-tag/{question_id}")
    assert response.status_code == 200
    client.post("/api/normalize-categories")
    assert _details_for_interview(test_db, interview_id) == ["algorithm_coding"]
    assert _refresh_status(test_db, "agent_llm") == "pending"
```

- [ ] **Step 2: Run RED**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/pipeline/test_interview_distribution_write_paths.py -q
```

Expected: FAIL because current detail inserts omit `interview_id/question_type/dimension` and do not enqueue distribution refresh.

- [ ] **Step 3: Implement transaction-local propagation**

Change the insert/replace SQL to include `interview_id`, `question_type`, and `dimension`. In `submit_interview_txn*`, capture `cursor.lastrowid` before detail insertion; in reprocess/edit flows, load the exact interview row by primary key before replacement. Apply the same linked write routine in `pipeline/writer.py::tag_and_write_details`. Add one transaction-local helper that loads impacted linked public interviews, retypes details with the shared mapper, and marks their old/new scopes stale before commit. Call it from `data.py` single/batch delete, restore, generic `questions_detail` category edits, `interview.py` reprocess, `questions.py` synchronized question-text edits, `questions_pkg/bulk.py` original-question deletes, `questions_pkg/mutations.py` category/tag/difficulty mutation, and `analytics.py` category normalization/data-clear paths. The data-clear path must queue every affected public position before deleting facts. Use the shared mapper for each tagged row and call `mark_distribution_refresh(cursor, job_position)` only when the interview is public and approved; ownership/status transitions must mark both old and new scopes.

- [ ] **Step 4: Run GREEN with existing pipeline regression suite**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/pipeline/test_interview_distribution_write_paths.py backend/tests/pipeline/ -q
```

Expected: all pass; reprocess and edits cannot create unlinked or stale typed details.

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/operations.py backend/app/services/pipeline/batch.py backend/app/services/pipeline/writer.py backend/app/routers/data.py backend/app/routers/interview.py backend/app/routers/questions.py backend/app/routers/questions_pkg/bulk.py backend/app/routers/questions_pkg/mutations.py backend/app/routers/analytics.py backend/tests/pipeline/test_interview_distribution_write_paths.py backend/app/db/CLAUDE.md backend/app/services/pipeline/CLAUDE.md backend/app/routers/CLAUDE.md backend/app/routers/questions_pkg/CLAUDE.md
git commit -m "feat(backend): keep distribution facts synchronized"
```

## Task 4: Expose defaults and persist user distribution preferences

**Files:**
- Create: `backend/app/routers/interview_distribution.py`
- Create: `backend/app/routers/profile_pkg/interview_distribution.py`
- Modify: `backend/app/routers/profile_pkg/__init__.py`
- Modify: `backend/app/asgi.py`
- Modify: `backend/app/models/schemas.py`
- Create: `backend/tests/interview/test_interview_distribution_api.py`
- Modify: `backend/app/routers/profile_pkg/CLAUDE.md`, `backend/app/routers/CLAUDE.md`

**Interfaces:**
- `GET /api/interview/distribution/default?job_position=<optional>` returns `{stats_version, source_snapshot, recommended_total_count, distribution, confidence, stale}`.
- `GET|PUT /api/profile/interview-distribution-preference` returns/persists `{mode, target_question_count, custom_distribution, selected_experience_id, style_strength}` for the authenticated user and current/specified position.
- `DistributionPreferenceRequest` rejects missing types, ratios not summing to one, invalid total counts, and inaccessible selected experiences.

- [ ] **Step 1: Write RED API contract tests**

```python
def test_default_endpoint_returns_one_complete_stats_version(client, test_db, auth_headers):
    response = client.get("/api/interview/distribution/default?job_position=agent_llm", headers=auth_headers)
    body = response.json()["data"]
    assert set(body["distribution"]) == {"project_followup", "knowledge_probe", "algorithm_coding", "system_design", "behavioral"}
    assert sum(body["distribution"].values()) == pytest.approx(1.0)

def test_preference_put_rejects_non_normalized_distribution(client, auth_headers):
    response = client.put("/api/profile/interview-distribution-preference", headers=auth_headers, json={
        "mode": "custom", "target_question_count": 10,
        "custom_distribution": {"project_followup": .5, "knowledge_probe": .5, "algorithm_coding": .5, "system_design": 0, "behavioral": 0},
    })
    assert response.status_code == 422
```

- [ ] **Step 2: Run RED**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/interview/test_interview_distribution_api.py -q
```

Expected: FAIL because routes and request model do not exist.

- [ ] **Step 3: Implement authenticated routes and exact validation**

Use `get_current_user`, resolve `job_position` server-side when omitted, and return a structured 409 when no complete/default version can be produced. In PUT, persist a normalized five-key JSON object; selected-experience mode validates accessibility with `(owner_id = user_id OR owner_id IS NULL)`, approved status, and undeleted state. Register both routers without changing unrelated profile endpoints.

- [ ] **Step 4: Run GREEN**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/interview/test_interview_distribution_api.py backend/tests/security/ -q
```

Expected: all pass; one user cannot save another user's private experience as a style source.

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/interview_distribution.py backend/app/routers/profile_pkg/interview_distribution.py backend/app/routers/profile_pkg/__init__.py backend/app/asgi.py backend/app/models/schemas.py backend/tests/interview/test_interview_distribution_api.py backend/app/routers/profile_pkg/CLAUDE.md backend/app/routers/CLAUDE.md
git commit -m "feat(backend): add interview distribution settings APIs"
```

## Task 5: Compile an immutable session plan from defaults, preferences, or a selected experience

**Files:**
- Modify: `backend/app/services/interview_distribution.py`
- Modify: `backend/app/services/chat_service.py`
- Modify: `backend/app/models/schemas.py`
- Modify: `backend/app/routers/chat.py`
- Create: `backend/app/agents/chat/distribution_execution.py`
- Create: `backend/tests/chat/test_interview_distribution_plan.py`
- Modify: `backend/app/agents/chat/CLAUDE.md`, `backend/tests/chat/CLAUDE.md`

**Interfaces:**
- `compile_distribution_plan(conn, *, user_id, job_position, request_override, preference) -> dict` returns a JSON-safe immutable plan with `plan_id`, `stats_version`, all five ratios/counts/bounds, `random_seed`, and `style_source_snapshot` when applicable.
- `CreateConversationRequest.distribution_override` has the same validated shape as a preference but applies only to one conversation.
- `get_conversation()` returns its immutable metadata plan and `distribution_execution`, derived by folding persisted assistant-message events; reconnecting to the same conversation returns the same derived counts.

- [ ] **Step 1: Write RED plan tests**

```python
def test_conversation_snapshots_current_default_and_does_not_drift(test_db):
    conversation = create_conversation(user_id=1, mode="free_practice", job_position="agent_llm")
    before = get_conversation_metadata(conversation["id"])["interview_config"]["distribution_plan"]
    refresh_distribution_scope(test_db, "public_job_position", "agent_llm")
    after = get_conversation_metadata(conversation["id"])["interview_config"]["distribution_plan"]
    assert after == before

def test_selected_experience_plan_contains_auditable_blend_snapshot(test_db):
    plan = compile_distribution_plan(test_db, user_id=1, job_position="agent_llm", request_override={"mode": "selected_experience", "selected_experience_id": 7, "style_strength": "normal"}, preference=None)
    assert plan["style_source_snapshot"]["experience_id"] == 7
    assert 0 <= plan["style_source_snapshot"]["blend_weight"] <= 1

def test_soft_targets_sum_to_target_and_bounds_are_feasible(test_db):
    plan = compile_distribution_plan(
        test_db, user_id=1, job_position="agent_llm", request_override=None, preference=None,
    )
    assert sum(plan["soft_target_counts"].values()) == plan["target_question_count"]
    assert sum(item["min"] for item in plan["allowed_counts"].values()) <= plan["target_question_count"] <= sum(item["max"] for item in plan["allowed_counts"].values())

def test_conversation_detail_derives_execution_from_persisted_events(test_db):
    conversation = create_conversation(user_id=1, mode="free_practice", job_position="agent_llm")
    plan = get_conversation_metadata(conversation["id"])["interview_config"]["distribution_plan"]
    save_message(conversation["id"], "assistant", "问题", metadata={"coverage_events": [{"plan_id": plan["plan_id"], "question_type": "knowledge_probe", "counts_toward_target": True}]})
    detail = get_conversation(conversation["id"], user_id=1, job_position="agent_llm")
    assert detail["distribution_execution"]["actual_counts"]["knowledge_probe"] == 1

def test_active_conversation_is_in_progress_until_an_explicit_terminal_event(test_db):
    plan = make_plan(target=3)
    assert distribution_execution_from_events(plan, events_for("knowledge_probe"))["status"] == "in_progress"
    terminal = events_for("knowledge_probe") + [{"type": "distribution_result", "plan_id": "p", "status": "incomplete", "reason": "candidate_requested_end"}]
    assert distribution_execution_from_events(plan, terminal)["status"] == "incomplete"

def test_reopening_a_conversation_preserves_its_persisted_terminal_result(test_db):
    conversation = create_conversation(user_id=1, mode="free_practice", job_position="agent_llm")
    plan = get_conversation_metadata(conversation["id"])["interview_config"]["distribution_plan"]
    save_message(conversation["id"], "assistant", "结束", metadata={"distribution_result": {"plan_id": plan["plan_id"], "status": "incomplete", "reason": "candidate_requested_end"}})
    assert get_conversation(conversation["id"], user_id=1, job_position="agent_llm")["distribution_execution"]["status"] == "incomplete"
```

- [ ] **Step 2: Run RED**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_interview_distribution_plan.py -q
```

Expected: FAIL because conversation creation does not compile or snapshot a distribution plan.

- [ ] **Step 3: Implement plan compilation and session persistence**

Generate integer soft targets with largest-remainder allocation. Use the posterior predictive/dispersion helper to construct feasible min/max bounds, then store the result under `metadata.interview_config.distribution_plan` before inserting the conversation. Create the pure `distribution_execution_from_events(plan, events)` module before using it: it derives actual counts and remaining capacity from matching counted events, returns `completed` once the target is reached, returns `incomplete` only after an explicit matching `distribution_result` terminal event with that status, and otherwise returns `in_progress`. Modify `get_conversation()` to select and decode conversation metadata, load every assistant-message metadata record in chronological order, merge matching-plan `coverage_events` and `distribution_result` values into one ordered event stream, fold it through that pure function, and return its existing identity fields together with `metadata` and `distribution_execution`. Preserve existing `difficulty`, `experience_id`, and `rhythm_profile`; do not mutate the plan after insert.

- [ ] **Step 4: Run GREEN with conversation regression tests**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_interview_distribution_plan.py backend/tests/chat/test_chat.py -q
```

Expected: all pass; old clients with no override receive a default plan, while existing conversation fields stay compatible.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/interview_distribution.py backend/app/services/chat_service.py backend/app/models/schemas.py backend/app/routers/chat.py backend/app/agents/chat/distribution_execution.py backend/tests/chat/test_interview_distribution_plan.py backend/app/agents/chat/CLAUDE.md backend/tests/chat/CLAUDE.md
git commit -m "feat(backend): snapshot interview distribution plans"
```

## Task 6: Add the programmatic distribution controller and append-only event ledger

**Files:**
- Create: `backend/app/agents/chat/distribution_controller.py`
- Modify: `backend/app/agents/chat/{question_plan,tool_strategy,coverage_events,metadata,stop_policy,nodes,pipeline,state}.py`
- Create: `backend/tests/chat/test_distribution_controller.py`
- Modify: `backend/app/agents/chat/CLAUDE.md`, `backend/tests/chat/CLAUDE.md`

**Interfaces:**
- `decide_next_question_type(plan, events, candidate_signal) -> DistributionDecision` returns `allowed_types`, `preferred_type`, `forbidden_reasons`, and `selection_reason`.
- The controller consumes Task 5's `distribution_execution_from_events(plan, events)` as the sole source of actual counts, status, and remaining capacity.
- `MAX_CONSECUTIVE_PRIMARY_TYPE = 3`; exceeding it is allowed only with `constraint_exception` equal to `pool_exhausted`, `candidate_risk`, or `remaining_minimums`.
- Every primary event contains `plan_id`, canonical `question_type`, `counts_toward_target=True`, `selection_reason`, `seed_step`, and an optional structured `constraint_exception`. Conversation-only clarification events always carry `False`.

- [ ] **Step 1: Write RED controller tests**

```python
_TYPES = ("project_followup", "knowledge_probe", "algorithm_coding", "system_design", "behavioral")

def make_plan(target, bounds=None):
    bounds = bounds or {name: (0, target) for name in _TYPES}
    return {
        "plan_id": "p", "target_question_count": target,
        "soft_target_counts": {name: 0 for name in _TYPES},
        "allowed_counts": {name: {"min": low, "max": high} for name, (low, high) in bounds.items()},
    }

def events_for(*types):
    return [{"plan_id": "p", "question_type": value, "counts_toward_target": True} for value in types]

def completed_events(plan):
    return events_for(*(["knowledge_probe"] * plan["target_question_count"]))

def test_controller_forbids_type_that_makes_remaining_minimums_impossible():
    plan = make_plan(target=4, bounds={"project_followup": (1, 2), "knowledge_probe": (2, 3), "algorithm_coding": (0, 1), "system_design": (0, 1), "behavioral": (0, 1)})
    decision = decide_next_question_type(plan, events_for("project_followup", "project_followup"), candidate_signal={})
    assert "project_followup" not in decision.allowed_types

def test_clarification_event_does_not_increment_primary_count():
    execution = distribution_execution_from_events(make_plan(target=2), [{"plan_id": "p", "question_type": "knowledge_probe", "counts_toward_target": False}])
    assert execution["actual_primary_count"] == 0

def test_completed_and_incomplete_results_are_derived_not_written_into_plan():
    plan = make_plan(target=1)
    assert "status" not in plan
    assert distribution_execution_from_events(plan, completed_events(plan))["status"] == "completed"

def test_seed_breaks_ties_reproducibly():
    plan = {**make_plan(target=3), "random_seed": "seed-7"}
    first = decide_next_question_type(plan, [], candidate_signal={"eligible_types": ["algorithm_coding", "system_design"]})
    second = decide_next_question_type(plan, [], candidate_signal={"eligible_types": ["algorithm_coding", "system_design"]})
    assert first.preferred_type == second.preferred_type

def test_fourth_consecutive_type_is_rejected_when_other_type_is_feasible():
    plan = make_plan(target=5)
    events = events_for("knowledge_probe", "knowledge_probe", "knowledge_probe")
    decision = decide_next_question_type(plan, events, candidate_signal={"eligible_types": ["knowledge_probe", "algorithm_coding"]})
    assert decision.preferred_type != "knowledge_probe"
    assert "max_consecutive_primary_type" in decision.forbidden_reasons["knowledge_probe"]

@pytest.mark.parametrize("reason", ["pool_exhausted", "candidate_risk", "remaining_minimums"])
def test_fourth_consecutive_type_allows_only_documented_exception(reason):
    plan = make_plan(target=5)
    events = events_for("knowledge_probe", "knowledge_probe", "knowledge_probe")
    decision = decide_next_question_type(
        plan, events,
        candidate_signal={"eligible_types": ["knowledge_probe"], "constraint_exception": reason, "exception_evidence": {"code": reason}},
    )
    assert decision.preferred_type == "knowledge_probe"
    assert decision.constraint_exception == reason
```

- [ ] **Step 2: Run RED**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_distribution_controller.py -q
```

Expected: FAIL because the controller and event-derived execution model do not exist.

- [ ] **Step 3: Implement feasibility first, prompt second**

Implement the remaining-capacity test before scoring candidate signals. `question_plan` requests a `DistributionDecision`; `tool_strategy` exposes only `allowed_types`; `stop_policy` closes once the Task 5 derived primary count reaches the target. Use `random.Random(f"{plan['random_seed']}:{len(counted_events)}")` only to choose among equal-scoring feasible types, and record its step in `seed_step`. `metadata` appends primary events and the final `distribution_result`; a consecutive-type exception must include one of the three interface reasons plus nonempty `exception_evidence`, and the event must persist both. `nodes.build_react_system_prompt()` renders only the same derived counts/bounds/next type; it must not independently calculate a distribution.

- [ ] **Step 4: Run GREEN and existing rhythm/stop-policy suites**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_distribution_controller.py backend/tests/chat/test_interview_rhythm.py backend/tests/chat/test_react_loop.py -q
```

Expected: all pass; candidate signals can choose among feasible types but cannot violate hard bounds or extend primary question count.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/chat/distribution_controller.py backend/app/agents/chat/question_plan.py backend/app/agents/chat/tool_strategy.py backend/app/agents/chat/coverage_events.py backend/app/agents/chat/metadata.py backend/app/agents/chat/stop_policy.py backend/app/agents/chat/nodes.py backend/app/agents/chat/pipeline.py backend/app/agents/chat/state.py backend/tests/chat/test_distribution_controller.py backend/app/agents/chat/CLAUDE.md backend/tests/chat/CLAUDE.md
git commit -m "feat(backend): enforce interview distribution plans"
```

## Task 7: Enforce canonical types at Gateway, search, draw, and selection boundaries

**Files:**
- Modify: `backend/app/agents/chat/{tool_gateway,tools}.py`
- Modify: `backend/app/mcp_server/{app,interview_tools}.py`
- Modify: `backend/app/services/{fts_service,question_draw_service}.py`
- Create: `backend/tests/chat/test_distribution_tool_contract.py`
- Modify: `backend/tests/chat/test_tools.py`, `backend/tests/chat/CLAUDE.md`

**Interfaces:**
- Both `SearchQuestionsInput.question_type` and `DrawQuestionsInput.question_type` accept canonical types; the `hr` adapter maps to `behavioral` before validation.
- `enforce_distribution_tool_type(state, requested_type)` returns a permitted canonical type or raises a validation envelope before the database search/draw runs.
- Candidate results are filtered by `map_question_type(cat1, cat2, tags, question) == required_type` before entering `candidate_questions` or `select_question`.

- [ ] **Step 1: Write RED Gateway and candidate-filter tests**

```python
async def test_gateway_overrides_llm_requested_type_with_controller_preference(sample_state):
    sample_state["distribution_decision"] = {"allowed_types": ["algorithm_coding"], "preferred_type": "algorithm_coding"}
    envelope = await draw_questions_tool({"count": 1, "question_type": "knowledge_probe"}, sample_state)
    assert envelope["metadata"]["enforced_question_type"] == "algorithm_coding"

async def test_search_discards_candidate_with_wrong_canonical_type(sample_state, monkeypatch):
    monkeypatch.setattr("app.mcp_server.interview_tools._hybrid_search_for_tool", AsyncMock(return_value=[{"id": 1, "question": "Redis", "cat1": "C.基础工程能力", "cat2": "", "tags": ""}]))
    sample_state["distribution_decision"] = {"allowed_types": ["algorithm_coding"], "preferred_type": "algorithm_coding"}
    envelope = await search_questions_tool({"keywords": ["Redis"]}, sample_state)
    assert envelope["items"] == []
```

- [ ] **Step 2: Run RED**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_distribution_tool_contract.py -q
```

Expected: FAIL because the current schemas accept inconsistent enums and do not filter candidates by canonical type.

- [ ] **Step 3: Implement one tool enum and defence in depth**

Import `QuestionType` into gateway Pydantic models and OpenAI tool schemas. Keep `new_question` in the semantic classifier only. Normalize `hr` in a compatibility helper, then enforce controller output in `interview_tools` immediately before calling `hybrid_search`/`draw_questions`. Make `fts_service` and `question_draw_service` support all five canonical filters. Recheck candidates after results return and again in `select_question`.

- [ ] **Step 4: Run GREEN and existing tool tests**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_distribution_tool_contract.py backend/tests/chat/test_tools.py backend/tests/chat/test_interview_mcp_tools.py backend/tests/services/test_question_draw_service.py -q
```

Expected: all pass; LLM supplied types cannot bypass the controller and legacy `hr` is observable only as normalized `behavioral`.

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/chat/tool_gateway.py backend/app/agents/chat/tools.py backend/app/mcp_server/app.py backend/app/mcp_server/interview_tools.py backend/app/services/fts_service.py backend/app/services/question_draw_service.py backend/tests/chat/test_distribution_tool_contract.py backend/tests/chat/test_tools.py backend/tests/chat/CLAUDE.md
git commit -m "feat(backend): enforce distribution types at tool gateway"
```

## Task 8: Add backend alignment integration tests and the opt-in real SSE verifier

**Files:**
- Create: `backend/tests/chat/test_interview_distribution_e2e.py`
- Create: `backend/tests/chat/test_interview_distribution_e2e_verifier.py`
- Create: `backend/scripts/verify_interview_distribution_e2e.py`
- Modify: `backend/scripts/CLAUDE.md`, `backend/tests/chat/CLAUDE.md`

**Interfaces:**
- `verify_interview_distribution_e2e.py --report <path> --target-question-count <n> --mode <system_default|selected_experience|custom>` exits nonzero for mismatch and writes a JSON report.
- The report contains `facts_recomputed`, `stats_response`, `distribution_plan`, `coverage_events`, `execution`, `comparison`, and `verdict`.

- [ ] **Step 1: Write RED deterministic full-chain test**

```python
def test_default_facts_stats_plan_and_execution_are_aligned(test_db):
    facts = recompute_public_facts(test_db, "agent_llm")
    stats = get_distribution_default(test_db, "agent_llm")
    plan = compile_distribution_plan(test_db, user_id=1, job_position="agent_llm", request_override=None, preference=None)
    events = simulate_distribution_controller(plan, seeds=range(1000))
    assert stats["raw_counts"] == facts["raw_counts"]
    assert plan["stats_version"] == stats["stats_version"]
    assert mean_distribution(events) == pytest.approx(plan["expected_distribution"], abs=0.03)
```

- [ ] **Step 2: Run RED**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_interview_distribution_e2e.py backend/tests/chat/test_interview_distribution_e2e_verifier.py -q
```

Expected: FAIL because no recomputation/comparison verifier exists.

- [ ] **Step 3: Implement deterministic comparison and real-script guard**

The pytest E2E uses seeded, canned candidate signals and never calls a network or LLM. The manual script must begin with:

```python
if os.environ.get("RUN_REAL_INTERVIEW_DISTRIBUTION_E2E") != "1":
    raise SystemExit("Set RUN_REAL_INTERVIEW_DISTRIBUTION_E2E=1 to run real distribution E2E")
```

The real script authenticates, obtains the default endpoint, creates a conversation, drives HTTP/SSE turns using canned or configured candidate replies, and fails if the plan version differs from the retrieved statistics, if a counted SSE event lacks the plan ID/type, if execution violates a bound without an allowed reason, or if its recomputation disagrees with the stats response.

- [ ] **Step 4: Run GREEN deterministic E2E and test parser suite**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/chat/test_interview_distribution_e2e.py backend/tests/chat/test_interview_distribution_e2e_verifier.py -q
```

Expected: all pass and prove the deterministic controller's multi-session mean is within 3 percentage points of the plan.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/chat/test_interview_distribution_e2e.py backend/tests/chat/test_interview_distribution_e2e_verifier.py backend/scripts/verify_interview_distribution_e2e.py backend/scripts/CLAUDE.md backend/tests/chat/CLAUDE.md
git commit -m "test(backend): verify interview distribution alignment"
```

## Task 9: Add frontend API wrappers and editable settings sliders

**Files:**
- Create: `frontend/src/services/interviewDistributionApi.js`
- Modify: `frontend/src/api/index.js`
- Create: `frontend/src/components/business/InterviewDistributionSettings.vue`
- Modify: `frontend/src/components/business/SettingsInterview.vue`
- Create: `frontend/tests/e2e/interview-distribution-settings.spec.js`
- Modify: `frontend/src/services/CLAUDE.md`, `frontend/src/components/business/CLAUDE.md`, `frontend/CLAUDE.md`

**Interfaces:**
- Frontend service exports `getDistributionDefault()`, `getDistributionPreference()`, and `saveDistributionPreference(payload)`.
- `InterviewDistributionSettings` accepts `jobPosition` and emits `saved` with the normalized API response.
- Custom slider state contains all five canonical keys and uses integer percentages summing to 100 before save.

- [ ] **Step 1: Write Playwright RED test for system/default/custom settings**

```javascript
test('user can inspect system defaults and save a normalized custom distribution', async ({ page }) => {
  const defaultStats = {
    stats_version: 12, recommended_total_count: 10, confidence: 'high',
    distribution: { project_followup: 0.1, knowledge_probe: 0.5, algorithm_coding: 0.15, system_design: 0.15, behavioral: 0.1 },
  }
  const systemDefaultPreference = { mode: 'system_default', target_question_count: 10, custom_distribution: null }
  let savedPayload = null
  await page.route('**/api/interview/distribution/default**', route => route.fulfill({ json: { status: 'success', data: defaultStats } }))
  await page.route('**/api/profile/interview-distribution-preference**', route => route.fulfill({ json: { status: 'success', data: systemDefaultPreference } }))
  await page.route('**/api/profile/interview-distribution-preference', async route => {
    savedPayload = route.request().postDataJSON()
    await route.fulfill({ json: { status: 'success', data: savedPayload } })
  })
  await page.goto('/settings')
  await page.getByRole('button', { name: '自定义分布' }).click()
  await page.getByLabel('项目深挖').fill('25')
  await page.getByRole('button', { name: '保存面试分布' }).click()
  await expect.poll(() => savedPayload.custom_distribution.project_followup).toBe(0.25)
  expect(Object.values(savedPayload.custom_distribution).reduce((a, b) => a + b, 0)).toBe(1)
})
```

- [ ] **Step 2: Run RED**

```bash
cd frontend && npm run test:e2e -- interview-distribution-settings.spec.js
```

Expected: FAIL because no service, controls, or save endpoint use exists.

- [ ] **Step 3: Implement service and shadcn/reka settings component**

Use the existing `http.js` helpers in `interviewDistributionApi.js`; re-export from `api/index.js`. Build the settings UI with Reka/shadcn slider primitives and accessible numeric inputs. System-default and selected-experience modes show computed read-only values with source/sample/version/confidence; custom mode enables controls. The component normalizes the last changed percentage so all five integers total 100, blocks save otherwise, and includes target primary-question count plus reset-to-system-default action.

- [ ] **Step 4: Run GREEN and production build**

```bash
cd frontend && npm run test:e2e -- interview-distribution-settings.spec.js && npm run build
```

Expected: Playwright passes and Vite build exits 0.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/services/interviewDistributionApi.js frontend/src/api/index.js frontend/src/components/business/InterviewDistributionSettings.vue frontend/src/components/business/SettingsInterview.vue frontend/tests/e2e/interview-distribution-settings.spec.js frontend/src/services/CLAUDE.md frontend/src/components/business/CLAUDE.md frontend/CLAUDE.md
git commit -m "feat(frontend): add interview distribution settings"
```

## Task 10: Support one-time frontend overrides and render live plan progress

**Files:**
- Create: `frontend/src/components/business/DistributionPlanProgress.vue`
- Modify: `frontend/src/components/business/NewChatModal.vue`
- Modify: `frontend/src/components/business/ChatView.vue`
- Modify: `frontend/src/services/chatApi.js`
- Create: `frontend/tests/e2e/interview-distribution-chat.spec.js`
- Modify: `frontend/src/components/business/CLAUDE.md`

**Interfaces:**
- NewChatModal emits `distribution_override` only when the user selects “本次临时调整”; it has the validated five-key structure expected by `CreateConversationRequest`.
- `DistributionPlanProgress` receives `{ plan, events, result }`, derives counts only from `counts_toward_target === true`, and renders planned/actual/bounds/status without inventing values.

- [ ] **Step 1: Write RED conversation creation and SSE progress test**

```javascript
test('one-time override is sent and counted SSE events render against the frozen plan', async ({ page }) => {
  const createConversationWithPlan = {
    status: 'success', data: {
      id: 'distribution-e2e', opening_message: '请自我介绍。',
      metadata: { interview_config: { distribution_plan: {
        plan_id: 'p', target_question_count: 8,
        soft_target_counts: { project_followup: 1, knowledge_probe: 4, algorithm_coding: 1, system_design: 1, behavioral: 1 },
        allowed_counts: { project_followup: { min: 0, max: 2 }, knowledge_probe: { min: 3, max: 5 }, algorithm_coding: { min: 0, max: 2 }, system_design: { min: 0, max: 2 }, behavioral: { min: 0, max: 2 } },
      } } },
    },
  }
  const countedProjectEvent = { plan_id: 'p', question_type: 'project_followup', counts_toward_target: true, selection_reason: 'target_deficit' }
  await page.route('**/api/chat/conversations', route => {
    const body = route.request().postDataJSON()
    expect(body.distribution_override.target_question_count).toBe(8)
    return route.fulfill({ json: createConversationWithPlan })
  })
  await page.getByRole('button', { name: '本次临时调整' }).click()
  await page.getByLabel('本场主问题数').fill('8')
  await page.getByRole('button', { name: '开始面试' }).click()
  await page.route('**/api/chat/conversations/distribution-e2e/messages', route => route.fulfill({
    contentType: 'text/event-stream',
    body: `data: ${JSON.stringify({ type: 'done', metadata: { coverage_events: [countedProjectEvent] } })}\n\n`,
  }))
  await page.locator('textarea').fill('我负责过一个项目。')
  await page.keyboard.press('Enter')
  await expect(page.getByText('项目深挖 1 / 1')).toBeVisible()
})
```

- [ ] **Step 2: Run RED**

```bash
cd frontend && npm run test:e2e -- interview-distribution-chat.spec.js
```

Expected: FAIL because NewChatModal does not submit an override and ChatView does not render distribution events.

- [ ] **Step 3: Implement modal override and progress rendering**

Fetch the current default/preference when the dialog opens; preserve the saved preference unless the user enables the local override. Send the override unchanged through `chatApi.createConversation`. Extend ChatView's SSE handler to retain `coverage_events` and `distribution_result` from done metadata, then pass the immutable plan plus event list to `DistributionPlanProgress`. Do not calculate an "actual" value from non-counted conversation events.

- [ ] **Step 4: Run GREEN and full frontend smoke suite**

```bash
cd frontend && npm run test:e2e -- interview-distribution-chat.spec.js && npm run test && npm run build
```

Expected: all commands exit 0; a frontend override, server plan, and shown event counts have matching canonical keys.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/business/DistributionPlanProgress.vue frontend/src/components/business/NewChatModal.vue frontend/src/components/business/ChatView.vue frontend/src/services/chatApi.js frontend/tests/e2e/interview-distribution-chat.spec.js frontend/src/components/business/CLAUDE.md
git commit -m "feat(frontend): show and override interview distribution plans"
```

## Task 11: Run complete alignment gates and record real E2E evidence

**Files:**
- Modify: `docs/superpowers/specs/2026-07-11-interview-dimension-distribution.md` only if verified implementation decisions changed its stated contract.
- Modify: `README.md` only if the README checklist is triggered by the implemented routes/services/components.
- Create: `docs/tdd-reports/2026-07-11-interview-distribution-quality-control/test_report.md`
- Modify: all affected `CLAUDE.md` files identified by prior tasks.

**Interfaces:**
- Final report includes exact commands, test counts, generated `stats_version`, `plan_id`, and path to the real E2E JSON report. It does not claim live success without an actual opt-in run.

- [ ] **Step 1: Run all deterministic backend gates**

```bash
docker compose --profile test run --rm test uv run pytest backend/tests/interview/test_interview_distribution_storage.py backend/tests/interview/test_interview_distribution_stats.py backend/tests/interview/test_interview_distribution_api.py backend/tests/pipeline/test_interview_distribution_write_paths.py backend/tests/chat/test_interview_distribution_plan.py backend/tests/chat/test_distribution_controller.py backend/tests/chat/test_distribution_tool_contract.py backend/tests/chat/test_interview_distribution_e2e.py backend/tests/chat/test_interview_distribution_e2e_verifier.py -q
docker compose --profile test run --rm test uv run pytest backend/tests/chat/ backend/tests/interview/ backend/tests/pipeline/ backend/tests/infra/ -q
```

Expected: both commands exit 0.

- [ ] **Step 2: Run full frontend gates**

```bash
cd frontend && npm run test:e2e -- interview-distribution-settings.spec.js interview-distribution-chat.spec.js && npm run test && npm run build
```

Expected: all commands exit 0.

- [ ] **Step 3: Deploy the backend/frontend change and run opt-in real verifier**

```bash
./deploy/docker-deploy.sh update
RUN_REAL_INTERVIEW_DISTRIBUTION_E2E=1 docker compose exec backend uv run python backend/scripts/verify_interview_distribution_e2e.py --report backend/data/evaluations/interview-distribution-e2e.json --mode system_default --target-question-count 10
```

Expected: verifier exits 0 and report verdict is `pass`, with fact recomputation equal to the stats response, plan `stats_version` equal to the response version, every counted SSE event linked to the plan, and execution within bounds or carrying an allowed structured deviation reason.

- [ ] **Step 4: Inspect, record, and commit evidence**

```bash
git status --short
git diff --check
git add docs/tdd-reports/2026-07-11-interview-distribution-quality-control/test_report.md README.md docs/superpowers/specs/2026-07-11-interview-dimension-distribution.md
git commit -m "docs: record interview distribution verification"
```

Write the report with actual command output and report-path reference. If the opt-in real verifier is unavailable because credentials or deployment are absent, document that precise blocker; do not write a passing live-E2E conclusion.

## Plan Self-Review

| Spec requirement | Plan coverage |
|---|---|
| Linked typed facts and safe migration | Tasks 1 and 3 |
| Public stats, median total, posterior ratios, fallback and refresh versioning | Task 2 |
| User-editable default/selected/custom configuration | Tasks 4 and 9 |
| Immutable session plan and auditable selected-experience blend | Task 5 |
| Hard runtime control, prompt alignment, event-derived result | Task 6 |
| Gateway/tool filter enforcement across all five types | Task 7 |
| Deterministic and real HTTP/SSE E2E alignment | Tasks 8 and 11 |
| Frontend one-time override and live progress | Task 10 |
| Documentation, README checklist, Docker verification, real evidence | Task 11 |

Placeholder scan: no unresolved design decision is deferred; all external live-LLM work is explicitly opt-in and has a non-fabricated blocker path.
