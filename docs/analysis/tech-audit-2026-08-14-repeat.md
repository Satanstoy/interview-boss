# Tech audit — 2026-08-14 (repeat pass)

**Auditor**: tech-audit skill, under user's direction
**Scope**: full (delta pass on top of 2026-08-13 / 2026-08-14 main audit)
**Repo HEAD at audit time**: f8e1f41
**Findings source**: `.tech-audit/work/2026-08-14/findings.tsv` (113 rows)

---

## Executive summary

- 🔴 **Top risk**: 无真实全栈 E2E(用户已计划以独立 eval part 解决)
- 🟢 **Top strength**: 结构债清偿显著——5 个 god-file 全部 <1500 行;静态检查(ruff/mypy/eslint)与 1500 行 blocking 门禁已接入 check.sh;并行修复线同时落地了登录限速中间件、洞察 owner 隔离、MCP token 内存化等 4 处安全修复
- 🟡 **Biggest gap**: 并发/数据一致性组(双写、email 500、验证码竞态)与 CI fresh-clone 必红仍未动,是全仓最集中的剩余风险

---

## 本轮做什么(Repeat-audit delta)

1. **机械基线**: 主 findings.tsv 上一轮已对齐(28 FIXED; open 1×🔴 + 19🟡 + 47🟢 + 9 信息)
2. **新发现源**: 环境并行审计产出的 `.tech-audit/work/2026-08-14/interaction/findings.tsv`(10 条)——逐条读代码路径验证
3. **新变化核查**: god-file 拆分产物(facade/子模块语法、循环导入)、line_guard/eslint 接线、未提交并行修复(pyproject per-file-ignores 标准化、migration 084 CASE WHEN 强化 + 回归测试)

## Interaction findings 验证结果(10 条)

| 状态 | 发现 |
|---|---|
| ✅ FIXED(4) | D4 登录限速(request_ip 可信代理 + asgi GlobalRateLimitMiddleware 已存在); D5 洞察 owner 过滤(_scope_condition + JOIN 已存在); D4 MCP token sessionStorage(已改内存持有); D4 login-form CSRF(跨源拒绝已存在) |
| 🟢 仍 open(5) | D4 mcp_api_key URL query 参数(app.py:127); D1 上传全量 read 再校验(chat.py:695/resume.py:31); D4 refresh 轮转 check-then-delete 非原子(auth.py:296/305); D4 refresh cookie secure 信任 x-forwarded-proto(auth.py:238); D1 outbound_url DNS-rebinding TOCTOU(低危) |

## 状态概览(全仓)

| Dim | 状态 | 备注 |
|---|---|---|
| D1 Code essentiality | ✅ 改善 | 5 god-file <1500; 新增 11 个聚焦子模块; 残留 2 条 1 级(上传读全量、batch_v2 死模块) |
| D2 Docs integrity | ✅ 改善 | Python 3.12 / include_router 22 / composables 22 已修; services/agents CLAUDE.md 已同步拆分 |
| D3 Tests as adversaries | ⚠️ | 🔴 无真实 E2E; Redis 纯 mock; check.sh 全量未纳入; 测试硬编码 key |
| D4 Security posture | ⚠️ | interaction 4 条已修; 残留 mcp_api_key query / refresh cookie secure / 验证码无锁定 / LLM 无配额 |
| D5 Multi-tenant | ✅ | 洞察 owner 隔离已修; LLM per-user 配额仍缺(D3→归 D5 配额) |
| D6 Operational | ⚠️ | 无 restore 演练; worker 无 healthcheck; cron 无 LastRunAt |
| D8 CI/dev-loop | ⚠️ | fresh-clone 必红; gitleaks 全史必红; check.sh 子集 |
| D9 Data model | ⚠️ | 双写权威源; JSON 双写漂移; test 容器挂生产 data 卷 |
| D14 Correctness | ⚠️ | email 500 / verify_code 竞态 / refresh 轮转非原子 |

---

## 决策清单(按优先级,供用户选择)

| 优先 | 问题 | 类型 |
|---|---|---|
| 1 | 并发/数据正确性组: 双写收敛、email 409、verify_code 原子化、复习幂等键(spec M31/M32) | 🟡 |
| 2 | CI fresh-clone 跑绿 + gitleaks allowlist | 🟡 |
| 3 | 测试硬编码 key 字面量清理(2 文件) | 🟡 |
| 4 | check.sh 纳入 backend 全量 pytest(先收敛 FTS/零散失败) | 🟡 |
| 5 | LLM per-user 配额(spec M33) | 🟡 |
| 6 | interaction 残留: mcp_api_key query / 上传校验 / refresh 轮转原子化 | 🟢/1 |
| 7 | 运维: restore 命令、worker healthcheck、cron LastRunAt | 🟡 |
| 8 | E2E → 用户新 eval part | 🔴 |
