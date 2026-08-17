# Tech audit — 2026-08-17

**Auditor**: tech-audit skill, under user's direction
**Scope**: full (D1-D16)
**Repo HEAD at audit time**: `6d7e25ba04e2f850ceafcadd654dc313304422b5`
**Findings source**: `.tech-audit/work/2026-08-17/findings.tsv`
**Previous audit**: [2026-08-15-r3](../analysis/tech-audit-2026-08-15-r3.md)

> 审计期间保留了用户/并发产生的未提交 `uv.lock` 和 `experiment_reports/`，没有纳入审计提交。依赖漏洞数字按当前工作树导出结果记录。

## Executive summary

- 🔴 **Top risk**: SiliconFlow API key 仍在运行环境和可达 git 历史中；是否仍有效需要在服务商侧确认并立即轮换。
- 🟢 **Top strength**: 认证、API key Fernet 加密、题库公共范围过滤、SQLite 在线备份、基础构建/结构测试已明显改善。
- 🟡 **Biggest gap**: `check.sh` 的“总 PASS”掩盖了质量债：后端关键子集 72 个失败，静态检查仍有 175 ruff / 436 mypy / 13 ESLint errors。

## Status overview

| Dim | Title | Status | 🔴 | 🟡 | 🟢 |
|---|---|---:|---:|---:|---:|
| D1 | Code essentiality | ⚠️ | 0 | 1 | 0 |
| D2 | Docs integrity | ⚠️ | 0 | 2 | 0 |
| D3 | Tests as adversaries | ⚠️ | 0 | 2 | 0 |
| D4 | Security posture | ❌ | 1 | 3 | 0 |
| D5 | Multi-tenant isolation | ⚠️ | 0 | 2 | 0 |
| D6 | Operational readiness | ⚠️ | 0 | 7 | 0 |
| D7 | Dependency hygiene | ⚠️ | 0 | 4 | 0 |
| D8 | Build / CI / dev-loop | ⚠️ | 0 | 4 | 0 |
| D9 | Data model integrity | ⚠️ | 0 | 3 | 0 |
| D10 | Performance & cost | ⚠️ | 0 | 1 | 0 |
| D11 | Legal / compliance | ⚠️ | 0 | 3 | 0 |
| D12 | Admin surface consistency | ⚠️ | 0 | 1 | 0 |
| D13 | Setup replicability | ⚠️ | 0 | 2 | 0 |
| D14 | Correctness & robustness | ⚠️ | 0 | 2 | 1 |
| D15 | UX & interaction | ⚠️ | 0 | 2 | 1 |
| D16 | UI & design-system craft | ⚠️ | 0 | 1 | 1 |
| **Total** | | **⚠️** | **1** | **40** | **3** |

## Verification evidence

- `./scripts/check.sh all` exit 0，但其 summary 明确标注 “Audit checks: WARN only”。阻塞项通过；审计项并不代表通过。
- 后端关键子集：`72 failed, 2404 passed, 7 skipped, 11 deselected`。
- `uv run ruff check backend/app`：175 条、66 个文件；`uv run mypy backend/app`：436 条、79 个文件。
- `npm run build` 和默认 Playwright smoke 通过；`npm run lint`：13 errors / 50 warnings。
- `npm audit --omit=dev`：16 条生产漏洞，其中 9 high；当前工作树导出依赖 `pip-audit`：9 条、4 个包。
- `PRAGMA foreign_key_check`：178 条违规；其中 115 条验证码记录已过期且仍未使用。
- 运行态：核心服务健康，但 eval timer 为 `inactive/not-found`，没有 `eval-worker`；worker 仍运行旧 image digest。

## Trend vs previous audit

按 findings.tsv 的机械口径（4=🔴，2/3=🟡，1=🟢）：

| | This pass | Last pass | Delta |
|---|---:|---:|---:|
| 🔴 | 1 | 3 | ▼ 2 |
| 🟡 | 40 | 47 | ▼ 7 |
| 🟢 | 3 | 8 | ▼ 5 |
| Total | 44 | 58 | ▼ 14 |

这个下降不能直接当作“已清零”：本轮合并了同类项、把已修复项移出 TSV，并新增了运行态/门禁证据。

### 已确认修复或缓解

