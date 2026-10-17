# Tech audit — 2026-08-27

**Auditor**: tech-audit skill, under user's direction
**Scope**: full project cut, D1–D16
**Repo HEAD at audit time**: `d5eeb814693619dde996809439bddaf2ebd64ca9`
**Findings source**: `.tech-audit/work/2026-08-27/findings.tsv` — all 🔴 survived the refutation pass
**Previous audit**: [tech-audit-2026-08-26.md](tech-audit-2026-08-26.md)

审计期间保留了预先存在的未跟踪 `backups/`，没有纳入审计提交；没有修改业务代码。

## Executive summary

- 🔴 **Top risk**: 用户简历、JD、聊天和音频可原样出站到第三方，运行数据库与备份中也发现明文敏感数据。
- 🟢 **Top strength**: 上一轮的 SSRF DNS pinning、非 root 镜像、schema freshness、clear-db durable audit、真实 disposable-stack smoke 和前端质量门禁均已建立或通过。
- 🟡 **Biggest gap**: 合规证据仍停留在通用文档/未填写模板，且大量失败路径与 quota/容量/静态扫描门禁尚未形成闭环。

## Status overview

| Dim | Title | Status | 🔴 | 🟡 | 🟢 |
|---|---|---:|---:|---:|---:|
| D1 | Code essentiality | ⚠️ | 0 | 1 | 0 |
| D2 | Docs integrity | ⚠️ | 0 | 2 | 0 |
| D3 | Tests as adversaries | ⚠️ | 0 | 0 | 0 |
| D4 | Security posture | ❌ | 3 | 0 | 0 |
| D5 | Multi-tenant isolation | ⚠️ | 0 | 1 | 1 |
| D6 | Operational readiness | ⚠️ | 0 | 1 | 0 |
| D7 | Dependency hygiene | ✅ | 0 | 0 | 0 |
| D8 | Build / CI / dev-loop | ⚠️ | 0 | 1 | 0 |
| D9 | Data model integrity | ⚠️ | 0 | 2 | 0 |
| D10 | Performance & cost | ⚠️ | 0 | 1 | 0 |
| D11 | Legal / compliance | ❌ | 1 | 2 | 0 |
| D12 | Admin surface consistency | ⚠️ | 0 | 1 | 0 |
| D13 | Setup replicability | ✅ | 0 | 0 | 0 |
| D14 | Correctness & robustness | ⚠️ | 0 | 4 | 0 |
| D15 | UX & interaction | ⚠️ | 0 | 3 | 0 |
| D16 | UI & design-system craft | ⚠️ | 0 | 1 | 1 |
| **Total** | | **❌** | **4** | **20** | **2** |

## Verification evidence

- `bash scripts/line_guard.sh`: passed; no production/test source file exceeded 1,500 lines or its frozen cap.
- `.venv/bin/ruff check backend/app`: passed.
- `MYPY_BASELINE=551 bash scripts/check_mypy_baseline.sh`: passed against the tracked baseline, reporting 551 existing errors in 96 files. This remains suppressed by `D8-static-type-baseline` in `.tech-audit/debt.tsv`.
- `.venv/bin/python scripts/generate_schema_docs.py --check`: passed (`schema docs are fresh`).
- `docker compose config --quiet` and `docker compose -f docker-compose.real-e2e.yml config --quiet`: passed.
- `bash -n deploy/docker-deploy.sh deploy/entrypoint.sh deploy/storage-retention.sh scripts/check.sh scripts/real_stack_smoke.sh`: passed.
- Frontend after `npm ci`: build passed; lint passed with the configured 38 warnings; `npm run type-check`, smoke test, and `npm run audit:prod` passed with zero production vulnerabilities.
- `./scripts/check.sh backend` did not reach tests: the host had about 1.3 GB free at the first check, below the deliberate 6,144 MB test-image hard floor. The current host remains near full with about 783 MB free and approximately 4.8 GB under `backend/data`; this is recorded as D6 capacity risk, not as a fabricated test failure.
- The mocked Playwright run was intentionally stopped after 30 of 425 tests: 13 failed, 16 passed, one was interrupted, and 395 did not run. The failures reproduce the existing mock/selector drift; they do not replace the open debt baseline of 174 failed / 250 passed. The debt row `D3-mocked-playwright-contract-drift` therefore remains open and suppresses a duplicate finding.
- The latest completed real disposable-stack smoke from the current remediation window passed 1 test and exercised nginx, backend, Redis, SQLite, worker and a local stub provider. It remains separate from the mocked Playwright result.
- Local `shellcheck`, `gitleaks`, `semgrep`, `trivy`, and `hadolint` executables were unavailable. CI has Gitleaks and Trivy definitions, but the Trivy and frontend dependency audit jobs are currently non-blocking; this limitation is reflected in D8.

