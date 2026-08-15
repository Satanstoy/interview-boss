# Tech audit — 2026-08-15

**Auditor**: tech-audit skill, under the user's direction
**Scope**: full (all dimensions, D10 skipped — not a release cut)
**Repo HEAD at audit time**: `ec446e5658bcccb17ae27b008847f57991995d97`
**Findings source**: `.tech-audit/work/2026-08-15/findings.tsv` (31 findings; both 🔴 survived the refutation pass)
**Previous audit**: `docs/analysis/tech-audit-2026-08-14.md`

---

## Executive summary

- 🔴 **Top risk**: the quality gate is blind — `scripts/check.sh` calls two functions that do not exist, so ruff / mypy / eslint have never actually run in the gate, and 175 ruff + 436 mypy + 119 eslint errors accumulated invisibly.
- 🟢 **Top strength**: prod stack is up and healthy; 2548/2559 tests collect, secret scan passes, line-guard passes, compose config validates, and the 2026-08-14 fix round (concurrency → 409, quota 429, FTS sync, test-data volume isolation, compliance docs) is verifiably in the tree.
- 🟡 **Biggest gap**: D8 (build/CI/dev-loop) — every other dimension's findings are downstream of a gate that cannot see them.

---

## Status overview

| Dim | Title | Status | 🔴 | 🟡 | 🟢 |
|---|---|---|---|---|---|
| D1 | Code essentiality | ⚠️ | 0 | 1 | 1 |
| D2 | Docs integrity | ✅ | 0 | 0 | 1 |
| D3 | Tests as adversaries | ⚠️ | 0 | 2 | 0 |
| D4 | Security posture | ⚠️ | 0 | 3 | 0 |
| D5 | Multi-tenant isolation | ✅ | 0 | 0 | 0 |
| D6 | Operational readiness | ⚠️ | 0 | 2 | 0 |
| D7 | Dependency hygiene | ⚠️ | 0 | 3 | 0 |
| D8 | Build / CI / dev-loop | ❌ | 1 | 4 | 0 |
| D9 | Data model integrity | ⚠️ | 0 | 5 | 0 |
| D10 | Performance & cost | — | skipped (release-only) | | |
| D11 | Legal / compliance | ✅ | 0 | 0 | 0 |
| D12 | Admin surface | ✅ | 0 | 0 | 0 |
| D13 | Setup replicability | ✅ | 0 | 0 | 0 |
| D14 | Correctness & robustness | ⚠️ | 1 | 2 | 2 |
| D15 | UX & interaction | ⚠️ | 0 | 0 | 1 |
| D16 | UI & design-system craft | ⚠️ | 0 | 0 | 1 |
| **Total** | | | **2** | **22** | **6** |

整体健康：❌（存在未缓解的 🔴）。D10 未跑（无 release tag）；D15/D16 的 rendered pass 因无浏览器截图环境 **deferred**，仅做 source-level。

---

## Trend vs previous audit

上一轮（2026-08-14）从 40+61+104 条来源对账出 55 FIXED / 48 still-open。本轮重新实测后：

- 上轮标记 FIXED 的关键项复核仍为真：并发 email → 409、LLM 配额 429、FTS sync/rebuild、test-data 卷隔离、compliance 三文档、secret scan 修复、E2E 关闭口径。
- 上轮"看似已修实为半修"第 1 条（check.sh 静态检查静默失效）**仍 open 且升级为 🔴**。
- 新回归：`bank_build.py` 未导入 `match_new_questions`（生产端点 NameError）——上轮 reconcile 未覆盖到该行。
- 仍 open 的代表性项：MCP query key 已在源码移除（复查关闭）；refresh cookie 信任 XFP、API key 明文落库、备份同盘 SPOF、6 套队列表碎片化、vite/uvicorn 落后、无 Dependabot、nginx/oauth-gateway 无 healthcheck 等。

Closed since last time:
- ✅ MCP `mcp_api_key` URL query 读取路径已从 `mcp_server/app.py` 源码移除（只剩 `x-mcp-api-key` header + bearer）。

New regressions:
- 🔴 D14 — `bank_build.py:277` `match_new_questions` 未导入。
- 🔴 D8 — check.sh 静态检查函数未定义（重新确认，此前被标为"待收敛"）。

---

## D1 — Code essentiality

**Status**: ⚠️ 无超红线 app/src 文件（上轮 god-file 拆分落地，chat_service 2395→104、nodes 2028→1343、ChatView 1577→1497 均 <1500）；死模块与盲区仍在。

