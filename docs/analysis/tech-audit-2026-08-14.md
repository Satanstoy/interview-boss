# Tech audit — 2026-08-14（第二轮续跑）

**Auditor**: tech-audit skill（5 个并行维度 subagent + 主 agent 交叉验证）
**Scope**: full（16 维度；D10 release-only 未跑深扫，D15/D16 为 source-level pass）
**Repo HEAD at audit time**: fe9685f（master，2026-08-14 01:22）
**Findings source**: `.tech-audit/work/2026-08-14/findings.tsv`（54 行：4🔴 / 15🟡 / 29🟢 / 6 FIXED）
**Previous audit**: [tech-audit-2026-08-13.md](tech-audit-2026-08-13.md)（61 条：10🔴 / 16🟡 / 35🟢）
**Stack**: Python/FastAPI + LangGraph · Vue3/Vite/Tailwind/shadcn-vue · SQLite WAL + FAISS · Docker Compose + ARQ worker + oauth-gateway · Bash (deploy/)

---

## Executive summary

- 🔴 **Top risk（本轮新增，已当场修复）**: 上轮新增的 secret 扫描门禁（check_secrets.py）存在**排除过滤器恒真短路**——`part in EXCLUDE_DIRS` 遍历集合自身恒为 True，导致 `iter_source_files()` 产出 **0 个文件**，check.sh 与 CI 的 secret scan **恒绿假门禁**；且 PROJECT_ROOT 错指 backend/ 漏扫 frontend/。修复后全仓 2256 文件扫描即刻**检出 3 个 5 月旧脚本中的真实小米 MiMo API key**（tp-ck 开头，已进 git 历史 529f232）——上轮审计因扫描器空转而漏掉这批真实泄露。
- 🟢 **Top strength**: 上轮 6 个 🔴 全部修复落地（D4-1 硬编码 key 删字面量、D13-1 JWT 占位注释化、D13-2 OAuth 兜底移除、D14-1 email 唯一索引、D8-1 CI workflow、D8-2 secret 扫描）——本轮逐项代码路径验证通过。
- 🟡 **Biggest gap（仍开放）**: 工程基建债持续：三个 god-file 未拆（行数未变）、零 CI 可跑（新 workflow 有依赖引导缺口）、无真实 E2E、无静态检查；上轮 16 个 🟡 无一生效修复（除随 🔴 处理的）。

---

## Status overview（对比上轮）

| Dim | 上轮 | 本轮 | 变化 |
|---|---|---|---|
| D1 Code essentiality | ❌ 3🔴 | ❌ 3🔴 +1修正 | 未动；batch_v2 死模块结论修正 |
| D2 Docs integrity | ✅ | ⚠️ | JWT 描述已随 D13 修复；版本/计数 3 处仍错 |
| D3 Tests as adversaries | ❌ 1🔴 | ❌ 1🔴 +2新🟡 | 无真 E2E；新测试含 key 字面量 |
| D4 Security posture | ❌ 1🔴 | ⚠️ | D4-1 已修；**新检出 MiMo key 泄露（已修）**；5 个 🟡 未修 |
| D5 Multi-tenant isolation | ⚠️ | ⚠️ | 无进展 |
| D6 Operational readiness | ⚠️ | ⚠️ | 无进展 |
| D7 Dependency hygiene | ✅ | ✅ | 无进展（Vite/uvicorn/未用依赖） |
| D8 Build/CI/dev-loop | ❌ 2🔴 | ⚠️ | 2🔴 已修但**新 CI 有 3 个新 🟡**（依赖引导/gitleaks 必红/扫描器已修） |
| D9 Data model integrity | ⚠️ | ⚠️ | init_db FK 已缓解可归档；test 卷/备份 SPOF 未修 |
| D10 Performance & cost | ✅ | ✅ | 无进展（release-only 未深扫） |
| D11 Legal/compliance | ⚠️ 3🟡 | ⚠️ 3🟡 | 无进展 |
| D12 Admin surface | ✅ | ⚠️ | test-global 无进度确认 |
| D13 Setup replicability | ⚠️ 2🔴 | ⚠️ | 2🔴 已修；OAUTH 空密钥静默生成新🟡；HF 路径/IP 兜底未修 |
| D14 Correctness & robustness | ❌ 1🔴 | ⚠️ | email 唯一索引已修；**并发注册 500 新🟡** |
| D15 UX & interaction | ✅ | ⚠️ | a11y 升级（AppTooltip 触点设备无 label） |
| D16 UI & design-system | ✅ | ✅ | 色板范围收敛 6→2 图 |
| **Total** | **10🔴/16🟡/35🟢** | **4🔴/15🟡/29🟢+6FIXED** | 🔴 ▼6（4 修复+2 新），🟡 ▼1 |

