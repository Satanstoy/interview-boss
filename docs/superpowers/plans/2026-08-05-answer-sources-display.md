# 联网搜索来源落库 + 双端展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把答案生成时联网搜索的来源（`search_sources`）落库到 `question_bank.answer_sources` 并在题库卡片（题解）与刷题页（背诵稿）折叠展示，无搜索时零影响。

**Architecture:** 新增 `question_bank.answer_sources TEXT`（JSON 数组 `[{title, url, snippet, published_at}]`，无来源存 NULL）。所有写 `ai_answer` 的生成路径同时写 `answer_sources`；所有"答案复制/保留"路径（聚类合并、题库重建、分享、答案转移、回滚）随答案一并保留/复制。列表/详情 API 返回解析后的数组。前端 QuestionCard（题解参考来源）与 PracticeMode（背诵稿来源）折叠展示，字段为空不渲染。

**Tech Stack:** Python 3.10 / FastAPI / SQLite (WAL) / Vue 3 Composition API / shadcn-vue / @lucide/vue

---

## 关键事实（实现前必须知道）

- `search_web()` 返回 `{"provider": ..., "results": [{title, url, snippet, published_at}]}`，未配置时 `results: []` 不抛错（`backend/app/services/search_service.py:143`）
- 生成路径调用 `prepare_answer_prompt` / `prepare_recitation_prompt`，均返回 `(prompt, sources)`，sources 空数组时回退纯模型（`backend/app/services/answer_enrichment.py`）
- `answer_sources` 存 JSON 字符串，无来源写 `None`（与 `ai_answer` 的 NULL 语义对齐）；API 返回时 `json.loads` 解析成数组，无/解析失败返回 `null`
- `saved_answers` map（`pipeline/batch.py`）当前为 `{question: answer}`，本计划改为 `{question: {"answer": ..., "sources": ...}}`，消费者只有 `writer.py:118-120` 和 `writer.py:194-200` 两处
- `batch_v2.py` 是死代码（仅源码级回归参考），**不改**
- 测试必须在 Docker `test-runtime` 中运行，禁止宿主机直接 pytest

---

### Task 1: 迁移 `answer_sources` 列

**Files:**
- Modify: `backend/app/db/migrations/question_bank.py`
- Modify: `backend/app/db/migrations/__init__.py`
- Create: `backend/tests/services/test_answer_sources.py`

- [ ] **Step 1: 写失败测试**

创建 `backend/tests/services/test_answer_sources.py`：

```python
import json


def test_migration_creates_answer_sources_column(test_db):
    """question_bank 应有 answer_sources 列（联网搜索来源 JSON）"""
    columns = {
        row[1]
        for row in test_db.execute("PRAGMA table_info('question_bank')").fetchall()
    }
    assert "answer_sources" in columns
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_answer_sources.py -q`
Expected: FAIL（`PRAGMA table_info` 无 `answer_sources` 列）

- [ ] **Step 3: 写迁移**

在 `backend/app/db/migrations/question_bank.py` 末尾追加：

```python
def _migration_063_answer_sources(conn):
    """question_bank 增加 answer_sources 列（答案生成时联网搜索的来源，JSON 数组，无来源为 NULL）"""
    cursor = conn.cursor()
    columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info('question_bank')").fetchall()
    }
    if "answer_sources" not in columns:
        cursor.execute(
            "ALTER TABLE question_bank ADD COLUMN answer_sources TEXT DEFAULT NULL"
        )
```

在 `backend/app/db/migrations/__init__.py`：
1. `question_bank` import 块（:11-18）追加 `_migration_063_answer_sources`
2. `_MIGRATIONS` 列表末尾（:170 后）追加 `(63, "answer_sources", _migration_063_answer_sources),`

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_answer_sources.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/db/migrations/question_bank.py backend/app/db/migrations/__init__.py backend/tests/services/test_answer_sources.py
git commit -m "feat(backend): add answer_sources column for search evidence"
```

---

### Task 2: 单题/批量生成写入 `answer_sources`

**Files:**
- Modify: `backend/app/routers/answers.py:95-103, 251-264`
- Test: `backend/tests/services/test_answer_sources.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/services/test_answer_sources.py` 追加：

```python
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_generate_answer_admin_writes_answer_sources():
    """管理员单题生成：有搜索结果时 answer_sources 落库为 JSON"""
    from app.routers.answers import generate_master_answer

    user = {"id": 1, "is_admin": True}
    mock_question = {"id": 10, "question": "什么是微服务？", "ai_answer": None}
    sources = [
        {"title": "Redis 官方文档", "url": "https://redis.io/docs", "snippet": "官方文档"}
    ]

    with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
        mock_run_db.side_effect = [mock_question, None]
        with patch("app.routers.answers.get_db_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_get_conn.return_value = mock_conn
            with patch(
                "app.routers.answers._call_llm_with_retry", new_callable=AsyncMock
            ) as mock_llm:
                mock_llm.return_value = "微服务是一种架构风格..."
                with patch(
                    "app.routers.answers.prepare_answer_prompt",
                    new_callable=AsyncMock,
                ) as mock_prep:
                    mock_prep.return_value = ("prompt", sources)
                    result = await generate_master_answer(10, user)

    assert result["search_sources"] == sources
    sql, params = mock_conn.execute.call_args[0]
    assert "answer_sources" in sql
    assert json.loads(params[1]) == sources


@pytest.mark.asyncio
async def test_generate_answer_writes_null_when_no_sources():
    """无搜索结果（未配置搜索/搜索失败）时 answer_sources 写 NULL"""
    from app.routers.answers import generate_master_answer

    user = {"id": 1, "is_admin": True}
    mock_question = {"id": 10, "question": "什么是微服务？", "ai_answer": None}

    with patch("app.routers.answers.run_db", new_callable=AsyncMock) as mock_run_db:
        mock_run_db.side_effect = [mock_question, None]
        with patch("app.routers.answers.get_db_connection") as mock_get_conn:
            mock_conn = MagicMock()
            mock_get_conn.return_value = mock_conn
            with patch(
                "app.routers.answers._call_llm_with_retry", new_callable=AsyncMock
            ) as mock_llm:
                mock_llm.return_value = "微服务是一种架构风格..."
                with patch(
                    "app.routers.answers.prepare_answer_prompt",
                    new_callable=AsyncMock,
                ) as mock_prep:
                    mock_prep.return_value = ("prompt", [])
                    result = await generate_master_answer(10, user)

    assert result["search_sources"] == []
    sql, params = mock_conn.execute.call_args[0]
    assert "answer_sources" in sql
    assert params[1] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_answer_sources.py -q`
Expected: FAIL（UPDATE SQL 无 `answer_sources`，断言 `"answer_sources" in sql` 失败）

- [ ] **Step 3: 实现单题生成写入**

`backend/app/routers/answers.py` 单题生成 `_update`（:95-103）：

```python
            def _update():
                with get_db_connection() as conn:
                    conn.execute(
                        "UPDATE question_bank SET ai_answer = ?, answer_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (
                            answer,
                            json.dumps(search_sources, ensure_ascii=False)
                            if search_sources
                            else None,
                            question_id,
                        ),
                    )
                    conn.commit()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_answer_sources.py -q`
Expected: PASS（两个新测试）

- [ ] **Step 5: 实现批量生成写入**

`backend/app/routers/answers.py` 批量 `_gen_one`（:251-264）：`prompt, _ = await prepare_answer_prompt(...)` 改为 `prompt, search_sources = await prepare_answer_prompt(...)`，`_update` 改为：

```python
                        def _update():
                            with get_db_connection() as conn:
                                conn.execute(
                                    "UPDATE question_bank SET ai_answer = ?, answer_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                    (
                                        answer,
                                        json.dumps(search_sources, ensure_ascii=False)
                                        if search_sources
                                        else None,
                                        qid,
                                    ),
                                )
                                conn.commit()
