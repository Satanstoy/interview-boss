# 修复计划

**Bug ID:** BUG-001 ~ BUG-010
**日期:** 2026-06-05
**优先级排序:** P0 → P1 → P2

---

## 步骤 1: 新增 migration — 修复 merge_history 表 (BUG-001)

**文件:** `backend/app/db/migrations.py`
**修改类型:** 新增

**新增 `_migration_036_merge_history_columns` 函数:**
```python
def _migration_036_merge_history_columns(conn):
    """添加 merge_history 回滚字段 + 创建 merge_feedback 表"""
    # 1. merge_history 添加回滚字段
    existing = {row[1] for row in conn.execute("PRAGMA table_info(merge_history)").fetchall()}
    if 'is_rolled_back' not in existing:
        conn.execute("ALTER TABLE merge_history ADD COLUMN is_rolled_back INTEGER DEFAULT 0")
    if 'rolled_back_at' not in existing:
        conn.execute("ALTER TABLE merge_history ADD COLUMN rolled_back_at TIMESTAMP")
    if 'rolled_back_by' not in existing:
        conn.execute("ALTER TABLE merge_history ADD COLUMN rolled_back_by INTEGER")

    # 2. 创建 merge_feedback 表
    conn.execute("""
        CREATE TABLE IF NOT EXISTS merge_feedback (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merge_history_id INTEGER,
            question_bank_id INTEGER,
            feedback_type TEXT NOT NULL,
            comment TEXT DEFAULT '',
            user_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
```

---

## 步骤 2: Embedding backfill (BUG-003)

**文件:** `backend/app/db/migrations.py`
**修改类型:** 新增

**新增 `_migration_037_backfill_embeddings` 函数:**
```python
def _migration_037_backfill_embeddings(conn):
    """为所有活跃题目生成 embedding（批量处理）"""
    rows = conn.execute(
        "SELECT id, question FROM question_bank "
        "WHERE deleted_at IS NULL AND status = 'approved' AND embedding IS NULL"
    ).fetchall()
    if not rows:
        return
    try:
        from app.services.embedding_service import encode_texts
        batch_size = 64
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            texts = [r['question'] or '' for r in batch]
            embeddings = encode_texts(texts)
            for j, row in enumerate(batch):
                conn.execute(
                    "UPDATE question_bank SET embedding = ? WHERE id = ?",
                    (embeddings[j].tobytes(), row['id'])
                )
        logger.info(f"[Migration 037] backfilled {len(rows)} embeddings")
    except Exception as e:
        logger.warning(f"[Migration 037] embedding backfill failed (will retry on next restart): {e}")
        # 不阻塞 migration，下次重启时重试
```

**注意:** 此 migration 需要在容器内执行（因为需要加载 bge-small-zh-v1.5 模型）。

---

## 步骤 3: 修复 batch_v2.py — 添加 merge_history 记录 (BUG-005)

**文件:** `backend/app/services/pipeline/batch_v2.py`
**修改类型:** 修改

**方案:** 将 batch_v2.py 中的内联合并逻辑替换为调用 `_do_merge_to_existing`（来自 batch.py）

**修改 `_do_match_merge` 闭包 (line 143-232):**
```python
# 原: 内联 SQL 合并
# 改为:
from app.services.pipeline.batch import _do_merge_to_existing

def _do_match_merge(m=match):
    conn = get_db_connection()
    conn.execute("BEGIN")
    try:
        entry = conn.execute(
            "SELECT id, question, cat1, cat2, sources, original_questions, "
            "original_question_sources, ai_answer FROM question_bank WHERE id = ?",
            (m['qd_id'],)
        ).fetchone()
        if entry:
            _do_merge_to_existing(
                m['cluster_id'], dict(entry),
                operation_type='compaction',
                phase='compaction_v2',
                cat2=entry.get('cat2', ''),
                confidence=0.8
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
```

**同样修改 `_do_merge` 闭包 (line 288-362):**

---

## 步骤 4: 修复 full_recluster_hybrid — 完整合并 (BUG-006)

**文件:** `backend/app/services/clustering.py`
**行号:** 1093-1119
**修改类型:** 修改

**修改前:**
```python
def _do_merge(s=survivor_id, m=merged_id, c=confidence):
    conn = get_db_connection()
    conn.execute("BEGIN")
    try:
        conn.execute(
            "UPDATE question_bank SET duplicate_of = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (s, m)
        )
        conn.execute(
            "UPDATE question_bank SET frequency = frequency + 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (s,)
        )
        conn.execute(
            "INSERT INTO merge_history "
            "(survivor_id, merged_ids, merged_questions, pre_snapshot, "
            "operation_type, phase, confidence) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ...
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
```

