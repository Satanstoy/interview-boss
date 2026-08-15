# Tech audit — 2026-08-15 (round 3)

**Auditor**: tech-audit skill, under the user's direction
**Scope**: full (all dimensions, D10 skipped — not a release cut)
**Repo HEAD at audit time**: c50e463（工作树含未提交的 docs/adr/chat-agent-quality-protection.md 修改与未跟踪 experiment_reports/）
**Findings source**: .tech-audit/work/2026-08-15-r3/findings.tsv（54 条；2 条 🔴 均通过 refutation pass）
**Previous audit**: docs/analysis/tech-audit-2026-08-15.md（同日 round 2）+ 同日 deep-dive
**Companion**: docs/analysis/over-engineering-audit-2026-08-15-r3.md（D1 ≥5 findings 触发）

---

## Executive summary

- 🔴 **Top risk**: 生产 SiliconFlow API key 泄漏进 git 历史（8 个提交）且**从未轮换——backend/.env 里还是同一把活 key**（实测复核）；另有 2 个 🔴：管理员全量重建题库会把全部用户私有/pending 面经题目公开化（build_master_bank_task 无 owner 过滤，整链已读码核实）、CI 缺容器镜像扫描（D08 目录级 🔴）。生产库 178 行 FK 孤儿持续存在（round-2 已知）。
- 🟢 **Top strength**: round-2 的两个 🔴（check.sh 门禁失明、bank_build NameError）与 eslint TS parser、pip-audit 容器化等 7 项已在 HEAD 修复并复核；CI（gitleaks + 前端构建 + 后端结构门禁）首次存在；行数红线全绿；迁移体系（081-086 备份/FK 断言/双写一致性）设计扎实
- 🟡 **Biggest gap**: 生产环境与门禁脱节 —— worker 仍跑 08-14 旧镜像（retention cron 从未运行）、关键测试子集 123 failed + 14 errors 与 round-2 持平、CI 里静态检查 || true 永不阻断（ruff 179 / mypy 436 / eslint 63 存量）。修测试隔离（threading.local→contextvars）与部署对齐是本轮最高杠杆动作

---

## Status overview

| Dim | Title | Status | 🔴 | 🟡 | 🟢 |
|---|---|---|---|---|---|
| D1 | Code essentiality | ⚠️ | 0 | 2 | 3 |
| D2 | Docs integrity | ⚠️ | 0 | 0 | 2 |
| D3 | Tests as adversaries | ❌ | 0 | 4 | 4 |
| D4 | Security posture | ❌ | 1 | 2 | 1 |
| D5 | Multi-tenant isolation | ❌ | 1 | 0 | 0 |
| D6 | Operational readiness | ⚠️ | 0 | 1 | 5 |
| D7 | Dependency hygiene | ⚠️ | 0 | 3 | 3 |
| D8 | Build / CI / dev-loop | ❌ | 1 | 3 | 2 |
| D9 | Data model integrity | ⚠️ | 0 | 2 | 4 |
| D10 | Performance & cost | — | skipped (release-only) | | |
| D11 | Legal / compliance | ⚠️ | 0 | 0 | 2 |
| D12 | Admin surface | ⚠️ | 0 | 1 | 1 |
| D13 | Setup replicability | ⚠️ | 0 | 1 | 0 |
| D14 | Correctness & robustness | ⚠️ | 0 | 0 | 3 |
| D15 | UX & interaction | ⚠️ | 0 | 0 | 3 |
| D16 | UI & design-system craft | ⚠️ | 0 | 0 | 3 |
| **Total** | | | **3** | **17** | **38** |

整体健康：❌（存在未缓解的 🔴，其中一把活 key 泄漏为最高优先级）。D15/D16 的 rendered pass 在只读委派环境不可行，仅做 source-level。D10 未跑（无 release tag）。

---

## Trend vs previous audit

| | This pass | Last pass (round 2) | Delta |
|---|---|---|---|
| 🔴 | 3 | 2 | ▲1 |
| 🟡 | 15+ | 22 | ▼ |
| Avg dim status | ❌ | ❌ | → |

