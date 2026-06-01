# Bug 预览报告

**日期:** 2026-05-27
**问题:** E2E 测试发现 3 个前后端 Bug
**严重程度:** Medium

## 初步诊断

### BUG-001: 前后端正则表达式字符范围不一致

**问题现象:** 前端 `validate.js` 的 `USERNAME_RE` 使用 `一-龥`（U+4E00-U+9FA5），后端 `auth.py` 使用 `一-鿿`（U+4E00-U+9FFF）。90 个 CJK 扩展 A 区汉字（U+9FA6-U+9FFF）后端接受但前端拒绝。

**根本原因:** 前端正则写入时使用了较早的 Unicode 范围，后端更新后未同步。

**影响范围:**
- **功能:** 用户名含扩展汉字的用户无法通过前端注册
- **用户:** 使用生僻汉字的用户
- **数据:** 不影响数据完整性

### BUG-002: PracticePanel 消毒函数返回值被丢弃

**问题现象:** `PracticePanel.vue` 中 `handleSaveAnswer` 和 `handleEvaluate` 调用 `sanitizeAgainstInjection` 但丢弃返回值，未消毒的输入直接发送到服务器。

**根本原因:** `const sanitized = sanitizeAgainstInjection(...)` 写成了 `sanitizeAgainstInjection(...)`，返回值未赋值。且 try-catch 是死代码（函数永不抛异常）。

**影响范围:**
- **功能:** XSS 防护失效，恶意脚本可存储到数据库
- **用户:** 所有用户
- **数据:** 数据库中可能存储未消毒内容

### BUG-003: GET 缓存在数据变更后未失效

**问题现象:** `http.js` 的 GET 缓存（30s TTL）在数据变更后未清除。用户点击"刷新"按钮可能看到过期数据。

**根本原因:** 只有 `handleBankModeChanged` 调用了 `invalidateCache`，其他变更操作未清除缓存。

**影响范围:**
- **功能:** 刷新按钮可能返回过期数据
- **用户:** 快速操作后刷新的用户
- **数据:** 不影响数据完整性，仅影响显示

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | Low | 正则不一致影响极少数用户名 |
| 数据完整性 | Medium | 未消毒输入存储到数据库 |
| 安全风险 | Medium | DOMPurify 是最后防线，存储层无保护 |