## Red refutation pass

The four severity-4 rows were re-read against source and runtime evidence:

1. **D4 PII egress**: `backend/app/agents/submit/extract.py:45-66` inserts raw `raw_text` and images into an LLM request; `backend/app/agents/chat/nodes.py:718-770,792-850` inserts resume and memory context into the model request. No de-identification gateway, token map, or PII corpus was found. URL safety/DNS pinning protects destination selection, not the content sent there.
2. **D4 plaintext at rest**: `deploy/docker-deploy.sh:868-910` creates ordinary SQLite/RDB copies and `backend/data` currently contains a 1,036,095,488-byte database plus multiple backup families. `stat` showed the live DB and several backups as `0644`, and some backups as `0664`; no independent-key encryption step exists in the backup path.
3. **D4 plaintext API keys**: a read-only query of the current `backend/data/interview-boss.db` found 10 non-empty `user_llm_config.api_key` values, only 1 recognizable as a valid Fernet token. `backend/app/services/encryption.py:38-49` intentionally returns failed decrypt input unchanged, so plaintext values remain accepted and usable.
4. **D11 missing data-flow evidence**: `docs/compliance/deployment-matrix.template.md` is explicitly a placeholder with `<...>` fields and there is no `docs/privacy/data-flow.md`. Under the D11 method, a missing physical data-flow document is a red finding even though generic privacy and subprocessor documents exist.

## Trend vs 2026-08-26

Mechanical mapping: severity `4 = 🔴`, `3 = 🟡`, `0–2 = 🟢`.

| | This pass | Last pass | Delta |
|---|---:|---:|---:|
| 🔴 | 4 | 3 | +1 |
| 🟡 | 20 | 13 | +7 |
| 🟢 | 2 | 4 | -2 |
| Total | 26 | 20 | +6 |

The count increase is partly a reclassification/expansion after the remediation round: the former generic D11 geography gap is now backed by the still-unfilled instance matrix and missing data-flow document; the old D13 configuration finding is now recorded under D2; and source/runtime inspection exposed PII egress, plaintext secrets and failure-path risks. It is not evidence that the closed remediation work regressed.

### Closed since the previous audit

- ✅ D1: the five production modules previously above 1,500 lines are now below the redline and `line_guard` passes.
- ✅ D2: the `sj` versus `admin` seed-admin mismatch is closed; README, `.env.example` and migration agree.
- ✅ D3: a real disposable-stack smoke path exists and passed; the mocked Playwright contract drift remains a separate registered debt.
- ✅ D4: outbound DNS rebinding protection and explicit non-root runtime users are present.
- ✅ D6: nginx/OAuth healthchecks and the missing operational failure runbooks were added.
- ✅ D7: the OAuth gateway now has a committed lock and an independent CI audit path.
- ✅ D8: the line-guard regression is closed; static typing remains tracked debt rather than a new row.
- ✅ D9: generated schema documentation is fresh at migration 120.
- ✅ D12: clear-db confirmation replay protection and durable admin audit evidence are present.
- ✅ D14: JWT secret read failures now fail distinctly instead of silently rotating the key.

### Still open or reclassified

