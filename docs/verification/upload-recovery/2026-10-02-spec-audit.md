# ADR 与上传恢复 spec 全量对账

**审计日期：** 2026-10-02
**代码基线：** `1cb3915410c6243b2834d0acc1ed79e4e25b02cb`，分支 `codex/frontend-ui-hierarchy-cleanup`
**范围：** 已接受 ADR-0048；上传恢复 Draft 的 AC-001～AC-029；管理员、个人用户、公共题库和个人题库边界。
**产品代码改动：** 无。本次只整理审计证据与修正过期验证记录。

## 结论

**没有完全对齐。** 普通用户的个人/公共 scope、逐题 resolution、审核投影、撤回并发、worker fencing 等核心后端路径有回归测试支持，且本轮重点后端测试通过；但 ADR-0048 仍被管理员旧入口违反：管理员 SSE 能读/处理其他用户私人面经，管理员回收站能返回私人原文和题目，管理员个人题库重建会隐式发布自己的私人题，旧 retry 还能以原用户身份重放任务。另有管理员分析状态接口扫描私人面经元数据。

上传恢复文档自身明确标注为 **Draft / 待设计审阅**，所以 AC 通过与否只说明实现是否符合这份拟议验收契约，不代表该 Draft 已成为获批产品决策。AC-028 本轮确实跑过隔离 Compose + SQLite + Redis/ARQ worker + Playwright 的个人上传/worker 停启/精确结果链路，**1 passed**；其范围没有覆盖公共申请审核，不足以把 AC-028 标为通过。AC-029 的 HTTP/worker 函数组合测试也不是 Redis/ARQ 活体执行，并没有测试 spec 明确要求的“命中已存在公共 canonical”分支。

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
| 私人上传命中公共 canonical 时只关联公共规范题，保留私有 occurrence/resolution，不改公共来源和频次 | **回归覆盖；AC-029 链路仍缺分支** | `test_question_resolutions.py`、`test_public_personal_scope_contract.py` 验证解析关系和不改公共统计；但 AC-029 集成测试的 `deterministic_cluster` 固定返回空 `matched_to_existing`（见其 278–294 行），不能证明该完整上传/审核链路命中既有公共题。 |
| 未命中公共题时只写当前用户个人池；公共池只读 | **后端回归覆盖** | 本轮 `test_public_personal_scope_contract.py` 与 `test_question_resolutions.py` 所在定向套件通过（见验证账）。这证明受测业务入口的 scope，不覆盖所有旧管理员入口。 |
| 个人题升级必须走不可变申请快照、审核、显式发布 | **未完全对齐** | 普通用户贡献申请、投影和审核有测试；但 `/api/master-bank/build-personal` 的管理员分支把管理员自己的私人题并入公共题并删除私有行。现有 `test_admin_merge_still_merges_into_public` 直接把这个反例当成期望行为。 |
| 管理员默认不得查看其他用户私题；例外必须显式授权并审计 | **未对齐（隐私阻断项）** | `/api/interview/{id}/re-process-stream` 只要求管理员身份，按任意 `interview_id` 读取全文并将处理结果通过 SSE 返回；`/api/data/{file_type}/trash` 只筛 `deleted_at` 并序列化私人 `questions_list`/题目正文。另有分析状态接口泄露私人记录的 ID、公司、轮次等元数据。以上入口没有相应跨用户 marker 隔离测试。 |
| 公共待审内容只对提交者/审核人员可见；审核通过后才能进入公共检索和处理 | **主路径回归覆盖，管理员遗留路径未闭环** | 公共投影、状态迁移及撤回测试通过；管理员 build-personal 隐式发布与旧 SSE/回收站读私有数据仍违背此边界。 |
| 个人阶段用提交者模型配置，审核后的公共阶段用全局配置 | **stub 回归覆盖** | 本轮凭据/预检/账本套件通过，包含 scope 严格解析与禁止跨 scope fallback；不连接真实供应商（符合 Draft 的隔离验收原则）。 |
| 重分析、恢复、清理基于实体/occurrence ID；发布记录保留来源和审计 | **部分对齐** | 新 root/import 链路有 owner、attempt、generation 和 resolution 测试；旧 retry 允许管理员越过 owner 检查，并将 `actor_id` 设为原用户，形成未审计的代操作。 |
| 面经与 JD 共用申请/审核外壳、进入不同领域流水线 | **主要路径回归覆盖；全栈未闭环** | JD legacy compatibility、投影和申请测试存在；AC-028/029 的实栈浏览器演练目前只覆盖私人面经路径。 |

