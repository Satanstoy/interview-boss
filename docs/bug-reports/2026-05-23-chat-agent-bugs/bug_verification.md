# Bug 验证报告

**日期:** 2026-05-23

## 可追溯性矩阵

| Bug ID | Bug 描述 | 测试函数 | 覆盖状态 |
|--------|---------|---------|---------|
| BUG-001 | _llm_compress 不传递 user_id | test_compress_passes_user_id_to_llm | 已覆盖 |
| BUG-002 | SYSTEM_BUDGET 常量不一致 | test_system_budget_consistent | 已覆盖 |
| BUG-003 | 错误内容作为 chunk 输出 | test_llm_failure_yields_error_not_chunk + test_llm_failure_does_not_persist_error_as_message | 已覆盖 |
| BUG-004 | session_notes 截断切断标签 | test_truncation_preserves_tag_integrity + test_extract_memory_skips_broken_tags + test_actual_truncation_preserves_all_tags | 已覆盖 |

## 测试结果预测

**修复前:**
- FAIL test_compress_passes_user_id_to_llm (user_id=None)
- FAIL test_system_budget_consistent (2000 != 3000)
- FAIL test_llm_failure_yields_error_not_chunk (1 chunk, 0 errors)
- FAIL test_llm_failure_does_not_persist_error_as_message ("抱歉" in chunk)

**修复后:**
- PASS test_compress_passes_user_id_to_llm (user_id=42)
- PASS test_system_budget_consistent (3000 == 3000)
- PASS test_llm_failure_yields_error_not_chunk (error event)
- PASS test_llm_failure_does_not_persist_error_as_message (no chunk)
- PASS test_truncation_preserves_tag_integrity
- PASS test_extract_memory_skips_broken_tags
- PASS test_actual_truncation_preserves_all_tags

## 覆盖率检查

100% bug 场景已覆盖
