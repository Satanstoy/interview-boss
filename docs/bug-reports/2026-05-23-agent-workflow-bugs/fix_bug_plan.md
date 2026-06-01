# 修复计划

**Bug ID:** BUG-005 ~ BUG-010
**日期:** 2026-05-23
**优先级:** P1 > P2 > P3

## 修复步骤

### 步骤 1: BUG-005 — classify_node 传递 user_id
**文件:** `backend/app/agents/submit/classify.py`
**行号:** 94
**修改类型:** 修正

**修改前:**
```python
taxonomy_config = await run_db(get_taxonomy_for_position)
```

**修改后:**
```python
taxonomy_config = await run_db(lambda: get_taxonomy_for_position(user_id=state.get("user_id")))
```

### 步骤 2: BUG-006 — taxonomy children 类型安全解析
**文件:** `backend/app/agents/submit/classify.py`
**行号:** 115
**修改类型:** 修正

**修改前:**
```python
valid_cat2_by_cat1[cname] = set(cat.get("children", []))
```

**修改后:**
```python
children = cat.get("children", [])
valid_cat2_by_cat1[cname] = set(
    c if isinstance(c, str) else c.get("name", "")
    for c in children
)
```

### 步骤 3: BUG-007 — evaluate_tagging_quality 归一化评分
**文件:** `backend/app/agents/shared/quality.py`
**行号:** 35-68
**修改类型:** 修正

**修改后:**
```python
def evaluate_tagging_quality(rows: list[list[str]], valid_cat1: set = None, valid_cat2_by_cat1: dict = None) -> float:
    if not rows:
        return 0.0

    valid_diffs = {"L1-基础", "L2-中等", "L2-中级", "L3-高级", "L3-困难"}
    error_count = 0

    for row in rows:
        if len(row) < 8:
            error_count += 1
            continue
        cat1 = row[4] if len(row) > 4 else ""
        cat2 = row[5] if len(row) > 5 else ""
        diff_tag = row[7] if len(row) > 7 else ""

        has_error = False
        if valid_cat1 and cat1 and cat1 not in valid_cat1 and "未分类" not in cat1:
            has_error = True
        if valid_cat2_by_cat1 and cat1 and cat2:
            expected = valid_cat2_by_cat1.get(cat1, set())
            if expected and cat2 not in expected and "未分类" not in cat2:
                has_error = True
        if diff_tag and diff_tag not in valid_diffs and diff_tag != "未知":
            has_error = True
        if has_error:
            error_count += 1

    error_rate = error_count / len(rows)
    score = 10.0 * (1.0 - error_rate)
    return max(0.0, min(10.0, round(score, 1)))
```

### 步骤 4: BUG-008 — clear_qb_node 使用 with conn 事务管理
**文件:** `backend/app/agents/build/nodes.py`
**行号:** 28-45
**修改类型:** 修正

**修改后:**
```python
async def clear_qb_node(state: BuildBankState) -> dict:
    from app.db.connection import get_db_connection, run_db

    def _clear():
        with get_db_connection() as conn:
            conn.execute("DELETE FROM question_bank")
            conn.execute("DELETE FROM question_position")
            conn.execute("DELETE FROM question_sources")
            conn.execute("DELETE FROM question_original_items")

    await run_db(_clear)
    logger.info("题库已清空")
    return {
        "events": [make_progress_event("tag", "题库已清空，准备重建")],
    }
```

### 步骤 5: BUG-009 — 黑名单改为子串匹配
**文件:** `backend/app/agents/submit/extract.py`
**行号:** 76
**修改类型:** 修正

**修改前:**
```python
q_list = [q for q in q_list if q.strip() and not any(q.strip() == b for b in _EXTRACT_BLACKLIST)]
```

**修改后:**
```python
q_list = [q for q in q_list if q.strip() and not any(b in q for b in _EXTRACT_BLACKLIST)]
```

### 步骤 6: BUG-010 — build 节点使用 run_db 包装
**文件:** `backend/app/agents/build/nodes.py`
**行号:** 14-25 (backup_db_node), 48-66 (load_all_node)
**修改类型:** 修正

**backup_db_node 修改后:**
```python
async def backup_db_node(state: BuildBankState) -> dict:
    from app.db.connection import get_db_connection, run_db

    def _backup():
        db_path = get_db_connection().execute("PRAGMA database_list").fetchone()[2]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = f"{db_path}.bak_{timestamp}"
        shutil.copy2(db_path, backup_path)
        return backup_path

    backup_path = await run_db(_backup)
    logger.info(f"数据库已备份到: {backup_path}")
    return {
        "backup_path": backup_path,
        "events": [make_progress_event("tag", "数据库已备份")],
    }
```

**load_all_node 修改后:**
```python
async def load_all_node(state: BuildBankState) -> dict:
    from app.db.connection import get_db_connection, run_db
    from app.services.pipeline import enqueue_questions

    def _load():
        conn = get_db_connection()
        rows = conn.execute("SELECT id FROM interview WHERE deleted_at IS NULL").fetchall()
        return [r[0] for r in rows]

    interview_ids = await run_db(_load)
    total = 0
    for iid in interview_ids:
        count = enqueue_questions(iid)
        total += count

    logger.info(f"已将 {total} 道题加入队列")
    return {
        "total_questions": total,
        "processed_count": 0,
        "events": [make_progress_event("cluster", f"已加载 {total} 道题，开始聚类")],
    }
```

## 验证方法
1. `uv run pytest backend/tests/test_agent_workflow_bugs.py -v`
2. `uv run pytest backend/tests/ -q` 回归测试

## 回滚方案
每个 bug 修复独立，可通过 `git diff` 逐个回滚。
