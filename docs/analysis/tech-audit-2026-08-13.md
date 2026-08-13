# Tech audit — 2026-08-13

**Auditor**: tech-audit skill，在用户指示下执行
**Scope**: full（全部 16 维度）
**Repo HEAD at audit time**: 96d25f2（master，2026-08-13）
**Findings source**: `.tech-audit/work/2026-08-13/findings.tsv`（60 条）— 全部 🔴 已过 refutation pass
**Previous audit**: [tech-audit-2026-08-05.md](tech-audit-2026-08-05.md)（13🔴 / 50🟡 / 15🟢）
**Stack**: Python/FastAPI + LangGraph（chat 为纯 async harness）· Vue3/Vite/Tailwind/shadcn-vue · SQLite WAL + FAISS · Docker Compose + ARQ worker + oauth-gateway · Bash (deploy/)

---

## Executive summary

- 🔴 **Top risk**: 密钥卫生出现真实泄露 — SiliconFlow API key 硬编码在 4 个实验脚本且进入 git 历史（工作树中仍存在）；JWT_SECRET 与 OAUTH_SECRET_KEY 两个集群内部密钥以公开占位值 ship 进 .env.example / compose 兜底。当前生产 env 均已覆盖强随机值，风险集中在**新建部署照抄示例**与**密钥泄露面**。
- 🟢 **Top strength**: 核心工程持续优秀 — chat 链路（BEGIN IMMEDIATE 回合占用、client_request_id 幂等、side-effect job 持久化）、认证（bcrypt+锁定+JWT 轮转+jti 服务端记录+CSRF）、78 个幂等事务迁移、55 个跨用户对抗用例、WAL 安全在线备份均已到位且上轮 🔴（裸 cp 备份、PROJECT_DIR 硬编码、commit-msg 文档谎言、EOL 基础镜像、oauth-gateway root 容器）全部修复。
- 🟡 **Biggest gap**: 工程化基建依旧是最大债 — 零 CI（上轮 🔴 未落地）且门禁无 secret 扫描（本轮实测发现已提交的 API key，若 CI 有 gitleaks 可当场拦截）；test 容器读写挂载生产 data 卷（一条未走 fixture 的测试路径即可污染真库）；D1 三个巨型文件继续膨胀（chat_service +106 行/8 天）。

---

## Status overview

| Dim | Title | Status | 🔴 | 🟡 | 🟢 |
|---|---|---|---|---|---|
| D1 | Code essentiality | ❌ | 3 | 0 | 4 |
| D2 | Docs integrity | ✅ | 0 | 0 | 3 |
| D3 | Tests as adversaries | ❌ | 1 | 3 | 2 |
| D4 | Security posture | ❌ | 1 | 5 | 1 |
| D5 | Multi-tenant isolation | ⚠️ | 0 | 1 | 0 |
| D6 | Operational readiness | ⚠️ | 0 | 2 | 3 |
| D7 | Dependency hygiene | ✅ | 0 | 0 | 4 |
| D8 | Build / CI / dev-loop | ❌ | 2 | 0 | 2 |
| D9 | Data model integrity | ⚠️ | 0 | 1 | 3 |
| D10 | Performance & cost | ✅ | 0 | 0 | 2 |
| D11 | Legal / compliance | ⚠️ | 0 | 3 | 0 |
| D12 | Admin surface consistency | ✅ | 0 | 0 | 1 |
| D13 | Setup replicability | ⚠️ | 2 | 1 | 1 |
| D14 | Correctness & robustness | ❌ | 1 | 0 | 5 |
| D15 | UX & interaction | ✅ | 0 | 0 | 2 |
| D16 | UI & design-system craft | ✅ | 0 | 0 | 1 |
| **Total** | | | **10** | **16** | **34** |

（状态口径：✅ = 无 🔴 且 🟡≤2；⚠️ = 有 🟡 或已被缓解的 🔴；❌ = 未缓解的 🔴。D13 的两个密钥占位 🔴 因生产 env 已覆盖强随机值，记为「已缓解」→ ⚠️；D10 为 scan 级（非 release 标记），D15/D16 渲染级 pass 记为 **deferred**（未启动浏览器）。）

