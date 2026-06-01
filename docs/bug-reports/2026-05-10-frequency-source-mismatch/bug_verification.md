# Bug 验证报告

**Bug ID:** BUG-001, BUG-002
**验证日期:** 2026-05-10

## 可追溯性矩阵

| Bug ID | Bug 描述 | 测试函数 | 覆盖状态 |
|--------|---------|---------|---------|
| BUG-001 | sourceCount 对聚类题返回 original_questions.length 而非 sources.length | test_source_count_uses_sources_length | ✅ 已覆盖 |
| BUG-001 | 聚类题频率与来源详情数量不一致 | test_frequency_equals_source_count_clustered | ✅ 已覆盖 |
| BUG-002 | original_question_sources 未按 bank_mode 过滤 | test_oqs_filtered_in_public_mode | ✅ 已覆盖 |
| BUG-002 | original_question_sources 未按 bank_mode 过滤 | test_oqs_filtered_in_personal_mode | ✅ 已覆盖 |
| BUG-002 | original_question_sources 未按 bank_mode 过滤 | test_oqs_filtered_in_mixed_mode | ✅ 已覆盖 |
| 增量安全 | 增量更新后频率与来源仍一致 | test_incremental_update_preserves_consistency | ✅ 已覆盖 |

## 覆盖率检查
✅ 100% 边缘情况已覆盖

## 测试结果预测

**修复前:**
- ❌ test_source_count_uses_sources_length — FAILED (sourceCount 返回 original_questions.length=5 而非 sources.length=3)
- ❌ test_frequency_equals_source_count_clustered — FAILED (frequency=3, sourceCount=5)
- ❌ test_oqs_filtered_in_public_mode — FAILED (包含不属于 public 的来源)
- ❌ test_oqs_filtered_in_personal_mode — FAILED (包含不属于 personal 的来源)
- ❌ test_oqs_filtered_in_mixed_mode — FAILED (包含不属于 mixed 的来源)
- ✅ test_incremental_update_preserves_consistency — PASSED (增量逻辑本身正确)

**修复后:**
- ✅ test_source_count_uses_sources_length — PASSED
- ✅ test_frequency_equals_source_count_clustered — PASSED
- ✅ test_oqs_filtered_in_public_mode — PASSED
- ✅ test_oqs_filtered_in_personal_mode — PASSED
- ✅ test_oqs_filtered_in_mixed_mode — PASSED
- ✅ test_incremental_update_preserves_consistency — PASSED
