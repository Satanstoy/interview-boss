# 修复计划

**Bug ID:** BUG-001 ~ BUG-005
**日期:** 2026-06-02
**优先级:** P0 ~ P1

## 修复步骤

### 步骤 1: BUG-002 — 修复置信度 (P0)

**文件:** `backend/app/services/embedding_service.py`
**修改类型:** 新增

新增 `compute_confidence_from_embeddings(emb1, emb2)` 函数:
- sim >= 0.95 → confidence = 0.95
- sim >= 0.85 → confidence = 0.85
- sim >= 0.70 → confidence = 0.75
- sim < 0.70 → confidence = 0.60

**文件:** `backend/app/services/pipeline/batch.py`
**修改类型:** 新增 + 修正

1. 新增 `_compute_merge_confidence(survivor_id, merged_question)` — 从 DB 中读取 embedding 计算置信度
2. `_do_merge_to_existing`: 当 confidence=0 时使用 embedding fallback
3. `compact_singletons_in_db`: 当 conf<=0 时使用 fallback 而非跳过

**文件:** `backend/app/db/migrations.py`
**修改类型:** 新增

新增 `_migration_034_backfill_confidence`: 回填 123 条 confidence=0 的历史记录

### 步骤 2: BUG-004 — 拆分 E 分类 (P1)

**文件:** `backend/app/core/prompts.py` line 100
**修改类型:** 修正

```python
# 修改前
"children": ["E1.算法手撕与数据结构"]
# 修改后
"children": ["E1.数据结构", "E2.算法手撕"]
```

**文件:** `backend/app/services/utils.py`
**修改类型:** 新增

新增 `_TAXONOMY_ALIASES` 别名映射到 `normalize_category`

**文件:** `backend/app/db/migrations.py`
**修改类型:** 新增

新增 `_migration_035_split_e_category`: 关键词分类现有 E 类题目

### 步骤 3: BUG-001 — 添加 cluster_id (P1)

**文件:** `backend/app/db/migrations.py`
**修改类型:** 新增

新增 `_migration_033_cluster_id`: 添加 cluster_id 列并回填

**文件:** `backend/app/db/operations.py`, `backend/app/services/pipeline/writer.py`, `backend/app/routers/questions_pkg/mutations.py`
**修改类型:** 新增

在所有新建题目的路径中设置 cluster_id = id

### 步骤 4: BUG-003 + BUG-005 — 修复孤岛 (P0)

**文件:** `backend/app/routers/admin_review.py`
**修改类型:** 新增

新增 `POST /api/master-bank/fix-lone-islands` 端点:
- 全量 embedding 相似度扫描
- 可配置阈值和最大合并数
- 自动合并 sources、original_questions、frequency

## 验证方法

1. `uv run pytest tests/test_confidence_backfill.py tests/test_e_category_split.py tests/test_cluster_id.py tests/test_fix_lone_islands.py -q`
2. 生产数据库查询验证

## 回滚方案

- Migration 033/034/035 都是 additive 的，不破坏现有功能
- fix-lone-islands 端点是独立的管理操作，不影响正常流程