Closed since round 2（7 项，均经代码复核）:
- ✅ 🔴 D14 bank_build.py:277 — match_new_questions 已导入（bank_build.py:8），build-personal NameError 修复
- ✅ 🔴 D8 check.sh 未定义静态检查函数 — run_static_backend/run_static_frontend 已定义（check.sh:151,164）并调用（:178-179）
- ✅ 🟡 D8 eslint 无 TS parser — @typescript-eslint/parser 已接入（eslint.config.js:4,16-20）
- ✅ 🟡 D8 pip-audit 宿主机直跑 — 已改走 test-runtime 容器（check.sh:120-122）
- ✅ 🟡 D14 login _record_failure 竞态 — 已是原子 upsert（auth.py:83-97 复核）
- ✅ 🟡 D9 fts _idf_cache — delete 路径已重置（fts_service.py:388）
- ✅ 🟢 D2 asgi.py 计数 — 文档已改 23+1（backend/CLAUDE.md:65）
- 附：CI 首次存在（.github/workflows/ci.yml：gitleaks + 前端 build/test + 后端结构门禁 + lineguard + check_secrets）

Still open（代表性，均重新实测确认）:
- 🟡 D3 关键子集 pytest 123 failed + 14 errors（round-2 为 127+14，统计持平；真根因首次定位：threading.local 连接对 asyncio.to_thread 不可见）
- 🟡 D6 生产 worker 跑 08-14 旧镜像，retention cron 从未运行（实测容器内 0 命中 vs backend 3 命中）
- 🟡 D9 生产库 178 行 FK 孤儿（interview_asked_questions；schema_version max=89，无 090）
- 🟡 D4 npm 16 漏洞（9 high）+ pip-audit 14 条（uv.lock 复核 aiohttp 3.14.1 / cryptography 49.0.0 / ecdsa 0.19.2 / pyasn1 0.6.3 原样）；ADMIN_PASSWORD 仍 8 字符；refresh cookie 信任 XFP（宿主 nginx 覆写 XFP，生产拓扑下不可伪造，残余为 default 站点纯 HTTP 路径）
- 🟡 D7 uvicorn==0.24.0 硬钉 / python-jose、passlib 停更 / vite ^4.4.5 / 无 Dependabot
- 🟡 D6 备份同盘 SPOF（根分区 82%）、nginx/oauth-gateway 无 healthcheck、6 个 ARQ cron 无可见性
- 🟡 D9 chat.py:451 软删 JD 进 LLM 上下文；email_service naive 时间（retention 偏差 ~8h）
- 🟢 D1 batch_v2 死模块 / D14 react_loop 死代码 / D15 window.confirm×2 / D16 chartTokens 内联 hex（全部仍在）

New regressions / 新发现（本轮）:
- 🔴 D5 build_master_bank_task 无 owner 过滤 → 全量重建把全部用户私有/pending 面经公开化（整链读码核实）
- 🔴 D8 CI 存在后暴露：deploy 镜像无容器扫描（Trivy）阶段（按 D08 方法目录为 🔴）
- 🟡 D12 评测中心（新功能）async run 无已部署消费者：arq:eval 队列的 eval-worker 无任何 deploy 命令拉起，admin 建 run 永久 queued
- 🟡 D3 回归测试比例实测 ~21%（15 个 fix 提交仅 3 个带测试），低于仓库自定 ≥80% 红线
- 🟡 D13 README 环境变量表 7 个变量在 .env.example 无占位行
- 🟡 D9 FK 回归套件不覆盖 081→085 孤儿窗口（CI 全绿但生产库带病）
- 🟢 D11 eval_human_reviews RESTRICT 阻塞删号 / 无数据导出；D6 无 runbook、恢复无演练；D7 3 个未使用依赖、无 Node engines；D2 README 计数 20 vs 22、requires-python 漂移；D16 4 个死组件；D15 4 处原生 title；D1 5 个孤儿 Nav 组件 + 8 个评测 harness + yagni/shrink 各 1

---

## D1 — Code essentiality

**Status**: ⚠️ 无超红线文件（最大 ChatView.vue 1498 / worker.py 1388 / nodes.py 1343）；TODO=4；无孤儿迁移、无过度抽象；死代码集中于三簇 + 两个薄点。