**修改后:**
```python
def _do_merge(s=survivor_id, m=merged_id, c=confidence):
    from app.services.pipeline.batch import _do_merge_to_existing
    conn = get_db_connection()
    conn.execute("BEGIN")
    try:
        entry = conn.execute(
            "SELECT id, question, cat1, cat2, sources, original_questions, "
            "original_question_sources, ai_answer FROM question_bank WHERE id = ?",
            (m,)
        ).fetchone()
        if entry:
            _do_merge_to_existing(
                s, dict(entry),
                operation_type='three_stage',
                phase='full_recluster',
                cat2=entry.get('cat2', ''),
                confidence=c,
            )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
```

---

## 步骤 5: 修复 "其他" 分类策略 (BUG-008)

**文件:** `backend/app/services/clustering.py`
**行号:** 981-982
**修改类型:** 修改

**修改前:**
```python
if cat2 in ('其他', ''):
    logger.info(f"[V2] Stage 3 [{cat2 or '未分类'}] 跳过（兜底分类，避免误合并）")
    return
```

**修改后:**
```python
if cat2 == '':
    logger.info(f"[V2] Stage 3 [未分类] 跳过（无分类信息）")
    return
# "其他" 分类不再跳过，但对 prompt 增加额外谨慎提示
```

**同时修改 `_V2_GROUP_PROMPT` 增加:**
```
⚠️ "其他"分类下的题目通常不太相关，要特别谨慎合并。只在核心知识点完全相同时才合并。
```
（此提示已存在于 prompt 中，无需修改。只需移除跳过逻辑。）

**文件:** `backend/app/services/pipeline/batch.py`
**行号:** 770-771
**修改类型:** 修改

**修改前:**
```python
skip_cats = {'其他', ''}
```

**修改后:**
```python
skip_cats = {''}  # 只跳过无分类，不再跳过"其他"
```

---

## 步骤 6: 修复 V2 Union-Find 并发问题 (BUG-009)

**文件:** `backend/app/services/clustering.py`
**行号:** 968-1030
**修改类型:** 重构

将共享的 `parent`/`rank` 字典改为每个 cat2 组独立维护，最后统一合并：

```python
# 每个 cat2 组返回本地的 merge_pairs
async def _process_cat2_group(cat2, idx_set):
    local_parent = {}
    local_rank = {}
    # ... 初始化 local_parent/local_rank ...
    # ... LLM 调用 ...
    # ... union-find 合并 ...
    # 提取本地 merge pairs
    local_clusters = {}
    for idx in local_parent:
        root = _union_find(local_parent, idx)
        local_clusters.setdefault(root, []).append(idx)
    return [(members[0], members[1:]) for members in local_clusters.values() if len(members) >= 2]

# 主函数统一处理
all_local_merges = await asyncio.gather(...)
# 全局 union-find 合并
global_parent = {}
global_rank = {}
for group_merges in all_local_merges:
    for rep, members in group_merges:
        for m in members:
            _union_merge(global_parent, global_rank, rep, m)
```

---

## 步骤 7: 更新测试 (BUG-007)

**文件:** `backend/tests/test_clustering_quality.py`
**修改类型:** 修改

1. 更新 prompt 断言：移除 "索引优化"、"TCP为什么是三次握手" 断言，改为检查当前 prompt 中的实际负面案例（如 "Redis 缓存穿透" ≠ "Redis 缓存雪崩"）
2. 更新 migration 导入：`_migration_032_merge_history` → 适配新的 migration 函数

---

## 验证方法

1. **BUG-001/002:** `sqlite3 data/interview-boss.db ".schema merge_history"` 确认包含新列
2. **BUG-003:** `sqlite3 data/interview-boss.db "SELECT COUNT(*) FROM question_bank WHERE embedding IS NOT NULL"` 应返回 325
3. **BUG-004:** 运行 compaction 后 `SELECT COUNT(*) FROM question_bank WHERE frequency=1` 应显著下降
4. **BUG-005/006:** 查看 merge_history 记录确认合并后有完整的 sources 和 original_questions
5. **BUG-007:** `pytest test_clustering_quality.py -v` 应全部通过
6. **BUG-008:** "其他" 分类孤岛率应从 75% 下降

## 回滚方案

1. Migration 036/037 添加的列/表不影响现有功能（ALTER TABLE ADD COLUMN 是向后兼容的）
2. 代码修改可通过 git revert 回滚
3. Embedding backfill 失败不会阻塞系统（降级为无 embedding 模式）