- ⚠️ `D3-mocked-playwright-contract-drift` is open in the debt register and is not re-counted here; the current interrupted sample still showed the same class of failures.
- ⚠️ `D8-static-type-baseline` is tracked in the debt register and is not re-counted here; mypy remains at 551 errors although the budget contract passes.
- ⚠️ The two low-severity public-contribution boundedness/query observations remain under D5; the new quota coverage gap is a separate yellow finding.
- ⚠️ The chart token duplication remains a low-severity D16 observation; inline business SVG duplication is a new yellow finding.
- ❌ The generic D11 provider-geography gap is still open and is escalated because no completed instance-level evidence exists.

### New or newly confirmed rows

- 🔴 D4: unmasked PII egress, plaintext database/backups, and plaintext API-key fallback.
- 🟡 D1/D2/D5/D6/D8/D9/D10/D12/D14/D15/D16: structural, capacity, quota, data-model, measurement, admin recovery, failure-path, accessibility and design-system gaps listed below.

## D1 — Code essentiality

**Status**: ⚠️ · 核心文件已回到 1,500 行红线以内，但仍有 25 个生产源码文件超过 800 行，且没有一致的职责边界/拆分说明。

- 🟡 `backend/app/db/operations.py:1`, `backend/app/agents/chat/nodes.py:1`, `backend/app/services/llm.py:1`, `backend/app/worker.py:1`, `frontend/src/components/business/ChatView.vue:1`, `PracticeMode.vue:1`, `LoginModal.vue:1` — 多个 800+ 行生产文件仍难以审计职责边界。建议按领域拆出查询、编排、渲染和外部调用，并在文件头记录保留聚合的理由。

## D2 — Docs integrity

**Status**: ⚠️ · 入口文档可用，但部署阈值与配置完整性声明已经与实现发生漂移。

- 🟡 `README.md:223` 与 `deploy/docker-deploy.sh:20-23,496-518` — README 仍写构建前 2 GB / 构建后 5 GB，脚本硬下限是 6 GB、目标是 8 GB。建议统一单一配置源。
- 🟡 `README.md:219`, `backend/.env.example:1-49`, `backend/app/core/config.py:39-137` — README 声称 `.env.example` 是完整变量列表，但运行时/调优变量仍有遗漏。建议生成配置参考或收窄表述并标注敏感性。

## D3 — Tests as adversaries

**Status**: ⚠️ · 真实栈证据已补齐，但 mocked Playwright debt 未清；本轮 backend 全量测试又被主机空间门禁阻断。

没有新增 TSV 行：`D3-mocked-playwright-contract-drift` 已登记并抑制重复 finding。当前 425-test 尝试在停止前已出现 13 failures / 16 passes；后续应完成 fixture/selector 合约收敛后再恢复完整统计。不要把真实 stub provider smoke 当作真实第三方模型验证。

## D4 — Security posture

**Status**: ❌ · 4 个红灯中的 3 个属于 D4，均通过 refutation pass。

- 🔴 `backend/app/agents/submit/extract.py:45-66`, `backend/app/agents/chat/nodes.py:718-770,792-850`, `backend/app/services/search_service.py:155-228`, `backend/app/services/embedding_service.py:199-214`, `backend/app/services/deepgram_service.py:29-69` — 用户内容可原样发送至第三方 LLM、搜索、embedding 或转写服务。影响是简历/聊天/音频的个人信息可能离开部署边界，且当前没有可验证的脱敏契约。建议所有外部内容先经过统一 PII gateway，加入本地化检测器、token 化/回填、provider retention/consent 记录与固定语料回归。
- 🔴 `deploy/docker-deploy.sh:868-910`, `backend/data/interview-boss.db`, `backend/data/interview-boss.db.bak.*`, `backend/data/backups/*.db`, `docs/runbooks/backup-restore.md:7-32` — 在线备份是普通 SQLite/RDB 文件，运行数据库和部分备份权限为 0644/0664，未见独立密钥加密。建议使用 age/gpg/restic 等方案，密钥放在备份目录之外，并将数据库/备份权限收紧到运行者可读。
- 🔴 `backend/data/interview-boss.db:user_llm_config.api_key`, `backend/app/services/encryption.py:38-49`, `backend/app/routers/profile_pkg/llm.py:194-204` — 当前工作区数据库中 10 条非空 API Key 只有 1 条是 Fernet 密文；解密失败会原样返回输入，明文 fallback 仍是有效路径。建议一次性重加密并在生产环境拒绝明文/损坏 secret。

