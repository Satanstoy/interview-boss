# Tech audit — 2026-08-05

**Auditor**: tech-audit skill, under 用户's direction
**Scope**: full (all 16 dimensions)
**Repo HEAD at audit time**: b282e2cb9d11854e78520c683fa82392e58aaa4c
**Findings source**: `.tech-audit/work/2026-08-05/findings.tsv` — 所有 🔴 均通过 refutation pass
**Previous audit**: 无（首次审计）
**Stack**: Python/FastAPI + LangGraph · TypeScript/Vue3/Vite · SQLite WAL + FAISS · Docker Compose + ARQ worker · Bash (deploy/)

---

## Executive summary

- 🔴 **Top risk**: 合规裸奔 — 产品已上线且收集简历/音频/LLM 提示词等个人信息，但无隐私政策、无账号注销、无数据导出、无 sub-processor 文档（PIPL 语境下四项硬性义务全缺）。
- 🟢 **Top strength**: 核心工程健壮性出色 — chat 链路（BEGIN IMMEDIATE 回合占用、client_request_id 幂等、side-effect job 持久化重试、SSE finally 清理）、认证（JWT 轮转 + bcrypt 锁定 + CSRF）、授权隔离（55 个跨用户 404 对抗用例）、日志（JSON + request_id）均为教科书级。
- 🟡 **Biggest gap**: 工程化基础设施缺失 — 零 CI、零 lint/type-check 强制、备份方式在 WAL 模式下裸 cp（数据丢失向量）、D1 三个 >1500 行巨型文件持续膨胀。

---

## Status overview

| Dim | Title | Status | 🔴 | 🟡 | 🟢 |
|---|---|---|---|---|---|
| D1 | Code essentiality | ⚠️ | 3 | 4 | 0 |
| D2 | Docs integrity | ⚠️ | 0 | 5 | 2 |
| D3 | Tests as adversaries | ⚠️ | 2 | 2 | 2 |
| D4 | Security posture | ⚠️ | 0 | 4 | 1 |
| D5 | Multi-tenant isolation | ✅ | 0 | 1 | 1 |
| D6 | Operational readiness | ⚠️ | 1 | 2 | 1 |
| D7 | Dependency hygiene | ⚠️ | 0 | 6 | 1 |
| D8 | Build / CI / dev-loop | ❌ | 1 | 2 | 1 |
| D9 | Data model integrity | ⚠️ | 1 | 1 | 1 |
| D10 | Performance & cost | ⚠️ | 0 | 3 | 1 |
| D11 | Legal / compliance | ❌ | 3 | 1 | 0 |
| D12 | Admin surface consistency | ✅ | 0 | 1 | 2 |
| D13 | Setup replicability | ⚠️ | 1 | 7 | 0 |
| D14 | Correctness & robustness | ⚠️ | 1 | 4 | 0 |
| D15 | UX & interaction | ⚠️ | 0 | 3 | 1 |
| D16 | UI & design-system craft | ⚠️ | 0 | 4 | 1 |
| **Total** | | | **13** | **50** | **15** |

---

## D1 — Code essentiality

**Status**: ⚠️ · 三个巨型文件为真实复杂度，需拆分；双端均无 lint 强制

### Findings

- 🔴 `backend/app/services/chat_service.py:1` — shrink: 2289 行模块承载 5 个职责（回合生命周期/消息/记忆/side-effect jobs/会话 CRUD），`finalize_chat_turn` 单函数 181 行。
  _Why_: 位于 3 个月 churn 热区，每个新功能都在膨胀，阅读与回归成本随行数线性增长。
  _Fix_: 拆为 `app/services/chat/{turns,messages,memories,side_effect_jobs}.py`，router 层 re-export 保持稳定。
- 🔴 `backend/app/agents/chat/nodes.py:1` — shrink: 2028 行混装 13 个状态机节点 + prompt 构建器 + LLM 助手，`generate_response` 308 行。
  _Fix_: prompt 构建器移入现有 `prompts.py`，LLM 重试助手移入 `services/llm.py`。
