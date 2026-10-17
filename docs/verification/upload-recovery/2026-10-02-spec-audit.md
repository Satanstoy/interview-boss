# ADR 与上传恢复 spec 全量对账

**审计日期：** 2026-10-02
**最新复核：** 2026-10-03；实现提交 `513af96e` 已部署。下表是本次复核状态，初审和历史验证账仍保留作时间线证据。
**初始审计基线：** `1cb3915410c6243b2834d0acc1ed79e4e25b02cb`，分支 `codex/frontend-ui-hierarchy-cleanup`
**修复提交：** `3a2020b6`（管理员 scope 与逐题 resolution）；审计记录另有提交。
**部署镜像：** backend/worker `sha256:68de9d343cfb4b4444ea4d13b638a03b267f1b9b0384a745f888134bb2385ca7`；nginx 与 OAuth gateway 已在本次 update 重建并健康运行。
**范围：** 已接受 ADR-0048；上传恢复 Draft 的 AC-001～AC-029；管理员、个人用户、公共题库和个人题库边界。
**产品代码改动：** 已修复 4 条管理员跨 scope 入口和管理员分析状态元数据范围；补全直接命中既有公共 canonical 时的逐题 resolve checkpoint。

## 结论

**ADR-0048 已确认的管理员越权项已关闭；上传恢复矩阵已由新测试重新分级，但仍有多项部分对齐。** 管理员重分析 SSE、通用回收站、个人题库重建、旧 retry 和分析状态元数据范围均已改为遵守 scope，并通过新红绿测试。AC-029 现在覆盖真实隔离栈的既有公共 canonical 命中、管理员审核、逐题失败恢复及公共字段保持不变；逐题 `resolve` checkpoint 也能追踪该直接命中。

上传恢复文档自身明确标注为 **Draft / 待设计审阅**，所以 AC 通过与否不代表 Draft 已成为获批产品决策。生产更新和 worker restart 已完成，所有服务 healthy，站点与 `/api/health` 为 200，backend 与 worker 镜像一致；唯一最新备份 `quick_check=ok`。隔离 Compose + SQLite + Redis/ARQ worker + Playwright 本轮通过通用 smoke、AC-021 丢响应恢复、AC-028 个人停启恢复、AC-029 公共分享/审核/失败项重试共 **4 个浏览器场景**。生产数据库没有被行为验收脚本写入。普通公共/个人 rootless 项终态失败后的应用级 retry 是否需要增加仍待产品选择；默认 LLM 请求走本地 stub，外部已过期模型不在本轮验证范围。

## 规范层级与审计口径

| 文件 | 状态 | 本次如何使用 |
|---|---|---|
| [ADR-0048](../../adr/0048-public-personal-question-bank-boundaries.md) | Accepted，2026-08-20 | 判定公共/个人归属、管理员可见性、显式公共化和写入 scope 的已接受行为。 |
| [上传恢复 README](../../superpowers/specs/2026-09-29-upload-recovery/README.md) 与 contracts/acceptance | Draft / 待设计审阅 | 用 AC-001～029 盘点拟议行为、测试覆盖和未闭环验收；不把 Draft 说成已批准。 |
| [2026-10-01 reconciliation-v2](../../../.tech-audit/work/2026-10-01/reconciliation-v2.tsv) | 历史修复台账 | 其列为 FIXED 的既有差异只说明那些差异已修，不推导整份 ADR/AC 已通过。 |

“代码有实现”“某个服务/路由测试通过”“活体部署栈通过”分别记账。除 AC-028 行明确说明外，本表中的回归测试均不是生产部署后测试。Draft 要求使用隔离数据库、Redis namespace 和本地模型 stub；真实模型供应商/费用不属于验收前提。

## ADR-0048 对账

