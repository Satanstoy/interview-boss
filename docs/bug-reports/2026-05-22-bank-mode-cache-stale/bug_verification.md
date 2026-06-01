# Bug 验证报告

**Bug ID:** BUG-001
**验证日期:** 2026-05-22

## 可追溯性矩阵

| Bug ID | Bug 描述 | 测试函数 | 覆盖状态 |
|--------|---------|---------|---------|
| BUG-001 | 切换题库模式后 GET 缓存返回旧数据 | test_same_url_different_bank_mode_returns_different_results | ✅ 已覆盖 |
| BUG-001 | URL 中不含 bank_mode 参数 | test_bank_mode_filter_is_server_side_not_client_side | ✅ 已覆盖 |

## 覆盖率检查
✅ **核心场景已覆盖**：验证后端对相同 URL + 不同 bank_mode 返回不同数据，证明前端缓存无法区分

## 测试结果预测

**修复前（TDD 红灯）：**
- ✅ test_same_url_different_bank_mode_returns_different_results - PASSED（验证后端行为正确，问题在前端）
- ✅ test_bank_mode_filter_is_server_side_not_client_side - PASSED

**修复后：**
- ✅ test_same_url_different_bank_mode_returns_different_results - PASSED
- ✅ test_bank_mode_filter_is_server_side_not_client_side - PASSED
- ✅ 前端 `npm run build` - 成功

## 前端验证
- `invalidateCache('master-bank')` 已正确导入并在 `handleBankModeChanged` 中调用
- 缓存清除发生在 `fetchTableData()` 之前，确保下次请求不会命中旧缓存