- 用户 API key 已改为 Fernet 加密落库；旧的明文落库 finding 不再列为当前开放项。
- `python-jose/passlib` 已迁移到 PyJWT/bcrypt，`uvicorn` 硬钉已解开；但当前 `uv.lock` 仍是未提交的工作树变更，必须提交后才算可复现修复。
- `threading.local` 已改为 `ContextVar`，管理员题库重建已限制为公共、approved 面经，`clear_db` 已增加确认 token 和备份。
- `analysis_queue.interview_id` 已加入 `ON DELETE CASCADE`；但历史孤儿数据仍需单独修复，不能把迁移代码修复当作数据库已健康。
- PracticePanel 关闭按钮、KnowledgeGraph 图表 token、验证码原子消费等旧项已落地。
- Trivy、gitleaks、合规文档已加入仓库；但 Trivy/static/audit 仍不是 blocking，合规导出/删除仍未实现。

### 之前 TSV 仍未解决的重点

- D4：历史 API key、ADMIN_PASSWORD 弱口令、路由缺少 response model、动态 SQL 拼接。
- D3/D8：真实全栈 E2E 缺失、后端测试仍有 72 失败、line guard 不扫测试、静态检查 WARN-only。
- D6/D12：eval worker 没有实际启用、cron 没有 last-run 可见性、健康检查只查 SQLite、缺运维 runbook、破坏性操作缺应用审计。
- D7：npm 16 条生产漏洞、Python 9 条漏洞、Vite 4、没有依赖机器人；旧 jose/passlib/uvicorn 本身已修复。
- D9/D14：生产库 178 条 FK 违规、迁移连接 FK 开关不显式、email naive datetime、client cache 半清空、提交后再入队的崩溃窗口。
- D11/D15/D16：无导出/自助删除路径、注册无明确隐私同意记录、原生 `window.confirm`、图表 token 漂移和死组件。

## D1 — Code essentiality

**Status**: ⚠️ · 仍有生产零调用的历史实现被测试依赖。

- 🟡 `backend/app/services/pipeline/batch_v2.py:1-383` — batch_v2 是死实现，但被源码回归测试保留，形成维护分叉。建议先把测试改到 live compact/batch 路径，再删除或隔离该模块。

## D2 — Docs integrity

**Status**: ⚠️ · 修复状态和运行版本声明存在漂移。

- 🟡 `docs/specs/2026-08-17-audit-round4-fixes.md:10-20` — A-I 仍全部是“未开始”，与已落地提交相反；应按提交逐项回填并与 findings.tsv 对齐。
- 🟡 `pyproject.toml:6; Dockerfile:30; .python-version:1` — 项目声明 Python >=3.11，但实际 Docker/mypy/文档按 3.12；统一最低版本或增加 3.11 CI 矩阵。

## D3 — Tests as adversaries

**Status**: ⚠️ · 回归套件不是绿色，真实链路和对抗覆盖不足。

- 🟡 `scripts/check.sh:84-90` — 关键后端子集 72 个失败，仍被 WARN-only 包装；应按失败簇修复并恢复 blocking。
- 🟡 `frontend/tests/e2e/*.spec.js` — 29 条 spec 中 25 条使用 `page.route` mock，没有自动化真实前后端/Redis/worker 链路；现有 real-e2e verifier 更像手动/显式 opt-in 工具，不能替代 CI gate。

## D4 — Security posture

**Status**: ❌ · 有一项必须立即处理的密钥暴露风险。

- 🔴 `backend/.env:22; git history (43b0a3a7, 8c070972 等)` — SiliconFlow key 仍在当前运行环境并留在可达历史，是否仍有效尚未核实。立即轮换/撤销、重写可达历史，并用 gitleaks 全史扫描确认；报告不记录 key 内容。
- 🟡 `backend/.env:17; backend/app/db/migrations/auth.py:114-123` — 当前 ADMIN_PASSWORD 仅 11 字符，源码只检查存在，不强制长度；应轮换为随机 16+ 字符并加入生产配置校验。
- 🟡 `backend/app/routers/` — 约 190 个路由只有 `audio.py` 声明 `response_model`，DB row/dict 直接穿过 API 边界；优先给 auth/profile/data/admin 补响应模型。
- 🟡 `backend/app/db/queries.py:72-96` — user_id 直接进入动态 SQL f-string；当前调用类型为 int，但缺少边界强制和参数化契约，应先 int 校验并白名单 alias。

## D5 — Multi-tenant isolation

**Status**: ⚠️ · 公共题库隔离已改善，但软删可见性和额度并发仍有缺口。

- 🟡 `backend/app/routers/chat.py:444-454; backend/app/agents/chat/memory_extract.py:121-134` — JD 读取只按 id，不过滤 `deleted_at`；软删 JD 仍可能进入上下文/标题，应统一走 owner + deleted_at 可见性查询。
- 🟡 `backend/app/services/llm_quota.py:34-55` — 配额先 SELECT 再 UPSERT，并发下可能多个请求同时通过并超出上限；改为单条条件 UPSERT 并补并发测试。