| 已接受决策 | 状态 | 证据与缺口 |
|---|---|---|
| 私人上传命中公共 canonical 时只关联公共规范题，保留私有 occurrence/resolution，不改公共来源和频次 | **通过（隔离全栈）** | AC-029 disposable browser/worker trace 命中预置公共题，私有 resolution 指向原 canonical 且正文/来源/频次不变；同题有逐题 resolve checkpoint。 |
| 未命中公共题时只写当前用户个人池；公共池只读 | **后端回归覆盖** | 本轮 `test_public_personal_scope_contract.py` 与 `test_question_resolutions.py` 所在定向套件通过（见验证账）。这证明受测业务入口的 scope，不覆盖所有旧管理员入口。 |
| 个人题升级必须走不可变申请快照、审核、显式发布 | **回归覆盖** | 管理员的个人 rebuild 不再把私题并入公共规范题或删除私有行；反向测试断言公共来源、频次和 canonical 不变。 |
| 管理员默认不得查看其他用户私题；例外必须显式授权并审计 | **已对齐（本轮回归）** | 新测试覆盖私有面经 reprocess/SSE、通用回收站及 tagged 详情、分析状态元数据、旧 retry 和管理员自己的私有 rebuild；公共已发布面经仍可按允许路径处理。 |
| 公共待审内容只对提交者/审核人员可见；审核通过后才能进入公共检索和处理 | **通过（隔离全栈）** | AC-029 由浏览器提交 share，普通公共读取在审核前不可见；管理员审核后经真实 worker 发布，包含失败 item 的停启与 retry。 |
| 个人阶段用提交者模型配置，审核后的公共阶段用全局配置 | **stub 回归覆盖** | 本轮凭据/预检/账本套件通过，包含 scope 严格解析与禁止跨 scope fallback；不连接真实供应商（符合 Draft 的隔离验收原则）。 |
| 重分析、恢复、清理基于实体/occurrence ID；发布记录保留来源和审计 | **回归覆盖** | 新 root/import 链路有 owner、attempt、generation 和 resolution 测试；legacy retry 现要求原 owner，管理员跨 owner 请求被拒绝，actor 使用当前认证用户。 |
| 面经与 JD 共用申请/审核外壳、进入不同领域流水线 | **部分** | 面经公共分享审核链已在 AC-029 隔离全栈验证；JD legacy compatibility 有回归，但 JD 兼容 retry 后的完整审批链未走 real-stack。 |

## AC-001～AC-029 验收矩阵

状态定义：**通过（回归）**表示受测契约有自动化断言且相关测试结果通过；**部分**表示有部分实现/测试但至少一个必须场景未证实；**未对齐**表示确认违反契约；**未运行**表示本次没有足够执行证据。通过（回归）不等于生产部署验收。

