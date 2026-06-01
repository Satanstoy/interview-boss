# Bug 验证报告

**日期:** 2026-05-23

## 可追溯性矩阵

| Bug ID | Bug 描述 | 测试函数 | 覆盖状态 |
|--------|---------|---------|---------|
| BUG-005 | classify_node 未传递 user_id 给 get_taxonomy_for_position | test_classify_passes_user_id_to_taxonomy | 已覆盖 |
| BUG-006 | taxonomy children 字典列表导致 TypeError | test_children_as_dicts_causes_type_error + test_classify_valid_cat2_parses_children_correctly | 已覆盖 |
| BUG-007 | evaluate_tagging_quality 不按题目数归一化 | test_many_questions_unfairly_penalized + test_same_error_rate_different_scores | 已覆盖 |
| BUG-008 | clear_qb_node 裸 BEGIN/COMMIT 事务管理 | test_clear_qb_uses_manual_transaction | 已覆盖 |
| BUG-009 | 黑名单精确匹配无法过滤变体 | test_exact_match_misses_variants | 已覆盖 |
| BUG-010 | build 节点绕过 run_db 直接用 get_db_connection | test_backup_db_node_uses_run_db | 已覆盖 |

## 测试结果预测

**修复前:**
- FAIL test_classify_passes_user_id_to_taxonomy (直接传函数引用)
- FAIL test_classify_valid_cat2_parses_children_correctly (TypeError)
- FAIL test_many_questions_unfairly_penalized (14% 错误率得 0 分)
- FAIL test_same_error_rate_different_scores (33% 错误率: 3 题=8.5, 30 题=0)
- FAIL test_clear_qb_uses_manual_transaction (裸 BEGIN/COMMIT)
- FAIL test_exact_match_misses_variants (精确匹配)
- FAIL test_backup_db_node_uses_run_db (绕过 run_db)

**修复后:**
- PASS test_classify_passes_user_id_to_taxonomy (lambda 传递 user_id)
- PASS test_classify_valid_cat2_parses_children_correctly (isinstance 类型检查)
- PASS test_many_questions_unfairly_penalized (错误率归一化)
- PASS test_same_error_rate_different_scores (同样错误率评分一致)
- PASS test_clear_qb_uses_manual_transaction (with conn 上下文管理器)
- PASS test_exact_match_misses_variants (子串匹配)
- PASS test_backup_db_node_uses_run_db (run_db 包装)

## 覆盖率检查

100% bug 场景已覆盖