### Findings

- 🟡 `backend/app/services/pipeline/batch_v2.py:40` — `delete:` 383 行死模块，仅为 inspect.getsource 回归夹具而存在（round-2 遗留）。_Fix_: 删除；三个回归测试改指 live compact.py 路径，删 verify_compaction_real.py:83 引用。(S, certain)
- 🟡 `frontend/src/components/NavMain.vue:1` — `delete:` 5 个孤儿 shadcn-vue 侧边栏模板组件（NavMain/NavUser/NavSecondary/NavDocuments/DragHandle，326 行，0 引用）。_Fix_: 删除 5 个文件。(S, certain)
- 🟢 `clustering/experiments/draw_questions_eval.py` — `delete:` 8 个独立评测 harness（~2275 行，无调用者）；保留 memory_labels/prompts/evaluate。_Fix_: 删除 8 文件。(S, certain)
- 🟢 `agents/chat/structured_turn.py:234` — `yagni:` validate_writer_output 全量测试但从未接入生产。_Fix_: 接入 contract writer 路径或删除+移除断言。(S, certain)
- 🟢 `agents/chat/structured_turn.py:150` — `shrink:` WriterBrief 同名双定义（turn_intent dataclass vs structured_turn BaseModel）+ TurnContract/V2 并行。_Fix_: 改名或内联。(S, probable)

→ 详见 companion: docs/analysis/over-engineering-audit-2026-08-15-r3.md

---

## D2 — Docs integrity

**Status**: ⚠️ 结构性文档与代码一致（asgi 计数已修、composables=22 根 CLAUDE 正确）；漂移集中在 README 细节。

### Findings

- 🟢 `README.md:280` — composables 计数 20 vs 实际 22（根 CLAUDE.md 已正确）。_Fix_: 更新为 22 或去掉精确计数。(S, certain)
- 🟢 `pyproject.toml:6` — requires-python >=3.11 与 Dockerfile/README/CLAUDE 的 3.12 不一致。_Fix_: 统一为 >=3.12 或修正文档。(S, certain)

---

## D3 — Tests as adversaries

**Status**: ❌ 2548 collect / 2315 passed，但关键子集 123 failed + 14 errors 与 round-2 持平；本轮定位到真根因（threading.local 对 to_thread 不可见），修复路径明确。

### Findings

- 🟡 `backend/tests/services/clustering/test_reupload_after_soft_delete.py:38` — autouse fixture 直连 get_db_connection() 落到 DB_PATH（空 test-data 卷）→ 14 errors（round-2 已知）。_Fix_: fixture 注入 test_db 内存连接 + conftest sentinel 禁止测试开 DB_PATH。(S, certain)
- 🟡 `backend/app/db/connection.py:19-37` — **threading.local 连接对 asyncio.to_thread 不可见**：chat 流水线经 to_thread 的 DB 访问落到真实 DB_PATH → ~80 个 chat 测试 no-such-table（round-2『chat 断言失败』的真根因，非断言漂移）。_Fix_: contextvars 传播连接（或 client fixture 在 sqlite3.connect 边界全局路由到 test_db）；补 to_thread 全链路内存库回归测试。(M, certain)
- 🟡 `backend/tests/infra/test_public_ip_exposure.py:10-11` — test 镜像缺 git、未挂 oauth-gateway 源码 → 4 failures。_Fix_: 镜像装 git + 挂载 oauth-gateway 或改写测试。(S, certain)
- 🟡 回归纪律 — 最近 15 个 fix 提交仅 3 个带回归测试（~21%），远低于仓库自定 ≥80% 红线。_Fix_: 门禁检查 fix 提交必须带测试变更（按豁免类别）。_Fix_: (M, certain)
- 🟢 `backend/tests/coding/test_coding.py` — 缺跨用户越权/50000 字符边界/恶意 markdown 用例（round-2 已知）。_Fix_: 补用例；auth_client 收敛进共享 conftest。(S, probable)
- 🟢 `backend/tests/security/` — 无对抗 fuzz corpus（SQL/XSS 语料、Unicode/1MB 边界、hypothesis 皆无）。_Fix_: 注入语料 fixture + 属性测试。(M, probable)
- 🟢 `scripts/line_guard.sh:48,53` — 不覆盖 backend/tests（test_react_loop.py 3728L / test_chat.py 2038L）。_Fix_: 纳入扫描（可放宽上限）并拆分超大测试文件。(S, certain)
- 🟢 `frontend/tests/e2e/*.spec.js` — Playwright E2E 全 page.route mock，无一条真栈链路。_Fix_: 补 1 条对 docker-compose 真栈的 E2E（LLM 在服务边界 mock）。(M, probable)