## D6 — Operational readiness

**Status**: ⚠️ · 核心服务可启动，但后台任务、告警和恢复能力仍不闭环。

- 🟡 `docker-compose.yml:160-181; deploy/systemd/interview-boss-eval-worker.timer` — eval worker 依赖的 timer 当前 inactive/not-found，运行态无 eval-worker，queued 评测可能无人消费。
- 🟡 `runtime worker image; backend/data/interview-boss.db` — worker 仍运行旧 image；当前有 115 条未使用过期验证码和 574 条 done analysis_queue，说明 retention 任务不能只看代码存在，还要看实际部署执行。
- 🟡 `backend/app/routers/health.py:10-21; docker-compose.yml:224-276` — health 只检查 SQLite，nginx/oauth-gateway 无 healthcheck，Redis/worker 故障可能仍显示健康。
- 🟡 `backend/app/worker.py:1384-1391` — 6 个 cron 没有 last-run/status/失败可见性。
- 🟡 `backend/data/` + `backups/` — 数据 738M、备份 1.3G 位于同一故障域，备份无保留轮转；需外部存储、容量告警、恢复演练。
- 🟡 `docs/; deploy/docker-deploy.sh` — 没有覆盖 DB down、LLM 5xx、配额耗尽、磁盘满、OOM、恢复回滚的最小 runbook。

## D7 — Dependency hygiene

**Status**: ⚠️ · 当前前后端依赖仍有可修漏洞，更新流程也不自动化。

- 🟡 `frontend/package.json; frontend/package-lock.json` — production audit 16 条、9 high；需要升级/替换受影响包并保留可审计豁免。
- 🟡 `pyproject.toml; uv.lock` — 当前导出依赖 audit 9 条，涉及 aiohttp/click/cryptography/mcp；按修复版本升级并提交锁文件。
- 🟡 `frontend/package.json:47` — Vite 仍为 4.x，且没有 Node engines，CI Node 20 与 Docker Node 22 无兼容性守卫。
- 🟡 `.github/` — 没有 Dependabot/Renovate，漏洞发现依赖人工。

## D8 — Build / CI / dev-loop

**Status**: ⚠️ · 阻塞结构检查通过，但静态质量未成为门禁。

- 🟡 `scripts/check.sh:151-179; .github/workflows/ci.yml:38-39` — 175 ruff、436 mypy、13 ESLint errors/50 warnings 都可通过总门禁；应逐步清债并 blocking。
- 🟡 `scripts/line_guard.sh:45-53` — 不扫 backend/tests，超大测试文件没有增长约束。
- 🟡 `.githooks/commit-msg` — hook 没有 fresh-clone 安装入口。
- 🟡 `oauth-gateway/Dockerfile:1; Dockerfile:30` — 基础镜像可变 tag、未 digest pin，构建不可完全复现。

## D9 — Data model integrity

**Status**: ⚠️ · 迁移代码有改善，但当前库仍不健康。

- 🟡 `backend/data/interview-boss.db; schema_hygiene_2.py:30-72` — `foreign_key_check` 实测 178 条违规；migration 090 只改 FK 策略，没有清理既有孤儿。
- 🟡 `backend/app/db/connection.py:48-53` — `init_db` 迁移连接未显式开启 `PRAGMA foreign_keys=ON`，应在迁移前后设置并断言。
- 🟡 `backend/app/db/migrations/__init__.py:15-16; schema_hygiene_2.py:48-72` — migration 090 会 DROP/rebuild `analysis_queue`，却不在 destructive backup 集合中；应纳入自动备份和回滚测试。

## D10 — Performance & cost

**Status**: ⚠️ · 已有调用次数配额，但成本上限不精确。

- 🟡 `backend/app/services/llm_quota.py:4-14` — `total_tokens` 只统计，不参与决策；短答和长文的同次数成本可能差异很大。增加 token/金额预算及 provider/model 成本表。

## D11 — Legal / compliance

**Status**: ⚠️ · 合规文档已补齐，但注册同意和用户权利执行仍不完整。

- 🟡 `frontend/src/components/business/LoginModal.vue:137-149` — 注册表单没有呈现政策/条款并记录版本化同意；应在注册前展示链接并保存 policy version/timestamp。
- 🟡 `backend/app/db/migrations/evaluation.py:194-204; docs/compliance/account-deletion.md:7-16` — 删除仍靠运营者手工处理，`eval_human_reviews.reviewer_id ON DELETE RESTRICT` 可能阻塞管理员删除；需设计匿名化/SET NULL 和可审计流程。
- 🟡 `backend` — 没有 account export endpoint 或可审计导出流程，隐私政策的“可协助导出”仍是人工口径。

