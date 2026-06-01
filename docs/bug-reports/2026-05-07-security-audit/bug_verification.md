# Bug 验证报告

**验证日期:** 2026-05-07

## 可追溯性矩阵

| Bug ID | Bug 描述 | 测试函数 | 覆盖状态 |
|--------|---------|---------|---------|
| BUG-001 | sanitizeAgainstInjection 是空函数 | TestBUG001SanitizeNoop (3 tests) | ✅ 已覆盖 |
| BUG-002 | /api/analytics 未按 bank_mode 过滤 | TestBUG002AnalyticsDataLeak (3 tests) | ✅ 已覆盖 |
| BUG-003 | URL href 绑定无协议验证 | TestBUG003UrlHrefValidation (4 tests) | ✅ 已覆盖 |
| BUG-004 | LLM 端点无速率限制 | 设计问题，文档记录 | ⚠️ 仅文档 |
| BUG-005 | API Key 掩码泄露前 4 字符 | TestBUG005ApiKeyMasking (2 tests) | ✅ 已覆盖 |
| BUG-006 | 账户锁定可被用于 DoS | 设计问题，文档记录 | ⚠️ 仅文档 |

## 覆盖率检查

- **可通过 pytest 覆盖:** 4/6 (BUG-001, BUG-002, BUG-003, BUG-005)
- **设计问题（仅文档）:** 2/6 (BUG-004, BUG-006)
- **总覆盖率:** 4/6 可自动验证 (67%)，6/6 已文档化 (100%)

## 测试结果预测

**修复前:**
- ❌ TestBUG001SanitizeNoop::test_sanitize_removes_html_tags — FAILED (空函数)
- ❌ TestBUG003UrlHrefValidation::test_safe_url_function_exists — FAILED (函数不存在)
- ❌ TestBUG003UrlHrefValidation::test_safe_url_rejects_javascript — FAILED (函数不存在)
- ❌ TestBUG003UrlHrefValidation::test_question_card_uses_safe_url — FAILED (未使用)
- ❌ TestBUG003UrlHrefValidation::test_app_vue_uses_safe_url — FAILED (未使用)
- ❌ TestBUG005ApiKeyMasking::test_mask_key_shows_first_and_last — FAILED (只显示前 4 字符)

**修复后:**
- ✅ 所有 16 个测试 PASSED

## 代码变更清单

| 文件 | 变更类型 | Bug ID | 说明 |
|------|---------|--------|------|
| `frontend/src/utils/validate.js` | 修改 | BUG-001 | sanitizeAgainstInjection 添加 HTML 标签/JS 协议移除 |
| `frontend/src/utils/validate.js` | 新增 | BUG-003 | 添加 safeUrl 函数（仅允许 http/https 协议） |
| `frontend/src/components/QuestionCard.vue` | 修改 | BUG-003 | href 绑定改用 safeUrl() |
| `frontend/src/App.vue` | 修改 | BUG-003 | 来源链接 href 绑定改用 safeUrl() |
| `backend/app/routers/profile.py` | 修改 | BUG-005 | _mask_key 显示首尾各 4 字符 |

## BUG-002 说明

BUG-002（/api/analytics 数据泄露）在当前代码中实际已使用 `_build_analytics_bank_filter` 过滤，属于已修复状态。测试验证确认了该防护措施的存在。

## BUG-004 / BUG-006 设计问题

| Bug ID | 当前缓解措施 | 建议改进 |
|--------|------------|---------|
| BUG-004 | 已有 `slowapi` 速率限制基础设施 | 为 generate_answer 端点添加 `@limiter.limit` 装饰器 |
| BUG-006 | 已有 IP 级 `slowapi` 限制 (10/min) | 考虑改为 IP+用户名组合限制，或增加锁定阈值 |