---

## Trend vs previous audit（2026-08-05 → 2026-08-13）

| | This pass | Last pass | Delta |
|---|---|---|---|
| 🔴 | 10 | 13 | ▼3 |
| 🟡 | 16 | 50 | ▼34 |
| 🟢 | 32 | 15 | ▲17 |

**已修复（上轮 → 本轮）**：
- ✅ D9-1 WAL 裸 cp 备份 → 已改 sqlite .backup 在线备份（deploy/docker-deploy.sh:401-413）
- ✅ D13-1 PROJECT_DIR 硬编码 → 已改脚本自定位（deploy/docker-deploy.sh:9）
- ✅ D8-2 commit-msg「文档谎言」→ hook 已入库（.githooks/commit-msg，b9e980f）
- ✅ Dockerfile EOL 基础镜像 → node:22-alpine / python:3.12-slim-bookworm / nginx:1.29-alpine
- ✅ oauth-gateway root 容器 → 已加 USER oauthuser
- ✅ README PR 流程与 CLAUDE.md 单人维护冲突 → README:315 已改为直接提交 master

**上轮 🔴 仍开放**：D1-1/2/3 三个巨型文件（且全部继续增长）、D3-1 JWT 零直接测试、D3-2 零真 E2E、D6-1 零 runbook、D8-1 零 CI、D14-1 users.email 无唯一约束。D11-1/2/3（隐私/删除/sub-processor）本轮按 PIPL 口径从 🔴 下调为 🟡 —— 上轮未落地，功能缺口未变。

**本轮新增 🔴**：D4-1 已提交 API key（工作树 + 历史）、D13-1/2 JWT/OAUTH 密钥公开占位。

---

## D1 — Code essentiality

**Status**: ❌ · 三个 >1500 行 god-file 持续膨胀且无「为什么这么大」说明；双端零静态检查

### Findings

- 🔴 `backend/app/services/chat_service.py:1` — shrink: 2395 行（上轮 2289，8 天 +106 行），1 行 docstring 未说明规模成因；churn 热区，阅读与回归成本线性增长。
  _Why_: 位于 3 个月 churn 榜首区，每个新功能都在膨胀。
  _Fix_: 拆为 app/services/chat/{turns,messages,memories,side_effect_jobs}.py，router 层 re-export 保持稳定。
- 🔴 `backend/app/agents/chat/nodes.py:1` — shrink: 2028 行混装 13 个状态机节点 + prompt 构建器 + LLM 助手。
  _Fix_: prompt 构建器移入 prompts.py，LLM 重试助手移入 services/llm.py。
- 🔴 `frontend/src/components/business/ChatView.vue:1` — shrink: 1577 行 SFC（上轮 1539），无 header 说明。
  _Fix_: 流式/会话逻辑提取到 composables（已有 20 个 use* 先例）。
- 🟢 `backend/app/services/worker.py:1`（1685 行）+ `services/llm.py:1`（1554 行，无 docstring）— 本轮新超 1500 行；另有 14 个 >800 行文件。_Fix_: 补 docstring 说明规模成因与模块边界。
- 🟢 `backend/app/services/pipeline/batch_v2.py` — yagni: 364 行生产死模块（生产 import 0，仅测试经 inspect.getsource 引用）。_Fix_: 固化契约后删除。
- 🟢 `services/llm.py:890 + llm_judge.py + unmerged_quality.py + clustering/experiments/memory_labels.py` — shrink: LLM 容错 JSON 解析逻辑重复 ×4。_Fix_: llm_judge.parse_json_* 为唯一实现。
- 🟢 `pyproject.toml`（无 [tool.ruff]/[tool.mypy]）+ `frontend/tsconfig.json`（仅 baseUrl/paths、无 strict、无 eslint/biome）— 约 500 个源文件零静态检查。_Fix_: 加 ruff/mypy + eslint 或 biome 并接入 check.sh。

---

## D2 — Docs integrity

**Status**: ✅ · 架构路由表抽查准确、无断链、devplan 无 audit-theater；仅版本/计数陈旧

### Findings

