# Audit 回顾与分类处置 — 2026-08-24

> 覆盖 `.tech-audit/work/` 全部 11 轮审计（2025-01-01 ~ 2026-08-20）共 409 条发现（去重约 300 条），
> 逐簇读码验证后的最终对账。当日两项 owner 决策已录入 `accepted.tsv` 基线，后续审计自动过滤。

## Owner 决策（2026-08-24）

| 决策 | 影响 |
|---|---|
| SiliconFlow 老 key 已在服务商侧轮换 | git 历史中的 key（sk-hkaopkq...，8 提交可达）为死凭据，**关闭**该项；不做 filter-repo |
| 不限制 ADMIN_PASSWORD 长度 | 关闭对应 🟡；缓解在位：登录失败 5 次锁 15 分钟 + IP 5/min 限速 |

## 一、已解决（✅ 读码验证，非仅凭 FIXED 标记）

| 发现 | 来源 | 解决证据 |
|---|---|---|
| 🔴 CI 完全缺失 / 缺 Trivy 镜像扫描 | 08-13, 08-15-r3 | `.github/workflows/ci.yml` 存在且含 trivy |
| 🔴 JWT_SECRET 公开占位可伪造 token | 08-13 | example 注释化 + 留空自动生成强随机值 |
| 🔴 OAUTH_SECRET_KEY 公开兜底 | 08-13 | compose 无兜底；`oauth-gateway/auth.py` fail-closed（<32 字符拒启） |
| 🔴 users.email TOCTOU 并发重复注册 | 08-13 | `idx_users_email_unique` 部分唯一索引（migration 079/085） |
| 🔴 实验脚本硬编码 API key（工作树） | 08-13 | 工作树 0 命中（历史残留见 accepted.tsv） |
| 🔴 bank_build 未导入 match_new_questions 必 NameError | 08-15 | `bank_build.py:8` import 在位 |
| 🔴 check.sh 调用未定义 run_static_* | 08-15 | 函数已定义并在 all 分支调用（ruff/eslint WARN 执行） |
| 🔴 build_master_bank_task 私有面经公开化 | 08-15-r3 | worker 加 `owner_id IS NULL AND status='approved'` 过滤 |
| 🔴 eval retry-failed job-id 复用静默丢失 | 08-18-eval | retry 传 `eval-run-{id}-{uuid8}` 唯一 id；None 不标 queued |
| 🔴×5 评测前端组件未导入渲染崩溃 | 08-19 | Experiments/Experiment/Run/Reviews 四视图 import 齐全 |
| 🔴 URL 连接私有明细泄漏进公共查询/重建 | 08-20 | worker/data 改 `interview_id` join；URL 仅 legacy fallback 且带 owner scope；migration 109 隔离+quarantine |
| 🔴 聚类写库 owner_id 硬编码 NULL | 08-20 | `insert_new_clusters(owner_id)` 参数化 + 回归测试钉住 |
| 🟡 python-jose/passlib 死依赖 CVE 链（连续 4 轮） | 08-13~17 | `7fc0cf60` 迁移 PyJWT/bcrypt；uvicorn 解钉 |
| 🟡 用户 LLM/search key 明文落库（连续 3 轮） | 08-13~15-r3 | `encryption.py` Fernet 接线 profile_pkg/{llm,search} |
| 🟡 verify_code 无 per-email 锁定可爆破 | 08-13 | LOCKOUT_THRESHOLD(5) 作废机制 |
| 🟡 Redis/ARQ 关键路径纯 mock | 08-13 | `RUN_REAL_REDIS=1` 真实集成测试（默认 skip） |
| 🟡 test 容器读写生产 data 卷 | 08-13 | 独立命名卷 `test-data` |
| 🟡 HF 缓存硬编码路径挂空 root | 08-13 | `${HF_CACHE_DIR:-...}` 参数化 |
| 🟡 worker/eval-worker 无 healthcheck、eval 无消费者 | 08-13, 08-15-r3 | 5 个 healthcheck + eval-worker 服务 + launcher 脚本 |
| 🟡 生产库 178 行 FK 违规（连续 2 轮） | 08-15, 08-17 | 生产库实测 foreign_key_check = 0 |
| 🟡 chat_service 2395 行 / nodes.py 2028 行 | 08-13 | 109 行 facade / 1409 行 |
| 🟡 eslint 不解析 TS 组件空转 | 08-15 | flat config + @typescript-eslint/parser |
| 🟡 sub-processor/隐私文档缺失（PIPL） | 08-13 | docs/compliance/{privacy-policy,sub-processors,account-deletion}.md |
| 结构清理（本轮）：lineguard FAIL、schema.db 入库、死 requirements.txt、根 main.py、oauth-gateway 误报 | 08-24 | commits b374d5d4 / ff78a42f |

