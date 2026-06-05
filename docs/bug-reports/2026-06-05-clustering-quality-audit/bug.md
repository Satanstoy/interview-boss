# Bug 详细分析报告

**Bug ID:** BUG-001 ~ BUG-010
**发现日期:** 2026-06-05
**状态:** 已确认

## 问题概述

对聚类系统进行全量质量审计，覆盖代码审查 + 生产数据库验证 + 测试执行三个维度。发现 10 个缺陷，其中 P0 级 2 个（API 崩溃）、P1 级 4 个（数据质量/完整性）、P2 级 4 个（测试/策略/并发）。

## 生产数据快照

| 指标 | 数值 | 说明 |
|------|------|------|
| 活跃题目总数 | 325 | deleted_at IS NULL AND status='approved' |
| frequency=1 孤岛 | 183 (56.3%) | 未被合并的独立题 |
| frequency=2 | 98 (30.2%) | 最小合并 |
| frequency=3-5 | 39 (12.0%) | |
| frequency>5 | 5 (1.5%) | 大聚类极少 |
| Embedding 覆盖率 | **0%** | 所有 embedding 列 NULL |
| merge_history 记录 | 59 条 | 全部 confidence=1.0 或 0.9 |
| merge_feedback 表 | **不存在** | |
| cluster_id NULL | 0 | ✅ 正常 |

---

## BUG-001: merge_history 表缺少回滚字段 (P0)

- **位置:** `admin_review.py:101-103, 148-156, 248-252`
- **症状:** 管理员调用 `/merge-history`、`/merge-rollback`、`/merge-stats` 时 SQL 报错
- **根因:** admin_review.py 引用了 `is_rolled_back`、`rolled_back_at`、`rolled_back_by` 列，但生产 merge_history 表只有 12 列（无回滚相关列）。migration 链中无创建 merge_history 的迁移。
- **影响:** 所有管理员合并管理功能不可用
- **严重程度:** P0

**生产表结构:**
```sql
CREATE TABLE merge_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    survivor_id INTEGER NOT NULL,
    merged_ids TEXT NOT NULL,
    merged_questions TEXT NOT NULL,
    pre_snapshot TEXT NOT NULL,
    post_snapshot TEXT NOT NULL,
    operation_type TEXT DEFAULT 'auto',
    phase TEXT DEFAULT '',
    confidence REAL DEFAULT 0,
    cat2 TEXT DEFAULT '',
    operator_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- 缺少: is_rolled_back, rolled_back_at, rolled_back_by
```

**admin_review.py 引用（会报错的 SQL）:**
```python
# line 109: SELECT ... mh.is_rolled_back, mh.rolled_back_at
# line 101: WHERE mh.is_rolled_back = ?
# line 149: LEFT JOIN users rb ON mh.rolled_back_by = rb.id
# line 188: if mh['is_rolled_back']:
# line 249: UPDATE merge_history SET is_rolled_back = 1, rolled_back_at = CURRENT_TIMESTAMP, rolled_back_by = ?
```

---

## BUG-002: merge_feedback 表不存在 (P0)

- **位置:** `admin_review.py:292-299, 328-334`
- **症状:** 调用 `POST /merge-feedback` 和 `GET /merge-stats` 时 SQL 报错 `no such table: merge_feedback`
- **根因:** merge_feedback 表从未在任何 migration 中创建，生产数据库中不存在
- **影响:** 合并反馈和统计功能不可用
- **严重程度:** P0

---

## BUG-003: Embedding 覆盖率为 0% (P1)

- **位置:** `embedding_service.py`, `pipeline/writer.py:126`, `migrations.py:migration_032`
- **症状:** 生产数据库 325 条活跃题目的 embedding 列全部为 NULL
- **根因:**
  1. Migration 032 只添加了 `embedding BLOB` 列，但无 backfill 逻辑
  2. `insert_new_clusters` (writer.py:126) 虽然有生成 embedding 的代码，但只对新建聚类生效
  3. 历史数据从未被重新编码
  4. `prefilter_centroids` 在无 embedding 时降级返回全部数据（不报错但无效）
- **影响:**
  - Phase 1 预筛选从 top-30 降级为全量扫描（LLM token 浪费）
  - Phase 2 的 `_MIN_CLUSTER_SIMILARITY` embedding 门控失效（emb_map 为空直接跳过）
  - V2 三阶段 Stage 2 embedding 粗筛完全失效
  - confidence backfill (migration 034) 也因无 embedding 而使用文本 fallback
- **严重程度:** P1

---

## BUG-004: 56.3% 孤岛率过高 (P1)

- **位置:** 聚类策略全局问题
- **症状:** 183/325 题是 frequency=1 的孤岛
- **根因:**
  1. Embedding 预筛选失效（BUG-003）导致 LLM 匹配范围过大或遗漏
  2. "其他"分类（40 题）被策略性跳过，75% 是孤岛
  3. E1.数据结构（10 题）100% 孤岛率
  4. 高频分类（B1.Agent, B2.RAG 等）也有 40-60% 孤岛率
  5. `_validate_merges` 验证失败时拒绝所有合并（保守策略）
- **影响:** 用户搜索体验差，同一知识点散落多处
- **严重程度:** P1

**各分类孤岛率:**

| 分类 | 总数 | 孤岛 | 孤岛率 |
|------|------|------|--------|
| B1.Agent架构与范式 | 42 | 21 | 50.0% |
| 其他 | 40 | 30 | 75.0% |
| B2.RAG系统设计 | 28 | 11 | 39.3% |
| B6.评估安全与优化 | 26 | 15 | 57.7% |
| C3.数据库基础 | 19 | 12 | 63.2% |
| E1.数据结构 | 10 | 10 | **100%** |
| B5.Prompt工程 | 4 | 3 | **75.0%** |