| AC | 状态 | 本次核对的证据 / 未闭环范围 |
|---|---|---|
| 001 结果定位 | **部分** | AC-028 实栈证明个人结果可按 location 打开；AC-029 栈证明审核和发布后的题目可读，但没有覆盖审核后从用户任务卡片直接定位到公共结果。 |
| 002 真实分页 | **部分** | 后端分页/授权测试与 121 条边界测试通过；浏览器覆盖换页、排序、岗位过滤、页大小和页码回退，但页面测试使用 mock API，未做浏览器到真实分页 API 的一体活验。旧审计所称“本地分页”已过时。 |
| 003 四格提交策略 | **通过（回归）** | policy/submit 回归覆盖个人/分享入口；反向测试锁定管理员个人 rebuild 不会隐式发布，旧 retry 不接受管理员跨 owner 重放。 |
| 004 费用与配置 | **通过（回归）** | credential/preflight/账本测试覆盖 scope、fallback 拒绝、指纹和调用记录；HTTP provider 使用 stub/MockTransport，不验证外部模型可用性或质量。 |
| 005 私人引用与归属 | **通过（隔离全栈）** | AC-029 真实栈中私人 resolution 命中预置公共 canonical；公共题面、来源和频次保持不变，逐题 trace 指向同一 canonical。 |
| 006 判断失败不等于新题 | **通过（回归）** | `test_upload_matching_outcomes.py` 区分认证/超时/结构错误/跨 scope ID 与 no-match，失败不创建 canonical。 |
| 007 残余队列被推进 | **部分** | 独立 SQLite/Redis/ARQ 测试、六种 public/contribution/personal continuation 和部署栈恢复均通过；普通 public/personal rootless 项达到终态 failed 后缺少应用级 retry 入口，是否新增待用户决定。 |
| 008 故障点恢复 | **通过（隔离全栈）** | 同一 SQLite 文件跨连接 checkpoint、未提交事务回滚、已提交数据恢复、真实 worker 停启后续跑均有断言；部署栈 AC-028/029 均通过。 |
| 009 并发输入不串单 | **部分** | 两个独立 SQLite 连接验证同秒不同 payload 的 root/attempt 隔离；没有在浏览器+多个真实 worker 间交错处理多个用户输入。 |
| 010 连接恢复 | **部分** | 部署栈 AC-021 验证 POST 响应丢失后相同幂等键恢复同一 import；EOF、乱序 revision、换账号的 UI 收敛仍由 mock/API 回归证明。 |
| 011 真实完成 | **部分** | 状态投影及隔离栈上传/贡献流程确认未终结子工作不会报 completed；多题答案 8/2 部分失败恢复仍未在真实模型/provider 栈活验。 |
| 012 旧 worker 不可写 | **通过（回归）** | `test_upload_leases.py` 覆盖 generation、过期 lease、canonical/resolution/答案提交 fencing。 |
| 013 错误与重试预算 | **部分** | MockTransport 实际 HTTP 请求锁定 401/429/结构修复共享预算，日志脱敏有回归；真实供应商和所有 live SSE/旧消费者组合未验证。 |
| 014 公开等于审核投影 | **通过（隔离全栈）** | AC-029 真实管理员浏览器审核投影，脱敏、排除、修订和批准由实际 API/worker/SQLite trace 验证；待审内容在普通公共读取中不可见。 |
| 015 失败子项恢复 | **通过（隔离全栈）** | 公共 contribution 单题注错、管理员 retry、worker restart 后只恢复失败 ordinal；其他成功 item 身份不变且完成前不发布。 |
| 016 追加贡献保持一致 | **部分** | service regression 覆盖已发布/未发布条目与失败恢复；真实栈验证一份 contribution 的逐题行为，没有验证第二份追加 contribution 后的累积列表。 |
| 017 跨代与并发恢复 | **部分** | `test_upload_retry_family.py` 与 UI mock 覆盖 owner、单活跃 attempt、并发恢复及 `created_attempt=false` 文案；没有多浏览器/worker 实时并发。 |
| 018 私人正文隔离 | **通过（隔离全栈）** | AC-029 浏览器以 U2 访问 U1 root、原稿、by-key 均被拒；管理员可审快照但不能读取 U1 其他私人 root。 |
| 019 不静默漏题 | **通过（隔离全栈）** | AC-029 trace 核对 5 个输入 ordinal、1 个明确排除、4 个最终公开条目；单题失败恢复后成功条目未重复或丢失。 |
| 020 审批与撤回互斥 | **通过（回归）** | 双连接 approve/withdraw 竞争、重复动作和事务失败回滚有测试。 |
| 021 幂等键与响应丢失 | **通过（隔离全栈）** | 部署候选镜像浏览器真实 POST 提交后丢弃响应；同一 idempotency key 恢复到同一个 import ID。生产只做健康探针。 |
| 022 文件校验与草稿保留 | **部分** | 400/413/不支持 MIME 的 UI 草稿保留和无幽灵 root 有后端/mock 浏览器回归；尚未在真实 API 浏览器旅程跑坏文件/超限恢复。 |
| 023 迁移与回填幂等 | **通过（隔离回归，既有证据）** | 历史隔离迁移回归记录通过；本轮未重跑全部 migration suite，也没有在生产 apply 或检查历史歧义数据。 |
| 024 JD 与旧数据兼容 | **部分** | JD 不进入面经题队列、旧 approved 数据/legacy job 的回归通过；JD 兼容 retry 后完整审批流程没有 real-stack 覆盖。 |
| 025 源删除/岗位退休/分类升级 | **通过（回归）** | worker 入队后复核 source 删除、岗位退休、pipeline 版本和分类指纹；四种变化的反例均阻止过期工作进入 graph 并保留已完成 checkpoint。 |
| 026 历史与保留清理 | **通过（回归）** | 完成历史 payload 清理、legacy 兼容及严格 90 天边界有 SQLite/服务测试；旧任务结果 UI 降级通过 mock browser。 |
| 027 可访问性 | **通过（回归）** | 375/1440 两种宽度覆盖排队、审核、needs-action、partial-failed、键盘焦点和 aria 状态播报；浏览器 API 使用 mock。 |
| 028 隔离全栈 | **通过（隔离全栈）** | disposable 栈通用 smoke、AC-028 个人上传停启恢复、AC-029 公共分享恢复全绿；本轮 real-stack runner 退出码 0，生产不写验收数据。 |
| 029 逐题数据流 | **通过（隔离全栈）** | 公共 share→管理员审核/脱敏→公共 worker 失败→worker 停启→管理员 retry 全链真实 API/SQLite/Redis/ARQ/browser 通过；最终 4 项发布、排除 1 项，canonical 未变。LLM provider 为本地 stub。 |
## 本轮确认缺口与建议测试