---

## D4 — Security posture

**Status**: ❌ 本轮新增 🔴（活 key 泄漏）。防御面整体扎实：admin_assistant 写工具确认门、ToolPolicy 不可变、MCP 账户级 HMAC token 哈希落库、SQL 注入由表/列白名单+参数化拦截、非 root 容器、限速与上传尺寸守卫均在。pip-audit 复测结论以 uv.lock 版本为准：14 条 PYSEC 仍 open（D4 agent 的『No known vulnerabilities』为超时重试导致的假阴性，已用锁文件版本复核排除）。

### Findings

- 🔴 `backend/.env:22` — 生产 SiliconFlow API key（sk-hkaopkq...clym）仍在 git 历史 8 个提交中（c48260d/e6f4f0d/95fcf63/78c77d0/d6f70b0/eb50a92/42cf667/a26aaf5，其中 42cf667 本身就是『修复 secret scan』提交）且从未轮换：**backend/.env:22 仍是同一把活 key**（round-2 遗留，升级为 🔴）。
  _Why it matters_: 仓库历史是活凭据的公开副本——任何拿到仓库（或仓库将来公开/被 fork）的人都能直接消费该账号的 SiliconFlow 额度；泄漏已持续存在多轮审计。
  _Fix_: 立即在服务商控制台轮换并更新 backend/.env；对 8 个提交做 git filter-repo 重写/脱敏。(M, certain)
- 🟡 `backend/app/routers/profile_pkg/llm.py:143-150` — 用户自带 LLM/search API key 明文落库（user_llm_config.api_key / user_search_config.api_key 直插；读路径 llm.py:31 / search.py:169 明文 SELECT，仅 GET 响应 _mask_key 遮蔽）（round-2 遗留）。_Fix_: Fernet 加密落库（JWT_SECRET 派生密钥），llm.py/search_service.py 调用点解密。(M, certain)
- 🟡 `backend/.env:17` — 生产 ADMIN_PASSWORD 仍 8 字符（round-2 遗留，实测 len=8；虽有锁定防护但弱口令削弱之）。_Fix_: 生成 ≥16 字符随机密码并轮换。(S, certain)
- 🟢 `backend/app/routers/`（189 个路由）— 仅 audio.py:29 声明 response_model，其余直接返回 dict/DB 行，响应侧无形状强制。_Fix_: 优先为 auth/data/profile 返回用户 dict 的路由补 response_model / Field(exclude)。(L, probable)

---

## D5 — Multi-tenant isolation

**Status**: ❌ 本轮新增 🔴（全量重建跨租户泄漏）。认证/查询层 owner 作用域整体可靠（JWT 身份、build_bank_where_clause、MCP principal ContextVar、ARQ job payload 快照），但管理员全量重建路径破坏隔离。

### Findings

- 🔴 `backend/app/worker.py:715-750 (build_master_bank_task)` — 管理员全量重建题库把**全部用户私有/pending 面经题目公开化**：_load/_enqueue_all 无 interview.owner_id/status 过滤 → analysis_queue 以 NULL（公共桶）入队 → dequeue_batch 按 NULL 桶消费 → insert_new_clusters 硬编码 owner_id=NULL（整链已读码核实：worker.py:657-663,681-704,722-725 + writer.py:187-197 + queue.py:91-108）。questions_detail 本身无 owner 列，必须 JOIN interview 过滤。
  _Why it matters_: 任意用户提交的私有面经（含 pending 未审核内容）在一次管理员重建后进入全体可见的公共题库，属跨租户机密性破坏；触发条件为管理员操作（非远程利用），故修复优先级仍为 S-M 级单点修复。
  _Fix_: 在 _load/_enqueue_all 的 JOIN 中限定 i.owner_id IS NULL AND i.status='approved'；补回归测试断言私有面经题目永不进入公共题库。(M, certain)

