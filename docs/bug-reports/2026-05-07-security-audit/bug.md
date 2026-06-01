# Bug 详细分析报告

**Bug ID:** BUG-001 ~ BUG-006
**发现日期:** 2026-05-07
**状态:** 已确认

## BUG-001: 前端 `sanitizeAgainstInjection` 是空函数

- **位置:** `frontend/src/utils/validate.js:15-17`
- **症状:** 函数签名存在但直接返回原始字符串
- **根因:** 开发者移除了 SQL 注入正则（"后端使用参数化查询"），但未清理调用点
- **调用点:**
  1. `validatePayload()` (`validate.js:153-162`) — 批量消毒入口
  2. `PracticePanel.vue` — 用户答案输入
  3. `StagingPanel.vue` — 暂存区数据
  4. `MasterBankList.vue` — 题库编辑
  5. `SearchFilterBar.vue` — 搜索输入
- **影响:** 虽然后端使用参数化查询防 SQL 注入，但前端缺少 XSS 消毒。用户输入如果包含 `<script>` 等标签，可能在 markdown 渲染或 DOM 插入时触发 XSS
- **缓解因素:** 项目使用 DOMPurify 对 markdown 渲染做了消毒（`markdown.js`），`v-html` 使用受限。但直接的 DOM 绑定（如 `:href`）仍存在风险
- **严重程度:** P1

## BUG-002: `/api/analytics` 未按 bank_mode 过滤数据

- **位置:** `backend/app/routers/analytics.py:46-62`
- **症状:** `_query()` 函数内执行 `SELECT tech_stack FROM jd` 和 `SELECT tags, diff_tag FROM questions_detail` 无 WHERE 条件
- **根因:** `get_analytics` 虽然通过 `Depends(get_current_user)` 获取了用户信息，但 `_query()` 闭包完全忽略了 `user` 变量
- **对比:** 同文件中的 `get_practice_stats` 和 `get_knowledge_graph` 都正确使用了 `_build_analytics_bank_filter(user)` 来过滤数据
- **影响:**
  - 个人模式用户可看到所有用户的 JD 技术栈数据
  - 个人模式用户可看到所有用户的面试题标签和难度分布
  - 违反了项目设计的多租户数据隔离原则
- **严重程度:** P0

## BUG-003: URL `href` 绑定无协议验证

- **位置:**
  - `frontend/src/components/QuestionCard.vue:149` — 题目来源链接
  - `frontend/src/components/QuestionCard.vue:172` — 面经来源链接
  - `frontend/src/App.vue:219` — JD 来源链接
  - `frontend/src/App.vue:276` — 面经来源链接
- **症状:** `v-bind:href="item.url"` 或类似绑定，直接将数据库中的 URL 值赋给 `href` 属性
- **根因:** 数据库中的 `url` 字段来自用户上传或爬虫抓取，未经过协议白名单验证
- **攻击向量:**
  1. 攻击者上传包含 `javascript:alert(document.cookie)` 的 URL
  2. 其他用户在页面上看到该链接
  3. 点击链接后执行攻击者注入的 JavaScript
- **严重程度:** P1

## BUG-004: LLM 生成答案端点无速率限制

- **位置:**
  - `backend/app/routers/master_bank.py:767` — `generate_answer`
  - `backend/app/routers/master_bank.py:888` — `batch_generate_answers`
- **症状:** 端点无调用频率限制
- **根因:** 项目未实现速率限制中间件
- **影响:** 恶意用户可通过脚本批量调用 LLM API，消耗配额
- **严重程度:** P2

## BUG-005: API Key 掩码泄露前 4 字符

- **位置:** `backend/app/routers/profile.py:46-49`
- **症状:** `_mask_key("sk-abc123xyz")` 返回 `"sk-a****"`
- **根因:** 掩码逻辑选择暴露前 4 字符以帮助用户识别 Key
- **影响:** API Key 前缀（如 `sk-p` for OpenAI）被泄露，降低了暴力破解的搜索空间
- **严重程度:** P2

## BUG-006: 账户锁定可被用于 DoS

- **位置:** `backend/app/routers/auth.py` 中的登录失败锁定逻辑
- **症状:** 连续 5 次登录失败后锁定账户 15 分钟，锁定基于用户名
- **根因:** 未使用 IP 维度的速率限制
- **攻击场景:**
  1. 攻击者知道目标用户名（如 `sj`）
  2. 故意输入错误密码 5 次
  3. 目标用户被锁定 15 分钟，无法登录
- **严重程度:** P2