```

- [ ] **Step 6: 跑 bank 测试回归**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/bank/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/answers.py backend/tests/services/test_answer_sources.py
git commit -m "feat(backend): persist search sources on answer generation"
```

---

### Task 3: 流水线/Agent 生成写入 `answer_sources`

**Files:**
- Modify: `backend/app/services/submit_service.py:28-53`
- Modify: `backend/app/agents/batch_generate/nodes.py:70-82`
- Test: `backend/tests/services/test_answer_sources.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/services/test_answer_sources.py` 追加：

```python
@pytest.mark.asyncio
async def test_background_generate_answer_writes_answer_sources():
    """后台流水线生成：answer_sources 随 ai_answer 一起写库"""
    from app.services.submit_service import background_generate_answer

    sources = [
        {"title": "Redis 官方文档", "url": "https://redis.io/docs", "snippet": "x"}
    ]

    with patch("app.routers.answers.run_db", new_callable=AsyncMock):
        pass  # 仅确保导入正常

    from unittest.mock import patch as _patch

    with _patch(
        "app.services.submit_service.prepare_answer_prompt",
        new_callable=AsyncMock,
    ) as mock_prep:
        mock_prep.return_value = ("prompt", sources)
        with _patch(
            "app.services.submit_service._call_llm_with_retry",
            new_callable=AsyncMock,
        ) as mock_llm:
            mock_llm.return_value = "答案内容"
            with _patch(
                "app.services.submit_service.run_db", new_callable=AsyncMock
            ) as mock_run_db:
                mock_run_db.side_effect = [None]
                with _patch(
                    "app.services.submit_service.get_db_connection"
                ) as mock_get_conn:
                    mock_conn = MagicMock()
                    mock_get_conn.return_value = mock_conn
                    await background_generate_answer(10, "什么是微服务？", user_id=1)

    sql, params = mock_conn.execute.call_args[0]
    assert "answer_sources" in sql
    assert json.loads(params[1]) == sources
```

注意：`submit_service.py` 内部 `from app.services.answer_enrichment import prepare_answer_prompt` 是在函数内 import 的，patch 目标必须是 `app.services.submit_service.prepare_answer_prompt`（函数内 import 后模块属性仍指向同一个函数对象，patch 模块属性有效——若无效则改用 patch `app.services.answer_enrichment.prepare_answer_prompt` 并让测试先行确认）。

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_answer_sources.py -q`
Expected: FAIL（UPDATE SQL 无 `answer_sources`）

- [ ] **Step 3: 实现流水线写入**

`backend/app/services/submit_service.py:33-38`：

```python
        prompt, search_sources = await prepare_answer_prompt(
            question_text, user_id=user_id
        )
        answer = await _call_llm_with_retry(prompt, user_id=user_id)

        def _update():
            with get_db_connection() as conn:
                conn.execute(
                    "UPDATE question_bank SET ai_answer = ?, answer_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (
                        answer,
                        json.dumps(search_sources, ensure_ascii=False)
                        if search_sources
                        else None,
                        question_id,
                    ),
                )
                conn.commit()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_answer_sources.py -q`
Expected: PASS

- [ ] **Step 5: 实现 batch_generate agent 写入**

`backend/app/agents/batch_generate/nodes.py:72-81`：

```python
        prompt, search_sources = await prepare_answer_prompt(
            question, user_id=state.get("user_id")
        )
        answer = await _call_llm_with_retry(prompt, user_id=state.get("user_id"))
        elapsed = time.monotonic() - start
        quality = evaluate_answer_quality(answer, question)

        # 保存答案
        def _save():
            conn = get_db_connection()
            conn.execute(
                "UPDATE question_bank SET ai_answer = ?, answer_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (
                    answer,
                    json.dumps(search_sources, ensure_ascii=False)
                    if search_sources
                    else None,
                    qid,
                ),
            )
            conn.commit()