| 未完全闭环 AC | 当前差异 | 下一条红绿测试 |
|---|---|---|
| 001、002 | 结果定位的公共目标和分页的 UI→真实 API 联动尚未在部署栈覆盖；AC-002 旧“本地分页”结论已过时 | 在 disposable stack 接真实分页 API；从个人任务卡定位到公共发布结果；使用 121 条数据断言请求参数、授权、页码、排序和目标定位。 |
| 007 | public/personal rootless 终态失败会停止 poison-row 自动重派并标 failed；普通队列没有应用级 retry 入口，是否需要待产品选择 | 若确认需要入口，先锁 owner/admin 权限和审计契约，再测授权失败、重复点击、budget reset/继承和只重试失败项；现有部署不应被称为具备用户自助 retry。 |
| 009、010、017 | 多用户 live worker 交错、真实 EOF/换账号/并发 retry 未由 browser+API 一体栈覆盖 | 两浏览器、两用户和两个 worker 并发提交/恢复；断言 root、attempt、SSE revision 与题目归属不串。 |
| 011、013 | 多题答案 partial-failed 的 live SSE/页面生命周期仍未跑；真实 provider 已过期，本轮只能模拟 provider 状态 | 用本地 stub 对 8/10 答案成功并确定性失败 2 项，检查真实 ARQ、SSE、retry 和日志预算；外部模型可用性须在有效凭据恢复后单独验证。 |
| 016、024 | 第二份追加 contribution 的累计投影、JD 兼容 retry 后审批链尚无 live stack 证据 | 在隔离栈追加第二份贡献并运行 legacy JD retry→admin review→发布；断言已有 canonical 与历史记录不重复/不丢。 |
| 022 | 400/413/不支持 MIME 的草稿保留目前是后端和 mock UI 证据 | 用真实 API/浏览器上传坏 MIME 和超限文件，验证 read 前拒绝、草稿保留、修正后相同 key 安全重提。 |

AC-028、AC-029 和 AC-021 的指定隔离浏览器旅程已通过；它们的 LLM 调用由本地 stub 应答，不能据此推断真实模型可用或输出质量合格。
## 初审验证账（修复前基线，作为历史证据保留）