已有的 JWT issuer/expiry/refresh rotation、MCP 账户命名空间、SSRF DNS pinning、redirect 禁用和非 root 镜像均通过复核；accepted baseline 中的弱管理员密码和历史死 key 不重新计数。

## D5 — Multi-tenant isolation

**Status**: ⚠️ · 用户级 scope 查询和跨用户负向测试存在，但 quota 没覆盖所有用户触发的 LLM 入口。

- 🟡 `backend/app/routers/profile_pkg/resume.py:114-134`, `backend/app/routers/submit.py:113-170`, `backend/app/services/submit_service.py:80-120` — 简历优化和提交流水线直接调用 LLM，没有进入 `llm_quota.check_and_record`，用户可绕过每日配额放大成本。建议把 quota reservation 下沉到统一 LLM 调用层，或覆盖所有入口并原子释放失败预留。
- 🟢 `backend/app/routers/public_contributions.py:60-71`, `backend/app/services/public_contributions.py:183-201` — `/mine` 仍先全量查询再过滤，active request 也无用户级上限；当前没有发现跨用户泄露，但这是低严重度容量/查询问题。

## D6 — Operational readiness

**Status**: ⚠️ · 服务健康检查、备份恢复 runbook 和真实栈演练已存在，但存储策略无法对当前容量风险形成闭环。

- 🟡 `deploy/storage-retention.sh:28-81,128-142`, `deploy/docker-deploy.sh:496-518,1132-1167` — 备份/数据清理只有按时间和最少文件数规则，没有 byte budget 或容量告警；当前根分区约 783 MB 可用，低于 6 GB 部署硬阈值，`check.sh backend` 因此无法开始构建测试镜像。建议增加按字节预算、分级告警、指标和独立数据卷，并演练满盘处置。

## D7 — Dependency hygiene

**Status**: ✅ · root Python/npm 生产依赖审计与 OAuth gateway lock/audit 路径已建立；Dependabot 也已配置。当前本地缺少 trivy/pip-audit 等部分工具，因此以已执行门禁和 CI 配置为证据，不声称本地扫描更强。

## D8 — Build / CI / dev-loop

**Status**: ⚠️ · 关键编译、lint、type-check 和 line guard 可运行，但高危依赖/容器扫描不能阻断主分支。

- 🟡 `.github/workflows/ci.yml:38-40,103-144`, `scripts/check.sh:291-320` — frontend `npm audit` 与三处 Trivy scan 使用 WARN-only / `exit-code: '0'`，高危结果不会使 CI 失败。建议改为 blocking，并维护明确的误报/不可修复例外清单；mypy 551 错误则继续按 `D8-static-type-baseline` 到期计划收敛。

## D9 — Data model integrity

**Status**: ⚠️ · schema 文档已更新、FK integrity 当前为 0 violations，但账户删除契约与部分用户归属表定义仍不一致。

- 🟡 `backend/app/db/migrations/coding.py:51-68`, `backend/app/db/migrations/schema_hygiene.py:599-623`, `docs/architecture/schema.md:224-226` — `coding_submissions` 的 user/problem/parent FK 在实际 fresh/current 表中为 NO ACTION，而账号删除文档写成级联删除。现状可能阻塞删除或留下个人提交。建议新增迁移明确 CASCADE/SET NULL 策略，并测试真实删除顺序。
- 🟡 `backend/app/db/migrations/llm.py:19-31`, `backend/app/db/migrations/recruitment.py:4-15`, `docs/architecture/schema.md:394-397,554-557` — `llm_usage`、`user_recruitment_pref` 等用户归属表没有 users FK/删除策略。建议补齐关系、删除策略、迁移后的 orphan 检查和 schema 文档。

## D10 — Performance & cost baseline

**Status**: ⚠️ · 性能 spec 有真实接口耗时与锁竞争数字，但没有能支撑规模决策的成本/容量模型或可运行压测。