```

在文件头部确认 `import json` 已存在（如无则添加）。

- [ ] **Step 6: 跑 pipeline 测试回归**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/pipeline/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/submit_service.py backend/app/agents/batch_generate/nodes.py backend/tests/services/test_answer_sources.py
git commit -m "feat(backend): persist search sources in pipeline and agent generation"
```

---

### Task 4: API 返回 `answer_sources`

**Files:**
- Modify: `backend/app/routers/questions.py:94, 120-152, 239-264`
- Test: `backend/tests/services/test_answer_sources.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/services/test_answer_sources.py` 追加：

```python
@pytest.mark.asyncio
async def test_master_bank_list_returns_answer_sources_array():
    """列表 API 返回解析后的 answer_sources 数组"""
    from app.routers.questions import get_master_bank

    row = {
        "id": 10,
        "question": "什么是微服务？",
        "cat1": "架构",
        "cat2": "",
        "tags": "",
        "difficulty": "L2",
        "ai_answer": "答",
        "sources": "[]",
        "original_questions": "[]",
        "original_question_sources": "[]",
        "is_starred": 0,
        "user_answer": "",
        "review_state": "new",
        "proficiency": 0,
        "review_count": 0,
        "last_rating": None,
        "last_reviewed_at": None,
        "next_review_at": None,
        "interval_days": 0,
        "ease_factor": 2.3,
        "owner_id": None,
        "status": "approved",
        "job_position": "",
        "answer_sources": json.dumps(
            [{"title": "Redis 官方文档", "url": "https://redis.io", "snippet": "x"}]
        ),
    }
    filter_counts = {
        "overall_total": 1,
        "category_counts": [],
        "popular_tags": [],
        "filtered_tag_counts": [],
    }
    user = {"id": 1, "is_admin": True}

    with patch("app.routers.questions.run_db", new_callable=AsyncMock) as mock_run_db:
        mock_run_db.side_effect = [(1, [row]), {}, filter_counts]
        resp = await get_master_bank(page=1, page_size=50, compact=False, filter="all", user=user)

    item = resp["items"][0]
    assert item["answer_sources"] == [
        {"title": "Redis 官方文档", "url": "https://redis.io", "snippet": "x"}
    ]


@pytest.mark.asyncio
async def test_master_bank_list_returns_null_without_sources():
    """无来源时列表 API 返回 answer_sources = None"""
    from app.routers.questions import get_master_bank

    row = {
        "id": 11,
        "question": "什么是微服务？",
        "cat1": "架构",
        "cat2": "",
        "tags": "",
        "difficulty": "L2",
        "ai_answer": "答",
        "sources": "[]",
        "original_questions": "[]",
        "original_question_sources": "[]",
        "is_starred": 0,
        "user_answer": "",
        "review_state": "new",
        "proficiency": 0,
        "review_count": 0,
        "last_rating": None,
        "last_reviewed_at": None,
        "next_review_at": None,
        "interval_days": 0,
        "ease_factor": 2.3,
        "owner_id": None,
        "status": "approved",
        "job_position": "",
        "answer_sources": None,
    }
    filter_counts = {
        "overall_total": 1,
        "category_counts": [],
        "popular_tags": [],
        "filtered_tag_counts": [],
    }
    user = {"id": 1, "is_admin": True}

    with patch("app.routers.questions.run_db", new_callable=AsyncMock) as mock_run_db:
        mock_run_db.side_effect = [(1, [row]), {}, filter_counts]
        resp = await get_master_bank(page=1, page_size=50, compact=False, filter="all", user=user)

    assert resp["items"][0]["answer_sources"] is None
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_answer_sources.py -q`
Expected: FAIL（KeyError `answer_sources`，SQL 未 select）

- [ ] **Step 3: 实现列表 SQL + 响应构造**

`backend/app/routers/questions.py:94` 的 SELECT 中，`qb.ai_answer` 后追加 `qb.answer_sources`：

```python
            full_sql = f"SELECT qb.id, qb.question, qb.cat1, qb.cat2, qb.tags, qb.difficulty, ({dyn_freq_sql}) as dyn_frequency, qb.ai_answer, qb.answer_sources, qb.sources, qb.original_questions, qb.original_question_sources, COALESCE(uqv.is_starred, 0) as is_starred, COALESCE(uqv.user_answer, '') as user_answer, COALESCE(uqr.state, 'new') as review_state, COALESCE(uqr.proficiency, 0) as proficiency, COALESCE(uqr.review_count, 0) as review_count, uqr.last_rating, uqr.last_reviewed_at, uqr.next_review_at, COALESCE(uqr.interval_days, 0) as interval_days, COALESCE(uqr.ease_factor, 2.3) as ease_factor, qb.owner_id, qb.status, qb.job_position {from_clause} LEFT JOIN user_question_view uqv ON uqv.question_bank_id = qb.id AND uqv.user_id = ? LEFT JOIN user_question_review uqr ON uqr.question_bank_id = qb.id AND uqr.user_id = ? {where_clause} {order_clause} LIMIT ? OFFSET ?"
```

在 `get_master_bank` 内 `_query` 函数之后（:104 前后）添加解析 helper（模块级函数放在文件顶部 import 区后）：

```python
def _parse_answer_sources(value):
    """解析 question_bank.answer_sources JSON 字符串为数组；无/非法返回 None"""
    if not value:
        return None
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, list) else None
    except Exception:
        return None
```

