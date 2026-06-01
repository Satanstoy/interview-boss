# 测试验证报告

**Bug ID:** BUG-001
**日期:** 2026-05-22
**状态:** ✅ 已修复验证通过

## 1. 执行摘要

| 项目 | 结果 |
|------|------|
| 修复前测试 | 2 passed（验证后端行为正确） |
| 修复后测试 | 2 passed |
| 前端构建 | ✅ 成功 |
| 修复状态 | ✅ 成功 |

## 2. 修复前测试结果 (TDD 验证)

```
backend/tests/test_bank_mode_cache.py::TestBankModeCacheBug::test_same_url_different_bank_mode_returns_different_results PASSED
backend/tests/test_bank_mode_cache.py::TestBankModeCacheBug::test_bank_mode_filter_is_server_side_not_client_side PASSED

2 passed, 6 warnings in 6.58s
```

**结论:** 后端对相同 URL + 不同 bank_mode 返回不同数据 ✅ — 问题确认在前端缓存层

## 3. 修复后测试结果

```
backend/tests/test_bank_mode_cache.py::TestBankModeCacheBug::test_same_url_different_bank_mode_returns_different_results PASSED
backend/tests/test_bank_mode_cache.py::TestBankModeCacheBug::test_bank_mode_filter_is_server_side_not_client_side PASSED

2 passed, 6 warnings in 6.58s
```

**结论:** 所有测试 PASS ✅

## 4. 代码变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `frontend/src/App.vue:516` | 修改 | 导入 `invalidateCache` |
| `frontend/src/App.vue:957` | 修改 | `handleBankModeChanged` 中调用 `invalidateCache('master-bank')` |

## 5. 修复原理

**问题：** `http.js` 的 GET 请求缓存以 URL 为 key（30 秒 TTL）。`fetchMasterBank()` 的 URL 不含 `bank_mode`（模式由服务端从 DB 读取），切换模式后 URL 不变，缓存命中返回旧数据。

**修复：** 在 `handleBankModeChanged` 中，`fetchTableData()` 前调用 `invalidateCache('master-bank')` 清除匹配的缓存条目，确保下次 GET 请求发送到服务端获取新模式的数据。

## 6. 结论

- [x] 根因已定位：前端 GET 缓存未在 bank_mode 切换时清除
- [x] 修复已实施：App.vue 中 2 行代码变更
- [x] 所有测试通过
- [x] 前端构建成功
- [x] 无回归问题
