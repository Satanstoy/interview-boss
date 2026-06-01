# Bug 预览报告

**日期:** 2026-05-07
**问题:** 安全专项审计 — 发现多个安全漏洞
**严重程度:** Critical / High / Medium 混合

## 审计范围

| 领域 | 审计内容 |
|------|---------|
| 注入风险 | SQL 注入、XSS、命令注入 |
| 认证与授权 | Token 处理、权限绕过、CSRF |
| 敏感数据暴露 | 错误信息泄露、API Key 处理 |
| 输入校验 | 文件上传、边界值、消毒函数 |
| 并发安全 | 竞态条件、数据损坏 |

## 初步诊断

### BUG-001: 前端 `sanitizeAgainstInjection` 是空函数（High）

- **位置:** `frontend/src/utils/validate.js:15-17`
- **症状:** `sanitizeAgainstInjection(str)` 直接 `return str`，不做任何消毒
- **根因:** 开发者移除了 SQL 注入检测正则（注释说"后端使用参数化查询"），但保留了函数签名和 5 个调用点
- **影响:** `validatePayload()` 遍历对象所有字符串字段调用此函数，实际无任何保护。虽然后端使用参数化查询防 SQL 注入，但前端仍需要 XSS 消毒
- **风险:** 中 — XSS 注入风险（用户输入直接渲染到 DOM）

### BUG-002: `/api/analytics` 未按 bank_mode 过滤数据（High）

- **位置:** `backend/app/routers/analytics.py:51-54`
- **症状:** `SELECT tech_stack FROM jd` 和 `SELECT tags, diff_tag FROM questions_detail` 无任何过滤条件
- **根因:** `get_analytics` 函数虽有 `user` 参数（`Depends(get_current_user)`），但 `_query()` 内部完全忽略用户身份和 bank_mode
- **影响:** 任何登录用户都能看到所有用户的 JD 和面试题数据，绕过 bank_mode 隔离
- **风险:** 高 — 数据泄露，违反多租户隔离原则

### BUG-003: URL `href` 绑定无协议验证（High）

- **位置:** `frontend/src/components/QuestionCard.vue:149,172` 和 `frontend/src/App.vue:219,276`
- **症状:** `v-bind:href` 或 `:href` 直接绑定用户可控的 URL 字段
- **根因:** 未验证 URL 协议是否为 `http:` 或 `https:`
- **影响:** 攻击者可提交 `javascript:alert(1)` 形式的 URL，点击后执行任意 JS
- **风险:** 高 — 存储型 XSS

### BUG-004: LLM 生成答案端点无速率限制（Medium）

- **位置:** `backend/app/routers/master_bank.py:767` (`generate_answer`) 和 `master_bank.py:888` (`batch_generate_answers`)
- **症状:** 无调用频率限制，单用户可无限调用 LLM API
- **根因:** 缺少速率限制中间件或端点级限制
- **影响:** 恶意用户可大量消耗 LLM API 额度，造成经济损失
- **风险:** 中 — 资源滥用

### BUG-005: API Key 掩码泄露前 4 字符（Medium）

- **位置:** `backend/app/routers/profile.py:46-49`
- **症状:** `_mask_key` 返回 `value[:4] + "****"`，暴露 API Key 前 4 个字符
- **根因:** 掩码逻辑设计不当
- **影响:** 部分 API Key 前缀泄露，降低暴力破解难度
- **风险:** 中 — 信息泄露

### BUG-006: 账户锁定可被用于 DoS（Medium）

- **位置:** `backend/app/routers/auth.py:26-27`
- **症状:** 按用户名锁定账户（非 IP），攻击者可对任意用户名发起锁定
- **根因:** 锁定策略基于用户名而非 IP 地址
- **影响:** 攻击者可锁定任意用户账户，阻止合法用户登录
- **风险:** 中 — 拒绝服务

## 风险评估

| Bug ID | 风险类型 | 等级 | 说明 |
|--------|---------|------|------|
| BUG-001 | XSS | High | 空消毒函数，5 个调用点无保护 |
| BUG-002 | 数据泄露 | High | analytics 绕过 bank_mode 隔离 |
| BUG-003 | 存储型 XSS | High | URL href 绑定无协议验证 |
| BUG-004 | 资源滥用 | Medium | LLM 端点无速率限制 |
| BUG-005 | 信息泄露 | Medium | API Key 前 4 字符暴露 |
| BUG-006 | DoS | Medium | 按用户名锁定可被滥用 |

## 优先级排序

| 优先级 | Bug ID | 理由 |
|--------|--------|------|
| P0 | BUG-002 | 数据泄露，任何用户可绕过 bank_mode |
| P1 | BUG-001 | XSS 风险，影响所有用户 |
| P1 | BUG-003 | 存储型 XSS，点击触发 |
| P2 | BUG-006 | DoS 风险，影响可用性 |
| P2 | BUG-005 | 信息泄露，影响机密性 |
| P2 | BUG-004 | 资源滥用，影响成本 |