- 🟢 `CLAUDE.md:7` — 声称 Python 3.10，实际 3.12（.python-version=3.12、pyproject >=3.11、README:130 >=3.12）。_Fix_: 改为 3.12。
- 🟢 `backend/CLAUDE.md` + 根 `CLAUDE.md` — include_router 计数 18 vs 实际 22；composables 19 vs 实际 20。_Fix_: 更新计数或改「约 N 个」。

（✅ 项：README+docs 全部相对链接无断链；docs/superpowers/plans 最近 3 个计划的对应功能均已在 git 中；deploy/docker-deploy.sh 19 个子命令全部真实存在。附：README.md:194 声称 JWT_SECRET「自动生成」与 .env.example:19 静态占位矛盾，随 D13 修复统一。）

---

## D3 — Tests as adversaries

**Status**: ❌ · 分层覆盖丰富（230 测试文件 + 32 个 Playwright spec、55 个跨用户对抗用例），但零真 E2E、门禁只跑子集

### Findings

- 🔴 `frontend/tests/e2e/*.spec.js + backend/scripts/verify_*_real_e2e.py + scripts/check.sh` — 无真实全栈 E2E：nginx→backend→LLM→SSE→前端渲染整链从未被自动验证（Playwright 全 mock API 为项目规则；verify_*_real_e2e.py 为手动脚本）。
  _Fix_: compose 增加 gated E2E job（frontend→test-runtime 真实后端→可选真实 LLM）接入门禁，或把 verify_*_real_e2e.py 编入可选发布门禁。
- 🟡 `scripts/check.sh:71,77-81 + frontend/package.json:10` — 日常门禁只跑子集：后端仅 3 个结构文件、前端仅 quality-gate.spec.js（全 API mock 成 401），完整对抗套件不在门禁。
  _Fix_: check.sh backend 段跑 pytest 全量（或至少 security+pipeline+chat 关键子集）。
- 🟡 `git log 96d25f2..ccd5e56` — regression-after-fix 70%（10 条 fix 仅 7 条带回归测试；答案编辑持久化域连续两个 bug 均无测试钉住）。
  _Fix_: 补回归测试并在 CLAUDE/test-files.md 固化 ≥80% 规则。
- 🟡 `backend/tests/infra/test_arq_integration.py + conftest.py mock_redis` — Redis/ARQ worker 关键路径纯 mock-only，无真实 Redis 集成测试。
  _Fix_: 加 RUN_REAL_REDIS=1 集成测试。
- 🟢 `backend/tests/security/*.py` — 无注入/Unicode/1MB/property-based 对抗语料。_Fix_: 补固定语料 + hypothesis。
- 🟢 `backend/tests/coding/test_coding.py` — 21 用例单文件偏薄，auth_client fixture 三处重复定义。_Fix_: 补越权/超长/恶意输入用例，fixture 收敛 conftest。

（✅ 项：test_db 真实执行 run_migrations 建全 schema；LLM 负向契约有 httpx.MockTransport + opt-in live_llm 兜底；test_authz_unification.py 55 用例可作样板。）

---

## D4 — Security posture

**Status**: ❌ · 认证姿势优秀，但出现已提交 API key 泄露；弃维护密码/token 库未迁移

### Findings

- 🔴 `backend/app/services/clustering/experiments/{reranker_cross_encoder_eval.py:24, vector_rerank_eval.py:25, embedding_recompute_eval.py:24, draw_questions_eval.py:26}` — SiliconFlow API key（sk-…）硬编码在 4 个实验脚本（当前工作树仍在），且进入 git 历史（78c77d0/e6f4f0d/95fcf63，2026-08-06）；该 key 曾用于生产 embedding 切换，可能仍有效；仓库同时推送 gitee+github 远端。
  _Why_: 密钥泄露 = 用你的账号烧别人 LLM 预算 / 数据被读；工作树中现存的 key 比历史更危险（任何拿到仓库副本的人直接可用）。
  _Fix_: 立即在 SiliconFlow 控制台轮换该 key；删除 4 处字面量改读 env；用 git filter-repo 清洗历史（或确认远端私有后仅轮换 + 删字面量）。
  _Threat_: threat-models/secret-management.md