## AC-001～AC-029 验收矩阵

状态定义：**通过（回归）**表示受测契约有自动化断言且相关测试结果通过；**部分**表示有部分实现/测试但至少一个必须场景未证实；**未对齐**表示确认违反契约；**未运行**表示本次没有足够执行证据。通过（回归）不等于生产部署验收。

| AC | 状态 | 本次核对的证据 / 未闭环范围 |
|---|---|---|
| 001 结果定位 | 部分 | `upload-task-center.spec.js` 有任务结果定位 mock 用例，曾有 14 项 mock E2E 通过记录；本轮 mock 前端子集有失败，且活体浏览器只证明 AC-028 单一个人上传结果。 |
| 002 真实分页 | 部分 | `test_interview_server_pagination.py` 覆盖服务端排序/分页/授权数据；历史复审记录指出页面仍将数据拉回后本地分页，缺少前端真实分页完整验收。 |
| 003 四格提交策略 | 部分 | policy/submit tests 覆盖个人/分享入口；管理员旧 build-personal 隐式并入公共题，且 legacy SSE/retry 边界仍需要负向测试。 |
| 004 费用与配置 | **通过（回归）** | `test_upload_credential_preflight.py`、`test_upload_credentials.py`、`test_upload_llm_accounting.py` 覆盖严格 scope、fallback 拒绝、预检账本/指纹和调用记录；使用 stub，不测试真实供应商。 |
| 005 私人引用与归属 | **通过（回归）** | `test_question_resolutions.py`、`test_public_personal_scope_contract.py` 覆盖公共引用保持唯一 canonical、私人 resolution 归属及不修改公共计数。完整 AC-029 仍缺同一链路的既有公共命中。 |
| 006 判断失败不等于新题 | **通过（回归）** | `test_upload_matching_outcomes.py` 覆盖认证/超时/结构错误/跨 scope ID 与 no-match 区分，失败不建 canonical。 |
| 007 残余队列被推进 | 部分 | 存在 queue reconciliation/root wiring 回归；验收要求多 root、持续入队、有限轮次推进及 dispatcher 不可用后的实际 Redis 接管，未由本次活体测试覆盖。 |
| 008 故障点恢复 | 部分 | `test_upload_stage_recovery.py` 和 fullstack 函数链路覆盖 checkpoint/retry；AC-028 活体只验证排队工作在 worker 停启后完成，没有逐一实测 spec 列出的进程崩溃故障点。 |
| 009 并发输入不串单 | 部分 | 有稳定 root/attempt 和相同秒提交回归；未在本次浏览器+多 worker 活体栈做并发交错验收。 |
| 010 连接恢复 | 部分 | `upload-task-center.spec.js` 有 mock EOF/状态收敛覆盖；受 D3 mock E2E 契约漂移影响，本轮相关前端测试集未全绿，也未用真实 API 做换账号/乱序恢复。 |
| 011 真实完成 | 部分 | `test_upload_status_projection.py` 验证子工作未结束不能把 root 标为 completed、失败计数/可恢复动作；没有完整活体的多题答案部分失败及历史入口流程。 |
| 012 旧 worker 不可写 | **通过（回归）** | 本轮 `test_upload_leases.py` 在相关 59 项安全/边界回归中通过，覆盖 generation、过期 lease、canonical/resolution/答案提交 fencing。 |
| 013 错误与重试预算 | 部分 | snapshot、账本、status projection 有回归覆盖；本轮未在活体 SSE/浏览器验证旧消费者兼容、所有 429/结构修复预算与日志脱敏组合。 |
| 014 公开等于审核投影 | **通过（回归）** | `test_public_contributions_materialize.py` 检查预览/投影同源、清空字段不回填、跨申请 item 拒绝；前端审核用例是 mock，真实浏览器审核投影待补。 |
| 015 失败子项恢复 | **通过（回归）** | `test_public_contribution_recovery.py` 与 admin retry/状态测试覆盖只重试失败 item、已有明细不能冒充完成、完成前不发布。 |
| 016 追加贡献保持一致 | **通过（回归）** | `test_public_contribution_recovery.py` 覆盖相同 URL 的已发布/未发布列表和失败恢复；未在 live browser 重跑。 |
| 017 跨代与并发恢复 | 部分 | `test_upload_retry_family.py` 覆盖 owner、单活跃 attempt 与并发恢复基础；`created_attempt=false` 的真实前端解释及活体并发未证实。 |
| 018 私人正文隔离 | **未对齐** | 新 upload root/SSE/status 对非 owner 的测试通过，但覆盖面不含旧管理员 SSE、通用 `/api/data/{file_type}/trash` 和管理员跨 owner retry；前两者已确认能读出私人内容。现有 `TestTrashScope` 只测 `questions_pkg.bulk.get_master_bank_trash`，不是此处的通用回收站路由。 |
| 019 不静默漏题 | **通过（回归）** | `test_upload_extraction_integrity.py` 与逐题 ordinal 测试覆盖 schema/题目数量守恒。 |
| 020 审批与撤回互斥 | **通过（回归）** | 本轮 `test_public_contribution_transitions.py` 覆盖双连接 approve/withdraw 竞争、重复动作与事务失败回滚。 |
| 021 幂等键与响应丢失 | 部分 | 后端 `test_upload_submit_api.py`/migration tests 覆盖稳定 root、冲突和 owner 隔离；前端丢响应后表单重发/恢复闭环未由活体浏览器证明。 |
| 022 文件校验与草稿保留 | 部分 | 后端 400/413 与无幽灵任务有测试；表单在错误/needs_action 后保留输入并可修复重发的全 UI 流程没有本轮活体验收。 |
| 023 迁移与回填幂等 | **通过（隔离回归）** | broad 361 项记录包含迁移/回填测试；本轮没有对生产数据库 apply 或检查生产历史歧义数据（生产 apply 不是 Draft 隔离测试的替代物）。 |
| 024 JD 与旧数据兼容 | 部分 | 有 JD 不进入面经题队列、旧 approved 数据可见及 projection 回归；兼容 retry 的完整 JD 审批后链路未在 live stack 验证。 |
| 025 源删除/岗位退休/分类升级 | 部分 | legacy compatibility 覆盖源删除阻止恢复；岗位退休、分类版本变化与 worker 提交前状态重检没有一条端到端断言覆盖。 |
| 026 历史与保留清理 | 部分 | 有 retention 测试保护活跃/失败 payload；完成任务长时间后仍能找到结果、缺 payload 时 UI 明确降级的长期路径未活体验收。 |
| 027 可访问性 | 部分 | 有 mock UI/常规 Playwright 覆盖；本轮没有跑 AC 指定的 375/1440、键盘、焦点稳定和 aria 完整矩阵。 |
| 028 隔离全栈 | **部分；个人路径活体通过** | disposable Compose 栈的真实 API、SQLite、Redis、worker 与浏览器完成个人上传→queued→worker 停/启→completed→打开精确结果：**1 passed，26.9s**。没有覆盖公共申请审核步骤。总 `real_stack_smoke.sh` 在先行 smoke 的 Playwright `Network.getResponseBody` 读取处失败退出；后端日志显示该 API 200/47 bytes，不能将 wrapper 失败说成业务通过或 AC 全绿。 |
| 029 逐题数据流 | **部分** | `test_upload_question_data_flow_worker.py` 通过真实 submit/review HTTP 和 worker 函数，数据库逐题 trace、失败项恢复及公共读取回归通过；Redis/ARQ enqueue 被 stub，未重启真实 worker。`deterministic_cluster` 固定 `matched_to_existing: []`，缺 spec 要求的既有公共命中；也缺管理员不能访问其他私人任务的同场景反例。 |