- 🟡 `docs/superpowers/specs/2026-08-19-practice-page-performance-design.md:8-28,121-127`, `docs/superpowers/plans/2026-08-19-practice-page-performance-m1-m5.md:110-127` — 有 p95/锁竞争目标，却缺少真实 usage/cost、tier mix、容量余量和 load test。建议补充按用户/功能的 provider 成本模型、2×峰值容量验证和可重跑压测；本轮不把 mocked UI 测试当 benchmark。

## D11 — Legal / compliance

**Status**: ❌ · generic privacy/subprocessor documents exist, but instance-level data-flow evidence is absent.

- 🔴 `docs/compliance/sub-processors.md:5-57`, `docs/compliance/deployment-matrix.template.md:1-49`, missing `docs/privacy/data-flow.md` — 没有已填写的部署实例、法律实体、物理地域、跨境机制、retention/deletion evidence。建议每个部署实例复制并完成 processor/data-flow matrix，并把实际 provider、DPA/transfer basis 和删除证据链接回隐私说明。
- 🟡 `docs/compliance/privacy-policy.md:56-64`, no authenticated export route under `backend/app/routers` — 数据可携带权目前是条件式“如实例提供则可导出/否则联系运营者”，没有明确范围、身份核验、SLA、交付记录或测试。建议实现认证导出任务，或把人工流程补成可演练的控制。
- 🟡 missing `docs/legal/dpia*` and `docs/privacy/dpia*` — 产品处理简历、聊天和自动化 AI 评估，但没有 DPIA。建议记录处理目的、风险、人工复核、缓解措施和复审日期。

`.tech-audit/accepted.tsv` 的“人工账号删除”仍是 owner-accepted 项，本轮没有把它重复计数；但它不能替代 D11 的 instance-specific data-flow/DPIA 证据。

## D12 — Admin surface consistency

**Status**: ⚠️ · 管理路由授权统一，clear-db durable audit 已修复，但评测详情初始失败不可直接恢复。

- 🟡 `frontend/src/views/admin/EvaluationRunView.vue:80-92,322-325` — 首次加载失败只展示错误文本，没有刷新/重试按钮；已有的 SSE 重连与 terminal retry 不覆盖初始 fetch。建议在 `error && !run` 状态提供明确重试入口。

## D13 — Setup replicability

**Status**: ✅ · fresh-clone 入口、`npm ci`、Compose config、占位 env bootstrap、部署脚本和 real-stack smoke 均可复核；配置参考完整性问题已在 D2 计数。

## D14 — Correctness & robustness

**Status**: ⚠️ · 主要 happy path 有测试，但多个异常路径会把失败降级为成功/空状态或错误归属。

- 🟡 `backend/app/services/resume_service.py:155-174`, `backend/app/services/chat_memory_service.py:200-213` — 删除简历先提交主表，再单独停用简历记忆且吞掉异常；失败时已删除简历的 PII 可能继续被 agent 召回。建议单事务完成，或使用 durable retry/outbox，并做失败注入测试。
- 🟡 `backend/app/services/submit_service.py:124-150`, `backend/app/agents/batch_generate/nodes.py:128-156` — 答案生成失败后的失败标记写库异常被吞掉，任务可能没有结果也没有可靠 retry/dead-letter 信号。建议持久化二次失败、告警和重试状态。
- 🟡 `backend/app/agents/submit/persist_personal.py:51-75` — `original_questions` JSON 损坏时静默降级为当前题，可能丢去重依据并产生重复题。建议记录数据损坏并阻止不安全写入或进入修复队列。
- 🟡 `backend/app/db/queries.py:15-28,31-68`, `backend/app/routers/submit.py:118-129,263-274` — 岗位查询异常时回退默认岗位，写入可能产生错误岗位归属。建议区分未配置与数据库不可用，后者应失败并可重试。

## D15 — UX & interaction

**Status**: ⚠️ · 主流程和 reduced-motion 处理存在，但恢复性与表单可访问性仍有明显缺口。