- 🟡 `backend/.env` — 生产 ADMIN_PASSWORD 仅 8 字符（实测长度）。_Fix_: 改 ≥16 字符随机密码并轮换；auth.py 对 ADMIN_PASSWORD 加长度校验。
- 🟡 `pyproject.toml:17` — python-jose 自 2021 停更，传递依赖 python-ecdsa 有 CVE-2024-23342（上轮 🟡 未修）。_Fix_: 迁移 PyJWT。
- 🟡 `pyproject.toml:15-16` — passlib 1.7.4（2020 停更）迫使 bcrypt<4.1 冻结（上轮 🟡 未修）。_Fix_: 迁移 argon2 或 bcrypt 直连。
- 🟡 `backend/app/services/email_service.py:195-230` — 6 位数字验证码仅 IP 级限流，无 per-email 失败锁定，可分布式爆破 OTP 接管邮箱（上轮 🟡 未修）。_Fix_: per-email 失败计数 + 5 次作废 + 8 位码。
- 🟡 `backend/app/db/operations.py + routers/profile_pkg/llm.py:114` — 用户自带 LLM/搜索 API key 明文落库（上轮 🟡 未修）；oauth-gateway 仍以 :ro 挂生产 data 卷。_Fix_: Fernet 加密 api_key，读取解密。
- 🟢 `backend/app/db/queries.py:89` — user_id f-string 直插 SQL（值来自 JWT，非注入点，无 int 强转）。_Fix_: 参数化或 int() 前置。

（✅ 项（已验证，非 finding）：JWT HS256+issuer+jti、refresh 服务端轮转+每用户 10 条 eviction、bcrypt+锁定+slowapi 限流+CSRF 自定义头中间件、CORS 默认同源、安全头+CSP+HSTS、MCP bearer 认证+principal 覆盖防 confused-deputy、请求日志无 body、无 SQLi（f-string 仅限 PRAGMA/ALTER 且列名受控）、Dockerfile 全非 root、无请求体 PII 落日志。）

---

## D5 — Multi-tenant isolation

**Status**: ⚠️ · 应用层隔离在抽样路径全部正确，唯一缺口是 LLM 成本配额

### Findings

- 🟡 `backend/app/routers/{answers,chat,practice,coding}.py` — LLM 消耗型端点无按用户配额/门禁：开放注册 + 全局 OPENAI_API_KEY fallback 下可无限烧运营方 LLM 预算（上轮 🟡 未修）。
  _Fix_: LLM 调用前置 per-user 每日 token/次数配额，或移除未配置用户的全局 key fallback。

（✅ 项：全部路由 Depends(get_current_user)；owner_id/用户过滤全部参数化占位符；chat 会话归属校验（ConversationNotFound「不属于调用者」）；MCP principal 覆盖客户端参数；interview_merge_service 仅合并公共 owner_id IS NULL 数据。）

---

## D6 — Operational readiness

**Status**: ⚠️ · 运行时卫生优秀（JSON 日志+request_id、资源限制全覆盖、WAL 安全备份），事故就绪度缺口仍在

### Findings

- 🟡 `docker-compose.yml worker 段 + deploy/docker-deploy.sh do_worker_up` — ARQ worker 无 healthcheck：死亡/未连上 Redis 时静默停摆（承载全部 cron 与 durable job），--wait 视为就绪。
  _Fix_: worker 加 healthcheck 探针；do_status 显示最后活动时间。
- 🟡 `deploy/docker-deploy.sh do_backup` — 无 restore 命令/恢复演练/恢复文档，RPO/RTO 未定义（备份方式本身已 WAL 安全）。
  _Fix_: do_restore 子命令 + 一页恢复 runbook + 季度演练。
- 🟢 `docker-compose.yml` — nginx/oauth-gateway 无 healthcheck。_Fix_: 加 curl 探活 / /healthz。
- 🟢 `docs/` — 无 runbook（DB 宕/上游 5xx/限流/磁盘满/OOM 仅磁盘诊断有覆盖）。_Fix_: docs/runbook/ 五场景。
- 🟢 `backend/app/worker.py WorkerSettings.cron_jobs + do_status` — 6 个 ARQ cron 无 LastRunAt/失败可见性。_Fix_: 落库 last_run_at + 只读端点。

