# Bug 验证报告

**Bug ID:** BUG-001, BUG-002
**验证日期:** 2026-05-10

## 可追溯性矩阵

| Bug ID | Bug 描述 | 测试函数 | 覆盖状态 |
|--------|---------|---------|---------|
| BUG-001 | 增量更新时 oqs 未合并新 URL | test_new_url_merged_to_existing_question_sources | 已覆盖 |
| BUG-001 | 同 URL 不重复 | test_same_url_not_duplicated_in_oqs | 已覆盖 |
| BUG-001 | 新问题文本正常添加 | test_new_question_text_still_adds_entry | 已覆盖 |
| BUG-002 | 展开数量 = badge 数量 | test_deduped_sources_count_equals_sources_length | 已覆盖 |
| BUG-002 | 保留原始问题上下文 | test_deduped_preserves_orig_question_context | 已覆盖 |

## 覆盖率检查
100% 边缘情况已覆盖