## 已确认缺口与建议改法

| 优先级 | 缺口 | 建议用红绿灯测试锁定 |
|---|---|---|
| P0 | 管理员重分析 SSE 任意 ID 读私有面经 | U1 建独特 marker 私有面经；管理员请求该 ID。预期 404/403，SSE 全文、jobs.result、日志中均无 marker；公共面经可按授权流程处理。 |
| P0 | 管理员回收站不分 scope | 分别放入 U1/U2 私人软删除面经和题目、公共软删除数据。管理员回收站结果只含符合 ADR 的公共数据；任何私人 marker 不得出现在 `items` 或计数中。 |
| P0 | 管理员个人 rebuild 隐式公开 | 以管理员账号创建 personal canonical 后调用 build-personal。预期公共 canonical/source/frequency 不变、private row 保留、没有 contribution/projection；删除旧测试的“个人题被并入公共并删除”期望。 |
| P0 | legacy retry 管理员代用户重放 | U1 建失败私有 root，管理员请求旧 retry。预期拒绝且无新 attempt/job/LLM 调用；若确需支持，另建显式 support 授权和 audit actor，不得伪装 `actor_id=U1`。 |
| P1 | 管理分析状态读到私人元数据 | 用 U1 私有、公共和管理员自有面经混合建库。接口结果只含允许的公共对象；不能通过 ID/count/公司/轮次间接泄露。 |
| P1 | AC-029 缺既有公共 canonical hit | 预置公共 Q 和原始内容/来源/频次；上传含 Q 的 U1 share。批准并处理后断言 U1 resolution 指向 Q、没有私人重复 canonical，Q 的正文/来源/频次完全不变。 |
| P1 | AC-029 活体分享/审核/恢复腿缺失 | isolated stack 真实浏览器提交 share；API/Redis/ARQ worker 实际排队，审核后停止/杀掉 worker 再启动；验证投影、4 道保留题、失败子项只重试一次、最终浏览器结果及 U2/Admin 隔离。 |