---

## D6 — Operational readiness

**Status**: ⚠️ 日志轮转/重启策略/资源限制/备份恢复流程均在位；但 worker 部署滞后、磁盘 82%、双网关无 healthcheck。

### Findings

- 🟡 `backend/app/worker.py:1386` — 生产 worker 仍跑 08-14 旧镜像（783f58123828；容器内 worker.py 无 scheduled_db_retention_task，backend 容器 3 命中）；retention cron 从未运行（email_verification_codes 1052/1052 过期、analysis_queue 574 done 未清理）。_Fix_: ./deploy/docker-deploy.sh worker-up 重部署并验证 cron 生效。(S, certain)
- 🟢 `backend/data/ (738MB) + ./backups/ (1.3GB)` — 备份与残留同盘 SPOF，根分区 82% 已用（round-2 遗留：405MB pre_migration + 249MB 58 个 .bak + 1.3GB 顶层 backups/）。_Fix_: 备份移出数据盘 + 保留期清理并入 cleanup。(M, certain)
- 🟢 `docker-compose.yml:225-276` — nginx 与 oauth-gateway 无 healthcheck（round-2 遗留）。_Fix_: 加 /health 探测。(M, certain)
- 🟢 `worker.py:1379-1388` — 6 个 ARQ cron 无 LastRunAt/失败可见性（round-2 遗留）。_Fix_: DB 记录 last_run_at/status + 心跳 + admin 只读端点。(M, certain)
- 🟢 `docs/` — 无运维 runbook（DB down/LLM 5xx/配额耗尽/磁盘满/OOM）。_Fix_: 新增 docs/runbook/。(M, certain)
- 🟢 `deploy/docker-deploy.sh:488-556` — 恢复流程只手工演练过一次（08-12 smoke），无定期演练。_Fix_: 每周恢复演练或文档化节奏。(M, probable)

---

## D7 — Dependency hygiene

**Status**: ⚠️ lock 文件齐且干净（uv.lock + package-lock.json，构建可复现）；14 条 pip-audit / 16 条 npm 漏洞与三条显著滞后全部仍 open；新增 3 个未使用依赖与 Node 引擎漂移。

### Findings

- 🟡 `pyproject.toml:20-22` — 死依赖 python-jose/passlib（2021/2020 停更）经 ecdsa/pyasn1 保持 4 个生产 CVE 存活（round-2 遗留；uv export 实测均 via python-jose）。_Fix_: 迁 PyJWT + 直连 bcrypt。(M, certain)
- 🟡 `pyproject.toml:18` — uvicorn==0.24.0 硬钉锁死旧 click 8.3.2（PYSEC-2026-2132，round-2 遗留）。_Fix_: 放开 uvicorn>=0.30。(S, certain)
- 🟡 `frontend/package.json:47` — vite ^4.4.5 落后 4 个大版本；npm audit --omit=dev 16 个生产漏洞（9 high：postcss/undici），package.json overrides 仍钉在含漏洞版本（round-2 遗留）。_Fix_: 升 vite ^7/^8 + plugin-vue，更新 overrides，重跑 build+smoke。(M, certain)
- 🟢 `.github/` — 无 dependabot/renovate（round-2 遗留）。_Fix_: 加 dependabot.yml（weekly，HIGH/CRITICAL 标记）。(S, certain)
- 🟢 `frontend/package.json:12,30,31` — 3 个未使用生产依赖（puppeteer-core、@hugeicons/core-free-icons、@hugeicons/vue，0 导入）。_Fix_: 删除或移 devDependencies；清 components.json iconLibrary（实际 @lucide/vue 72 处）。(S, certain)
- 🟢 `frontend/package.json` — 无 engines/.nvmrc；CI Node 20 vs Docker Node 22 漂移。_Fix_: 加 engines + .nvmrc 对齐。(S, certain)

---

## D8 — Build / CI / dev-loop

