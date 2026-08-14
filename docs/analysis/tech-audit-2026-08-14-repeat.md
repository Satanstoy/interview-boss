# Tech audit — 2026-08-14 (repeat pass)

**Auditor**: tech-audit skill, under user's direction
**Scope**: full (delta pass on top of 2026-08-13 / 2026-08-14 main audit)
**Repo HEAD at audit time**: f8e1f41
**Findings source**: `.tech-audit/work/2026-08-14/findings.tsv` (113 rows; 截至 2026-08-14 修复轮次结束: 55 FIXED, 0 🔴, 0 🟡, 48 🟢, 10 信息)

---

## Executive summary

- 🟡→✅ **Top risk 已收敛**: 无真实全栈 E2E 由用户规划的新 eval part 承担（独立评测部件）；`verify_*_real_e2e.py` 转为手动/按需运行
- 🟡→✅ **审计决策清单 1-7 全部落地**（并发/数据正确性组、CI fresh-clone + gitleaks、测试硬编码 key、check.sh 关键子集、LLM per-user 配额、interaction 残留、运维 restore/worker healthcheck）
- 🟡→✅ **剩余 8 条 🟡 全部修复**（ARQ 真实 Redis 集成测试、test 数据卷隔离、HF_CACHE_DIR 参数化、AppTooltip icon-only a11y、回归纪律 ≥80%、question_bank JSON 双写事务内一致、check.sh 门禁确认、合规文档三件套）
- 🟢 **Top strength**: 结构债清偿显著——5 个 god-file 全部 <1500 行;静态检查（ruff/eslint）与 1500 行 blocking 门禁已接入 check.sh
- 剩余 open: 48×2 级 + 10×1 级（低危/信息级），无 🔴 无 🟡

---

## 本轮做什么(Repeat-audit delta)

1. **机械基线**: 主 findings.tsv 上一轮已对齐(28 FIXED; open 1×🔴 + 19🟡 + 47🟢 + 9 信息)
2. **新发现源**: 环境并行审计产出的 `.tech-audit/work/2026-08-14/interaction/findings.tsv`(10 条)——逐条读代码路径验证
3. **新变化核查**: god-file 拆分产物(facade/子模块语法、循环导入)、line_guard/eslint 接线、未提交并行修复(pyproject per-file-ignores 标准化、migration 084 CASE WHEN 强化 + 回归测试)

## 2026-08-14 修复轮次结果(决策清单 1-8)

| # | 修复项 | Commit | 验证 |
|---|---|---|---|
| 1 | 并发/数据正确性: 双写收敛、email 409、verify_code 原子化、复习幂等键 | d9c55ab / b7fdf7a / ec38d31 / 28251d7 / 5a9dc15 / 6b33a55 | Docker pytest 全绿 |
| 2 | CI fresh-clone 跑绿 + gitleaks allowlist | bd984c8 / 8965a59 | CI 绿 |
| 3 | 测试硬编码 key 字面量清理 | a26aaf5 | gitleaks 0 命中 |
| 4 | FTS 收敛 + check.sh 纳入关键子集 WARN | 6b33a55 / 64530ff | key-suite 全量失败面入报告 |
| 5 | LLM per-user 每日配额(429) | 6040c3e | llm_usage 测试 |
| 6 | interaction 残留: mcp_api_key query / 上传尺寸 / refresh 轮转 | 4a120dc / cf418f2 / 5a9dc15 | 回归测试 |
| 7 | 运维: restore 子命令 / worker healthcheck | 3530bd7 / 9729c76 | 脚本演练 |
| 8 | 全栈 E2E 🔴 | —（关闭） | 由用户新 eval part 承担 |
| — | ARQ 真实 Redis 集成测试(RUN_REAL_REDIS=1) | 18b3741 | 默认 skip / 真实 2 passed |
| — | test 数据卷隔离 + HF_CACHE_DIR 参数化 | 1904e15 | docker config + 57 passed |
| — | AppTooltip icon-only 可访问名(WCAG 4.1.2) | 75f65f8 | build + Playwright 绿 |
| — | fix 回归测试补齐 + ≥80% 红线固化 | 32fda42 | 变异验证红→绿 |
| — | question_bank JSON 双写事务内一致 | eeccb60 | 漂移复现红→绿, 53 passed |
| — | 合规文档(隐私/账号删除/子处理器) | 8c549f7 | eslint + SFC 编译 |