## 本轮验证账

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

## 代码发现定位

- `backend/app/routers/interview.py:82-100,140-149`：管理员 SSE 路由用 `interview_id` 无 scope 查询私人面经，并把 job 结果发回 SSE。
- `backend/app/routers/data.py:820-858,878-907`：回收站 SQL 条件只有 `deleted_at IS NOT NULL`，随后返回私人面经原文和私有题目文本。
- `backend/app/routers/bank_build.py:229-244,303-387`：只加载当前用户的私人行，但管理员分支将其并入公共 canonical 并删除私人行；现有反向测试位于 `backend/tests/security/test_authz_unification.py:337-364`。
- `backend/app/routers/submit.py:499-538`：旧 retry 的管理员豁免允许跨 owner，并以原任务 owner 作为 actor；新 root retry 的拒绝测试不能覆盖此旧路由。
- `backend/app/routers/admin_review.py:16-46`：管理分析状态 SQL 扫描全部未删除面经，返回未分析项 ID/company/round/内容长度布尔值。
- `backend/tests/integration/test_upload_question_data_flow_worker.py:1-7,278-294`：测试文件声明 Redis/browser leg intentionally not claimed；公共 cluster stub 只生成新题，不返回既有 canonical 匹配。

## 审计 Findings 与处置顺序

机器可读 findings 位于 [findings.tsv](../../../.tech-audit/work/2026-10-02/findings.tsv)。按项目既有 `F01…` finding 编号接续，建议先修管理员数据边界，再补公共命中与活体验收；实现整改后再更新相应验收结论。以上只是整改建议；本次没有提交产品代码修复。

### 🔴 确认的高优先级发现

- **F-21 — `backend/app/routers/interview.py:82`：** 管理员 SSE 只检查管理员身份，按调用方给出的 `interview_id` 读取任意面经；完成时把 job result 放进 SSE。该路径没有 ADR 要求的显式 support grant/audit。修复时把 scope 检查放在读取和 enqueue 之前，并加 U1 私有 marker 负向回归。
- **F-22 — `backend/app/routers/data.py:820`：** 管理员回收站对 `interview` 返回 `questions_list`，对 `tagged` 返回题干；查询只有软删除条件。修复时按实体 scope 过滤，并分别断言 U1/U2 私有 marker 和私有记录计数不可见。
- **F-23 — `backend/app/routers/bank_build.py:357`：** 个人重建只加载当前管理员自己的私有行，但其管理员分支将题目、来源和频次写入公共 canonical 后删除私有行。已有测试把隐式发布设为正确期望。移除该特例，只有显式发布申请和审批可以改变公共题库。
- **F-24 — `backend/app/routers/submit.py:516-538`：** 旧 retry 允许管理员跨 owner，并把 `original.created_by` 作为 `restore_upload` 的 actor。它不直接返回原文，但能以用户身份恢复私人 payload，造成未授权代操作和审计身份错置。拒绝跨 owner，或设计单独的显式授权/审计操作。

### 🟡 待补发现

| Finding | 状态与下一步 |
|---|---|
| D12 `admin_review.py:16` | 统计查询读全体私人面经元数据；缩小到公共 scope，并测试 ID/company/round/count 都不侧漏。 |
| D3 `test_upload_question_data_flow_worker.py:278` | AC-029 stub 不会命中已存在公共 canonical；增加既有题命中断言和 Redis/ARQ/browser 分享审核恢复腿。 |

由仓库 `_findings_to_milestones.py --prefix F --start 21` 生成的建议顺序为 F-21～F-24（管理员 SSE、回收站、隐式公共化、旧 retry），再处理 D12、AC-029 和文档证据。该编号只表示审计建议，不代表已建立 issue。