响应构造循环（:121-152）中 `d["frequency"] = ...` 之后（:123 附近）加：

```python
        d["answer_sources"] = _parse_answer_sources(d.get("answer_sources"))
```

compact 模式（:141-143，`d["ai_answer"] = None` 附近）加：

```python
            d["answer_sources"] = None
```

- [ ] **Step 4: 实现详情 SQL + 响应**

`backend/app/routers/questions.py:238-245`：

```python
            row = conn.execute(
                f"SELECT qb.id, qb.ai_answer, qb.answer_sources, COALESCE(uqv.user_answer, '') as user_answer, "
                "qb.original_question_sources "
                f"{from_clause} "
                "LEFT JOIN user_question_view uqv ON uqv.question_bank_id = qb.id AND uqv.user_id = ? "
                f"{where_clause} AND qb.id = ?",
                join_params + [user["id"]] + where_params + [question_id],
            ).fetchone()
```

`get_question_detail` 中 `d = dict(row)` 之后（:249 附近）加：

```python
            d["answer_sources"] = _parse_answer_sources(d.get("answer_sources"))
```

- [ ] **Step 5: 运行测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_answer_sources.py -q`
Expected: PASS

- [ ] **Step 6: 跑 bank 测试回归**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/bank/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/questions.py backend/tests/services/test_answer_sources.py
git commit -m "feat(backend): return answer_sources in master bank list and detail APIs"
```

---

### Task 5: 聚类/写库路径保留 `answer_sources`

**Files:**
- Modify: `backend/app/services/pipeline/writer.py:75, 118-130, 194-200`
- Modify: `backend/app/services/pipeline/batch.py:204-217`
- Modify: `backend/app/services/pipeline/compact.py:149-160, 203, 220-222, 257-269, 550-551`
- Modify: `backend/app/services/clustering/full_recluster.py:59-64`
- Modify: `backend/app/routers/admin_review.py:274-297`
- Test: `backend/tests/services/test_answer_sources.py`

- [ ] **Step 1: 写失败测试**

在 `backend/tests/services/test_answer_sources.py` 追加：

```python
def test_compact_merge_inherits_answer_sources_from_merged(test_db):
    """孤岛合并：survivor 无答案时，从被合并题继承 ai_answer 和 answer_sources"""
    from app.services.pipeline.compact import _do_merge_to_existing

    test_db.execute(
        "INSERT INTO question_bank (id, question, ai_answer, answer_sources, frequency, status, sources, original_questions, original_question_sources) "
        "VALUES (1, '什么是 Redis？', NULL, NULL, 2, 'approved', '[]', '[]', '[]')"
    )
    test_db.commit()

    entry = {
        "id": 2,
        "question": "Redis 是什么",
        "sources": [],
        "original_questions": [],
        "original_question_sources": [],
        "ai_answer": "Redis 是内存数据库",
        "answer_sources": json.dumps(
            [{"title": "Redis 官方文档", "url": "https://redis.io", "snippet": "x"}]
        ),
    }
    _do_merge_to_existing(
        1,
        entry,
        operation_type="auto",
        phase="test",
        cat2="",
        operator_id=1,
        confidence=0.5,
    )

    row = test_db.execute(
        "SELECT ai_answer, answer_sources FROM question_bank WHERE id = 1"
    ).fetchone()
    assert row["ai_answer"] == "Redis 是内存数据库"
    assert json.loads(row["answer_sources"]) == [
        {"title": "Redis 官方文档", "url": "https://redis.io", "snippet": "x"}
    ]


def test_apply_matched_keeps_existing_answer_sources(test_db):
    """apply_matched：survivor 已有答案时 answer_sources 保持不变"""
    from app.services.pipeline.writer import apply_matched

    test_db.execute(
        "INSERT INTO question_bank (id, question, ai_answer, answer_sources, frequency, status, sources, original_questions, original_question_sources, job_position, deleted_at) "
        "VALUES (1, '什么是 Redis？', '已有答案', ?, 2, 'approved', '[]', '[]', '[]', '后端开发', NULL)",
        (
            json.dumps(
                [{"title": "Redis 官方文档", "url": "https://redis.io", "snippet": "x"}]
            ),
        ),
    )
    test_db.commit()

    matched = [
        {
            "cluster_id": 1,
            "url": "https://example.com/mianshi",
            "company": "某公司",
            "round": "一面",
            "question": "Redis 集群怎么搭建",
        }
    ]
    apply_matched(test_db, matched, "后端开发", {})

    row = test_db.execute(
        "SELECT ai_answer, answer_sources FROM question_bank WHERE id = 1"
    ).fetchone()
    assert row["ai_answer"] == "已有答案"
    assert json.loads(row["answer_sources"]) == [
        {"title": "Redis 官方文档", "url": "https://redis.io", "snippet": "x"}
    ]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_answer_sources.py -q`
Expected: FAIL（compact 合并后 answer_sources 为 NULL；apply_matched UPDATE 无该列或写入失败）

- [ ] **Step 3: 实现 writer.py**

`backend/app/services/pipeline/writer.py:75` SELECT 加字段：

```python
        existing = conn.execute(
            "SELECT id, frequency, sources, original_questions, original_question_sources, ai_answer, answer_sources "
            "FROM question_bank WHERE id = ?",
            (cluster_id,)
        ).fetchone()
```

`writer.py:118-120`：

```python
        ai_answer = existing['ai_answer']
        answer_sources = existing['answer_sources']
        if not ai_answer:
            saved = saved_answers.get(q)
            if saved:
                ai_answer = saved['answer']
                answer_sources = saved.get('sources')
```

`writer.py:122-130` UPDATE：

