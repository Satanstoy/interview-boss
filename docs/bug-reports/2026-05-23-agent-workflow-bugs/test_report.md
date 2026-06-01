# 测试验证报告

**Bug ID:** BUG-005 ~ BUG-010
**日期:** 2026-05-23
**状态:** 已修复验证通过

## 1. 执行摘要

| 项目 | 结果 |
|------|------|
| 修复前测试 | 7 failed, 4 passed |
| 修复后测试 | 11 passed, 0 failed |
| 回归测试 | 578 passed, 72 failed (pre-existing), 39 skipped |
| 修复状态 | 全部成功 |

## 2. 修复前测试结果

```
FAILED test_classify_passes_user_id_to_taxonomy - BUG-005: run_db(get_taxonomy_for_position) 直接传函数引用
FAILED test_classify_valid_cat2_parses_children_correctly - BUG-006: children 字典列表导致 TypeError
FAILED test_many_questions_unfairly_penalized - BUG-007: 50 题 14% 错误率得 0 分
FAILED test_same_error_rate_different_scores - BUG-007: 33% 错误率 3 题=8.5, 30 题=0
FAILED test_clear_qb_uses_manual_transaction - BUG-008: 裸 BEGIN/COMMIT
FAILED test_exact_match_misses_variants - BUG-009: 精确匹配未过滤变体
FAILED test_backup_db_node_uses_run_db - BUG-010: 绕过 run_db
```

结论: 6 个 bug 全部 FAIL（符合预期）

## 3. 修复后测试结果

```
PASSED test_classify_passes_user_id_to_taxonomy
PASSED test_children_as_strings_works
PASSED test_children_as_dicts_causes_type_error
PASSED test_classify_valid_cat2_parses_children_correctly
PASSED test_children_type_safe_parsing
PASSED test_many_questions_unfairly_penalized
PASSED test_same_error_rate_different_scores
PASSED test_clear_qb_uses_manual_transaction
PASSED test_exact_match_misses_variants
PASSED test_substring_match_catches_variants
PASSED test_backup_db_node_uses_run_db
```

结论: 11 个测试全部 PASS

## 4. 代码变更清单

| 文件 | 变更 |
|------|------|
| `agents/submit/classify.py:94` | `run_db(get_taxonomy_for_position)` → `run_db(lambda: get_taxonomy_for_position(user_id=...))` |
| `agents/submit/classify.py:115` | `set(cat.get("children", []))` → isinstance 类型安全解析 |
| `agents/shared/quality.py:35-68` | 固定扣分 → 按错误率归一化评分 |
| `agents/build/nodes.py:28-45` | 裸 BEGIN/COMMIT → `with conn:` + `run_db` 包装 |
| `agents/build/nodes.py:14-25` | `get_db_connection().execute()` → `run_db` 包装 |
| `agents/build/nodes.py:48-66` | `get_db_connection().execute()` → `run_db` 包装 |
| `agents/submit/extract.py:76` | `q.strip() == b` → `b in q` 子串匹配 |

## 5. 回归测试结果

```
578 passed, 72 failed, 39 skipped in 137.72s
```

72 个失败均为 pre-existing（与本次修复无关），主要是：
- test_analysis_flow.py (3) — 预期事件格式不匹配
- test_bank_mode_sql.py (3) — SQL 模式测试
- test_integration_bugs.py (3) — 集成测试 mock 不完整
- test_langgraph_workflows.py (2) — 预期 events 字段（emit_progress 使用 contextvars）
- 其他 (61) — 各类 pre-existing 问题

本次修改的模块相关测试全部通过。

## 6. 测试覆盖矩阵

| Bug ID | Bug 描述 | 测试函数 | 修复前 | 修复后 |
|--------|---------|---------|--------|--------|
| BUG-005 | user_id 未传递 | test_classify_passes_user_id_to_taxonomy | ❌ FAIL | ✅ PASS |
| BUG-006 | children 类型不安全 | test_classify_valid_cat2_parses_children_correctly | ❌ FAIL | ✅ PASS |
| BUG-007 | 评分不归一化 | test_many_questions_unfairly_penalized + test_same_error_rate_different_scores | ❌ FAIL | ✅ PASS |
| BUG-008 | 裸事务控制 | test_clear_qb_uses_manual_transaction | ❌ FAIL | ✅ PASS |
| BUG-009 | 精确匹配 | test_exact_match_misses_variants | ❌ FAIL | ✅ PASS |
| BUG-010 | 绕过 run_db | test_backup_db_node_uses_run_db | ❌ FAIL | ✅ PASS |