## D12 — Admin surface consistency

**Status**: ⚠️ · 破坏性操作确认已补，但审计链不完整。

- 🟡 `backend/app/routers/analytics.py:323-396` — `clear_db` 有确认 token 和备份，却没有写入管理员审计日志；应记录 admin、目标、备份路径、结果和时间。

## D13 — Setup replicability

**Status**: ⚠️ · 新环境仍需要猜配置和机器路径。

- 🟡 `backend/.env.example:1-48` — 仅约 48 行，代码约读取 110 个变量，缺 63 个可选配置占位；应补默认值、敏感性和生产必填说明。
- 🟡 `docker-compose.yml:212` — HF cache 默认绑定 `/home/ubuntu/.cache/huggingface`，换用户/机器不可复现；应改为项目/XDG 路径并校验权限。

## D14 — Correctness & robustness

**Status**: ⚠️ · 时间、缓存和异步补偿仍有边界问题。

- 🟡 `backend/app/services/email_service.py:104,126,149,207,264` — 验证码/锁定账本混用 naive datetime.now；统一 timezone-aware UTC 并补跨时区测试。
- 🟡 `backend/app/services/llm.py:237-296` — client cache 满时一次性丢弃最旧一半，无 TTL/LRU；改为有界 LRU/TTL 并加指标。
- 🟡 `backend/app/routers/data.py:925-937` — interview 更新提交后才创建 reprocess job，进程在两步间退出会丢补处理；采用 outbox/durable job 事务或补偿扫描。
- 🟢 `backend/app/agents/chat/react_loop.py:522-543` — return 后有不可达日志代码，属于低优先级清理项。

## D15 — UX & interaction

**Status**: ⚠️ · destructive action 和统一提示组件仍有遗留。

- 🟡 `frontend/src/components/business/CodingPractice.vue:68,378` — 移出题单/取消收藏无确认。
- 🟡 `frontend/src/views/PracticeDecksView.vue:51; frontend/src/components/SiteHeader.vue:99` — 删除题单仍用原生 `window.confirm`，与统一 AlertDialog 约定不一致。
- 🟢 `frontend/src/components/business/PracticeMode.vue:141,177,435,462` — 原生 title 低优先级绕过 Tooltip 约定。

## D16 — UI & design-system craft

**Status**: ⚠️ · KnowledgeGraph 已修复，但其他图表仍绕 token。

- 🟡 `frontend/src/components/business/PracticeStarChart.vue:47-103; PracticeQuadChart.vue:33-122` — 多组 porcelain hex/rgba 内联，主题切换容易漂移；统一使用 chartTokens。
- 🟢 `frontend/src/components/business/ExamDistribution.vue:109-119` — 0 引用死组件仍随源码发布且内联主题色；删除或标为 fixture。

## Triage — proposed follow-up milestones

沿用仓库现有 `M-*` 编号，建议从 `M-57` 起分批处理：

| 优先级 | 建议 milestone | 范围 | Effort |
|---|---|---|---|
| P0 | **M-57** | 轮换/撤销 API key、历史脱敏重写、gitleaks 全史复核 | M |
| P0 | **M-58** | 让后端 72 个失败先按隔离/契约簇收敛，恢复 blocking | L |
| P0 | **M-59** | 修复 178 条 FK 违规，补 migration 090 备份和发布门禁 | M |
| P1 | **M-60** | 部署 eval timer/worker、cron 心跳、健康检查和 retention 观测 | M |
| P1 | **M-61** | npm/Python 漏洞清零，提交当前 uv.lock，升级 Vite/Node 并接 Dependabot | L |
| P1 | **M-62** | 真实全栈 E2E、静态检查清债、测试 line guard 和 CI blocking | L |
| P2 | **M-63** | 导出/删除/注册同意/评测 reviewer 删除策略 | M |
| P2 | **M-64** | 时间、配额并发、outbox、缓存、destructive UX 和图表 token 收敛 | M |

## Conclusion

当前项目不是“没有问题”，而是“核心阻塞检查通过，但审计质量项被静默降级”。之前 TSV 中最危险的密钥、生产数据完整性、评测 worker、依赖漏洞、真实 E2E、运维可观测性和合规执行问题仍没有全部解决。建议先处理 P0 三项，再把 `check.sh` 的 WARN-only 逐步收紧；在此之前不应把总退出码 0 作为可发布结论。
