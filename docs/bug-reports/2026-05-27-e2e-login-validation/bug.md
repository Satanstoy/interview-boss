# Bug 详细分析报告

**Bug ID:** BUG-001, BUG-002, BUG-003
**发现日期:** 2026-05-27
**状态:** 已确认

## 问题概述

E2E Playwright 测试 + 深度代码审查发现 3 个 Bug。

## 根本原因分析

### BUG-001: 前后端正则表达式字符范围不一致

- **位置:** `frontend/src/utils/validate.js:58` 和 `backend/app/routers/auth.py:95`
- **症状:** 前端 `USERNAME_RE = /^[a-zA-Z0-9_一-龥]{2,32}$/`（U+4E00-U+9FA5），后端 `_USERNAME_RE = re.compile(r'^[a-zA-Z0-9_一-鿿]{2,32}$')`（U+4E00-U+9FFF）。90 个 CJK 扩展 A 区汉字被前端误拒。
- **根因:** 前端使用了较早的 Unicode 范围 `龥`（U+9FA5），后端使用了完整的 CJK 范围 `鿿`（U+9FFF）。
- **影响:** 使用生僻汉字用户名的用户无法通过前端注册/登录。
- **严重程度:** P2

### BUG-002: PracticePanel 消毒函数返回值被丢弃

- **位置:** `frontend/src/components/business/PracticePanel.vue:330, 359`
- **症状:** `sanitizeAgainstInjection()` 调用后返回值被丢弃，未消毒的输入直接发送到服务器。try-catch 是死代码（函数永不抛异常）。
- **根因:** 开发者写成 `sanitizeAgainstInjection(...)` 而非 `qState._editAnswer = sanitizeAgainstInjection(...)`。
- **影响:** XSS 防护失效，恶意脚本可存储到数据库。DOMPurify 是最后防线，但存储层无保护。
- **严重程度:** P1

### BUG-003: GET 缓存在数据变更后未失效

- **位置:** `frontend/src/App.vue:635`（fetchTableData）
- **症状:** 用户点击"刷新"按钮时，30 秒内的 GET 缓存返回过期数据。
- **根因:** `fetchTableData` 未在请求前清除缓存。
- **影响:** 快速操作后刷新可能看到过期数据。
- **严重程度:** P3

## 复现步骤

### BUG-001
1. 打开注册页面
2. 输入含 U+9FA6-U+9FFF 字符的用户名（如 "鿿鿿"）
3. 前端报错 "用户名仅允许..."，但后端实际接受该用户名

### BUG-002
1. 打开练习面板
2. 在参考答案编辑框中输入 `<script>alert(1)</script>`
3. 点击保存
4. 检查数据库，未消毒的内容被存储

### BUG-003
1. 对题目进行操作（如标记星标）
2. 立即点击"刷新"按钮
3. 数据可能未更新（返回缓存）

## 修复建议
- BUG-001: 将 `一-龥` 改为 `一-鿿`
- BUG-002: 使用 `sanitizeAgainstInjection` 的返回值
- BUG-003: 在 `fetchTableData` 开头调用 `invalidateCache()`