**Status**: ❌ round-2 的门禁失明已修复（函数定义+执行），CI 首次存在；但静态检查存量 179/436/63 永不阻断，且缺容器扫描。

### Findings

- 🔴 `.github/workflows/ci.yml:9-59` — deploy 镜像无任何容器扫描（Trivy）阶段（D08 方法目录：missing container scan → 🔴；pip-audit/npm audit 仅覆盖语言层依赖）。_Fix_: 加 Trivy step（扫 app/nginx 镜像）或 build 前 hadolint+trivy。(S, certain)
- 🟡 `.github/workflows/ci.yml:39` — 静态检查在 CI 中 || true 永不阻断（实测 ruff 179 / mypy 436 / eslint 63 存量；与 CLAUDE.md『audit WARN 仅报告』策略一致，但存量已可观）。_Fix_: 先清零存量，再把 ruff/eslint 提为 blocking step。(M, certain)
- 🟡 `scripts/line_guard.sh:48,53` — 不扫 backend/tests（round-2 遗留）。_Fix_: 纳入 backend/tests（上限放宽至 2000）并拆分超大测试文件。(S, certain)
- 🟡 `.githooks/commit-msg` — 无 install.sh，fresh clone 无钩子（round-2 遗留）。_Fix_: 新增 .githooks/install.sh 写 core.hooksPath 并接入 README/check.sh。(S, certain)
- 🟢 `oauth-gateway/Dockerfile:1` — 基础镜像 minor-pinned 未 digest-pinned。_Fix_: 文档化权衡或 digest-pin。(S, certain)
- 🟢 `scripts/check.sh:2` — set -uo pipefail 缺 -e。_Fix_: 改 set -euo pipefail。(S, certain)

---

## D9 — Data model integrity

**Status**: ⚠️ 迁移体系设计扎实（081-086 备份+FK 断言+回归套件），但生产库 178 行 FK 孤儿仍在（无 090），回归套件有窗口盲区；软删读路径与碎片化持续。

### Findings

- 🟡 `backend/app/db/migrations/schema_hygiene.py:359-376` — 生产库 178 行 FK 违规持续存在（实测 interview_asked_questions 97+81 孤儿；schema_version max=89）。根因：085 _rebuild_table 原样搬运 081→085 FK-off 窗口期写入的孤儿。_Fix_: migration 090 删除孤儿 + 085 重建末尾加 foreign_key_check 断言 fail-closed。(M, certain)
- 🟡 `backend/tests/infra/test_schema_hygiene.py:362-400` — FK 回归套件不覆盖 081→085 孤儿写入窗口（CI 全绿而生产库带病）。_Fix_: 补『应用 081 后写孤儿再应用 085』用例。(S, certain)
- 🟢 `backend/app/routers/chat.py:451` — 关联 JD 查询无 deleted_at 过滤（round-2 遗留）；agents/chat/memory_extract.py:129 同类。_Fix_: 两处加 AND deleted_at IS NULL。(S, certain)
- 🟢 `backend/app/services/email_service.py:104,126,149,207,264` — 5 处 naive datetime.now()；run_db_retention 用 SQLite UTC now 比对本地 expires_at，清理偏差 ~8h（round-2 遗留，D14 同源合并）。_Fix_: 统一 tz-aware UTC（或 retention 侧 datetime(expires_at,'localtime')）。(M, probable)
- 🟢 `backend/app/db/migrations/llm.py:11-32` — 089 llm_usage 重复索引（UNIQUE(user_id,day) 后再建 idx_llm_usage_user_day）+ user_id 无 FK。_Fix_: 删重复索引、加 FK CASCADE。(S, certain)
- 🟢 `backend/app/db/` — 队列表碎片化持续（round-2 遗留；实测 jobs 302 / analysis_queue 574 全 done / cluster_review_tasks 333 / task_logs 8；payloads/distribution_refresh_jobs/side_effect_jobs 并非真实表）。_Fix_: 冻结旧表，新任务走 jobs 表；done/过期行纳入 retention。(M, probable)

---

## D11 — Legal / compliance

**Status**: ⚠️ 四份 compliance 文档与迁移一致（删除文档表清单准确）；两个新增缺口与评测表相关。

