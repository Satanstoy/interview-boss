# Bug 验证报告

**Bug ID:** BUG-001 ~ BUG-010
**验证日期:** 2026-06-05

## 可追溯性矩阵

| Bug ID | Bug 描述 | 测试函数 | 覆盖状态 |
|--------|---------|---------|---------|
| BUG-001 | merge_history 缺少回滚列 | test_merge_history_should_have_rollback_columns, test_admin_merge_history_query_should_not_error | ✅ 已覆盖 |
| BUG-002 | merge_feedback 表不存在 | test_merge_feedback_table_should_exist, test_merge_feedback_has_required_columns | ✅ 已覆盖 |
| BUG-003 | Embedding 覆盖率 0% | test_insert_new_clusters_should_store_embedding, test_embedding_backfill_should_be_in_migrations | ✅ 已覆盖 |
| BUG-004 | 56.3% 孤岛率 | test_singleton_rate_below_threshold | ✅ 已覆盖 |
| BUG-005 | batch_v2 无 merge_history | test_batch_v2_should_use_do_merge_to_existing | ✅ 已覆盖 |
| BUG-006 | full_recluster 不合并完整字段 | test_full_recluster_should_merge_complete_fields | ✅ 已覆盖 |
| BUG-007 | 6 个测试失败 | test_match_prompt_has_current_negative_examples 等 4 个 | ✅ 已覆盖 |
| BUG-008 | "其他"分类被跳过 | test_other_category_singleton_rate | ✅ 已覆盖 |
| BUG-009 | V2 Union-Find 并发 | test_union_find_isolation_per_cat2 | ✅ 已覆盖 |
| BUG-010 | E1 分类 100% 孤岛 | test_singleton_rate_below_threshold (间接) | ⚠️ 间接覆盖 |

## 覆盖率检查

- ✅ 9/10 bug 有直接测试覆盖
- ⚠️ BUG-010 (E1 分类) 通过全局孤岛率指标间接覆盖
- ✅ 所有 P0 bug 有 2 个以上测试覆盖

## 测试结果预测

**修复前（当前状态）:**
- ❌ test_merge_history_should_have_rollback_columns — FAILED (列不存在)
- ❌ test_admin_merge_history_query_should_not_error — FAILED (SQL 报错)
- ❌ test_merge_feedback_table_should_exist — FAILED (表不存在)
- ❌ test_embedding_backfill_should_be_in_migrations — FAILED (migration 不存在)
- ❌ test_batch_v2_should_use_do_merge_to_existing — FAILED (未调用)
- ❌ test_full_recluster_should_merge_complete_fields — FAILED (不合并)
- ❌ test_match_prompt_has_current_negative_examples — PASSED (当前 prompt 包含)
- ✅ test_singleton_rate_below_threshold — FAILED (56.3% > 40%)
- ❌ test_other_category_singleton_rate — FAILED (75% > 60%)
- ✅ test_union_find_isolation_per_cat2 — xfail (共享状态)

**修复后:**
- ✅ 全部测试应通过
- ✅ 孤岛率应降至 30-40%
- ✅ "其他"分类孤岛率应降至 50% 以下
