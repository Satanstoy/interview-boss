# 修复计划

**Bug ID:** BUG-001, BUG-002, BUG-003
**日期:** 2026-05-07
**优先级:** P0

## 修复步骤

### 步骤 1: 给 `questions_detail` 表添加 `job_position` 列
**文件:** `backend/app/db/connection.py`
**修改类型:** 新增迁移

在 `init_db()` 中现有的 `questions_detail` 迁移逻辑之后，添加 `job_position` 列迁移：
```python
# ── 迁移：questions_detail 添加 job_position 列 ──
qd_col_set = {row[1] for row in cursor.execute("PRAGMA table_info('questions_detail')").fetchall()}
if "job_position" not in qd_col_set:
    conn.execute("ALTER TABLE questions_detail ADD COLUMN job_position TEXT DEFAULT ''")
    # 回填：通过 question_bank 中已有的匹配题目获取 job_position
    conn.execute("""
        UPDATE questions_detail SET job_position = (
            SELECT qb.job_position FROM question_bank qb
            WHERE qb.original_questions LIKE '%' || questions_detail.question || '%'
            AND qb.job_position IS NOT NULL AND qb.job_position != ''
            LIMIT 1
        ) WHERE job_position IS NULL OR job_position = ''
    """)
    # 剩余未匹配的回填为当前岗位
    default_pos = get_current_job_position()
    conn.execute(
        "UPDATE questions_detail SET job_position = ? WHERE job_position IS NULL OR job_position = ''",
        (default_pos,)
    )
    logger.info("已为 questions_detail 表添加 job_position 列并回填")
```

### 步骤 2: 给 `interview` 表添加 `job_position` 列
**文件:** `backend/app/db/connection.py`
**修改类型:** 新增迁移

```python
# ── 迁移：interview 添加 job_position 列 ──
if "job_position" not in interview_col_set:
    conn.execute("ALTER TABLE interview ADD COLUMN job_position TEXT DEFAULT ''")
    default_pos = get_current_job_position()
    conn.execute(
        "UPDATE interview SET job_position = ? WHERE job_position IS NULL OR job_position = ''",
        (default_pos,)
    )
    logger.info("已为 interview 表添加 job_position 列并回填")
```

### 步骤 3: 修改 `_insert_details()` 支持 `job_position`
**文件:** `backend/app/db/operations.py:60-67`
**修改类型:** 修正

**修改前:**
```python
def _insert_details(tagged_rows: list):
    with get_db_connection() as conn:
        for tr in tagged_rows:
            conn.execute(
                "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(tr)
            )
        conn.commit()
```

**修改后:**
```python
def _insert_details(tagged_rows: list, job_position: str = ""):
    with get_db_connection() as conn:
        for tr in tagged_rows:
            conn.execute(
                "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*tr, job_position)
            )
        conn.commit()
```

### 步骤 4: 修改 `_insert_interview()` 支持 `job_position`
**文件:** `backend/app/db/operations.py:45-57`
**修改类型:** 修正

在 `_insert_interview()` 的 INSERT 语句中加入 `job_position` 字段。

### 步骤 5: 修改面经提交流程传递 `job_position`
**文件:** `backend/app/routers/submit.py`
**修改类型:** 修正

在提交面经时（约第 420 行），将 `current_pos` 传递给 `_insert_details()`：
```python
current_pos = get_current_job_position()
await run_db(lambda: _insert_details(tagged_rows, job_position=current_pos))
```

同时在 `_insert_interview()` 调用处传递 `job_position`。

### 步骤 6: 修改 `_load()` 函数按岗位过滤
**文件:** `backend/app/routers/master_bank.py:167-177`
**修改类型:** 修正

**修改前:**
```python
def _load():
    with get_db_connection() as conn:
        raw = conn.execute(
            "SELECT qd.id, qd.question, qd.cat1, qd.cat2, qd.tags, qd.diff_tag, qd.url, qd.company, qd.round "
            "FROM questions_detail qd WHERE qd.question IS NOT NULL AND qd.question != ''"
        ).fetchall()
```

**修改后:**
```python
def _load():
    with get_db_connection() as conn:
        raw = conn.execute(
            "SELECT qd.id, qd.question, qd.cat1, qd.cat2, qd.tags, qd.diff_tag, qd.url, qd.company, qd.round "
            "FROM questions_detail qd WHERE qd.question IS NOT NULL AND qd.question != '' AND qd.job_position = ?",
            (current_pos,)
        ).fetchall()
```

### 步骤 7: 优化答案恢复逻辑
**文件:** `backend/app/routers/master_bank.py:330-334`
**修改类型:** 修正

增加对 `original_questions` 列表中每个题目的答案匹配：
```python
for c in cluster_details:
    ai_answer = existing_answers_map.get(c['question'])
    if not ai_answer:
        for oq in c.get('original_questions', []):
            ai_answer = existing_answers_map.get(oq)
            if ai_answer: break
    # 新增：也从 original_question_sources 中的 question 字段匹配
    if not ai_answer:
        for oq_src in c.get('original_question_sources', []):
            ai_answer = existing_answers_map.get(oq_src.get('question', ''))
            if ai_answer: break
```

## 验证方法
1. 提交一条面经，确认 `questions_detail` 中写入了正确的 `job_position`
2. 切换到不同岗位，执行重建题库，确认不会混入其他岗位的面经题目
3. 确认已有 AI 答案在重建后能正确恢复

## 回滚方案
数据库备份在重建前自动创建（`*.bak.build.*`），可直接恢复。代码回滚通过 `git revert`。
