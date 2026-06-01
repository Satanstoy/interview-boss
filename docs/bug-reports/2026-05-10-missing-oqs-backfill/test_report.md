# 测试验证报告

**Bug ID:** BUG-004
**日期:** 2026-05-10
**状态:** 已修复验证通过

## 1. 执行摘要

| 项目 | 结果 |
|------|------|
| 修复前测试 | 6 passed, 2 skipped (数据库未修复) |
| 修复后测试 | 8 passed, 0 failed |
| 数据修复 | 161 条题目 oqs 已回填 |
| 修复状态 | 成功 |

## 2. 修复前测试结果

```
TestOqsBackfillOnRebuild::test_standalone_question_keeps_oqs PASSED
TestOqsPopulatedForNewQuestions::test_new_question_insert_includes_oqs PASSED
TestOqsPopulatedForNewQuestions::test_new_question_oqs_format PASSED
TestStartupAutoFixEmptyOqs::test_startup_fix_backfills_empty_oqs PASSED
TestStartupAutoFixEmptyOqs::test_startup_fix_handles_empty_sources_in_oqs PASSED
TestFrontendDedupedSourcesFallback::test_deduped_sources_handles_empty_oqs PASSED
TestRealDatabaseOqsIntegrity::test_no_questions_with_empty_oqs_but_nonempty_sources SKIPPED (数据未修复)
TestRealDatabaseOqsIntegrity::test_no_oqs_entries_with_empty_sources SKIPPED (数据未修复)
```

## 3. 修复后测试结果

```
8 passed in 0.07s
```

## 4. 代码变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| backend/app/routers/master_bank.py | 修改 | 保留独立题目的 original_question_sources |
| backend/app/db/operations.py | 修改 | 新建题目 INSERT 包含 original_question_sources |
| backend/app/db/connection.py | 修改 | 启动时自动回填空 oqs + 修复空 sources 条目 |
| backend/tests/test_oqs_backfill.py | 新增 | 8 个测试用例 |

## 5. 数据变更

| 操作 | 数量 |
|------|------|
| 回填空 oqs 题目 | 161 条 |
| 修复空 sources 条目 | 9 条 |
| 总题目 | 210 条（不变）|

## 6. 结论

- [x] 161 条空 oqs 题目已回填
- [x] 9 条空 sources 条目已修复
- [x] 重建题库不再清空独立题目的 oqs
- [x] 增量更新新建题目包含 oqs
- [x] 启动自动修复逻辑已添加
- [x] 8 个测试全部通过