---

## D7 — Dependency hygiene

**Status**: ✅ · 锁文件双全、无 GPL/AGPL、Python 依赖锁定很新；残留前端构建链与 uvicorn 陈旧

### Findings

- 🟢 `frontend/package.json:25` — Vite 4.5.14（最新 8.2.1，落后 4 个大版本，EOL 于 2024-12）。_Fix_: 升 ^7/^8 并同步 plugin-vue。
- 🟢 `pyproject.toml` — uvicorn 硬钉 0.24.0（2023-10，最新 0.52.2）。_Fix_: 放开 >=0.30 并升级重测。
- 🟢 无 Dependabot/Renovate 接线。_Fix_: .github/dependabot.yml（python-uv + npm）。
- 🟢 `frontend/package.json:6-7,33` — 3 个未用依赖（puppeteer-core、@hugeicons/core-free-icons、@hugeicons/vue）。_Fix_: npm rm。

---

## D8 — Build / CI / dev-loop

**Status**: ❌ · 零 CI（上轮 🔴 未落地）、门禁无 secret/SAST 扫描（本轮 API key 泄露正因此未被拦截）；构建可复现性与单一入口 ✅

### Findings

- 🔴 仓库根 — 完全无 CI（无 .github/workflows/.gitlab-ci.yml/.circleci），所有门禁靠人工跑 check.sh。
  _Fix_: GH Actions 接入 scripts/check.sh 全量门禁，每 push 触发并阻断。
- 🔴 `scripts/check.sh + deploy/docker-deploy.sh + .githooks/` — 门禁缺 secret 扫描与容器/SAST 扫描：唯一安全项是 npm audit(--omit=dev) 与 pip-audit 且均非阻断（WARN 不拦截）。
  _Why_: 本轮实测的 API key 提交若 CI 有 gitleaks 会在 push 时当场拦截。
  _Fix_: check.sh 增加 gitleaks（阻断）+ trivy + semgrep。
- 🟢 `.githooks/commit-msg` — 已入库但依赖本机 core.hooksPath，fresh clone 无 hook（无安装脚本、无 pre-commit）。_Fix_: .githooks/install.sh。
- 🟢 `frontend/package.json:10` — npm run test 只跑 1 个 smoke spec。_Fix_: 改跑全量 smoke。

（✅ 项：Dockerfile 多阶段 + uv export --frozen + npm ci + apt --no-install-recommends 可复现；.dockerignore 完整；deploy/docker-deploy.sh 为唯一 dev 入口。）

---

## D9 — Data model integrity

**Status**: ⚠️ · 78 个幂等事务迁移无 DROP 用户表、审计表只增改、FK 全开；新发现 test 容器可触及生产库

### Findings

- 🟡 `docker-compose.yml test 服务 volumes ./backend/data（rw）+ backend/app/core/config.py:9-13` — test 容器读写挂载生产 data 卷，DB_PATH 指向真库；conftest.py:183-186 仅靠 _local.conn 拦截且注释自述「会走到真实 DB_PATH 连接生产库」。
  _Why_: 任何未走 fixture 的测试路径（如 TestClient 线程）可读写/迁移生产 interview-boss.db；pytest 是项目文档规定的日常操作。
  _Fix_: test 服务改挂独立测试数据卷或 TEST_DB_PATH 环境覆盖；保留 conftest 兜底断言。
- 🟢 `backend/app/db/connection.py:41-48` — init_db() 迁移连接未开 PRAGMA foreign_keys（运行时连接已开）。_Fix_: 迁移连接同样开启。
- 🟢 `backend/app/db/migrations/{practice_defaults.py:8, auth.py:175-176, data_repair.py:355}` — 迁移含受控 DELETE/DROP ×3（系统题单种子/遗留表），020 已注释禁用。_Fix_: 加注释留痕 + 回填匹配率确认。
- 🟢 `backend/data/ + backups/` — 备份与生产库同盘/同卷（SPOF），backups/ 残留 7 月裸 cp 的 -wal/-shm 文件。_Fix_: 备份移出 data 卷 + 清理残留。

