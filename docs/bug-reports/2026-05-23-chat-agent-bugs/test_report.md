# 测试验证报告

**Bug ID:** BUG-001 ~ BUG-004
**日期:** 2026-05-23
**状态:** 已修复验证通过

## 1. 执行摘要

| 项目 | 结果 |
|------|------|
| 修复前测试 | 4 failed, 3 passed |
| 修复后测试 | 7 passed, 0 failed |
| 回归测试 | 77 passed, 6 skipped, 0 failed |
| 修复状态 | 全部成功 |

## 2. 修复前测试结果

```
FAILED test_compress_passes_user_id_to_llm - BUG-001: _llm_compress 未传递 user_id。期望 user_id=42，实际=None
FAILED test_system_budget_consistent - BUG-002: SYSTEM_BUDGET 不一致。nodes.py=3000，budget.py=2000
FAILED test_llm_failure_yields_error_not_chunk - BUG-003: LLM 失败时应 yield error 事件。实际: 1 chunks, 0 errors
FAILED test_llm_failure_does_not_persist_error_as_message - BUG-003: 错误消息不应作为 chunk 内容返回
```

结论: 4 个 bug 全部 FAIL（符合预期）

## 3. 修复后测试结果

```
PASSED test_compress_passes_user_id_to_llm
PASSED test_system_budget_consistent
PASSED test_llm_failure_yields_error_not_chunk
PASSED test_llm_failure_does_not_persist_error_as_message
PASSED test_truncation_preserves_tag_integrity
PASSED test_extract_memory_skips_broken_tags
PASSED test_actual_truncation_preserves_all_tags
```

结论: 7 个测试全部 PASS

## 4. 代码变更清单

| 文件 | 变更 |
|------|------|
| `agents/chat/budget.py:61` | system_budget 2000 → 3000 |
| `agents/chat/budget.py:204` | state_user_id=None → state_user_id=user_id |
| `agents/chat/nodes.py:323-326` | yield chunk → yield error + return |
| `agents/chat/nodes.py:395-396` | 简单切片 → 行边界截断 |

## 5. 回归测试结果

```
77 passed, 6 skipped in 20.47s
```

无回归问题。