```python
        conn.execute(
            "UPDATE question_bank SET frequency = ?, sources = ?, original_questions = ?, "
            "original_question_sources = ?, ai_answer = COALESCE(?, ai_answer), "
            "answer_sources = COALESCE(?, answer_sources), "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (len(oqs), json.dumps(sources, ensure_ascii=False),
             json.dumps(oqs, ensure_ascii=False),
             json.dumps(oqs_src, ensure_ascii=False),
             ai_answer, answer_sources, cluster_id)
        )
```

`writer.py:194-200`（insert_new_clusters 答案复用）：

```python
        ai_answer = None
        answer_sources = None
        for oq in entry['original_questions']:
            saved = saved_answers.get(oq)
            if saved:
                ai_answer = saved['answer']
                answer_sources = saved.get('sources')
                break
        if ai_answer:
            conn.execute(
                "UPDATE question_bank SET ai_answer = ?, answer_sources = ? WHERE id = ?",
                (ai_answer, answer_sources, new_id),
            )
```

- [ ] **Step 4: 实现 batch.py saved_answers 结构**

`backend/app/services/pipeline/batch.py:204-217`：

```python
    saved_answers = {}
```

```python
                existing = conn.execute(
                    "SELECT question, original_questions, ai_answer, answer_sources "
                    "FROM question_bank "
                    "WHERE sources LIKE ? AND ai_answer IS NOT NULL AND ai_answer != '' AND job_position = ?",
                    (source_url, current_pos),
                ).fetchall()
                for r in existing:
                    saved = {"answer": r["ai_answer"], "sources": r["answer_sources"]}
                    saved_answers[r["question"]] = saved
                    for oq in json.loads(r["original_questions"] or "[]"):
                        if oq and oq not in saved_answers:
                            saved_answers[oq] = saved
```

（以文件内实际代码为准调整缩进；`json` 已在 batch.py 顶部 import）

- [ ] **Step 5: 实现 compact.py**

`compact.py:151-154` `_snapshot_question` SELECT 加字段：

```python
    row = conn.execute(
        "SELECT id, question, cat1, cat2, tags, difficulty, frequency, "
        "ai_answer, answer_sources, sources, original_questions, original_question_sources, "
        "status, job_position, created_at, updated_at "
        "FROM question_bank WHERE id = ?",
        (qb_id,),
    ).fetchone()
```

`compact.py:203` `_do_merge_to_existing` SELECT 加字段：

```python
    existing = conn.execute(
        "SELECT question, sources, original_questions, original_question_sources, ai_answer, answer_sources "
        "FROM question_bank WHERE id = ?",
        (survivor_id,),
    ).fetchone()
```

`compact.py:220-222`：

```python
    s_ai_answer = existing["ai_answer"]
    s_answer_sources = existing["answer_sources"]
    if not s_ai_answer:
        s_ai_answer = entry.get("ai_answer")
        s_answer_sources = entry.get("answer_sources")
```

`compact.py:257-269` UPDATE：

```python
    conn.execute(
        "UPDATE question_bank SET frequency = ?, sources = ?, "
        "original_questions = ?, original_question_sources = ?, "
        "ai_answer = ?, answer_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (
            max(1, len(s_oqs)),
            json.dumps(s_src, ensure_ascii=False),
            json.dumps(s_oqs, ensure_ascii=False),
            json.dumps(s_oqs_src, ensure_ascii=False),
            s_ai_answer,
            s_answer_sources,
            survivor_id,
        ),
    )
```

`compact.py:550-551`（`compact_singletons_in_db` 加载页）SELECT 加字段：

```python
            rows = conn.execute(
                "SELECT id, question, cat1, cat2, tags, difficulty, frequency, sources, "
                "original_questions, original_question_sources, ai_answer, answer_sources "
                "FROM question_bank "
                "WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL "
                "AND frequency = 1 "
                "ORDER BY id LIMIT ? OFFSET ?",
                (_SINGLETONS_PAGE_SIZE, _offset),
            ).fetchall()
```

- [ ] **Step 6: 实现 full_recluster.py**

`full_recluster.py:59-64` SELECT 加字段：

```python
                entry = conn.execute(
                    "SELECT id, question, cat1, cat2, tags, difficulty, frequency, "
                    "sources, original_questions, original_question_sources, ai_answer, answer_sources "
                    "FROM question_bank WHERE id = ?",
                    (m,),
                ).fetchone()
```

（`entry_dict = dict(entry)` 自动携带 `answer_sources`，传给 `_do_merge_to_existing` 后由 Task 5 Step 5 的 `s_answer_sources = entry.get("answer_sources")` 继承）

- [ ] **Step 7: 实现 admin_review.py 回滚**

`admin_review.py:275-296` 回滚 UPDATE：

```python
                    conn.execute(
                        "UPDATE question_bank SET "
                        "question = ?, cat1 = ?, cat2 = ?, tags = ?, difficulty = ?, "
                        "frequency = ?, ai_answer = ?, answer_sources = ?, sources = ?, "
                        "original_questions = ?, original_question_sources = ?, "
                        "status = ?, job_position = ?, "
                        "updated_at = CURRENT_TIMESTAMP "
                        "WHERE id = ?",
                        (
                            pre_snapshot.get("question", ""),
                            pre_snapshot.get("cat1", ""),
                            pre_snapshot.get("cat2", ""),
                            pre_snapshot.get("tags", ""),
                            pre_snapshot.get("difficulty", ""),
                            pre_snapshot.get("frequency", 1),
                            pre_snapshot.get("ai_answer", ""),
                            pre_snapshot.get("answer_sources"),
                            pre_snapshot.get("sources", "[]"),
                            pre_snapshot.get("original_questions", "[]"),
                            pre_snapshot.get("original_question_sources", "[]"),
                            pre_snapshot.get("status", "approved"),
                            pre_snapshot.get("job_position", ""),
                            survivor_id,
                        ),
                    )
```