## 二、真正需要修（按优先级）—— 2026-08-24 修复轮结果

### P1 — 门禁硬化 ✅ 已落地（commits 4a8595a2 / 7c196e38）
1. ~~secret/SAST 扫描缺位~~ → **复核发现 CI 早已接入**：gitleaks-action（全历史，阻断）+ Trivy 镜像/fs 扫描在 ci.yml；check.sh 本地亦有阻断级 `run_secret_scan`（check_secrets.py）。原发现系审计记录过时。
2. ~~CI 静态检查 || true~~ → ruff 基线清零（8 处修复）后 `check.sh` 升级 blocking；ci.yml 前端 audit 步骤去掉 `|| true` 改 continue-on-error（失败可见但不拦 job）。
3. ~~npm audit 被镜像吞~~ → 复核发现 `audit:prod` 脚本早已固定官方 registry（原发现系手动跑法有误）；CI 步骤改为直跑该脚本。

### P2 — 依赖升级 ✅ 已落地（b13d7e76 / 873e88ac）
4. ~~Vite ^4.4.5 滞后~~ → **vite ^8.2.2 + plugin-vue ^6**（rolldown 函数式 manualChunks）；shadcn-vue 移 devDeps；dompurify ^3.4.14；删除死依赖 puppeteer-core。npm 生产 audit **14 条(7 high) → 0**。Dependabot 已配置（npm/pip/actions）。
5. ~~pip-audit 复测~~ → click/aiohttp/cryptography 升级 + mcp 钉 1.29（2.0 实测移除 FastMCP，加 `<2` 上界）。后端 pip-audit **9 条 → 0**。

### P3 — 结构与运维债务（部分落地）
6. **god-file 拆分** ⏸ 未动（llm.py/admin_evaluation/worker/ChatView.vue）：行数已冻结只许减；拆分需独立会话按 Stage B 流程做，避免与门禁变更混批。
7. ~~line_guard 不扫 tests~~ ✅ 已纳入扫描，存量 test_react_loop.py 3782 / test_chat.py 2038 冻结（29c14aae）。
8. ~~备份无恢复演练~~ ✅ 新增 `restore --verify` 演练命令 + runbook（RPO/RTO），首次演练 PASS（29fe675e）。
9. **questions_pkg 胖路由** ⏸ 未动（bulk/mutations 抽 service 属核心写路径重构，需专项 TDD 会话）。
10. **真实全栈 E2E 进门禁** ⏸ 未动（成本最高，排后续里程碑）。
11. **回归测试比例红线** ⏸ 过程指标，下轮审计重测。

> 附带修复：构建机 BuildKit builder 缺失 /etc/buildkitd.toml 导致冷缓存后拉 dockerfile frontend 走被污染 DNS——已补配置并重建 builder（对齐 daemon.json mirrors）。

## 三、过期 / 接受不管（含理由）

| 项 | 处置 |
|---|---|
| SiliconFlow key 在 git 历史 | ✅ 已轮换=死凭据，accepted.tsv 登记，2027-02 复查无复用 |
| ADMIN_PASSWORD 长度 | ✅ owner 决策不限制，缓解在位，accepted.tsv 登记 |
| 账号删除仅人工流程 | ✅ 当前规模可辩护（文档+入口齐备），用户增长后再立自助端点 |
| /mine 全表扫描、公共化申请数上限 | 🟢 低危接受（今日安全 pass 结论） |
| oauth-gateway「未入库」 | 今日审计误报，实际早已跟踪（7fc0cf60），撤销 |

## 四、移交事项

- 另一会话 WIP（public_contributions 已部分入库 = 1979959e）尚有 28 个预存测试失败（taxonomy/answers 所有权域），须在其主提交前落定。
- 下次审计入口：`.tech-audit/work/2026-08-24/findings.tsv`（当日 D4/D5 pass）+ 本文件。