### Findings

- 🟢 `backend/app/db/migrations/evaluation.py:200` — eval_human_reviews.reviewer_id ON DELETE RESTRICT 会阻塞管理员账号删除（eval_* 表未列入 account-deletion.md）。_Fix_: 改 SET NULL + 快照 reviewer 名，或文档化手工顺序。(S, probable)
- 🟢 `backend`（无导出端点）— 无数据导出/可携带性路径（privacy-policy.md sec.5 已留口子）。_Fix_: 实现 owner 作用域导出端点或明确 out-of-scope + 手册流程。(M, certain)

---

## D12 — Admin surface

**Status**: ⚠️ 管理面 authz 边界可靠（全部 admin 路由含新评测中心均 Depends(get_admin_user)，前端 meta.adminOnly 路由守卫）；新评测中心的部署缺口是主要问题。

### Findings

- 🟡 `docker-compose.yml:161-166 + app/eval_worker.py` — 评测中心 async run 无已部署消费者：eval_run_task 入队 arq:eval，但 eval worker 仅 profile:[eval] + restart:'no' + --burst，无任何 deploy 命令拉起（实测 docker ps 无 eval-worker）；admin 建 run 后永久 queued 且无提示。_Fix_: worker-up 兼容 eval profile / 默认 profile + restart + healthcheck；前端展示 worker offline。(M, certain)
- 🟢 `docker-compose.yml:165` — eval-worker --burst 单次排空即退出，后续批次静默堆积。_Fix_: restart: unless-stopped + 去 --burst。(S, certain)

---

## D13 — Setup replicability

**Status**: ⚠️ 核心可复现（uv 前置、Docker test-runtime、密钥自动生成）；README 环境变量模板缺口为本轮新发现。

### Findings

- 🟡 `backend/.env.example` — README 环境变量表 7 个变量在 .env.example 无占位行（SEARCH_PROVIDER/SEARCH_API_KEY/SEARCH_BASE_URL/SILICONFLOW_API_KEY/EMBEDDING_API_MODEL/CLUSTER_MIN_SIMILARITY/REDIS_URL/REDIS_PASSWORD_FILE）。_Fix_: 补注释占位行。(S, certain)

---

## D14 — Correctness & robustness

**Status**: ⚠️ 整体健壮（tenacity 仅限幂等调用、MCP 错误信封、auth 原子 upsert、reprocess 幂等化）；两个 round-2 🟢 仍 open，无新 🟡。

### Findings

- 🟢 `backend/app/agents/chat/react_loop.py:536-543` — return 后不可达死代码引用未定义 tool_names（round-2 遗留）。_Fix_: 删除不可达块。(S, certain)
- 🟢 `backend/app/services/cluster_review_lifecycle.py:721-730` — except 变量 exc 嵌套闭包引用（round-2 遗留，实测正常）。_Fix_: except 内预求值。(S, needs-verification)
- 🟢 `backend/app/routers/data.py:930-937` — interview 编辑 commit 后事务外提交 reprocess（round-2 遗留；现已幂等复用 queued/running job，风险降低）。_Fix_: 任务必达 + 告警/重试。(M, certain)

---

## D15 — UX & interaction

**Status**: ⚠️（source-level；rendered pass 不可行）主流程 loading/empty/error 分支覆盖充分、prefers-reduced-motion 广泛遵守；原生 confirm 与 title 遗留。

### Findings

- 🟢 `frontend/src/views/PracticeDecksView.vue:51` — 删除自定义题单仍用原生 window.confirm（round-2 遗留，破坏性操作）。_Fix_: 改用 useConfirm()/ConfirmDialog。(S, certain)
- 🟢 `frontend/src/components/SiteHeader.vue:99` — 全局头删除题单同用原生 confirm，且两处文案漂移。_Fix_: 同上并统一文案。(S, certain)
- 🟢 `frontend/src/components/business/PracticeMode.vue:141,177,435,462` — 4 处原生 title 绕过 AppTooltip 约定。_Fix_: 改用 AppTooltip（icon 按钮补 aria-label）。(S, probable)

---

## D16 — UI & design-system craft