- 🔴 `frontend/src/components/business/ChatView.vue:1` — shrink: 1539 行 SFC，script 1050 行 72 个函数（send/cancel/regenerate/SSE 重放状态），无 docstring。
  _Fix_: 流式/会话逻辑提取到 composables（已有 19 个 use* 先例）。
- 🟡 `frontend/src/components/business/LoginModal.vue:1` — 1142 行承载 5 种认证模式。_Fix_: 按模式拆子组件。
- 🟡 `pyproject.toml:57` — 无 `[tool.ruff]`/`[tool.mypy]`，check.sh/Dockerfile/CI 零 lint 步骤，F401/F841 死代码检查从未运行。_Fix_: 加 ruff 并接入 check.sh 作为 blocking 步骤。
- 🟡 `frontend/package.json:6 + tsconfig.json:1` — 无 eslint/biome 配置、无 lint script；tsconfig 无 `strict`。_Fix_: 加 eslint flat config + 开 strict。
- 🟡 `backend/app/agents/chat/react_loop.py:596` — shrink: `_react_loop` 576 行混合循环控制/预算/stop 策略/收尾契约/最终答案流式。_Fix_: 抽出收尾分支与流式 helper。

---

## D2 — Docs integrity

**Status**: ⚠️ · 架构路由表准确，但 churn 热区文档漂移 + README 与 CLAUDE.md 互斥

### Findings

