# Tech audit — 2026-08-17

**Auditor**: tech-audit skill, under user's direction
**Scope**: full (all dimensions)
**Repo HEAD at audit time**: 935da797239dad8c585428c615a5785adbded01d
**Findings source**: `.tech-audit/work/2026-08-17/findings.tsv` — all 🔴 survived the refutation pass
**Previous audit**: `.tech-audit/work/2026-08-15-r3/findings.tsv` (round-3)

---

## Executive summary

- 🔴 **Top risk**: 生产 SiliconFlow API key 仍在 git 历史且从未轮换，ADMIN_PASSWORD 仅 8 字符
- 🟢 **Top strength**: 认证体系健全（JWT + bcrypt + JTI 追踪 + 账号锁定），SQL 注入防护完善，CORS/安全响应头配置良好
- 🟡 **Biggest gap**: 测试隔离问题（threading.local vs asyncio.to_thread）导致 ~80 个 chat 测试失败，回归测试比例仅 21% 远低于 ≥80% 红线

---

## Status overview

| Dim | Title | Status | 🔴 | 🟡 | 🟢 |
|---|---|---|---|---|---|
| D1 | Code essentiality | ⚠️ | 0 | 1 | 2 |
| D2 | Docs integrity | ⚠️ | 0 | 0 | 2 |
| D3 | Tests as adversaries | ⚠️ | 0 | 2 | 3 |
| D4 | Security posture | ⚠️ | 2 | 0 | 3 |
| D5 | Multi-tenant isolation | ⚠️ | 0 | 0 | 2 |
| D6 | Operational readiness | ⚠️ | 0 | 0 | 3 |
| D7 | Dependency hygiene | ⚠️ | 0 | 1 | 1 |
| D8 | Build / CI / dev-loop | ⚠️ | 0 | 0 | 2 |
| D9 | Data model integrity | ⚠️ | 0 | 2 | 0 |
| D10 | Performance & cost | ⚠️ | 0 | 0 | 2 |
| D11 | Legal / compliance | ⚠️ | 0 | 1 | 2 |
| D12 | Admin surface consistency | ⚠️ | 0 | 2 | 0 |
| D13 | Setup replicability | ⚠️ | 0 | 0 | 1 |
| D14 | Correctness & robustness | ⚠️ | 0 | 0 | 2 |
| D15 | UX & interaction | ⚠️ | 0 | 0 | 2 |
| D16 | UI & design-system craft | ⚠️ | 0 | 0 | 2 |
| **Total** | | **⚠️** | **2** | **9** | **33** |

**Health**: ⚠️ some 3 or a mitigated 4

---

## Trend vs previous audit

| | This pass (round-4) | Last pass (round-3) | Delta |
|---|---|---|---|
| 🔴 | 2 | 2 | ▶ (持平) |
| 🟡 | 9 | 12 | ▼ (改善) |
| 🟢 | 33 | 33 | ▶ (持平) |
| Avg dim status | ⚠️ | ⚠️ | 持平 |

### Closed since last time:
- ✅ D8: CI 缺容器镜像扫描（Trivy）— 现在存在但 exit-code=0 永不阻断（severity 4→2）
- ✅ D13: .env.example 缺 7 个变量 — 现在缺 63+ 个可选变量（severity 3→2，因大部分有默认值）
- ✅ D5: 管理员全量重建题库公开化私有题目 — 已修复（round-2 D5）

### Still open (2+ audits old):
- D4: 生产 API key 在 git 历史（round-2, severity 4）
- D4: 用户 API key 明文落库（round-2, severity 3）
- D4: ADMIN_PASSWORD 仅 8 字符（round-2, severity 3）
- D3: 测试隔离问题（round-2, severity 3）
- D3: line_guard 不覆盖 backend/tests（round-2, severity 3）
- D3: 回归测试比例仅 21%（round-2, severity 3）
- D7: python-jose/passlib 死依赖（round-2, severity 3）
- D7: uvicorn 硬钉（round-2, severity 3）
- D7: vite 落后 4 个大版本（round-2, severity 3）
- D9: 生产库 FK 违规（round-2, severity 3）
- D12: 评测中心无消费者（round-2, severity 3）

### New regressions:
- 🟡 D14: insights.py naive datetime（round-2 email_service 修复的同类遗漏）

---

## D1 — Code essentiality

