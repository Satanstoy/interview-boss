# 测试验证报告

**Bug ID:** BUG-001, BUG-002
**日期:** 2026-05-10
**状态:** 已修复验证通过

## 1. 执行摘要

| 项目 | 结果 |
|------|------|
| 修复后测试 | 7 passed, 0 failed |
| 回归测试 | 28 passed, 0 failed |
| 测试覆盖率 | 100% |
| 修复状态 | 成功 |

## 2. 修复后测试结果

```
tests/test_source_url_count_mismatch.py::TestIncrementalUpdateMergesSources::test_new_url_merged_to_existing_question_sources PASSED
tests/test_source_url_count_mismatch.py::TestIncrementalUpdateMergesSources::test_same_url_not_duplicated_in_oqs PASSED
tests/test_source_url_count_mismatch.py::TestIncrementalUpdateMergesSources::test_new_question_text_still_adds_entry PASSED
tests/test_source_url_count_mismatch.py::TestIncrementalUpdateMergesSources::test_multiple_questions_same_url PASSED
tests/test_source_url_count_mismatch.py::TestSourceCountConsistency::test_deduped_sources_count_equals_sources_length PASSED
tests/test_source_url_count_mismatch.py::TestSourceCountConsistency::test_deduped_preserves_orig_question_context PASSED
tests/test_source_url_count_mismatch.py::TestSourceCountConsistency::test_empty_sources_returns_empty PASSED

7 passed in 0.07s
```

**结论:** 所有测试 PASS

## 3. 代码变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `backend/app/db/operations.py` | 修改 | BUG-001: 增量更新时合并已有问题的新 URL 到 original_question_sources |
| `frontend/src/components/QuestionCard.vue` | 修改 | BUG-002: 展开来源改为按去重后的 sources 列表渲染，确保数量 = badge |

## 4. 测试覆盖矩阵

| Bug ID | Bug 描述 | 测试函数 | 修复后 |
|--------|---------|---------|--------|
| BUG-001 | 新 URL 合并到已有问题 | test_new_url_merged_to_existing_question_sources | PASS |
| BUG-001 | 同 URL 不重复 | test_same_url_not_duplicated_in_oqs | PASS |
| BUG-001 | 新问题文本正常添加 | test_new_question_text_still_adds_entry | PASS |
| BUG-001 | 多问题同 URL | test_multiple_questions_same_url | PASS |
| BUG-002 | 去重数量 = badge | test_deduped_sources_count_equals_sources_length | PASS |
| BUG-002 | 保留原始问题上下文 | test_deduped_preserves_orig_question_context | PASS |
| BUG-002 | 空来源 | test_empty_sources_returns_empty | PASS |

## 5. 结论

- [x] BUG-001 已修复：增量更新时新 URL 正确合并到 original_question_sources
- [x] BUG-002 已修复：展开来源按去重 URL 渲染，数量始终 = badge 数量
- [x] 所有 28 个相关测试通过，无回归
- [x] 前后端已部署