| 类型 | 命令/场景 | 结果 | 证明边界 |
|---|---|---|---|
| 后端 scope/权限/撤回/重试/租约 | `cd backend && ALLOW_RFC2544_BENCHMARK_RANGE=1 PYTHONPATH=. ../.venv/bin/pytest -q tests/pipeline/test_public_personal_scope_contract.py tests/services/test_question_resolutions.py tests/services/test_public_contribution_transitions.py tests/services/test_admin_public_contribution_retry.py tests/services/test_upload_leases.py tests/security/test_upload_task_privacy.py` | **59 passed**, 1 既有 Pydantic warning | 这些具体后端回归通过；不覆盖上表列出的旧管理员路由。 |
| 后端 worker/trace/凭据/状态 | `cd backend && ALLOW_RFC2544_BENCHMARK_RANGE=1 PYTHONPATH=. ../.venv/bin/pytest -q tests/integration/test_upload_question_data_flow_worker.py tests/pipeline/test_upload_stage_recovery.py tests/pipeline/test_upload_credential_preflight.py tests/services/test_upload_credentials.py tests/services/test_upload_status_projection.py` | **46 passed**, 1 既有 Pydantic warning | AC-029 是 HTTP + worker 函数链路；Redis dispatcher 被 stub。 |
| 行为反例探针 | `tests/security/test_authz_unification.py::TestBuildPersonalMerge::test_admin_merge_still_merges_into_public` 与 `tests/pipeline/test_upload_import_retry.py::test_non_owner_and_admin_retry_are_404` | **2 passed** | 第一项通过代表当前测试明确期待错误的隐式管理员发布；第二项只证明新 root retry 拒绝管理员，不能推出 legacy retry 安全。 |
| AC-028 活体 | `docker compose --project-name audit-ac028-… -f docker-compose.real-e2e.yml up --no-build -d --wait`；worker 停止后由 runner 提供 `AC028_WORKER_RESTART_SIGNAL`、`AC028_BROWSER_RESULT_SCREENSHOT`、`AC028_BROWSER_RESULT_TRACE`，运行 `cd frontend && REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL=http://127.0.0.1:18082 ./node_modules/.bin/playwright test tests/e2e/upload-recovery-real-stack.spec.js --timeout 210000`；浏览器在 queued 后等待 runner 重启同一 worker，再打开结果 | **1 passed in 26.9s**；`import_id=beb5b13b-8abb-47f3-8831-eb8f788364e5`，最终 `completed`，面经 ID 1，指定题干可见 | 本地隔离栈，不是生产部署；只覆盖 personal upload，不含 public share/review。结果 trace/screenshot 在 `/tmp/audit-ac028-303259-1790951373.{json,png}`，临时栈已清理。 |
| 完整 real-stack runner | `REAL_STACK_REUSE_BUILT_IMAGES=1 ./scripts/real_stack_smoke.sh` | **失败，退出于 AC-028 前置 smoke**：Playwright 在 `real-stack-smoke.spec.js:30` 读取 response body 报 `Network.getResponseBody: No resource with given identifier found`；后端/nginx 对该请求记录 200/47 bytes | 不能算 AC-028 脚本通过；也没有证据证明该 HTTP handler 失败。单独的 AC-028 browser test 已运行通过。 |
| 前端 mock E2E | 当前受影响的 `public-contribution-review`、`upload-question-data-flow`、`upload-task-center` 子集 | reviewer 复跑 **2 passed / 14 failed**；当前 focused subset **1 passed / 2 failed** | 与已登记 D3 `D3-mocked-playwright-contract-drift` 重叠；mock 失败不等于实栈行为失败，也不能作为全绿证据。 |
| 同日较宽回归历史记录 | [旧验证记录](2026-10-02-alignment.md)所列 spec backend 命令 | **361 passed, 2 skipped, 14 warnings** | 作为已有测试记录引用，不声称本次审计再次运行了这条 188 秒命令。 |
| 生产部署 | 本次审计没有部署/改动生产；此前部署检查仅有 health/root 200 和 API 被拦截的前端竞态用例 | 不构成 ADR/AC 生产验收 | AC-028 的 disposable Compose 结果不是生产验证。 |

## 初审时的代码发现定位（修复位置见提交 `3a2020b6`）

- `backend/app/routers/interview.py:82-100,140-149`：管理员 SSE 路由用 `interview_id` 无 scope 查询私人面经，并把 job 结果发回 SSE。
- `backend/app/routers/data.py:820-858,878-907`：回收站 SQL 条件只有 `deleted_at IS NOT NULL`，随后返回私人面经原文和私有题目文本。
- `backend/app/routers/bank_build.py:229-244,303-387`：只加载当前用户的私人行，但管理员分支将其并入公共 canonical 并删除私人行；现有反向测试位于 `backend/tests/security/test_authz_unification.py:337-364`。
- `backend/app/routers/submit.py:499-538`：旧 retry 的管理员豁免允许跨 owner，并以原任务 owner 作为 actor；新 root retry 的拒绝测试不能覆盖此旧路由。
- `backend/app/routers/admin_review.py:16-46`：管理分析状态 SQL 扫描全部未删除面经，返回未分析项 ID/company/round/内容长度布尔值。
- `backend/tests/integration/test_upload_question_data_flow_worker.py:1-7,278-294`：测试文件声明 Redis/browser leg intentionally not claimed；公共 cluster stub 只生成新题，不返回既有 canonical 匹配。