**Status**: ⚠️（source-level）token 文件与 7 个图表组件正确消费；2 个组件 + KnowledgeGraph 仍内联 hex；4 个死组件随 build 发布。

### Findings

- 🟢 `frontend/src/components/business/PracticeStarChart.vue:47-103` — 内联 12 个 porcelain hex 绕过 chartTokens.js（round-2 遗留）。_Fix_: import { porcelain } from '@/utils/chartTokens.js'。(M, certain)
- 🟢 `frontend/src/components/business/PracticeQuadChart.vue:33-84` — 内联 7 个 hex + KnowledgeGraph 另硬编码 11 个（后者已 import RAMP_DARK 未用完）。_Fix_: 统一走 chartTokens（porcelain/porcelainTooltip/RAMP）。(M, certain)
- 🟢 `frontend/src/components/business/PracticeRecentTimeline.vue` — 4 个死组件（PracticeRecentTimeline/PracticeHighFreqChart/ThinkingBlock/ExamDistribution，0 引用）随 build 发布。_Fix_: 删除或显式 deprecated。(S, certain)

---

## Triage — proposed follow-up milestones

| Finding | Suggested milestone | Effort |
|---|---|---|
| 🔴 D4-1 活 key 泄漏 git 历史未轮换 | M-48: 轮换 SiliconFlow key + filter-repo 脱敏 | M |
| 🔴 D5-1 全量重建公开化私有面经 | M-49: rebuild 加 owner/status 过滤 + 回归测试 | M |
| 🔴 D8-1 CI 无容器扫描 | M-50: CI 加 Trivy/hadolint | S |
| 🟡 D3-2 threading.local→contextvars 测试隔离 | M-51: 修复测试隔离真根因（~80 chat 测试） | M |
| 🟡 D3-1/D3-3 其余测试失败簇（reupload/email_auth/public_ip） | M-52: 收敛 fixture 漂移 + 镜像缺口 | S |
| 🟡 D6-1/D9-1 worker 重部署 + migration 090 清孤儿 | M-53: 部署对齐 + FK 孤儿清理 | M |
| 🟡 D4-2..4 npm/pip 漏洞 + ADMIN_PASSWORD + key 明文 + response_model | M-54: 安全残余项 | M |
| 🟡 D7 依赖现代化（uvicorn/jose/vite）+ Dependabot | M-55: 依赖升级 | M |
| 🟡 D12-1 eval worker 部署 + D6 runbook/演练 | M-56: 评测中心上线 + 运维手册 | M |
| 🟡 D8-2/D13-1 静态检查收紧 + .env.example 补齐 | M-57: 门禁收紧第一档 | M |
| 🟢 D1/D2/D3/D6/D7/D9/D11/D14/D15/D16 清尾 | M-58: debt sweep（含死代码/死组件/文档计数） | S-M |

---

## Appendix — 🟢 findings

见 `.tech-audit/work/2026-08-15-r3/findings.tsv`（58 条全量）。🟢 已在各维度节内列出；重复项（D9/D14 email 时区、D8/D13 钩子安装）已合并为单条。

---

## Round 3 — execution notes

- Fan-out: 12 个维度 agent（D1-D9、D11-D16，D10 release-only 跳过），每个携带维度方法目录 + 语言文件 + 共享 inventory + round-2 TSV；所有 🔴 均经独立代码路径复核（D5 整链、D8 catalog、D9 生产库 PRAGMA、D6 容器内 grep、D3 复现）。

- 运行时探测均为只读：docker inspect/exec、生产库 PRAGMA/SELECT、docker compose config。
- D4 agent 因 pip-audit 网络下载反复超时收尾缓慢，其 pip-audit 复测出现假阴性（超时重试后报 No known vulnerabilities）；以 uv.lock 版本复核为准：aiohttp 3.14.1 / cryptography 49.0.0 / ecdsa 0.19.2 / pyasn1 0.6.3 原样，14 条 PYSEC 仍 open（与 D7 结论一致）。
- 未做：D10（无 release tag）、D15/D16 rendered pass（无浏览器环境）、容器镜像 Trivy 实扫（CI 无此阶段，本轮未引入）。