（✅ 项：admin_assistant_log 无 DELETE/UPDATE 路径；FK 声明完整、ON DELETE 策略合理；merge_history 只增改；迁移自动按序执行、独立事务。）

---

## D10 — Performance & cost（scan 级）

**Status**: ✅ · N+1 干净、索引充分（104 个 CREATE INDEX）；成本与延迟基线缺失

### Findings

- 🟢 `backend/app/services/llm.py:758-762` — LLM 成本追踪缺失（无 usage 落库/成本模型）；LLM 为主要可变成本。_Fix_: llm_usage 表 + cost-per-user 模型。
- 🟢 `docs/` — 无延迟基线/benchmark（2c4g 单机 + 已运营站点）。_Fix_: 补一次 p50/p95 基线。

---

## D11 — Legal / compliance（PIPL 口径）

**Status**: ⚠️ · 上轮三项 🔴（隐私政策/账号删除/sub-processor）均未落地，本轮按 PIPL 口径（无 EU/付费用户证据）下调为 🟡；功能缺口未变

### Findings

- 🟡 全仓 — 无隐私政策/用户协议，注册无知情同意勾选（PIPL 第 13/17 条）。_Fix_: 隐私政策 + 用户协议页 + 注册必选勾选。
- 🟡 `backend/app/routers/auth.py:435` — 注销仅清登录态，无账号删除/匿名化路径（PIPL 第 47 条删除权）。_Fix_: delete-account 接口 + 设置页二次确认 + 审计脱敏。
- 🟡 `docs/` — 无 sub-processor 清单与数据流向文档（LLM/SiliconFlow/Deepgram/邮箱/search provider）。_Fix_: docs/privacy/data-flow.md。

（注：若后续出现 EU 用户或付费用户，应立即升回 🔴 并优先落地「隐私+删除+导出+sub-processor」四件套。）

---

## D12 — Admin surface consistency

**Status**: ✅ · admin 四路由权限门禁一致、Settings* 三态齐全、写操作确认门 + reviewed_by 留痕健全

### Findings

- 🟢 `backend/app/routers/profile_pkg/llm.py:63-69` — 全局模型连通性探测为同步请求最长 120s（async 不阻塞事件循环，但管理面按钮无进度）。_Fix_: 可选改后台 job + 轮询/SSE。

（✅ 项：compact/建库/批量答案/重算均 SSE 或后台 job；错误均 toast 上抛非吞掉；confirm_and_execute 为唯一写执行点，强制批量置信度地板 0.85。）

---

## D13 — Setup replicability

**Status**: ⚠️ · 两个集群内部密钥以公开占位 ship 进示例与 compose（生产已覆盖强随机值，风险在新建部署）；HF 缓存路径硬编码

### Findings

- 🔴 `backend/.env.example:19 + core/auth.py:15-21` — JWT_SECRET 以公开静态占位（40 字节）ship 进 .env.example，且通过 auth.py 的 len<32 拒绝检查；照抄示例的部署共享同一已知签名密钥，可跨实例伪造 token（当前生产 .env 已用 130 字符随机值）。
  _Fix_: .env.example 注释掉 JWT_SECRET 行并说明由 auth.py 自动生成写回；README 点明勿填固定占位。
  _Threat_: threat-models/secret-management.md
- 🔴 `docker-compose.yml oauth-gateway 段 \${OAUTH_SECRET_KEY:-change-me-in-production}` — OAuth HS256 签名密钥带公开兜底值且不在 .env.example 中；oauth-gateway/auth.py:20 的自动生成逻辑因 env 恒非空永不触发，未设该变量的部署 OAuth 令牌可被伪造（当前生产已覆盖 64 字符随机值）。
  _Fix_: 去掉兜底改必填校验或启动时自动生成；补入 .env.example。
  _Threat_: threat-models/secret-management.md