### Findings

- 🟢 `backend/app/services/pipeline/batch_v2.py` — 死模块：生产零调用，仅测试 `inspect.getsource` 引用其行为。建议删除并把回归点固化为契约注释，或显式标 deprecated。(S)

---

## D2 — Docs integrity

**Status**: ✅ 抽样的 composables=22、Python 3.12、include_router 描述基本一致；compliance/ADR/schema 文档齐备。

### Findings

- 🟢 `backend/CLAUDE.md:65` — 文档写"22 次 include_router"，实际 23 次 `include_router` + 1 次 `app.mount("/mcp")`。(S)

---

## D3 — Tests as adversaries

**Status**: ⚠️ 2548/2559 tests collect；regression-after-fix 比例已 ≥80%（32fda42 固化）；但对抗性输入语料与 coding 越权覆盖缺失。

### Findings

- 🟡 `backend/tests/security/` — 无 SQL 注入语料、Unicode 边界、1MB 超长、hypothesis 属性化 fuzz。(M)
- 🟡 `backend/tests/coding/test_coding.py` — 无误越权、超长代码、恶意 markdown 边界；auth_client fixture 每文件重复。(S)

---

## D4 — Security posture

**Status**: ⚠️ secret scan 通过、MCP query key 已移除、配额已上；生产依赖 CVE 与两项长期 open 项仍存。

### Findings

- 🟡 `frontend/package-lock.json` — `npm audit --omit=dev` 16 个生产依赖漏洞（9 high：postcss/undici），有可用修复。(M)
- 🟡 `backend/app/routers/auth.py:228-233,240-244` — refresh cookie `secure` 信任可伪造的 `x-forwarded-proto`。(M, needs-verification)
- 🟡 git 历史 `529f232..78c77d0` — MiMo/SiliconFlow 历史 key 已从工作树移除但仍需服务商侧轮换。(S)
- 🟡 `db/operations.py` + `profile_pkg/llm.py` — 用户自带 LLM/search key 明文落库，无 Fernet 加密。(M)

---

## D5 — Multi-tenant isolation

**Status**: ✅ insights high_frequency owner 作用域、LLM per-user 配额（migration 089 + 4 入口 429）已落地复核通过；security 测试覆盖存在。无新增 cross-tenant 发现（未跑 runtime probe，依赖源码复核）。

---

## D6 — Operational readiness

**Status**: ⚠️

### Findings

- 🟡 `docker-compose.yml` nginx / oauth-gateway 段 — 无 healthcheck（backend/redis/redis-cache/worker 均有）。(M)
- 🟡 `worker.py` `WorkerSettings.cron_jobs` + `do_status` — 6 个 ARQ cron 无 LastRunAt/失败可见性，worker 关闭时静默缺跑。(M)

---

## D7 — Dependency hygiene

**Status**: ⚠️ lock 文件齐（uv.lock + package-lock.json）；三条显著滞后。

### Findings

- 🟡 `pyproject.toml` — uvicorn==0.24.0 硬钉 + python-jose/passlib（停更 4-5 年）。(M)
- 🟡 `frontend/package.json:56` — vite ^4.4.5 落后 4 个大版本。(M)
- 🟡 无 Dependabot/Renovate。(S)

---

## D8 — Build / CI / dev-loop

**Status**: ❌ 门禁失明是本轮最高风险维。

### Findings

- 🔴 `scripts/check.sh:153-154,190` — 调用未定义的 `run_static_backend`/`run_static_frontend`，静态检查从未运行（实测 `command not found`；all 分支重复调用一次）。Fix：定义两函数跑 ruff/mypy + eslint，去掉重复调用。(S)
- 🟡 `frontend/eslint.config.js` — 无 TS parser，101 个 `lang="ts"` 组件 100 个 parsing error。(M)
- 🟡 `scripts/line_guard.sh` — 不扫 `backend/tests`，3728 行测试 god-file 无约束。(M)
- 🟡 `.githooks/commit-msg` — 无 install.sh，fresh clone 无 hook。(S)
- 🟡 `check.sh:113-121` — 后端依赖审计（pip-audit）未像 collect/compile/tests 一样走 test-runtime 容器，而是直接在宿主机调用 uv；宿主 PATH 无 uv 即静默 SKIP（test 镜像已实测含 uv 0.12.4）。Fix: 用 `docker compose --profile test run --rm test` 包一层。(S)