**Status**: ⚠️ · 死代码清理不彻底，批量 v2 仍被测试引用

### Findings

- 🟡 `backend/app/services/pipeline/batch_v2.py:40` — 383 行死模块仍被 3 个测试/脚本引用
  _Why it matters_: CLAUDE.md 已标注"死代码已清理"但文件仍存在，维护者困惑
  _Suggested fix_: 删除模块，回归测试改指 live compact.py 路径

- 🟢 `frontend/src/components/NavMain.vue:1` — 5 个孤儿 shadcn-vue 组件（326 行，0 引用）
  _Why it matters_: 随 build 发布无用代码
  _Suggested fix_: 删除 5 个文件

- 🟢 `backend/app/services/clustering/experiments/draw_questions_eval.py` — 8 个独立评测 harness（2275 行，无生产/测试/CI 调用者）
  _Why it matters_: 维护负担
  _Suggested fix_: 删除 8 个文件；保留 memory_labels.py/prompts.py/evaluate.py

---

## D2 — Docs integrity

**Status**: ⚠️ · pipeline/CLAUDE.md 标注 batch_v2 "死代码已清理"但文件仍存在

### Findings

- 🟢 `pipeline/CLAUDE.md` — 标注 batch_v2 "死代码已清理"但文件仍存在
  _Why it matters_: 文档与代码不一致
  _Suggested fix_: 更新文档或删除文件

- 🟢 `项目级` — 无独立迁移文档说明破坏性变更与回滚步骤
  _Why it matters_: 迁移失败时运维困难
  _Suggested fix_: 新增 docs/migrations/ 记录关键迁移

---

## D3 — Tests as adversaries

**Status**: ⚠️ · 测试隔离问题严重，回归纪律不足

### Findings

- 🟡 `backend/tests/services/clustering/test_reupload_after_soft_delete.py:38` — autouse fixture 直接 get_db_connection() 直连 DB_PATH
  _Why it matters_: 绕过 test_db fixture，导致 14 errors
  _Suggested fix_: fixture 注入 test_db 内存连接；conftest 加 sentinel 断言无测试打开 DB_PATH

