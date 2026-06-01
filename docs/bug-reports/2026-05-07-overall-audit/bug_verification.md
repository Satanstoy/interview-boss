# Bug 验证报告

**审计日期:** 2026-05-07
**测试框架:** pytest + unittest.mock
**测试文件:** `backend/tests/test_bug_hunter.py`

---

## 可追溯性矩阵

| Bug ID | Bug 描述 | 测试类 | 测试方法 | 参数化用例 |
|--------|---------|--------|---------|-----------|
| BUG-001 | submit.py:48 未定义 response | TestBug001UndefinedResponse | test_tag_questions_batch_name_error | — |
| BUG-001 | submit.py:48 未定义 response | TestBug001UndefinedResponse | test_tag_questions_batch_should_use_raw_content | — |
| BUG-002 | master_bank.py:922 缩进错误 | TestBug002IndentationError | test_master_bank_module_import_fails | — |
| BUG-002 | master_bank.py:922 缩进错误 | TestBug002IndentationError | test_master_bank_syntax_check | — |
| BUG-003 | master_bank.py:420 返回值解包 | TestBug003BuildPersonalReturn | test_match_new_questions_returns_dict | — |
| BUG-003 | master_bank.py:420 返回值解包 | TestBug003BuildPersonalReturn | test_dict_unpack_returns_wrong_values | — |
| BUG-003 | master_bank.py:420 返回值解包 | TestBug003BuildPersonalReturn | test_build_personal_unpack_error | — |
| BUG-004 | analytics.py:34 SQL 优先级 | TestBug004SQLOperatorPrecedence | test_mixed_mode_sql_missing_parentheses | — |
| BUG-004 | analytics.py:34 SQL 优先级 | TestBug004SQLOperatorPrecedence | test_correct_sql_should_have_parentheses | — |
| BUG-005 | llm.py:61 大括号匹配 | TestBug005ExtractJson | test_json_with_braces_in_string_values | 正常 JSON |
| BUG-005 | llm.py:61 大括号匹配 | TestBug005ExtractJson | test_json_with_nested_braces_in_string | 含大括号字符串 |
| BUG-005 | llm.py:61 大括号匹配 | TestBug005ExtractJson | test_extract_json_direct_parse | 直接解析 |
| BUG-006 | utils.py:15 多分类丢失 | TestBug006NormalizeCategory | test_single_category_unchanged | 单分类 |
| BUG-006 | utils.py:15 多分类丢失 | TestBug006NormalizeCategory | test_comma_separated_keeps_only_first | 逗号分隔 |
| BUG-006 | utils.py:15 多分类丢失 | TestBug006NormalizeCategory | test_empty_string | 空字符串 |
| BUG-006 | utils.py:15 多分类丢失 | TestBug006NormalizeCategory | test_none_input | None |
| BUG-007 | connection.py 连接泄漏 | TestBug007ConnectionLeak | test_get_db_connection_returns_connection | — |
| BUG-007 | connection.py 连接泄漏 | TestBug007ConnectionLeak | test_connection_stored_in_thread_local | — |
| BUG-007 | connection.py 连接泄漏 | TestBug007ConnectionLeak | test_broken_connection_replaced | — |
| BUG-008 | auth.py:51 竞态条件 | TestBug008RecordFailureRace | test_record_failure_increments_count | — |
| BUG-008 | auth.py:51 竞态条件 | TestBug008RecordFailureRace | test_atomic_update_would_be_safer | — |
| BUG-009 | asgi.py:73 CSRF 不完整 | TestBug009CSRFMiddleware | test_csrf_blocks_request_without_header | 无自定义头 |
| BUG-009 | asgi.py:73 CSRF 不完整 | TestBug009CSRFMiddleware | test_csrf_allows_request_with_custom_header | 有自定义头 |
| BUG-009 | asgi.py:73 CSRF 不完整 | TestBug009CSRFMiddleware | test_csrf_exempt_paths | 豁免路径 |
| BUG-010 | http.js:368 缺少头 | TestBug010PostSSEHeaders | test_post_sse_headers_mismatch | — |
| BUG-010 | http.js:368 缺少头 | TestBug010PostSSEHeaders | test_sse_request_would_be_blocked_by_csrf | — |

---

## 覆盖率检查

### 已覆盖的 Edge Cases

| Edge Case | 测试方法 | 状态 |
|-----------|---------|------|
| 未定义变量 NameError | test_tag_questions_batch_name_error | ✅ 已覆盖 |
| 缩进错误 IndentationError | test_master_bank_module_import_fails | ✅ 已覆盖 |
| dict 解包为 tuple | test_dict_unpack_returns_wrong_values | ✅ 已覆盖 |
| SQL 运算符优先级 | test_mixed_mode_sql_missing_parentheses | ✅ 已覆盖 |
| JSON 含大括号字符串 | test_json_with_nested_braces_in_string | ✅ 已覆盖 |
| 逗号分隔多分类 | test_comma_separated_keeps_only_first | ✅ 已覆盖 |
| 空字符串输入 | test_empty_string | ✅ 已覆盖 |
| None 输入 | test_none_input | ✅ 已覆盖 |
| 连接损坏替换 | test_broken_connection_replaced | ✅ 已覆盖 |
| CSRF 无头请求 | test_csrf_blocks_request_without_header | ✅ 已覆盖 |
| CSRF 有头请求 | test_csrf_allows_request_with_custom_header | ✅ 已覆盖 |
| CSRF 豁免路径 | test_csrf_exempt_paths | ✅ 已覆盖 |

### 覆盖率确认

- **10/10 个 bug 已有对应的测试类**
- **26 个测试方法覆盖所有已识别的 edge case**
- **所有外部依赖（LLM、数据库、网络）均已 mock**

---

## 修复计划验证

### FIX-001 验证
- **测试:** `test_tag_questions_batch_name_error` — 验证当前代码会抛出 NameError
- **修复后:** `test_tag_questions_batch_should_use_raw_content` — 验证修复后应正常工作
- **预期:** 删除第48行后，NameError 消失，函数正常返回标签化结果

### FIX-002 验证
- **测试:** `test_master_bank_module_import_fails` — 验证模块无法加载
- **测试:** `test_master_bank_syntax_check` — 验证 py_compile 检测到错误
- **修复后:** `TestModuleLoadability.test_master_bank_module_loads` — 验证模块可加载
- **预期:** 修复缩进后，模块正常加载，所有路由可用

### FIX-003 验证
- **测试:** `test_match_new_questions_returns_dict` — 验证返回类型
- **测试:** `test_dict_unpack_returns_wrong_values` — 演示解包错误
- **修复后:** 验证 `result["matched"]` 和 `result["unmatched"]` 可正确访问
- **预期:** 使用字典访问后，build-personal 功能正常

### FIX-004 验证
- **测试:** `test_mixed_mode_sql_missing_parentheses` — 验证当前 SQL 缺少括号
- **修复后:** 验证 SQL 包含正确的括号结构
- **预期:** job_position 过滤应用于整个 WHERE 子句

### FIX-010 验证
- **测试:** `test_post_sse_headers_mismatch` — 验证 headers 不一致
- **测试:** `test_sse_request_would_be_blocked_by_csrf` — 验证会被阻止
- **修复后:** 验证 headers 包含 X-Requested-With
- **预期:** SSE 请求不再被 CSRF 中间件阻止

---

## 测试执行说明

```bash
cd /root/sj/interview-boss
python -m pytest backend/tests/test_bug_hunter.py -v
```

**注意:** 测试使用 `unittest.mock` mock 了所有外部依赖（LLM API、数据库、文件系统），不会连接真实服务。