## Interaction findings 验证结果(10 条)

| 状态 | 发现 |
|---|---|
| ✅ FIXED(4) | D4 登录限速(request_ip 可信代理 + asgi GlobalRateLimitMiddleware 已存在); D5 洞察 owner 过滤(_scope_condition + JOIN 已存在); D4 MCP token sessionStorage(已改内存持有); D4 login-form CSRF(跨源拒绝已存在) |
| ✅ FIXED(4) | D4 mcp_api_key URL query 参数(4a120dc 改 header-only); D1 上传全量 read 再校验(cf418f2 提前 Content-Length 拦截); D4 refresh 轮转原子化(5a9dc15); D4 验证码 per-email 锁定(ec38d31) |
| 🟢 1 级 open(1) | D1 outbound_url DNS-rebinding TOCTOU(低危) |

## 状态概览(全仓)

| Dim | 状态 | 备注 |
|---|---|---|
| D1 Code essentiality | ✅ | 5 god-file <1500; 残留 1 级(上传读全量已修、batch_v2 死模块 1 级) |
| D2 Docs integrity | ✅ | Python 3.12 / include_router 22 / composables 22 已修; compliance/ 目录已建 |
| D3 Tests as adversaries | ✅ | E2E→用户 eval part; Redis 真实集成测试(RUN_REAL_REDIS=1); check.sh 关键子集 WARN; 回归纪律 ≥80% 固化 |
| D4 Security posture | ✅ | interaction 8 条已修; verify_code 原子化 + 锁定 |
| D5 Multi-tenant | ✅ | 洞察 owner 隔离; LLM per-user 每日配额(llm_usage) |
| D6 Operational | ✅ | restore 子命令; worker healthcheck; 残留 cron LastRunAt(2 级) |
| D8 CI/dev-loop | ✅ | fresh-clone 绿; gitleaks allowlist; check.sh 关键子集 |
| D9 Data model | ✅ | 双写权威源收敛; JSON 双写事务内一致(compact 路径修复); test 卷隔离(test-data 命名卷) |
| D11 Compliance | ✅ | 隐私政策 / 账号删除 / 子处理器三件套 + 设置页入口 |
| D13 Infra | ✅ | HF_CACHE_DIR 参数化, 新机器不再挂空 root |
| D14 Correctness | ✅ | email 500 / verify_code 竞态 / refresh 轮转 / 幂等键全修 |

---

## 决策清单(全部完成)

| # | 问题 | 状态 |
|---|---|---|
| 1 | 并发/数据正确性组: 双写收敛、email 409、verify_code 原子化、复习幂等键(spec M31/M32) | ✅ d9c55ab/b7fdf7a/ec38d31/28251d7 |
| 2 | CI fresh-clone 跑绿 + gitleaks allowlist | ✅ bd984c8/8965a59 |
| 3 | 测试硬编码 key 字面量清理(2 文件) | ✅ a26aaf5 |
| 4 | check.sh 纳入 backend 全量 pytest(关键子集 WARN) | ✅ 64530ff |
| 5 | LLM per-user 配额(spec M33) | ✅ 6040c3e |
| 6 | interaction 残留: mcp_api_key query / 上传校验 / refresh 轮转原子化 | ✅ 4a120dc/cf418f2/5a9dc15 |
| 7 | 运维: restore 命令、worker healthcheck、cron LastRunAt | ✅ 3530bd7/9729c76(cron LastRunAt 2 级残留) |
| 8 | E2E → 用户新 eval part | ✅ 关闭 |
| 9 | ARQ 真实 Redis 集成测试 | ✅ 18b3741 |
| 10 | test 数据卷隔离 + HF_CACHE_DIR 参数化 | ✅ 1904e15 |
| 11 | AppTooltip icon-only a11y(WCAG 4.1.2) | ✅ 75f65f8 |
| 12 | fix 回归测试 + ≥80% 红线 | ✅ 32fda42 |
| 13 | question_bank JSON 双写一致性 | ✅ eeccb60 |
| 14 | 隐私政策/账号删除/sub-processor 文档 | ✅ 8c549f7 |