- 🟡 `backend/CLAUDE.md 回归纪律` — 回归测试比例 ~21%（最近 15 个 fix 提交仅 3 个带测试）
  _Why it matters_: 远低于仓库自定 ≥80% 红线
  _Suggested fix_: CI/门禁检查 fix 提交必须带 test_*.py/*.spec.js 变更

- 🟢 `backend/tests/infra/test_public_ip_exposure.py:10-11` — test 镜像缺 git 且未挂 oauth-gateway 源码 → 4 failures
  _Why it matters_: 测试环境不完整
  _Suggested fix_: 镜像装 git + 挂载 oauth-gateway 只读卷

- 🟢 `scripts/line_guard.sh:48,53` — line_guard 不覆盖 backend/tests
  _Why it matters_: test_react_loop.py 3728 行、test_chat.py 2038 行无约束
  _Suggested fix_: 增加第三个 find 循环扫 backend/tests

- 🟢 `backend/tests/coding/test_coding.py:48-418` — coding 测试缺对抗用例
  _Why it matters_: 无跨用户越权、50000 字符边界、恶意 markdown 测试
  _Suggested fix_: 补越权 404/超长边界/恶意导入用例

---

## D4 — Security posture

**Status**: ⚠️ · 2 个 🔴 发现（密钥泄露），认证体系健全

### Findings

- 🔴 `backend/.env:22` — 生产 SiliconFlow API key 仍在 git 历史（8 个提交含 sk-hkaopkq...clym）且从未轮换
  _Why it matters_: 密钥泄露，攻击者可调用 LLM 服务产生费用
  _Suggested fix_: 立即在服务商控制台轮换；git filter-repo 重写/脱敏 8 个提交

- 🔴 `backend/.env:17` — 生产 ADMIN_PASSWORD 仅 8 字符
  _Why it matters_: 暴力破解风险
  _Suggested fix_: 生成 ≥16 字符随机密码并轮换

- 🟡 `backend/app/routers/profile_pkg/llm.py:143-150` — 用户自带 LLM/search API key 明文落库
  _Why it matters_: 数据库泄露导致用户密钥暴露
  _Suggested fix_: Fernet 加密落库（JWT_SECRET 派生密钥）

- 🟢 `backend/app/routers/（189 个路由）` — 仅 audio.py:29 声明 response_model
  _Why it matters_: 响应侧 Pydantic 形状无强制，可能泄露内部字段
  _Suggested fix_: 优先为 auth/data/profile 返回用户 dict/DB 行的路由补 response_model

- 🟢 `error_report.py:19` — 匿名错误上报端点无认证无 IP 限速
  _Why it matters_: 可被滥用产生大量垃圾日志
  _Suggested fix_: 添加 rate limit（如 10/min per IP）

**安全正面评价**:
- 认证体系健全：JWT HS256 + passlib/bcrypt + JTI 追踪 + token family 轮转 + 账号锁定（5 次失败/15 分钟）
- CORS 配置安全：仅在设置 ALLOWED_ORIGINS 时启用
- 安全响应头完整：HSTS / X-Content-Type-Options / X-Frame-Options / CSP / Referrer-Policy / Permissions-Policy
- CSRF 中间件：检查 X-Requested-With 头（主防线有效）
- SQL 注入防护：参数化查询 + 表名白名单 + 列名正则 + ALLOWED_UPDATE_COLUMNS 白名单

---

## D5 — Multi-tenant isolation

**Status**: ⚠️ · owner_id 过滤覆盖广泛，chat 加载 JD 无 deleted_at 过滤

### Findings

- 🟡 `backend/app/routers/chat.py:450-454` — chat 加载关联 JD 无 deleted_at 过滤
  _Why it matters_: 软删 JD 仍进 LLM 上下文
  _Suggested fix_: 两处查询均加 AND deleted_at IS NULL

- 🟡 `backend/app/agents/chat/memory_extract.py:128-130` — _get_jd_title 无 owner_id/deleted_at 过滤
  _Why it matters_: 可能泄露其他用户数据
  _Suggested fix_: 添加 owner_id 和 deleted_at 过滤

**隔离正面评价**:
- owner_id 过滤覆盖广泛：routers/data.py、questions.py、coding.py、analytics.py、bank_build.py、admin_review.py 等均有完善的 owner_id 过滤
- deleted_at 过滤覆盖全面：interview、questions_detail、question_bank、jd 等主要表均有过滤
- chat 会话隔离正确：get_conversation/archive/delete 均校验 user_id

---

## D6 — Operational readiness

**Status**: ⚠️ · 健康检查不完整，无运维 runbook

### Findings

- 🟡 `deploy/docker-deploy.sh:458-476` — 备份文件无限积累无轮转策略（333 文件 / 1.3GB）
  _Why it matters_: 磁盘空间耗尽风险
  _Suggested fix_: 添加保留期清理（如保留最近 7 天）

- 🟡 `backend/app/routers/health.py:9-21` — 健康检查仅查 SQLite，不检查 Redis/worker 状态
  _Why it matters_: 部分组件故障无法通过健康检查发现
  _Suggested fix_: 添加 Redis ping + worker 状态检查

- 🟡 `项目级` — 无应用级监控（请求延迟/错误率/LLM 成功率）
  _Why it matters_: 性能问题无法及时发现
  _Suggested fix_: 添加 Prometheus 指标端点

---

## D7 — Dependency hygiene

**Status**: ⚠️ · 死依赖仍存在，基础镜像用可变 tag

### Findings

- 🟡 `Dockerfile:30,147` + `oauth-gateway/Dockerfile:1` — 基础镜像用可变 tag 无 digest 固定
  _Why it matters_: 构建不完全可复现
  _Suggested fix_: 至少文档化可变 tag 权衡；生产 bar 再 digest-pin

- 🟢 `项目级` — 无自动依赖更新工具（dependabot/renovate）
  _Why it matters_: CVE 修复延迟不可控
  _Suggested fix_: 新增 dependabot.yml（python-uv + npm，weekly，HIGH/CRITICAL 标记）

---

## D8 — Build / CI / dev-loop

**Status**: ⚠️ · Trivy 扫描存在但非阻断，部署脚本无版本号

### Findings

- 🟡 `.github/workflows/ci.yml:87-91` — Trivy 扫描存在但 exit-code=0 永不阻断
  _Why it matters_: 漏洞扫描形同虚设
  _Suggested fix_: 设置 exit-code=1 并清零存量漏洞

- 🟡 `deploy/docker-deploy.sh` — 部署脚本无版本号，无法回溯某次部署对应哪个 commit
  _Why it matters_: 问题排查困难
  _Suggested fix_: 部署时记录 git commit hash 到日志或文件

---

## D9 — Data model integrity

**Status**: ⚠️ · FK 缺 ON DELETE 策略，硬删数据无级联清理

### Findings

- 🟡 `schema_hygiene.py:484-493` — analysis_queue.interview_id FK 缺 ON DELETE 策略
  _Why it matters_: hard-delete interview 会因 NO ACTION 阻塞或留孤儿行
  _Suggested fix_: 添加 ON DELETE SET NULL 或 ON DELETE CASCADE

- 🟡 `analytics.py:316-342` — clear_db 硬删 jd/interview/questions_detail/question_bank 后 chat/practice 表成不可达孤儿
  _Why it matters_: 数据不一致，可能影响 LLM 上下文
  _Suggested fix_: 级联清理或软删除

---

## D10 — Performance & cost

**Status**: ⚠️ · 无性能基线，LLM 配额仅按调用次数限流

### Findings

- 🟡 `项目级` — 无性能基线：无 load test / latency benchmark / p50/p95 文档
  _Why it matters_: 性能退化无法量化
  _Suggested fix_: 添加基准测试和性能文档

- 🟡 `llm_quota.py:34-55` — LLM 配额仅按调用次数限流，total_tokens 仅统计不参与决策
  _Why it matters_: 200 次×短答 vs 200 次×长文成本差 2×
  _Suggested fix_: 配额考虑 token 数量（如每日 100 万 token）

---

## D11 — Legal / compliance

**Status**: ⚠️ · 无数据导出 API，破坏性操作无审计

### Findings

- 🟡 `analytics.py:285-352` — clear_db 高危操作无审计日志
  _Why it matters_: 误操作无法追溯
  _Suggested fix_: admin_assistant_log 记录 clear_db/normalize_categories

- 🟡 `项目级` — 无数据导出 API（privacy-policy.md sec.5 声明"可请求导出"但无实现）
  _Why it matters_: 违反隐私政策承诺
  _Suggested fix_: 实现 owner 作用域 GET /api/account/export

- 🟡 `account-deletion.md:9` — 账号删除纯手工流程，无自动化接口
  _Why it matters_: 用户体验差，运维负担
  _Suggested fix_: 实现账号删除 API + 定时清理任务

---

## D12 — Admin surface consistency

**Status**: ⚠️ · 破坏性操作无二次确认和审计

### Findings

- 🟡 `analytics.py:285-286` — clear_db 无二次确认
  _Why it matters_: 单个 POST 直接清空全库，误操作风险极高
  _Suggested fix_: 添加 confirmation token/预览步骤

- 🟡 `analytics.py:285-352` — 管理界面缺破坏性操作审计
  _Why it matters_: clear_db/normalize_categories/batch-delete 无统一审计日志
  _Suggested fix_: 统一审计日志（admin_assistant_log）

---

## D13 — Setup replicability

**Status**: ⚠️ · .env.example 缺 63+ 个可选变量

### Findings

- 🟡 `backend/.env.example:1-48` — .env.example 仅文档 48 个变量，代码实际使用 ~110 个
  _Why it matters_: 新运维者需 grep 源码发现可调旋钮
  _Suggested fix_: 按功能域分组补全所有 os.environ.get 调用的可选变量占位行

---

## D14 — Correctness & robustness

**Status**: ⚠️ · naive datetime 问题，缓存策略不合理

### Findings

- 🟡 `backend/app/services/insights.py:479` — datetime.now().date() 无时区感知
  _Why it matters_: 与 email_service 同类 naive datetime 问题，可能导致时间计算错误
  _Suggested fix_: 统一用 datetime.now(timezone.utc) 或项目级 utcnow() 辅助函数

- 🟡 `backend/app/services/llm.py:290-294` — _user_client_cache 半数淘汰策略无 TTL/LRU
  _Why it matters_: 高频用户可能刚被淘汰又被重建
  _Suggested fix_: 改为 LRU 淘汰或加 TTL

---

## D15 — UX & interaction

**Status**: ⚠️ · 无障碍访问不完整，destructive action 无确认

### Findings

- 🟡 `frontend/src/components/business/PracticePanel.vue:19` — 图标关闭按钮无 aria-label
  _Why it matters_: 屏幕阅读器无法识别
  _Suggested fix_: 加 aria-label="关闭" 或改用 AppTooltip 包裹

- 🟡 `frontend/src/components/business/CodingPractice.vue:68,378` — 移出题单/取消收藏 destructive action 无确认步骤
  _Why it matters_: 点击即执行，无撤销机会
  _Suggested fix_: 在 removeProblemFromCurrentList 入口加 useConfirm() 确认对话框

---

## D16 — UI & design-system craft

**Status**: ⚠️ · ECharts 配置内联设计 token，死组件随 build 发布

### Findings

- 🟡 `frontend/src/components/business/KnowledgeGraph.vue:94-177` — ECharts 图表配置内联 14 个 porcelain hex 值
  _Why it matters_: 绕过 chartTokens.js 设计 token，主题切换时颜色不一致
  _Suggested fix_: 统一 import { porcelain, porcelainTooltip } from '@/utils/chartTokens.js'

- 🟢 `frontend/src/components/business/ExamDistribution.vue:109-119` — 死组件（0 引用）内联 6 个主题色 hex
  _Why it matters_: 随 build 发布无用代码
  _Suggested fix_: 删除文件或标 deprecated

---

## Triage — proposed follow-up milestones

| Finding | Suggested milestone | Effort |
|---|---|---|
| 🔴 D4-3 — 生产 API key 在 git 历史 | SEC-1: 立即轮换密钥 + git filter-repo 重写 | 4 h |
| 🔴 D4-4 — ADMIN_PASSWORD 仅 8 字符 | SEC-2: 生成并轮换强密码 | 1 h |
| 🟡 D3-1 — 测试隔离问题 | TEST-1: 修复 threading.local vs asyncio.to_thread | 1 day |
| 🟡 D3-2 — 回归测试比例仅 21% | TEST-2: CI 门禁检查 fix 提交必须带测试 | 4 h |
| 🟡 D4-5 — 用户 API key 明文落库 | SEC-3: Fernet 加密落库 | 1 day |
| 🟡 D7-1 — 死依赖 python-jose/passlib | DEP-1: 迁 PyJWT + 直连 bcrypt | 4 h |
| 🟡 D7-2 — uvicorn 硬钉 | DEP-2: 放开 uvicorn>=0.30 | 2 h |
| 🟡 D9-1 — FK 缺 ON DELETE 策略 | DATA-1: 添加 ON DELETE 策略 | 2 h |
| 🟡 D12-1 — clear_db 无二次确认 | ADMIN-1: 添加 confirmation token | 4 h |

---

## Appendix — 🟢 findings (optional)

- D1-2: 5 个孤儿 shadcn-vue 组件（326 行，0 引用）
- D1-3: 8 个独立评测 harness（2275 行，无生产调用者）
- D2-1: pipeline/CLAUDE.md 标注 batch_v2 "死代码已清理"但文件仍存在
- D2-2: 无独立迁移文档
- D3-3: test 镜像缺 git 且未挂 oauth-gateway 源码
- D3-4: line_guard 不覆盖 backend/tests
- D3-5: coding 测试缺对抗用例
- D4-6: 仅 audio.py:29 声明 response_model
- D5-3: owner_id 过滤覆盖广泛
- D5-4: deleted_at 过滤覆盖全面
- D6-1: 备份文件无限积累无轮转策略
- D6-2: 健康检查仅查 SQLite
- D6-3: 无应用级监控
- D7-3: 无自动依赖更新工具
- D8-1: Trivy 扫描存在但 exit-code=0
- D8-2: 部署脚本无版本号
- D10-1: 无性能基线
- D10-2: LLM 配额仅按调用次数限流
- D11-1: clear_db 无审计日志
- D11-2: 无数据导出 API
- D11-3: 账号删除纯手工流程
- D13-1: .env.example 缺 63+ 个可选变量
- D14-1: insights.py naive datetime
- D14-2: _user_client_cache 半数淘汰策略无 TTL/LRU
- D15-1: 图标关闭按钮无 aria-label
- D15-2: destructive action 无确认步骤
- D16-1: ECharts 配置内联 14 个 porcelain hex
- D16-2: 死组件内联 6 个主题色 hex