- 🟡 `docker-compose.yml backend 段` — 硬编码 /home/ubuntu/.cache/huggingface bind mount，新机器首次启动挂空 root 目录致 embedding 静默失效（HF_HUB_OFFLINE=1）。_Fix_: HF_CACHE_DIR 参数化。
- 🟢 `docker-compose.yml oauth-gateway 段 GATEWAY_BASE_URL=${GATEWAY_BASE_URL:-https://81.71.140.248}` — 兜底硬编码生产公网 IP：新部署 OAuth discovery/回调默认指向生产站。_Fix_: 去掉 IP 兜底改必填校验或默认 localhost。

（✅ 项：PROJECT_DIR 自定位已修；all/update 幂等（不重新生成密钥、不重启健康容器）；set -euo pipefail + 变量引号 + rm -rf 守卫全部到位。）

---

## D14 — Correctness & robustness

**Status**: ❌ · 核心写路径（turn 幂等、复习 upsert、job 原子 claim、通用更新白名单）逐一验证安全；上轮 🔴（email 唯一约束）未修

### Findings

- 🔴 `backend/app/db/migrations/auth.py:86-87 + routers/auth.py:668` — users.email 无 UNIQUE 约束：_check_email_exists 后 INSERT 的 TOCTOU 在 uvicorn --workers 2 下可产生重复邮箱账号（上轮 🔴 未修）。
  _Fix_: users.email 加 UNIQUE index（SQLite 允许多 NULL），_insert_user 捕获 IntegrityError 返回 409。
- 🟢 `backend/app/services/email_service.py:215-230` — 验证码双用竞态：SELECT→比对→UPDATE 无 used=0 门控，并发验证两次都返回 True。_Fix_: UPDATE ... WHERE used=0 并检查 rowcount。
- 🟢 `backend/app/services/fts_service.py:70-110` — FTS IDF 模块缓存永不失效（sync/delete 不重置），RRF 权重永久陈旧（上轮 🟡 未修）。_Fix_: sync/delete 时重置 _idf_cache。
- 🟢 `services/email_service.py:81/159/216 + core/auth.py:84/106/127 + practice_review_service.py:16 + insights.py:479 + analytics.py:189` — 时间处理混用 ×6（验证码本地 naive / JWT UTC aware / 「今天」分桶不一致；容器默认 UTC 掩盖问题）。_Fix_: 统一 tz-aware UTC。
- 🟢 `services/source_health.py:55-96 + db/queries.py:134-148` — 裸 except Exception: pass 吞错 ×7（健康诊断静默返回 0；岗位过滤子查询失败静默丢 JOIN 且无日志——不涉 owner 过滤）。_Fix_: logger.warning + 仅限缺列场景兜底。
- 🟢 `backend/app/routers/practice.py evaluate_answer` — 历史落库失败吞成 warning，自评照常但记录可能整块丢失。_Fix_: 收窄 catch + logger.exception + 重试一次。

（✅ 项（已逐一验证）：reserve_chat_turn BEGIN IMMEDIATE + client_request_id 幂等 + fingerprint；record_review ON CONFLICT DO UPDATE + before_state_json；claim_job fenced 原子 claim + idempotency_key；update_generic_data 表/列双白名单 + owner 校验；LLM _extract_json 多级容错。）

---

## D15 — UX & interaction

**Status**: ✅（源码级）· 主流程闭环 + 异步四态覆盖 + 破坏性确认 + 防双提交齐全；rendered pass deferred

### Findings

- 🟢 `frontend/src/views/PracticeDecksView.vue:51` — 自定义题单删除用原生 window.confirm 与应用统一 ConfirmDialog 割裂。_Fix_: 改用 useConfirm()。
- 🟢 `frontend/src` — 少量可交互 icon-only 控件缺 aria-label（如侧栏折叠，WCAG 4.1.2）。_Fix_: 补 aria-label / sr-only。

---

## D16 — UI & design-system craft

**Status**: ✅（源码级）· token 体系健全（variables.css 0 raw hex + tailwind darkMode class + shadcn）；残余硬编码集中在 porcelain 图表；rendered pass deferred

### Findings

- 🟢 `frontend/src/components/business/PracticeStarChart.vue:50-58`（+Heatmap/QuadChart/TrendChart/DifficultyChart）— 图表色板硬编码 hex 多组件重复（#EDEFF1/#081F5C/#334EAC 等约 6 图表）。_Fix_: 抽为 chart-* token。