---

## BUG-005: batch_v2.py 合并无 merge_history 记录 (P1)

- **位置:** `pipeline/batch_v2.py:143-232, 288-362`
- **症状:** `compact_singletons_in_db_v2` 执行的合并不记录 merge_history
- **根因:** batch_v2.py 是独立实现，未复用 batch.py 的 `_do_merge_to_existing` 函数，直接用 SQL 执行合并
- **影响:** 无法回滚 batch_v2 的合并操作；合并统计不完整
- **严重程度:** P1

---

## BUG-006: 全量重聚不合并 sources/original_questions (P1)

- **位置:** `clustering.py:1093-1119` (`full_recluster_hybrid` `_do_merge` 闭包)
- **症状:** 全量重聚合并时只设置 `duplicate_of` 和 `frequency++`，不合并 sources、original_questions、ai_answer
- **根因:** `_do_merge` 闭包内的 SQL 只做了简单的 UPDATE frequency，没有像 `_do_merge_to_existing` 那样合并所有字段
- **影响:** 全量重聚后数据丢失（sources、original_questions 丢失）
- **严重程度:** P1

**问题代码:**
```python
def _do_merge(s=survivor_id, m=merged_id, c=confidence):
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
        # ❌ 缺少: 合并 sources, original_questions, original_question_sources, ai_answer
        # ❌ 缺少: 删除被合并题的 normalized 表数据
        # ❌ 缺少: 删除 question_position
```

---

## BUG-007: 6 个聚类测试失败 (P2)

- **位置:** `test_clustering_quality.py:62, 78, 89, 104, 317, 345`
- **症状:**
  - 4 个 prompt 断言失败：测试期望 prompt 包含 "索引优化"、"TCP为什么是三次握手" 等案例，但实际 prompt 已更新为不同案例
  - 2 个 migration 导入失败：`_migration_032_merge_history` 函数已被重命名
- **根因:** prompt 迭代时未同步更新测试断言；migration 函数重命名后测试引用未更新
- **影响:** CI 红灯，无法确定聚类质量是否退化
- **严重程度:** P2

---

## BUG-008: "其他"分类聚类策略过于保守 (P2)

- **位置:** `clustering.py:981-982`, `pipeline/batch.py:770-771`
- **症状:** "其他"分类 40 题中有 30 题是孤岛 (75%)
- **根因:** V2 三阶段聚类和 compaction 都跳过 "其他" 分类（认为是兜底分类容易误合并）
- **影响:** "其他"分类下的合理题目无法被合并
- **严重程度:** P2

---

## BUG-009: V2 Union-Find 并发安全问题 (P2)

- **位置:** `clustering.py:968-1030`
- **症状:** `cluster_three_stage_v2` 中 `parent` 和 `rank` 字典在多个协程中并发读写
- **根因:** `_process_cat2_group` 通过 `asyncio.gather` 并发执行，但每个组操作共享的 `parent` 和 `rank` 字典。虽然 Python GIL 保护了单个字典操作的原子性，但 `_union_find` 路径压缩和 `_union_merge` 的多步操作不是原子的。
- **影响:** 理论上可能导致传递性合并不完整（实际风险较低，因为 asyncio 是单线程协作式并发）
- **严重程度:** P2

---

## BUG-010: E1.数据结构分类 100% 孤岛率 (P2)

- **位置:** 聚类策略 / LLM prompt
- **症状:** E1.数据结构 下 10 题全部是 frequency=1
- **根因:** 可能是该分类题目差异较大，LLM 无法识别出重复；或者该分类题目提交时间分散，Phase 1.5 时间窗口未覆盖
- **影响:** 该分类用户搜索体验差
- **严重程度:** P2

## 复现步骤

### BUG-001/002 复现:
1. 以管理员登录
2. 调用 `GET /api/master-bank/merge-history`
3. 实际结果: SQLite OperationalError: no such column: mh.is_rolled_back
4. 调用 `POST /api/master-bank/merge-feedback`
5. 实际结果: SQLite OperationalError: no such table: merge_feedback

### BUG-003 复现:
1. `sqlite3 backend/data/interview-boss.db "SELECT COUNT(*) FROM question_bank WHERE embedding IS NOT NULL AND deleted_at IS NULL"`
2. 结果: 0

### BUG-004 复现:
1. `sqlite3 backend/data/interview-boss.db "SELECT COUNT(*) FROM question_bank WHERE frequency=1 AND deleted_at IS NULL AND status='approved'"`
2. 结果: 183 (56.3%)

## 修复建议

| Bug | 修复方向 |
|-----|---------|
| BUG-001 | 新增 migration 添加 `is_rolled_back`, `rolled_back_at`, `rolled_back_by` 列 |
| BUG-002 | 新增 migration 创建 `merge_feedback` 表 |
| BUG-003 | 新增 migration backfill 所有活跃题目的 embedding |
| BUG-004 | 修复 BUG-003 后重新运行 compaction |
| BUG-005 | batch_v2.py 复用 `_do_merge_to_existing` 或添加 `_record_merge_history` 调用 |
| BUG-006 | `full_recluster_hybrid._do_merge` 改用 `_do_merge_to_existing` |
| BUG-007 | 更新测试断言以匹配当前 prompt 文本 |
| BUG-008 | 对 "其他" 分类降级处理（允许高频题之间合并）而非完全跳过 |
| BUG-009 | 改为各 cat2 组独立维护 local parent/rank，最后统一合并 |
| BUG-010 | 检查 E1 分类数据，必要时手动触发 compaction |
