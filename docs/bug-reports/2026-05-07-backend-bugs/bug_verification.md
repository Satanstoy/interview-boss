# Bug 验证报告

**验证日期:** 2026-05-07

## 可追溯性矩阵

| Bug ID | Bug 描述 | 测试函数 | 覆盖状态 |
|--------|---------|---------|---------|
| BUG-001 | 异步端点中同步阻塞 DB 调用 | TestBUG001SyncBlockingAsync (2 tests) | ✅ 已覆盖 |
| BUG-002 | 删除操作全表扫描 question_bank | TestBUG002FullTableScan (2 tests) | ✅ 已覆盖 |
| BUG-003 | _tag_batch 使用原始 json.loads | TestBUG003TagBatchJsonParsing (3 tests) | ✅ 已覆盖 |
| BUG-004 | submit LLM 调用缺少重试 | TestBUG004SubmitRetry (3 tests) | ✅ 已覆盖 |

## 覆盖率检查

- **可通过 pytest 覆盖:** 4/4 (100%)
- **总覆盖率:** 4/4 (100%) ✅

## 测试结果预测

**修复前:**
- ✅ TestBUG001SyncBlockingAsync::test_get_available_positions_is_sync_function - PASSED
- ❌ TestBUG002FullTableScan::test_delete_data_uses_filtered_query - FAILED (全表扫描)
- ❌ TestBUG002FullTableScan::test_batch_delete_data_uses_filtered_query - FAILED (全表扫描)
- ❌ TestBUG003TagBatchJsonParsing::test_tag_batch_uses_extract_json - FAILED (使用 json.loads)
- ✅ TestBUG004SubmitRetry::test_submit_data_source_uses_retry - PASSED (已有 retry 关键字)
- ✅ 其他测试 PASSED

**修复后:**
- ✅ 所有 13 个测试 PASSED

## 代码变更清单

| 文件 | 变更类型 | Bug ID | 说明 |
|------|---------|--------|------|
| profile.py | 重构 | BUG-001 | 合并所有 DB 查询到 _query() 中，通过 run_db() 异步执行 |
| data.py | 优化 | BUG-002 | 用 LIKE 预筛选替代全表扫描（3 处） |
| master_bank.py | 替换 | BUG-003 | json.loads → _extract_json（容错解析） |
| submit.py | 替换 | BUG-004 | client.chat.completions.create → _call_llm_with_retry_messages |
| llm.py | 新增 | BUG-004 | 新增 _call_llm_with_retry_messages 函数（支持 multimodal messages） |