（✅ 项：LoginModal 等业务组件本轮未发现新增的 shadcn bypass 回归；全局 0 raw hex 于 variables.css。）

---

## Triage — proposed follow-up milestones

| Finding | Suggested milestone | Effort |
|---|---|---|
| 🔴 D4-1 — SiliconFlow API key 泄漏（工作树+历史） | **SEC-3**: 轮换 key + 删字面量 + filter-repo 清洗 | 2-4 h |
| 🔴 D13-1/2 — JWT_SECRET/OAUTH_SECRET_KEY 公开占位 | **OPS-3**: 示例/compose 去占位 + 自动生成说明 | 1 h |
| 🔴 D8-1 — 零 CI | **CI-2**: GH Actions 接入 check.sh（含 gitleaks 阻断，防同类泄露） | 半天 |
| 🔴 D8-2 — 门禁无 secret/SAST 扫描 | **CI-3**: check.sh 加 gitleaks（阻断）+ trivy + semgrep | 2-4 h |
| 🔴 D3-2 — 零真 E2E | **TEST-3**: gated E2E job（真实后端+可选真 LLM） | 半天 |
| 🔴 D3-1 — JWT 零直接测试 | **TEST-4**: test_auth_core.py（过期/错签/轮转/锁） | 半天 |
| 🔴 D14-1 — users.email 无唯一约束 | **AUTH-3**: UNIQUE index + IntegrityError 409 | 30 min |
| 🔴 D1-1/2/3 — 三个巨型文件 | **REFACTOR-2**: chat_service 拆分 → nodes → ChatView | 各 1-2 天 |
| 🟡 D9-1 — test 容器读写生产 data 卷 | **OPS-4**: test 服务独立数据卷 / TEST_DB_PATH | 30 min |
| 🟡 D6-1/2 — worker healthcheck + restore 演练 | **OPS-5**: worker 探针 + do_restore + runbook | 半天 |
| 🟡 D11-1/2/3 — 隐私/删除/sub-processor（PIPL） | **COMP-2**: 合规三件套（出现付费/EU 用户时升 🔴 优先） | 1-2 天 |
| 🟡 D5-1 — LLM 无 per-user 配额 | **PERF-2**: per-user 每日配额 | 半天 |
| 🟡 D4-2..6 — ADMIN 弱口令/jose/passlib/OTP 锁定/key 加密 | **SEC-4**: 认证与密钥库硬化批次 | 1 天 |
| 🟢 D7-1/2 — Vite/uvicorn 升级 | **DEPS-1**: 升级 + 重跑测试 | 半天 |
| 🟢 D1-4..7 — 静态检查接线 + 死模块清理 | **REFACTOR-3**: ruff/mypy/eslint 入 check.sh + batch_v2 删除 | 半天 |

---

## Appendix — 🟢 findings（完整清单见 findings.tsv）

- D1: worker.py/llm.py 新超 1500 行；batch_v2.py 死模块；JSON 解析 ×4 重复；零静态检查
- D2: Python 版本漂移；include_router/composables 计数过时
- D3: fuzz corpus 缺失；coding 测试单薄
- D4: queries.py:89 user_id f-string 直插
- D6: nginx/oauth-gateway 无 healthcheck；无 runbook；cron 无可见性
- D7: Vite 4 EOL；uvicorn 0.24 硬钉；无自动更新；3 个未用依赖
- D8: commit-msg 无安装脚本；npm test 只跑 1 个 spec
- D9: 迁移连接未开 FK；迁移含受控 DELETE ×3；备份同盘 SPOF
- D10: LLM 成本追踪缺失；无延迟基线
- D12: test-global 探测 120s 无进度
- D13: HF 缓存路径硬编码；GATEWAY_BASE_URL 兜底硬编码生产 IP
- D14: OTP 双用竞态；FTS IDF 缓存；时间混用 ×6；裸 except ×7；evaluate_answer 吞错
- D15: window.confirm 割裂；icon-only 缺 aria-label
- D16: porcelain 图表 hex 硬编码
