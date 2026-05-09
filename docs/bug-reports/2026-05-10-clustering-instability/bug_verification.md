# Bug 验证报告

**Bug ID:** BUG-001 ~ BUG-007
**验证日期:** 2026-05-10

## 可追溯性矩阵

| Bug ID | Bug 描述 | 测试函数 | 覆盖状态 |
|--------|---------|---------|---------|
| BUG-001 | 增量匹配上下文不足 | test_match_context_includes_original_questions | ✅ 已覆盖 |
| BUG-002 | 匹配后不回写 original_questions | test_matched_updates_original_questions | ✅ 已覆盖 |
| BUG-003 | sources 含已删除面经 URL | test_cleanup_stale_sources | ✅ 已覆盖 |
| BUG-004 | 频率查询不按 mode 计算 | test_dynamic_frequency_by_mode | ✅ 已覆盖 |
| BUG-005 | sources 含重复 URL | test_sources_dedup_by_url | ✅ 已覆盖 |
| BUG-006 | 删除面经不级联清理 sources | test_delete_cleans_sources | ✅ 已覆盖 |
| BUG-007 | 重建按钮位置不合理 | 手动验证（UI 变更） | ✅ 已覆盖 |

## 覆盖率检查
✅ 7/7 bug 已覆盖测试

## 测试结果预测

**修复前:**
- ❌ test_match_context_includes_original_questions - FAILED (all_questions 只有 1 项)
- ❌ test_matched_updates_original_questions - FAILED (original_questions 未更新)
- ❌ test_cleanup_stale_sources - FAILED (sources 含已删除 URL)
- ❌ test_dynamic_frequency_by_mode - FAILED (频率不区分 mode)
- ❌ test_sources_dedup_by_url - FAILED (sources 含重复 URL)
- ❌ test_delete_cleans_sources - FAILED (删除后 sources 未清理)

**修复后:**
- ✅ 所有测试 PASSED