## 初审 Findings（修复前状态）

机器可读 findings 位于 [findings.tsv](../../../.tech-audit/work/2026-10-02/findings.tsv)。初审当时建议先修管理员数据边界，再补公共命中与活体验收；当时尚未提交产品代码修复。后续修复及当前状态见下文“修复提交后的部署与复核”。

### 🔴 确认的高优先级发现

- **F-21 — `backend/app/routers/interview.py:82`：** 管理员 SSE 只检查管理员身份，按调用方给出的 `interview_id` 读取任意面经；完成时把 job result 放进 SSE。该路径没有 ADR 要求的显式 support grant/audit。修复时把 scope 检查放在读取和 enqueue 之前，并加 U1 私有 marker 负向回归。
- **F-22 — `backend/app/routers/data.py:820`：** 管理员回收站对 `interview` 返回 `questions_list`，对 `tagged` 返回题干；查询只有软删除条件。修复时按实体 scope 过滤，并分别断言 U1/U2 私有 marker 和私有记录计数不可见。
- **F-23 — `backend/app/routers/bank_build.py:357`：** 个人重建只加载当前管理员自己的私有行，但其管理员分支将题目、来源和频次写入公共 canonical 后删除私有行。已有测试把隐式发布设为正确期望。移除该特例，只有显式发布申请和审批可以改变公共题库。
- **F-24 — `backend/app/routers/submit.py:516-538`：** 旧 retry 允许管理员跨 owner，并把 `original.created_by` 作为 `restore_upload` 的 actor。它不直接返回原文，但能以用户身份恢复私人 payload，造成未授权代操作和审计身份错置。拒绝跨 owner，或设计单独的显式授权/审计操作。

### 🟡 待补发现

| Finding | 状态与下一步 |
|---|---|
| D12 `admin_review.py:16` | 统计查询读全体私人面经元数据；缩小到公共 scope，并测试 ID/company/round/count 都不侧漏。 |
| D3 `test_upload_question_data_flow_worker.py` | 初审时缺既有公共 canonical 命中；现已补齐。公共 share/admin review 的 Redis/ARQ/browser 活体腿也已由 AC-029 real-stack 通过。 |

以上 F-21～F-24 与 D12 是初审时的发现；它们已在 `3a2020b6` 中修复并由新红绿测试复核。D3 的公共活体腿已由本轮 AC-029 disposable real-stack 浏览器/ARQ 旅程补齐。

## 修复提交后的部署与复核

### 修复前后红绿证据

- 新增管理员/个人/公共 scope 反例先红 **7 failed / 1 passed**；实现 scope 修复后相同定向反例 **8 passed**，再扩展到本报告记录的 **86 passed** 组合回归。
- AC-029 扩展测试先因公共题库岗位关联未按当前用户筛选条件建立而失败；测试 fixture 补全真实岗位映射后，测试继续发现直接公共命中没有逐题 `resolve` checkpoint。实现 checkpoint 写入后逐题测试通过。
- `real_stack_smoke.spec.js` 初始因导航响应体已无法从 CDP 读取而在前置 smoke 中断；该断言只需 HTTP status，移除晚到的 body 读取后，完整实栈 runner 退出码 0。

### 当前验证账