（`pre_snapshot` 由 Task 5 Step 5 修改后的 `_snapshot_question` 生成，新快照含 `answer_sources`；旧快照缺该键时 `pre_snapshot.get("answer_sources")` 返回 None，安全）

- [ ] **Step 8: 运行测试确认通过**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/services/test_answer_sources.py -q`
Expected: PASS

- [ ] **Step 9: 跑 pipeline/clustering 测试回归**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/pipeline/ backend/tests/services/clustering/ -q`
Expected: PASS（`saved_answers` 结构变化不得破坏 `test_batch_optimization.py` 等既有测试；若有断言直接比较 `saved_answers[...] == "答案字符串"` 的用例，需同步更新为 `["answer"]`）

- [ ] **Step 10: Commit**

```bash
git add backend/app/services/pipeline/writer.py backend/app/services/pipeline/batch.py backend/app/services/pipeline/compact.py backend/app/services/clustering/full_recluster.py backend/app/routers/admin_review.py backend/tests/services/test_answer_sources.py
git commit -m "feat(backend): preserve answer_sources through clustering and merge paths"
```

---

### Task 6: 重建恢复与分享/合并转移

**Files:**
- Modify: `backend/app/routers/bank_build.py:211-215, 302-328`
- Modify: `backend/app/worker.py:253-257, 349-373`
- Modify: `backend/app/routers/questions_pkg/share.py:131-150`
- Modify: `backend/app/routers/questions_pkg/mutations.py:197-204, 270-272`

- [ ] **Step 1: 实现 bank_build.py 恢复**

`bank_build.py:211-215`：

```python
                existing = conn.execute(
                    "SELECT question, ai_answer, answer_sources FROM question_bank WHERE ai_answer IS NOT NULL AND ai_answer != '' AND job_position = ?",
                    (current_pos,),
                ).fetchall()
                return raw, {
                    r["question"]: {"answer": r["ai_answer"], "sources": r["answer_sources"]}
                    for r in existing
                }
```

`bank_build.py:302-328` `_restore_answers`：

```python
        def _restore_answers():
            with get_db_connection() as conn:
                restored = 0
                rows = conn.execute(
                    "SELECT id, question, original_questions FROM question_bank "
                    "WHERE job_position = ? AND owner_id IS NULL AND (ai_answer IS NULL OR ai_answer = '')",
                    (current_pos,),
                ).fetchall()
                for r in rows:
                    saved = existing_answers_map.get(r["question"])
                    ai_answer = saved["answer"] if saved else None
                    answer_sources = saved["sources"] if saved else None
                    if not ai_answer:
                        try:
                            oqs = json.loads(r["original_questions"] or "[]")
                            for oq in oqs:
                                saved = existing_answers_map.get(oq)
                                if saved and saved["answer"]:
                                    ai_answer = saved["answer"]
                                    answer_sources = saved["sources"]
                                    break
                        except Exception:
                            pass
                    if ai_answer:
                        conn.execute(
                            "UPDATE question_bank SET ai_answer = ?, answer_sources = ? WHERE id = ?",
                            (ai_answer, answer_sources, r["id"]),
                        )
                        restored += 1
                conn.commit()
                return restored
```

- [ ] **Step 2: 实现 worker.py 恢复**

`worker.py:253-257`：

```python
                existing = conn.execute(
                    "SELECT question, ai_answer, answer_sources FROM question_bank WHERE ai_answer IS NOT NULL AND ai_answer != '' AND job_position = ?",
                    (current_pos,)
                ).fetchall()
                return raw, {
                    r['question']: {"answer": r['ai_answer'], "sources": r['answer_sources']}
                    for r in existing
                }
```

`worker.py:349-373` `_restore_answers`（与 bank_build 相同的改法，含 oqs 循环与 UPDATE 双字段）：

```python
        def _restore_answers():
            with get_db_connection() as conn:
                restored = 0
                rows = conn.execute(
                    "SELECT id, question, original_questions FROM question_bank "
                    "WHERE job_position = ? AND owner_id IS NULL AND (ai_answer IS NULL OR ai_answer = '')",
                    (current_pos,)
                ).fetchall()
                for r in rows:
                    saved = existing_answers_map.get(r['question'])
                    ai_answer = saved['answer'] if saved else None
                    answer_sources = saved['sources'] if saved else None
                    if not ai_answer:
                        try:
                            import json
                            oqs = json.loads(r['original_questions'] or '[]')
                            for oq in oqs:
                                saved = existing_answers_map.get(oq)
                                if saved and saved['answer']:
                                    ai_answer = saved['answer']
                                    answer_sources = saved['sources']
                                    break
                        except Exception:
                            pass
                    if ai_answer:
                        conn.execute(
                            "UPDATE question_bank SET ai_answer = ?, answer_sources = ? WHERE id = ?",
                            (ai_answer, answer_sources, r['id'])
                        )
                        restored += 1
                conn.commit()
                return restored
```

- [ ] **Step 3: 实现 share.py 分享复制**

`share.py:131-150` INSERT 加列（`row` 来自 `SELECT *`，`:111`，自动包含 `answer_sources`）：

```python
    cur = conn.execute(
        "INSERT INTO question_bank "
        "(question, cat1, cat2, tags, difficulty, frequency, sources, "
        "original_questions, original_question_sources, ai_answer, answer_sources, owner_id, "
        "submitted_by, status, job_position) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, NULL, ?, 'pending', ?)",
        (
            row["question"],
            row["cat1"],
            row["cat2"],
            row["tags"],
            row["difficulty"],
            row["sources"],
            row["original_questions"],
            row["original_question_sources"],
            row["ai_answer"],
            row["answer_sources"],
            user_id,
            row["job_position"],
        ),
    )
```