- 🟡 `CLAUDE.md:7,73 + README.md:180,205,224` — 根文档仍称 chat 是 LangGraph 状态机，实际 `backend/app/agents/chat/CLAUDE.md` 已明确"纯 async harness（替代 LangGraph StateGraph）"。
- 🟡 `README.md:373-406` — README 的"分支规则/PR 流程"（dev→feature/*→PR→main）与 CLAUDE.md:52（单人维护直接 master 提交）正面冲突。
- 🟡 `README.md:3,229` — logo.png 缺失（图片破损）；结构图写 `backend/worker.py`，实际入口是 `backend/app/worker.py`。
- 🟡 `README.md:250 + CLAUDE.md:79` — docs/ 目录清单两侧都不完整且互不相同。
- 🟡 `backend/.env.example:12 vs README.md:356` — ADMIN_USERNAME 三处不一（README 表 sj、.env.example admin、代码默认 sj）。
- 🟢 `deploy/docker-deploy.sh:499-524` — 19 个子命令全部真实存在，`set -euo pipefail` + status/diagnose 自检。
- 🟢 `CLAUDE.md:120-149` — 代码路由表抽查 24 个模块文件全部存在，无 broken 引用。

---

## D3 — Tests as adversaries

**Status**: ⚠️ · 授权测试是标杆，但认证核心零直接测试 + 零真 E2E

### Findings

- 🔴 `backend/app/core/auth.py:162 (decode_token)` — JWT 核心零直接测试：无过期 token、无错误签名、无 refresh 轮转/JTI family 失效测试；登录锁无测试；API 测试全部用 `create_access_token` 现造 token，真实 `/api/auth/login` 从未被 HTTP 层执行。
  _Why_: 认证是最薄弱环节却完全没被测试"钉住"，任何 JWT 回归都会静默通过 CI。
  _Fix_: 新增 test_auth_core.py（过期/错签→401、refresh 轮转+family 失效、错误密码→锁、verify_password 往返），用 client fixture 走真实登录。
- 🔴 `frontend/tests/e2e/comprehensive.spec.js:4 + backend/tests/conftest.py:36-50` — 零真 E2E：前端 Playwright 全 mock API（项目规则），后端 test_pipeline_e2e 用真 SQLite 但 mock LLM；live_llm 真模型测试默认被剔除且不在 CI 跑。
  _Why_: 系统"分块被测试"，整体未验证——mock 契约漂移只有真模型才能暴露。
  _Fix_: CI 加 test-runtime 任务 `RUN_LIVE_LLM_TESTS=1` 跑 chat 全链路。
- 🟡 `backend/tests/` — 零 property-based 测试；无 null 字节/1MB+/unicode 边界语料；XSS 防御无跨端点注入。
- 🟡 `git log（近 60 提交）` — 30 个 fix 提交 0 个同 commit 带测试（in-commit 锁死比 0%），虽有 TDD test-first 前置提交覆盖约 9/12 近期修复，但未固化为规则。
- 🟢 mock_llm 关键路径有 live_llm 真实校验兜底（流式/工具调用/FAISS 真实现）。
- 🟢 `backend/tests/security/test_authz_unification.py` — 55 个跨用户隔离用例 + BUG006-009 权限升级回归，可作其他模块样板。

---

## D4 — Security posture

**Status**: ⚠️ · 认证姿势高于同类产品，缺口在 OTP 限流、密钥落库、弃维护库、root 容器

### Findings

- 🟡 `backend/app/services/email_service.py:195` — 6 位数字验证码无每邮箱尝试次数限制/锁定，仅 slowapi 按 IP 限流，5 分钟 TTL 窗口内可分布式爆破 OTP 接管账号。
  _Fix_: verify_code 加按 email+purpose 失败计数与锁退（5 次失败作废该 code），验证码改 8 位字母数字混合。
- 🟡 `backend/app/core/config.py:109 + routers/profile_pkg/llm.py:114` — 用户自带 LLM/搜索 API key 明文落库（无加密），且生产 DB 被 oauth-gateway 以 :ro 挂进 root 容器。
  _Fix_: Fernet 加密 api_key 字段（环境变量派生密钥），读取时解密；撤销 oauth-gateway 的 DB 挂载。
- 🟡 `backend/app/core/auth.py:7 (pyproject.toml:17)` — python-jose 自 2021 年无人维护，却是全部 token 签发/校验库。
  _Fix_: 迁移 PyJWT（单一签发/校验点），保持 algorithms=[HS256]/issuer/require_sub 参数。
- 🟡 `oauth-gateway/Dockerfile:11 + Dockerfile:145` — oauth-gateway 无 USER 指令以 root 运行且只读挂载生产 DB；nginx-runtime 无 USER（master 进程 root）。
  _Fix_: oauth-gateway 加非 root USER；nginx 显式 `user nginx;`。
- 🟢 `backend/app/mcp_server/app.py:123` — MCP 旧版认证接受 query 参数 + 非恒定时间比较（密钥可经代理日志泄露），但主通道是 header；工具侧 principal 覆盖客户端参数防 confused-deputy 正确。

---

## D5 — Multi-tenant isolation

**Status**: ✅ · 应用层过滤在抽样路径全部正确，未发现跨用户泄漏

### Findings

- 🟡 `backend/app/routers/chat.py:270 + routers/answers.py` — LLM 消耗型端点无按用户配额/速率门禁，仅全局 200/min 每 IP；开放注册 + 全局 OPENAI_API_KEY fallback 下可无限烧运营方 LLM 预算。
  _Fix_: LLM 调用前置 per-user 每日 token/次数配额，或移除未配置用户的全局 key fallback。
- 🟢 MCP `_init_tool_state_async` principal 覆盖客户端 user_id/bank_mode，匿名强制 None/public，外部工具无法越权访问他人题库（建议加回归测试固化）。

---

## D6 — Operational readiness

**Status**: ⚠️ · 运行时卫生优秀，事故就绪度薄弱（零 runbook、备份未验证）

### Findings

- 🔴 `docs/` — 零 runbook：DB down、LLM 上游 5xx、上游 rate-limit、磁盘满、容器 OOM 五大常见事故均无处置文档。
  _Fix_: 新建 `docs/operator/` runbook 覆盖 5 大事故（diagnose/status/logs 诊断命令、恢复步骤、预防阈值）。
- 🟡 `deploy/docker-deploy.sh:3,395` — 备份仅手动触发、无 restore 命令、无保留轮转、git 历史无恢复演练，RPO/RTO 未定义。
  _Fix_: 加 restore 子命令、backups/ 保留 14 份策略、执行一次真实恢复演练并记录。
- 🟡 `docker-compose.yml:133,159,90` — nginx/oauth-gateway/worker 无 healthcheck（worker 的 --wait 因无 healthcheck 实际不等待）。
  _Fix_: nginx curl 探活、oauth-gateway /healthz、worker arq 存活探测。
- 🟢 JSON 结构化日志 + contextvars request_id + X-Request-ID 响应头；sendBeacon 错误上报；全服务 mem_limit/cpus + 日志轮转 10m×3。

---

## D7 — Dependency hygiene

**Status**: ⚠️ · 锁文件双全、无 GPL/AGPL 风险，但 4 处真实腐化 + 零自动更新

### Findings

- 🟡 `pyproject.toml:14` — uvicorn pin `==0.24.0`（2024-02），最新 0.52.1，落后 2.5 年含安全修复。
- 🟡 `pyproject.toml:15-16` — passlib 1.7.4（2020 停更）迫使 bcrypt 冻结 <4.1，锁死依赖生态。
- 🟡 `pyproject.toml:17` — python-jose 弃维护（同 D4，见安全项）。
- 🟡 `frontend/package.json:52` — Vite 4.5.14 EOL（2024-12），最新 8.2.0 落后 4 个大版本；plugin-vue/tailwind/zod/vue-router 均落后 1+ 大版本。
- 🟡 `frontend/package.json:43` — vue-virtual-scroller 锁 2.0.0-beta.8（beta 进生产）。
- 🟡 仓库根 — 无 Renovate/Dependabot 接线（无 .github）。
- 🟢 锁文件已提交（uv.lock 含 sha256）；前端全 MIT，后端 pdfplumber/onnxruntime MIT、structlog Apache-2.0、faiss-cpu BSD-3。

---

## D8 — Build / CI / dev-loop

**Status**: ❌ · 零 CI、Git hook 是文档谎言、基础镜像 EOL

### Findings

- 🔴 仓库根 — 完全无 CI：无 .github/workflows、.gitlab-ci.yml、.circleci，git 历史无 CI 配置提交；所有门禁靠人工跑 docker-deploy.sh check。
  _Fix_: 建 GitHub Actions：push/PR 跑 pytest（test-runtime）+ 前端 build/smoke + audit 报告，最低限度把现有 check.sh 原样接入。
- 🟡 CLAUDE.md "Git hook 自动检查" — 文档谎言：.git/hooks 只有 *.sample，无 hooksPath、无 pre-commit/husky、无 commit-msg 检查脚本。
  _Fix_: 落地真实 commit-msg hook + 安装脚本，或删掉该声明。
- 🟡 `Dockerfile:15,30,145` — node:20-alpine EOL（2026-04）、python:3.10-slim-bookworm 距 EOL 仅 2 个月、nginx:1.27 落后 2 版；所有 FROM 无 digest pin。
  _Fix_: node:22-LTS、python:3.11/3.12-slim（同步 requires-python）、nginx:1.29；评估 digest 全 pin。
- 🟢 dev-loop 单一入口成立：check.sh 统一转发 + test profile Docker test-runtime。

---

## D9 — Data model integrity

**Status**: ⚠️ · FK 全开 + 审计表只增改，唯一真实数据丢失向量是 WAL 备份方式

### Findings

- 🔴 `deploy/docker-deploy.sh:401` — do_backup 对**运行中** WAL 模式 DB 裸 cp：checkpoint 前已提交事务只在 -wal 文件，cp 只拿到旧快照，写 checkpoint 期间拷贝可撕裂文件。
  _Fix_: 用 `sqlite3 "$DB" ".backup '$dest'"` 在线备份 API（或 wal_checkpoint(TRUNCATE) 后连 -wal/-shm 一起拷）。
- 🟡 `backend/app/db/migrations/data_repair.py:49 + practice_defaults.py:8 + auth.py:175` — 启动迁移无条件执行 DELETE/DROP TABLE，无生产环境 opt-in 门控。
  _Fix_: 破坏性迁移按 ENV==prod 显式 opt-in（或独立 backfill 命令），DELETE 前记录并断言受影响行数。
- 🟢 `connection.py:35` PRAGMA foreign_keys=ON 全连接开启；FK 声明完整且 ON DELETE 策略合理；merge_history 无 DELETE 路径，回滚写 is_rolled_back 审计标记。

---

## D10 — Performance & cost

**Status**: ⚠️ · 代码无 N+1，但可观测性债明显（无延迟基线、无成本模型、同步 LLM 调用）

### Findings

- 🟡 全仓 — 无任何 latency 基线/benchmark/load test；interviewboss.online 已在运营，p95 无测量记录。
- 🟡 `backend/app/services/chat_service.py:1160` — chat_messages 每行存 token_count 但无聚合查询；LLM 是主要可变成本（全局 key + 每用户 key）却无成本模型。
- 🟡 `backend/app/routers/answers.py:63,138` — 单题生成/背诵稿定制在 HTTP 请求线程内同步 await 完整 LLM 调用（LLM_TIMEOUT=120s + 3 重试），是 504/阻塞 worker 候选。
  _Fix_: 改 SSE 流式或入 ARQ worker（复用 submit.py:276 enqueue 模式）。
- 🟢 `question_bank_sources.py:424` — 题库列表无 N+1（批量整形 + FTS/向量混合检索已索引）。

---

## D11 — Legal / compliance

**Status**: ❌ · 最差维度，合规近乎裸奔（PIPL 四项硬性义务全缺）

### Findings

- 🔴 全仓 — 产品已上线并收集简历/音频转写/LLM 提示词等个人信息，但无任何隐私政策/用户协议页面（PIPL 第 13/17 条告知义务），也无 docs/privacy/。
  _Fix_: 新增 隐私政策 + 用户协议 页面（前端路由 + 注册处勾选），列明数据类别与用途。
- 🔴 `backend/app/routers/profile_pkg/` — 无任何账号删除/注销路径，用户数据永久留存（PIPL 第 47 条删除权）。
  _Fix_: 实现 delete-account endpoint（级联硬删或匿名化，审计日志保留但脱敏 PII），设置页入口 + 二次确认。
- 🔴 backend/ — 第三方处理者（OpenAI 兼容 LLM、Deepgram 音频、邮箱服务）无 sub-processor 清单与数据流向文档。
  _Fix_: 新增 `docs/privacy/data-flow.md`：数据类别 → 存储位置 → 第三方处理者清单。
- 🟡 backend/app/routers/ — 无用户数据导出/可携带性路径。
  _Fix_: 新增 /api/profile/export-data（JSON 打包下载）。

---

## D12 — Admin surface consistency

**Status**: ✅ · 空状态/401-403 拦截/SSE 路由规范，唯一系统性缺陷是 5 处静默吞错

### Findings

- 🟡 `frontend/src/components/business/SettingsAdmin.vue:34、ModelSelector.vue:168、SettingsInterview.vue:33,62、KnowledgeGraph.vue:64、NewChatModal.vue:193` — 5 处 catch 仅 console.error 静默吞错，用户零 UI 反馈（设置/模型加载失败表现为"空白"）。
  _Fix_: 统一 ChatView 的 toastError 模式（useToast 上浮 + 失败态）。
- 🟢 `http.js:478 + useAuth.js:72` — 401 自动 refresh 重试、失败弹登录框；403 映射"权限不足"文案。
- 🟢 题库/对话/练习空状态文案齐全，InsightsView 三态齐全。

---

## D13 — Setup replicability

**Status**: ⚠️ · 新鲜克隆 bootstrap 实质不可执行（本机仅靠符号链接幸存）

### Findings

- 🔴 `deploy/docker-deploy.sh:9` — PROJECT_DIR 硬编码 `/home/ubuntu/sj/interview-boss`，README 快速开始 `./deploy/docker-deploy.sh all` 在任意新克隆机器上 `set -euo pipefail` 直接退出。
  _Fix_: `PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"`。
- 🟡 `docker-compose.yml:42-43` — nginx/backend/test 三处 bind mount 硬编码 `/home/ubuntu/.cache/huggingface`，新鲜主机自动建空 root 目录，HF_HUB_OFFLINE=1 下 embedding 静默失效。
  _Fix_: `${HF_CACHE_DIR:-./.hf-cache}` 环境变量 + .env 声明。
- 🟡 `backend/.env.example:15` — JWT_SECRET 给了"操作员可填"占位符，与 core/auth.py:50 自动生成逻辑矛盾（集群内部密钥不应 operator-fillable）。
- 🟡 `README.md:461-462` — 给出裸 `docker compose build nginx` 命令绕过唯一部署入口与磁盘保护。
- 🟡 `README.md:272` — 快速开始 clone URL 是 gitee 占位符。
- 🟡 `README.md:309` — "浏览器打开 http://localhost" 与 compose 绑定的 `127.0.0.1:8081:80` 矛盾。
- 🟡 `README.md:317,673` — `docker compose exec backend uv run uvicorn --port 8000` 与容器内已运行 uvicorn 冲突，且 backend 未发布端口。
- 🟡 `docker-compose.yml:158-184` — 第 5 个服务 oauth-gateway 在 README/CLAUDE.md 完全无文档，硬编码 trycloudflare 临时隧道 URL + 默认 change-me-in-production 密钥。

---

## D14 — Correctness & robustness

**Status**: ⚠️ · 聊天核心链路教科书级健壮，缺陷集中在注册/验证码路径

### Findings

- 🔴 `backend/app/routers/auth.py:668 + migrations/auth.py:87` — check-then-act TOCTOU：`_check_email_exists` 后 INSERT，users.email 无 UNIQUE 约束，uvicorn `--workers 2` 下两个进程可同时通过检查产生重复邮箱账号。
  _Fix_: users.email 加 UNIQUE index（SQLite 允许多 NULL），或 _insert_user 捕获 IntegrityError 返回 409。
- 🟡 `backend/app/services/email_service.py:81` — 验证码 expires_at 用 naive server-local `datetime.now().isoformat()`，其余 DB 层存 UTC，时区语义混用。
- 🟡 `backend/app/services/email_service.py:112` — 验证码双用竞态：SELECT 未用 code → 比对 → UPDATE 标记，2 worker 下两次并发验证都返回 True（UPDATE 无门控）。
- 🟡 `backend/app/services/fts_service.py:73` — IDF 模块缓存永不失效（sync/delete 不重置），且全量扫描所有题入内存，RRF 权重永久陈旧。
- 🟡 `backend/app/agents/chat/nodes.py:1338` — 裸 `except:`（4 处）在元数据启发式中静默吞错，DB 失败降级为空串无任何 trace。

---

## D15 — UX & interaction

**Status**: ⚠️ · 核心流程四态齐全、路由完整，3 处可检测 a11y 缺失。rendered pass deferred（未启动浏览器渲染审查）

### Findings

- 🟡 `src/components/business/PracticePanel.vue:19` — icon-only 关闭按钮无 aria-label，屏幕阅读器/键盘用户获得无标签控件。
- 🟡 `src/components/business/SettingsAdmin.vue:185` — cat1/cat2 内联编辑 input 仅有 placeholder，无 label/aria-label（WCAG 1.3.1）。
- 🟡 `src/views/PracticeDecksView.vue:52` — 题单删除用原生 window.confirm，绕过项目共享 ConfirmDialog。
- 🟢 `SettingsAdmin.vue:47` — removeCat1/removeChild 直接 splice 删整个大类无逐项 confirm（仅靠保存兜底）。

---

## D16 — UI & design-system craft

**Status**: ⚠️ · token 体系完整但有两处系统性 bypass（LoginModal 绕过 shadcn、ECharts 硬编码 38 hex）

### Findings

- 🟡 `src/components/business/LoginModal.vue:82` — 四套表单 27 个裸 button/input 手写 class 重实现 shadcn 组件，零 ui/ import，违反 CLAUDE.md "一律使用 shadcn 组件"规则。
- 🟡 `src/components/business/PracticeTrendChart.vue:83` — ECharts 硬编码 hex 复制 token（#6366f1==--c-primary-500 等），.vue 内 38 个唯一 hex，dark 主题靠逐图表手动分支。
  _Fix_: getComputedStyle 读 CSS 变量喂 ECharts 或建共享 palette 模块。
- 🟡 `src/components/business/PracticePanel.vue:13` — 微字号蔓延：text-[10px]×42、text-[11px]×41、text-[9px]×3，全部低于 text-xs(12px) 基线。
- 🟡 `src/components/business/QuestionCard.vue:79` — 17 文件 ~78 处内联 svg，违反"图标统一 @lucide/vue，禁止内联 SVG"规则。
- 🟢 `LoginModal.vue:16` — transition-all 58 处（全库 290 处），hover 过渡全部属性有卡顿风险。

---

## Triage — proposed follow-up milestones

| Finding | Suggested milestone | Effort |
|---|---|---|
| 🔴 D11-1/2/3 — 隐私政策、账号注销、sub-processor 文档 | COMP-1: 合规三件套（隐私政策页 + delete-account API + data-flow.md） | 1-2 天 |
| 🔴 D9-1 — WAL 裸 cp 备份 | OPS-1: sqlite .backup 在线备份 + restore 子命令 + 一次演练 | 半天 |
| 🔴 D13-1 — PROJECT_DIR 硬编码 | OPS-2: 脚本自定位仓库根 | 10 min |
| 🔴 D8-1 — 零 CI | CI-1: GitHub Actions 接入现有 check.sh + live_llm 全链路 | 半天 |
| 🔴 D14-1 — users.email 无唯一约束 | AUTH-1: UNIQUE index + IntegrityError 409 | 30 min |
| 🔴 D3-1 — JWT 零直接测试 | TEST-1: test_auth_core.py（过期/错签/轮转/锁） | 半天 |
| 🔴 D3-2 — 零真 E2E | TEST-2: CI 内 RUN_LIVE_LLM_TESTS=1 chat 全链路 | 半天 |
| 🔴 D1-1/2/3 — 三个巨型文件 | REFACTOR-1: chat_service 拆分（最高收益）→ nodes → ChatView | 各 1-2 天 |
| 🔴 D6-1 — 零 runbook | OPS-3: docs/operator/ runbook 五场景 | 半天 |
| 🟡 D4-1 — OTP 无标识级限流 | AUTH-2: 验证码失败计数 + 8 位码 | 2 小时 |
| 🟡 D4-2 — 用户 API key 明文落库 | SEC-1: Fernet 加密 + 移除 oauth-gateway DB 挂载 | 半天 |
| 🟡 D4-3/D7-3 — python-jose | SEC-2: 迁移 PyJWT | 半天 |
| 🟡 D10-3 — answers.py 同步 LLM | PERF-1: 改 SSE 流式或入 worker | 1 天 |
| 🟡 D14-2/3 — 验证码时区/双用竞态 | AUTH-3: UTC 统一 + 原子 UPDATE 门控 | 2 小时 |
| 🟡 D16/D15 — LoginModal 迁移 shadcn + a11y | UI-1: 组件迁移 + aria-label 补全 | 1 天 |

---

## Appendix — 🟢 findings

- D3: live_llm 真实校验兜底；test_authz_unification 55 用例授权样板
- D4: MCP principal 覆盖客户端参数（建议加回归测试固化）
- D5: MCP 防 confused-deputy 措施正确
- D6: JSON 日志 + request_id + sendBeacon + 资源限制
- D7: 锁文件双全 + 无 GPL/AGPL
- D8: dev-loop 单一入口
- D9: FK 全开 + merge_history 只增改
- D10: 题库列表无 N+1
- D12: 401/403 统一拦截；空状态覆盖良好
- D15/D16: confirm 缺失提示、transition-all 收敛建议