| 类型 | 命令 / 场景 | 结果 | 能证明的范围 |
|---|---|---|---|
| 后端变更回归 | 本轮 upload/spec 对齐目标 backend regression | **79 passed, 79 warnings, 66.17s**；rootless continuation/terminal-poison 子集另有 **11 passed, 10 deselected** | 证明本轮队列持久化、续跑、终态防循环及相邻 scope 回归；不证明真实外部模型。 |
| 前端任务中心 | `upload-task-center.spec.js` 含 AC-027 375/1440、键盘/aria 状态矩阵 | **21 passed, 55.0s** | Playwright 使用 mock API；证明 UI 状态/可访问性，不替代真实 API 集成。 |
| 静态检查 | 变更文件 Ruff、`git diff --check`、`bash -n scripts/real_stack_smoke.sh` | **通过** | 未运行全仓 lint/type-check。 |
| 部署候选镜像 real-stack | `REAL_STACK_REUSE_BUILT_IMAGES=1 ./scripts/real_stack_smoke.sh` | **退出码 0；4 个浏览器场景通过**：通用 smoke、AC-021 丢响应、AC-028 个人 stop/restart、AC-029 公共分享审核与失败项 retry；AC-029 单场景 **1 passed / 11.3m** | 使用候选 Docker 服务、临时 SQLite、Redis、ARQ、worker、nginx、浏览器；LLM provider URL 是本地 stub，外部模型未调用。DB trace 位于 `test-results/real-stack/`，临时 volume 已删除。 |
| 生产部署 | `BACKUP_MIN_KEEP_FILES=1 BACKUP_RETENTION_DAYS=0 ./deploy/docker-deploy.sh update`；`./deploy/docker-deploy.sh worker-restart`；随后将 backend 重新指向当前 `app:local` | **成功**；backend/worker/nginx/OAuth gateway healthy；backend 和 worker 都为 `sha256:68de9d343cfb4b4444ea4d13b638a03b267f1b9b0384a745f888134bb2385ca7`；nginx `sha256:764234af0b6476b4d32b00444be52ae97b3d95643a4bfdb447536ad4f88d403f`；OAuth `sha256:0b6f8b652e430ddf1b44f6ccb0ea7d941fc05d580766a5066d4e78fe6fcea29d` | 部署了提交 `513af96e`；第一次 worker restart 曾产生 backend/worker 镜像不一致，已将 backend recreate 到相同 `app:local` image 后复核。 |
| 生产只读探针 | `curl http://127.0.0.1/`、`curl http://127.0.0.1/api/health`、`docker inspect` | root **200**、health **200**（`{"status":"ok","db":"connected"}`）；全部服务 healthy，backend/worker image IDs 一致 | 生产只做健康/镜像读取；业务验收数据只在隔离栈。 |
| 最新数据库备份 | `/data/projects/interview-boss/backups/interview-boss_20261003_222636.db`；只读 `PRAGMA quick_check` | **1,036,558,336 bytes；quick_check=ok；仅保留 1 份 `interview-boss_*.db`** | 线上部署自动备份有效；没有在生产 DB 写测试数据。 |
| 磁盘清理 | 删除旧 AC-029 隔离镜像/停止栈和默认 BuildKit cache | 默认 BuildKit **2.77GB** 已清理；根盘可用空间由 **2.47GB** 回升到 **5.4GB**；保留 `app:local`、`app:previous` 等生产/回滚镜像 | 没有执行全局 Docker prune；`/tmp/backups` 和生产 backups 都只留最新 SQLite 备份。 |
| LLM 边界 | 候选栈 provider 配置与 stub 容器 | 本轮所有 real-stack 的 LLM 请求都打到 deterministic local stub | 不是 mock 整个业务栈；是只 mock LLM provider。用户当前已过期的真实模型、凭据和生成质量均未被测试。 |

### 仍未对齐的部分

- **AC-001、002：** 公共发布结果的任务卡定位、UI 到真实分页 API 的组合链路仍需隔离栈验证；旧审计“本地分页”措辞已过时。
- **AC-007：** 普通 public/personal rootless queue 到终态失败后无应用级 retry 入口；已停止 poison-row 无限重派并标为 failed。待用户决定是否增加入口。
- **AC-009、010、011、013、016、017、022、024：** 矩阵列出的 live concurrency、连接切换、多题答案、追加贡献、错误草稿与 JD 链路尚未完成对应的浏览器+真实 API/worker 验收。
- **更广泛的 D3 前端 E2E debt：** 本轮目标任务中心 Playwright 已通过；仓库其他 mock contract drift 不在本次部署范围内。