（`_merge_private_into_public` 不动：该路径不转移 ai_answer，只合并 sources/oqs）

- [ ] **Step 4: 实现 mutations.py 答案转移**

`mutations.py:197-204` 两个 SELECT 加字段：

```python
                source = conn.execute(
                    "SELECT id, question, sources, original_questions, original_question_sources, ai_answer, answer_sources FROM question_bank WHERE id = ?",
                    (question_id,)
                ).fetchone()
                target = conn.execute(
                    "SELECT id, question, sources, original_questions, original_question_sources, ai_answer, answer_sources FROM question_bank WHERE id = ?",
                    (req.target_id,)
                ).fetchone()
```

`mutations.py:270-272`：

```python
                # 转移 ai_answer（目标没有答案时才转移）
                if source['ai_answer'] and not target['ai_answer']:
                    conn.execute(
                        "UPDATE question_bank SET ai_answer = ?, answer_sources = ? WHERE id = ?",
                        (source['ai_answer'], source['answer_sources'], req.target_id)
                    )
```

- [ ] **Step 5: 跑 bank/pipeline 测试回归**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/bank/ backend/tests/pipeline/ -q`
Expected: PASS

- [ ] **Step 6: 运行 compileall 确认无语法错误**

Run: `docker compose --profile test run --rm test uv run python -m compileall -q backend/app backend/worker.py`
Expected: 无输出（退出码 0）

- [ ] **Step 7: Commit**

```bash
git add backend/app/routers/bank_build.py backend/app/worker.py backend/app/routers/questions_pkg/share.py backend/app/routers/questions_pkg/mutations.py
git commit -m "feat(backend): carry answer_sources through rebuild, share and merge transfer"
```

---

### Task 7: 前端题解「参考来源」折叠展示

**Files:**
- Modify: `frontend/src/components/business/QuestionCard.vue`
- Modify: `frontend/src/composables/useQuestionOps.js:135-148`

- [ ] **Step 1: 实现 useQuestionOps 更新来源**

`frontend/src/composables/useQuestionOps.js:135-148` `generateAnswer`：

```js
  const generateAnswer = async (question) => {
    if (!await ensureModelReady({ action: 'AI 生成答案' })) return
    question._isLoadingAnswer = true
    try {
      const data = await api.generateAnswer(question.id)
      if (currentUser.value?.is_admin) {
        question.ai_answer = data.answer
      } else {
        question.user_answer = data.answer
      }
      question.answer_sources = data.search_sources || null
      toast.success('答案生成成功')
    } catch (e) { toast.error('生成失败：' + getFriendlyError(e)) }
    finally { question._isLoadingAnswer = false }
  }
```

- [ ] **Step 2: 实现 QuestionCard script**

`frontend/src/components/business/QuestionCard.vue` script 区（`safeUrl` import 之后，:252 附近）添加：

```js
import { computed } from 'vue'

const answerSources = computed(() => {
  const raw = props.question.answer_sources
  return Array.isArray(raw) ? raw : []
})
```

（若 `computed` 已在文件顶部 import，则只加 `answerSources`；以文件现有 import 为准，缺失的补上）

- [ ] **Step 3: 实现 QuestionCard 模板**

在 `QuestionCard.vue` 答案内容块（:155 `v-html="cachedMarkdown"` 的 div）结束之后、:158 `v-else-if="isLoadingDetail"` 之前，插入：

```html
            <!-- 参考来源（答案生成时的联网搜索证据） -->
            <div v-if="answerSources.length" class="border-t border-border/50 mt-3">
              <button @click="props.question._showAnswerSources = !props.question._showAnswerSources"
                class="w-full px-4 py-2 flex items-center gap-2 text-caption font-medium text-muted-foreground hover:text-foreground hover:bg-muted/50 dark:hover:bg-muted/25 transition-colors">
                <svg class="size-3 transform transition-transform duration-200" :class="props.question._showAnswerSources ? 'rotate-180' : ''" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 9l-7 7-7-7"/></svg>
                <span>参考来源</span>
                <span class="text-label text-muted-foreground ml-0.5">{{ answerSources.length }}条</span>
              </button>
              <div v-if="props.question._showAnswerSources" class="px-4 pb-4 flex flex-col gap-1.5">
                <div v-for="(src, idx) in answerSources" :key="src.url || idx"
                  class="bg-card border border-border rounded-md p-2.5 flex items-start gap-2.5">
                  <span class="text-caption text-muted-foreground font-mono shrink-0 mt-0.5">{{ idx + 1 }}.</span>
                  <div class="flex-1 min-w-0">
                    <a :href="safeUrl(src.url)" target="_blank" rel="noopener noreferrer"
                      class="text-xs font-medium text-primary hover:underline break-all">{{ src.title || src.url }}</a>
                    <p v-if="src.snippet" class="text-xs text-muted-foreground mt-0.5 line-clamp-2">{{ src.snippet }}</p>
                  </div>
                </div>
              </div>
            </div>
```

（模板中 `props` 在 `<script setup>` 模板里可直接用 `question`；请用 `question._showAnswerSources` 替代 `props.question._showAnswerSources`，与文件中 :196、:295 的既有写法 `question._showSources`/`props.question._showAnswer` 保持一致）

- [ ] **Step 4: 构建验证**

Run: `cd frontend && npm run build`
Expected: `✓ built in ...`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/business/QuestionCard.vue frontend/src/composables/useQuestionOps.js
git commit -m "feat(frontend): show answer sources on question card"
```

---

### Task 8: 前端背诵稿「参考来源」折叠展示

