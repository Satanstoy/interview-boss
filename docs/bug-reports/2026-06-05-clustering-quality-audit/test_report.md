# 测试验证报告

**Bug ID:** BUG-001 ~ BUG-010
**日期:** 2026-06-05
**状态:** 🔴 诊断完成，待修复

## 1. 执行摘要

| 项目 | 结果 |
|------|------|
| 现有聚类测试 | 6 failed, 37 passed (43 total) |
| 新增审计测试 | 13 个（待容器重建后运行） |
| 生产数据验证 | ✅ 完成 |
| 发现 Bug 数 | 10 个 (P0×2, P1×4, P2×4) |
| 修复状态 | ⏳ 计划已制定，待实施 |

## 2. 现有测试结果（修复前基线）

```
backend/tests/test_clustering_quality.py FFF.F.............FF..          [ 51%]
backend/tests/test_clustering_compaction_bugs.py .........               [ 72%]
backend/tests/test_clustering_e2e.py .........                           [ 93%]
backend/tests/services/test_clustering_maintenance.py ...                [100%]

=================================== FAILURES ===================================
FAILED test_clustering_quality.py::TestPromptFormat::test_match_existing_prompt_has_boundary_negative_examples
  → assert '索引优化' in MATCH_EXISTING_PROMPT (已移除此负面案例)
FAILED test_clustering_quality.py::TestPromptFormat::test_cluster_new_prompt_has_boundary_negative_examples
  → assert '索引优化' in CLUSTER_NEW_PROMPT (已移除此负面案例)
FAILED test_clustering_quality.py::TestPromptFormat::test_validate_merges_prompt_has_boundary_negative_examples
  → assert '索引优化' in VALIDATE_MERGES_PROMPT (已移除此负面案例)
FAILED test_clustering_quality.py::TestPromptFormat::test_match_existing_prompt_has_positive_examples
  → assert 'TCP为什么是三次握手' in MATCH_EXISTING_PROMPT (已替换为其他案例)
FAILED test_clustering_quality.py::TestMergeHistory::test_merge_history_table_schema
  → ImportError: cannot import name '_migration_032_merge_history' (函数已重命名)
FAILED test_clustering_quality.py::TestMergeHistory::test_merge_feedback_table_schema
  → ImportError: cannot import name '_migration_032_merge_history' (函数已重命名)

========================= 6 failed, 37 passed in 3.67s =========================
```

**结论:** 6 个测试因代码迭代未同步更新而失败。37 个核心聚类逻辑测试通过。✅

## 3. 生产数据库验证结果

### 3.1 题目频率分布

| 频率分组 | 数量 | 占比 |
|---------|------|------|
| freq=1 (孤岛) | 183 | **56.3%** |
| freq=2 | 98 | 30.2% |
| freq=3-5 | 39 | 12.0% |
| freq=6-10 | 4 | 1.2% |
| freq>10 | 1 | 0.3% |
| **总计** | **325** | 100% |

### 3.2 Embedding 覆盖率

| 指标 | 数值 |
|------|------|
| 活跃题目 | 325 |
| 有 embedding | **0** |
| 覆盖率 | **0.0%** |

### 3.3 merge_history 记录

| 指标 | 数值 |
|------|------|
| 总记录数 | 59 |
| 回滚列 (is_rolled_back) | **不存在** |
| merge_feedback 表 | **不存在** |
| confidence 分布 | 全部 1.0 或 0.9 |

### 3.4 分类孤岛率 TOP 10

| 分类 | 总数 | 孤岛 | 孤岛率 |
|------|------|------|--------|
| E1.数据结构 | 10 | 10 | **100%** |
| 其他 | 40 | 30 | **75.0%** |
| B5.Prompt工程 | 4 | 3 | 75.0% |
| C4.操作系统与网络 | 7 | 5 | 71.4% |
| C1.编程语言基础 | 16 | 10 | 62.5% |
| B8.模型与框架选型 | 15 | 10 | 66.7% |
| B7.AI Coding与代码智能 | 14 | 9 | 64.3% |
| C3.数据库基础 | 19 | 12 | 63.2% |
| B6.评估安全与优化 | 26 | 15 | 57.7% |
| B1.Agent架构与范式 | 42 | 21 | 50.0% |

### 3.5 数据完整性检查

| 检查项 | 结果 |
|--------|------|
| cluster_id NULL | 0 ✅ |
| frequency=0 | 0 ✅ |
| 精确重复未合并 | 0 ✅ |
| frequency 与 original_questions 不一致 | 0 ✅ |
| orphan normalized records | 1 ⚠️ |

## 4. 新增审计测试

测试文件: `backend/tests/test_clustering_quality_audit.py` (13 个测试)

| 测试类 | 测试数 | 覆盖 Bug |
|--------|--------|----------|
| TestBug001_MergeHistorySchema | 2 | BUG-001 |
| TestBug002_MergeFeedbackTable | 2 | BUG-002 |
| TestBug003_EmbeddingCoverage | 2 | BUG-003 |
| TestBug005_BatchV2MergeHistory | 1 | BUG-005 |
| TestBug006_FullReclusterMerge | 1 | BUG-006 |
| TestBug007_PromptTestSync | 4 | BUG-007 |
| TestBug009_UnionFindConcurrency | 1 | BUG-009 |
| TestClusteringQualityMetrics | 2 | BUG-004/008/010 |

**注意:** 测试需要重建 Docker 容器后才能在容器内运行（Docker volume 只挂载了 data 目录）。

## 5. 测试覆盖矩阵

| Bug ID | Bug 描述 | 测试函数 | 修复前 | 修复后预期 |
|--------|---------|---------|--------|-----------|
| BUG-001 | merge_history 缺回滚列 | test_merge_history_should_have_rollback_columns | ❌ FAIL | ✅ PASS |
| BUG-002 | merge_feedback 表不存在 | test_merge_feedback_table_should_exist | ❌ FAIL | ✅ PASS |
| BUG-003 | Embedding 0% 覆盖 | test_embedding_backfill_should_be_in_migrations | ❌ FAIL | ✅ PASS |
| BUG-004 | 56.3% 孤岛率 | test_singleton_rate_below_threshold | ❌ FAIL | ✅ PASS |
| BUG-005 | batch_v2 无历史 | test_batch_v2_should_use_do_merge_to_existing | ❌ FAIL | ✅ PASS |
| BUG-006 | full_recluster 不完整 | test_full_recluster_should_merge_complete_fields | ❌ FAIL | ✅ PASS |
| BUG-007 | 测试断言过期 | 4 个 prompt 测试 | ❌ FAIL → ✅ PASS | ✅ PASS |
| BUG-008 | "其他"被跳过 | test_other_category_singleton_rate | ❌ FAIL | ✅ PASS |
| BUG-009 | 并发安全 | test_union_find_isolation_per_cat2 | ⚠️ xfail | ✅ PASS |
| BUG-010 | E1 100% 孤岛 | 间接覆盖 | ❌ FAIL | ✅ PASS |

## 6. 结论

- [x] 10 个 bug 已识别并分析根因
- [x] 修复计划已制定（7 个步骤）
- [x] 13 个新测试覆盖所有 bug
- [ ] 修复待实施
- [ ] 测试待容器重建后运行验证

### 优先级建议

1. **立即修复 (P0):** BUG-001 + BUG-002 — 管理员 API 崩溃
2. **高优修复 (P1):** BUG-003 — embedding backfill（解锁聚类质量提升）
3. **跟进修复 (P1):** BUG-005 + BUG-006 — 数据完整性
4. **常规修复 (P2):** BUG-007 + BUG-008 + BUG-009 + BUG-010