---

## Trend vs previous audit（2026-08-13 → 2026-08-14）

**已修复（上轮 🔴 → 本轮 FIXED，代码路径逐项验证）**：
- ✅ D4-1 SiliconFlow key 硬编码 → 4 脚本改读 env，缺失即 SystemExit（工作树 0 命中）
- ✅ D13-1 JWT_SECRET 公开占位 → .env.example 注释化，auth.py 自动生成口径一致
- ✅ D13-2 OAUTH_SECRET_KEY 公开兜底 → compose 改 ${OAUTH_SECRET_KEY} 直引
- ✅ D14-1 users.email TOCTOU → migration 079 部分唯一索引 + 去重（DB 层封堵）
- ✅ D8-1 零 CI → .github/workflows/ci.yml（gitleaks + check.sh）
- ✅ D8-2 门禁无 secret 扫描 → check_secrets.py 接入 check.sh 阻断段

**上轮 🔴 仍开放**：D1-1/2/3 三个 god-file、D3-1 无真 E2E。

**本轮新增 🔴（均已当场修复）**：D4 真实 MiMo key 泄露×3 脚本（扫描器修复后检出）、D8 扫描器空转 bug（恒真短路 + PROJECT_ROOT 错位）。

**本轮新增 🟡**：并发注册 500（D14，migration 079 副作用）、CI 依赖引导缺口（D8）、gitleaks 全史必红（D8）、测试 key 字面量（D3）、OAUTH 静默生成无告警（D13）、AppTooltip 触点 a11y（D15）。

---

## 关键新发现详情

### D8: check_secrets.py 空转（🔴，已修）
`backend/scripts/check_secrets.py:47` 排除条件 `any(part in EXCLUDE_DIRS or rel.match(part) for part in EXCLUDE_DIRS)` 遍历集合自身，恒真 → 迭代器产出 0 文件。配套测试 `test_main_returns_zero_on_clean_repo` 因空转而 vacuous 通过——**假门禁 + 假测试双失效**。修复：排除逻辑改 `any(part in EXCLUDE_DIRS for part in parts)` + 多段前缀匹配；PROJECT_ROOT 上溯三级；新增 `test_iter_source_files_not_empty` 回归测试（>100 文件 + backend 覆盖断言）。修复后实测 2256 文件、mock 值正确过滤、exit 0。

### D4: 真实 MiMo API key 泄露（🔴，已修）
`backend/scripts/verify_improved_compaction.py:20`、`verify_compaction_on_backup.py:22`、`verify_compaction_match_existing_real.py:35`（5 月旧脚本）+ `CLUSTERING_QUALITY_SUMMARY.md:160` 硬编码小米 MiMo key（tp-ck 开头，token-plan-cn.xiaomimimo.com），进 git 历史（529f232 引入，39039e7 移除跟踪但历史仍含）。已删字面量改读 `MIMO_API_KEY` env（缺失即报错）、md 脱敏。**用户需在小米平台轮换该 key**。

### D14: 并发注册 500（🟡，本轮新，未修）
migration 079 生效后，并发重复 email 的第二个请求：注册路由 `_create` 泛 `except Exception` → 500；`/register-with-email` 的 `_insert_user` 裸 INSERT 无 try → 全局 handler 500。**应为 409**。两路径需捕获 `sqlite3.IntegrityError`。测试只盖 DB 层未盖路由。

---

## Triage（建议里程碑）

| 优先级 | 事项 | Effort |
|---|---|---|
| P0 | 用户轮换 MiMo key + SiliconFlow key（双平台控制台） | 手动 |
| P0 | 注册两路径捕获 IntegrityError 转 409 + API 级测试 | S |
| P1 | CI 依赖引导（npm ci / uv sync / playwright install）+ gitleaks allowlist 或历史清洗 | M |
| P1 | 测试文件 key 字面量改拼接（test_secret_scan.py:20 / test_check_secrets.py:27） | S |
| P2 | god-file 拆分（chat_service/nodes/ChatView） | L |
| P2 | 静态检查接入（ruff/mypy/eslint + tsconfig strict） | M |
| P3 | 上轮 16 个 🟡 逐项（依赖升级、配额、合规、healthcheck、runbook 等） | L |

---
*报告由 tech-audit skill 生成；findings 明细见 `.tech-audit/work/2026-08-14/findings.tsv`*