- 🟡 `frontend/src/views/ResumeView.vue:44-72,190-194` — 简历、优化结果和岗位列表加载失败被当成空状态，用户无法区分无数据与请求失败。建议补 loading/error/retry 状态。
- 🟡 `frontend/src/components/business/SettingsProfile.vue:39-67`, `SettingsAIConfig.vue:240-317`, `SettingsSecurity.vue:182-232` — 多处 Label 没有 `for`，Input 没有对应 `id`，辅助技术无法稳定建立字段关系。建议补稳定 id/for，并加入 axe/DOM contract 检查。
- 🟡 `frontend/src/components/business/PracticeMode.vue:141,188,453,480`, `ModelSelector.vue:10`, `SettingsMCP.vue:249,338` — 交互提示仍使用 native `title`，绕过统一 AppTooltip 的键盘/触摸交互。建议统一组件化提示并保留可聚焦语义。

## D16 — UI & design-system craft

**Status**: ⚠️ · token 基础存在且 reduced-motion/主题路径可用，但业务图标和图表色板仍在绕过共享系统。

- 🟡 `frontend/src/components/business/LoginModal.vue:75-87,173-185,260-272,344-356,470-482,569-581,656-668,740-752`, `QuestionCard.vue:24-233`, `PracticePanel.vue:20-176`, `NewChatModal.vue:23-99`, `UserMenu.vue:18-77` — 业务组件重复内联 SVG 图标，没有消费现有 Lucide 系统，容易造成视觉、主题和维护漂移。建议替换通用图标，保留确有必要的自定义/图表 SVG，并加源检查。
- 🟢 `PracticeStarChart.vue:47-103`, `PracticeQuadChart.vue:33-123`, `frontend/src/utils/chartTokens.js:1-47` — porcelain 明暗色值仍重复，属于低严重度主题漂移风险，延续记录而非本轮阻断。

## Triage — proposed follow-up milestones

Milestones were generated with the repository helper using `--prefix M --start 4`; the helper produced the red-item IDs below and grouped the yellow items by dimension.

| Milestone | Scope | Effort |
|---|---|---:|
| **M-4** | 完成实例级 compliance data-flow / processor matrix、地域、DPA/transfer、retention/deletion evidence | M |
| **M-5** | 建立 PII egress gateway，覆盖 LLM/search/embedding/Deepgram，并加入固定语料回归 | L |
| **M-6** | 加密数据库/备份、限制文件权限并完成独立密钥轮换/恢复演练 | M |
| **M-7** | 完成运行库 API key re-encryption，生产拒绝 plaintext/corrupt fallback | L |
| AUDIT-D1-followup | 800+ 行生产模块职责边界与拆分计划 | M |
| AUDIT-D2-followup | README 阈值与配置参考生成/校准 | S |
| AUDIT-D5-followup | quota 覆盖、SQL scope 下推和 active request 限制 | M |
| AUDIT-D6-followup | byte budget、容量告警、独立数据卷和满盘演练 | M |
| AUDIT-D8-followup | blocking vulnerability scans；按债务计划收敛 mypy | S/L |
| AUDIT-D9-followup | 用户归属表 FK/删除策略与账号删除回归 | M |
| AUDIT-D10-followup | cost model、容量假设、2×压测 | M |
| AUDIT-D11-followup | export/DPIA 补全 | M |
| AUDIT-D12-followup | EvaluationRun 初始失败重试 | S |
| AUDIT-D14-followup | 删除、失败标记、损坏 JSON、岗位 fallback 的失败闭环 | M |
| AUDIT-D15-followup | error/retry、label association、统一 tooltip | M |
| AUDIT-D16-followup | Lucide 图标迁移与 chart token 收敛 | M |

## Conclusion

当前项目的基础工程护栏比 2026-08-26 明显更完整：核心镜像运行用户、外部 URL 解析、schema 文档、clear-db 审计和真实栈 smoke 都有可复核证据。但从整体项目视角仍不能给出通过结论：D4 的 PII/secret 保护和 D11 的部署级合规证据是 release-blocking red；D14 的失败闭环、D6 的容量治理和 D3/D8 的测试/类型债务也需要在下一轮回归前收口。