**Files:**
- Modify: `frontend/src/composables/usePractice.js:40-50, 89-104`
- Modify: `frontend/src/components/business/PracticeMode.vue`

- [ ] **Step 1: 实现 usePractice.js 保存来源**

`frontend/src/composables/usePractice.js` `initQuestionState`（:40-50 区域）加一行：

```js
  qState._recitationSources = []
  qState._showRecitationSources = false
```

`generateRecitationForQuestion`（:89-104）：

```js
export async function generateRecitationForQuestion(question, qState) {
  const toast = useToast()
  const { ensureModelReady } = useModelGuard()
  if (!await ensureModelReady({ action: '生成背诵稿' })) return
  qState._isGeneratingRecitation = true
  try {
    const data = await apiGenerateRecitation(question.id)
    qState._recitation = data.answer
    qState._recitationSources = data.search_sources || []
    qState._isEditingRecitation = false
    toast.success('背诵稿已生成')
  } catch (e) {
    toast.error(`生成失败: ${e.message}`)
  } finally {
    qState._isGeneratingRecitation = false
  }
}
```

- [ ] **Step 2: 实现 PracticeMode script**

`frontend/src/components/business/PracticeMode.vue`：
1. `@lucide/vue` import 中加 `ChevronDown`
2. `@/utils/validate.js` 加 `import { safeUrl } from '@/utils/validate.js'`（若已 import 其他内容则合并）

- [ ] **Step 3: 实现 PracticeMode 模板**

在背诵稿内容 div（:133 `v-html="renderMarkdown(qState._recitation)"` 之后）内追加：

```html
              <div v-if="qState._recitationSources.length" class="mt-3 border-t border-border/70 pt-3">
                <button type="button"
                  class="flex items-center gap-1.5 text-xs font-medium text-muted-foreground hover:text-foreground"
                  @click="qState._showRecitationSources = !qState._showRecitationSources">
                  <ChevronDown class="size-3.5 transition-transform" :class="qState._showRecitationSources ? 'rotate-180' : ''" />
                  参考来源（{{ qState._recitationSources.length }}）
                </button>
                <div v-if="qState._showRecitationSources" class="mt-2 flex flex-col gap-1.5">
                  <a v-for="(src, idx) in qState._recitationSources" :key="src.url || idx"
                    :href="safeUrl(src.url)" target="_blank" rel="noopener noreferrer"
                    class="flex items-start gap-1.5 text-xs text-primary hover:underline break-all">
                    <span class="font-mono shrink-0">{{ idx + 1 }}.</span>
                    <span class="min-w-0">{{ src.title || src.url }}</span>
                  </a>
                </div>
              </div>
```

- [ ] **Step 4: 构建验证**

Run: `cd frontend && npm run build`
Expected: `✓ built in ...`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/composables/usePractice.js frontend/src/components/business/PracticeMode.vue
git commit -m "feat(frontend): show search sources on generated recitation"
```

---

### Task 9: 门禁与文档更新

**Files:**
- Modify: `backend/app/routers/CLAUDE.md`（answers 职责行补 answer_sources 说明）
- Modify: `backend/app/services/CLAUDE.md`（search 相关说明补来源落库）
- Modify: `docs/specs/2026-08-05-answer-dual-layer-leetcode-mode.md`（Phase 4 状态：已实施）
- Modify: `docs/CLAUDE.md` 或 `docs/superpowers/plans/`（本计划文件本身即记录）

- [ ] **Step 1: 更新 CLAUDE.md 文档**

`backend/app/routers/CLAUDE.md` 中 answers 行末尾追加：`；生成时联网搜索来源写入 question_bank.answer_sources 并在列表/详情 API 返回`。
`backend/app/services/CLAUDE.md` search 相关描述补充来源落库语义（如需要）。
`docs/specs/2026-08-05-answer-dual-layer-leetcode-mode.md` 头部 `状态: 待实施` 改为 `状态: 已实施（Phase 4 来源落库与展示，2026-08-05）`。

- [ ] **Step 2: 全量后端测试**

Run: `docker compose --profile test run --rm test uv run pytest backend/tests/ -q`
Expected: 全部 PASS（或仅既有已知失败）

- [ ] **Step 3: 前端 smoke**

Run: `cd frontend && npm run test`
Expected: PASS

- [ ] **Step 4: 门禁（如磁盘/时间允许）**

Run: `./deploy/docker-deploy.sh check`
Expected: 汇总通过（audit 报告可接受）

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/CLAUDE.md backend/app/services/CLAUDE.md docs/specs/2026-08-05-answer-dual-layer-leetcode-mode.md
git commit -m "docs: update CLAUDE.md and spec for answer_sources persistence"
```

---

## 不在范围内（YAGNI）

- 背诵稿来源不落库（随响应返回，仅当次展示）
- 不给 `data.py` 通用更新接口加 answer_sources 防清空校验（该列只由生成/继承路径管理）
- 不改 `batch_v2.py`（死代码）、`clustering_maintenance.py`（审计只读 SELECT，不回写）
- 不做 agent（模拟面试）联网搜索
- 不做旧数据回溯填充（来源为空则不渲染）

## 风险与对策

| 风险 | 对策 |
|------|------|
| `saved_answers` 结构变化破坏 pipeline 既有测试 | Task 5 Step 9 跑 pipeline/clustering 全量，失败同步更新断言 |
| 列表 API 每行 JSON 解析开销 | 来源 ≤5 条、长度受限，解析成本可忽略；compact 模式返回 None |
| 合并历史旧快照无 answer_sources 键 | `pre_snapshot.get("answer_sources")` 返回 None 安全 |
| 前端 `props`/`question` 引用不一致 | Task 7 Step 3 注明沿用文件中既有写法（:196 用 `question._showSources`） |