---

## D9 — Data model integrity

**Status**: ⚠️ 迁移体系与 FK 清理在上轮已大部修复（081-086、foreign_key_check、自动备份）；软删读路径与留存策略仍 open。

### Findings

- 🟡 `backend/app/routers/chat.py:450-454` — 关联 JD 查询无 `deleted_at` 过滤，软删 JD 进 LLM 上下文。(S)
- 🟡 `email_service.py:81/159/216` — `datetime.now()` naive。(M)
- 🟡 `fts_service.py:70-76` — `_idf_cache` 需确认 delete 路径也重置。(S)
- 🟡 `backend/data/` + `backups/` — 备份同盘 SPOF，残留 -wal/-shm。(M)
- 🟡 6 套队列表碎片化（jobs/analysis_queue/cluster_review_tasks/distribution_refresh_jobs/side_effect_jobs/task_logs）。(L)

---

## D11 — Legal / compliance

**Status**: ✅ docs/compliance 三文档 + SettingsSecurity 入口在建（8c549f7）。数据导出/自服务删除等增强项未列为本轮 finding（PoC 阶段可接受，手册流程已有）。

## D12 — Admin surface

**Status**: ✅ 上轮质量 tab/AI 助手/来源健康并入，无新增 surface 发现。

## D13 — Setup replicability

**Status**: ✅ README:130 已明确要求本地安装 uv；测试全走 Docker test-runtime（CLAUDE.md:158）。该维度本轮复核无 finding（原 "README 未提示 uv" 条目不成立，已撤回）。

## D14 — Correctness & robustness

**Status**: ⚠️ 一个生产端点必炸。

### Findings

- 🔴 `backend/app/routers/bank_build.py:277` — `match_new_questions` 未导入，build-personal 端点个人题目+公共题库均非空时必 NameError（前置分支已读代码核实；全文件无 import）。Fix：补 import。(S)
- 🟡 `backend/app/routers/data.py:925-937` — interview 编辑 commit 后才在事务外提交 reprocess 任务。(M)
- 🟡 `backend/app/routers/auth.py:62-85` — login `_record_failure` 并发边界复查。(S, needs-verification)
- 🟢 `react_loop.py:536-543` — return 后不可达死代码引用未定义 `tool_names`。(S)
- 🟢 `cluster_review_lifecycle.py:721-730` — except 变量 `exc` 闭包引用（实测正常，保守加固）。(S)

## D15 — UX & interaction

**Status**: ⚠️（source-level；rendered pass deferred）

### Findings

- 🟢 `PracticeDecksView.vue:51` + `SiteHeader.vue:99` — 删除仍用原生 `window.confirm`。(S)

## D16 — UI & design-system craft

**Status**: ⚠️（source-level；rendered pass deferred）

### Findings

- 🟢 `PracticeStarChart.vue` + `PracticeQuadChart.vue` — 绕过 `chartTokens.js` 内联同一套 hex。(S)

---

## Triage — proposed follow-up milestones

| Finding | Milestone | Effort |
|---|---|---|
| 🔴 D8-1 check.sh 静态函数未定义 | M-39: 修复门禁，恢复 ruff/mypy/eslint 执行 | S |
| 🔴 D14-1 bank_build.py 缺 import | M-40: 修复 build-personal NameError | S |
| 🟡 D8-2 eslint TS parser | M-41: 前端 lint 恢复 TS 组件扫描 | M |
| 🟡 D4-1 npm 16 漏洞 (9 high) | M-42: 升级 postcss/undici | M |
| 🟡 D4-3/D4-4 cookie secure + API key 明文 + 历史 key 轮换 | M-43: 安全残余项 | S-M |
| 🟡 D7 依赖滞后 + Dependabot | M-44: 依赖现代化 | M |
| 🟡 D6 healthcheck + cron 可见性 | M-45: 运维加固 | M |
| 🟡 D9 软删读路径 + 留存/碎片化 | M-46: 数据完整性收尾 | L |
| 🟢 D1/D2/D3/D8/D14/D15/D16 清尾 | M-47: debt sweep | S |

---

## Appendix — 🟢 findings

- D1-1 `batch_v2.py` 死模块
- D2-1 `backend/CLAUDE.md:65` 计数 22→23
- D14-3 `react_loop.py:536-543` 死代码
- D14-4 `cluster_review_lifecycle.py` except-closure（保守）
- D15-1 两处 `window.confirm`
- D16-1 两组件内联 hex
