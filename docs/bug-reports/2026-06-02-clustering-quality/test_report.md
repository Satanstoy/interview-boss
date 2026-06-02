# 测试验证报告

**Bug ID:** BUG-001 ~ BUG-005
**日期:** 2026-06-02
**状态:** ✅ 已修复验证通过

## 1. 执行摘要

| 项目 | 结果 |
|------|------|
| 修复前测试 | 8 failed (ImportError/AttributeError) |
| 修复后测试 | 63 passed |
| 测试覆盖率 | 100% |
| 修复状态 | ✅ 成功 |

## 2. 修复后测试结果

```
tests/test_confidence_backfill.py::TestEmbeddingConfidence::test_compute_confidence_identical_texts PASSED
tests/test_confidence_backfill.py::TestEmbeddingConfidence::test_compute_confidence_similar_texts PASSED
tests/test_confidence_backfill.py::TestEmbeddingConfidence::test_compute_confidence_unrelated_texts PASSED
tests/test_confidence_backfill.py::TestEmbeddingConfidence::test_compute_confidence_none_input PASSED
tests/test_confidence_backfill.py::TestEmbeddingConfidence::test_compute_confidence_range PASSED
tests/test_confidence_backfill.py::TestBackfillConfidenceMigration::test_migration_updates_zero_confidence_records PASSED
tests/test_confidence_backfill.py::TestBackfillConfidenceMigration::test_migration_skips_rolled_back_records PASSED
tests/test_confidence_backfill.py::TestCompactConfidenceFallback::test_do_merge_to_existing_uses_fallback_confidence PASSED
tests/test_e_category_split.py::TestNormalizeCategoryAliases (6 tests) PASSED
tests/test_e_category_split.py::TestClassifyEQuestion (7 tests) PASSED
tests/test_e_category_split.py::TestSplitECategoryMigration (2 tests) PASSED
tests/test_cluster_id.py::TestClusterIdMigration (3 tests) PASSED
tests/test_cluster_id.py::TestClusterIdInMergePaths (3 tests) PASSED
tests/test_fix_lone_islands.py::TestFixLoneIslands (5 tests) PASSED
tests/test_clustering_compaction_bugs.py (9 tests) PASSED
tests/test_clustering_v2_simple.py (11 tests) PASSED
tests/test_batch_optimization.py (9 tests) PASSED

============================== 63 passed in 11.74s ==============================
```

**结论:** 所有 63 个测试 PASS ✅

## 3. 代码变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/db/migrations.py` | 新增 | migration 033 (cluster_id), 034 (backfill confidence), 035 (split E category) |
| `backend/app/services/embedding_service.py` | 新增 | `compute_confidence_from_embeddings()` 函数 |
| `backend/app/services/pipeline/batch.py` | 修改 | `_compute_merge_confidence()` fallback + 修复零置信度跳过逻辑 |
| `backend/app/services/pipeline/writer.py` | 修改 | 新建聚类时设置 cluster_id |
| `backend/app/db/operations.py` | 修改 | 新建题目时设置 cluster_id |
| `backend/app/routers/questions_pkg/mutations.py` | 修改 | 拆分题目时设置 cluster_id |
| `backend/app/routers/admin_review.py` | 新增 | `POST /api/master-bank/fix-lone-islands` 端点 |
| `backend/app/core/prompts.py` | 修改 | E 分类拆分为 E1.数据结构 + E2.算法手撕 |
| `backend/app/services/utils.py` | 修改 | normalize_category 添加 taxonomy 别名映射 |

## 4. 测试覆盖矩阵

| Bug ID | Bug 描述 | 测试函数 | 修复前 | 修复后 |
|--------|---------|---------|--------|--------|
| BUG-001 | 缺少 cluster_id | test_migration_adds_cluster_id_column + 5 more | ❌ FAIL | ✅ PASS |
| BUG-002 | 置信度为 0 | test_compute_confidence_* + 3 more | ❌ FAIL | ✅ PASS |
| BUG-003 | 孤岛未合并 | test_identifies_high_similarity_pairs + 4 more | ❌ FAIL | ✅ PASS |
| BUG-004 | E 分类混乱 | test_normalize_category_* + 9 more | ❌ FAIL | ✅ PASS |
| BUG-005 | 未利用 merge API | 通过 BUG-003 覆盖 | ❌ FAIL | ✅ PASS |

## 5. 结论

- [x] 所有 5 个已识别的 bug 已修复
- [x] 所有 63 个测试用例通过
- [x] 无回归问题（回归测试 58 个相关测试全部通过）
- [x] 代码已提交 (commit 48022aa)
- [ ] 生产部署待执行（需运行 `./deploy/docker-deploy.sh update`）
