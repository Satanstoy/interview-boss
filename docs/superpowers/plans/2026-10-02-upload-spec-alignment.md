# 面经上传题库 spec 对齐后续计划

**目标：** 以 `docs/superpowers/specs/2026-09-29-upload-recovery/` 为验收源，对最新上传实现补齐仍未闭环的行为。按每一项红→绿→重构推进；不把 service 单测或 mock API 结果记作真实链路验收。

**本轮结论：** 上传个人题库、普通用户申请公共化、审核投影、逐题发布/恢复、scope 计费和旧 worker 写栅栏已有后端回归支持。提交 `3a2020b6` 修复了管理员遗留读写 scope，并增加 AC-029 既有公共 canonical 命中与逐题 resolve checkpoint。该提交已部署且 worker 已重启；部署镜像上的 disposable runner 两项通过。AC-028/029 仍 partial，因为真实浏览器公共分享审核/恢复腿还未覆盖。见[验证记录](../../verification/upload-recovery/2026-10-02-alignment.md)与[全量对账](../../verification/upload-recovery/2026-10-02-spec-audit.md)。

## Task 1：锁定上传模型调用的账本契约

**Files:**
- Test: `backend/tests/integration/test_upload_question_data_flow_worker.py`
- Test: `backend/tests/services/test_upload_llm_accounting.py`
- Update: `backend/app/services/llm.py`
- Update: `backend/app/services/upload_credentials.py`
- Update: 上传图节点中实际发起 LLM 请求的文件

- [x] 给 AC-029 worker 链路增加提取/分类物理调用断言，核对 scope、payer、provider、model、config fingerprint 和结果状态。
- [x] 先观察缺账本时的失败，再在实际 provider 请求边界逐物理尝试预留/结算；重试使用不同 call key。
- [x] 上传上下文限定到当前 import/stage/unit；非上传模型调用不写上传账本。
- [x] 运行 AC-029 与账本测试；规范化 `complete/fill/tag/match/cluster/save/preflight` 为 `extract/classify/resolve/credential_preflight/persist`，增加 migration 124。

**限制：** AC-029 对提取和分类物理调用做了端到端记账断言；聚类/答案 provider 边界由统一 wrapper 和定向测试覆盖，但逐题链路中的聚类决策使用确定性结果 stub。

## Task 2：管理员公共直导写入显式审批记录

**Files:**
- Test: `backend/tests/integration/test_upload_question_data_flow_worker.py`
- Test: `backend/tests/infra/test_upload_recovery_migrations.py`
- Update: `backend/app/db/migrations/` 与 `backend/app/db/migrations/__init__.py`
- Update: `backend/app/db/operations.py`
- Update: `backend/app/agents/submit/persist_public.py`

- [x] 增加管理员公共直导的 actor/import/明确批准动作/最终脱敏投影断言。
- [x] 先确认只有 policy 标记时审批事件和投影断言失败，再实现审批记录。
- [x] 在公共面经和明细事务内关联审批快照、审计事件、root 与队列；待处理公共投影保持隐藏。
- [x] 运行迁移幂等与管理员/普通用户 share 回归。

**限制：** 管理员直导审批审计测试从 `persist_public_node` 边界执行；AC-029 普通用户 share、管理员审核通过真实 HTTP 和 worker 边界执行。

## Task 3：上传聚类和答案工作拒绝旧代次写入

**Files:**
- Test: `backend/tests/services/test_upload_leases.py`
- Test: `backend/tests/integration/test_upload_question_data_flow_worker.py`
- Update: `backend/app/worker_cluster_tasks.py`
- Update: `backend/app/worker.py`
- Update: `backend/app/services/pipeline/batch.py`
- Update: `backend/app/services/pipeline/writer.py`
- Update: `backend/app/services/submit_service.py`

- [x] 让旧 job/scope generation 在 canonical、resolution、答案写边界被拒绝。
- [x] 以失败测试复现过期 worker 可完成/写入的问题，再把 fencing 传到对应事务边界。
- [x] v2 root job 校验 generation 与有效租约，rootless 旧 job 保持兼容；公共队列恢复按 root 隔离。
- [x] 运行租约、聚类、答案和 AC-029 回归。

## Task 4：AC-029 导出可读逐题 trace

**Files:**
- Update: `backend/tests/integration/test_upload_question_data_flow_worker.py`

- [x] 在现有真实 HTTP/worker 测试中导出 ordinal 到审核投影、公共 detail、resolution 与 canonical 的 ID 映射。
- [x] 跑测试确认映射只含测试 ID 与非敏感字段，并与逐题关系断言一致。

## Task 5：AC-028 浏览器腿与最终核对

**Files:**
- Inspect: `backend/tests/integration/test_upload_recovery_stack.py`
- Inspect: `frontend/tests/e2e/upload-task-center.spec.js`
- Add: `frontend/tests/e2e/upload-recovery-real-stack.spec.js` 与 `frontend/tests/_helpers/real-stack-model.js`
- Update: `scripts/real_stack_smoke.sh`、`e2e/stub-llm/provider.py`
- Update: `backend/tests/integration/test_upload_recovery_stack.py`、`backend/app/worker.py`

- [x] 核对隔离 API/SQLite/Redis/worker 结果，确认现有栈仍缺真实浏览器消费和独立 worker 进程重启。
- [x] 增加活体栈 Playwright harness：浏览器提交私有面经、观察 queued root、runner 重启同一个 worker、浏览器打开精确结果；mock API E2E 不代替此验收。
- [x] 按 AC-004 给预检 worker 的业务 job handoff 增加真实隔离 Redis 测试；先红（job 创建但无 `arq_job_id`），再绿（worker 立即投递）。
- [x] 活体个人上传腿：在隔离 disposable Compose 栈中实跑浏览器提交、观察 queued、runner 停/启同一 worker、等待完成并打开准确结果；部署镜像复跑 1 passed in 26.7s。旧的磁盘满尝试仍是历史记录。
- [x] 修复 real-stack 前置 smoke 在导航结束后读取 CDP response body 的测试脚本问题；完整 `scripts/real_stack_smoke.sh` 现退出码 0。
- [ ] 完整 AC-028：需要把公共申请/管理员审核纳入真实浏览器+API/Redis/ARQ worker 停启恢复链路；单独个人上传腿不满足整项 AC。
- [x] 已有 361 项 spec 后端 pytest（另 2 项跳过）与 14 项前端 mock Playwright 记录；本轮重跑 86 项权限/上传后端回归和 16 项上传/审核 Playwright mock；结果见验证记录。

## Task 6：修复管理员旧入口对个人/公共 scope 的越界

**修复提交：** `3a2020b6`。

- [x] 管理员 reprocess/SSE 只处理允许的公共已发布面经；回收站与 tagged detail 按来源实体 scope 过滤；分析状态不扫描其他用户私人元数据。
- [x] 管理员个人题库 rebuild 不发布私人 canonical；legacy retry 不允许管理员跨 owner 代用户重放，actor 绑定当前认证用户。
- [x] 先让新反例红（7 failed / 1 pass），修复后组合权限与上传链路回归 86 passed。
- [x] 部署 backend，并单独重启已有 worker，确认两者使用同一镜像 ID。
- [ ] 完整 AC-029：把既有公共 canonical hit、审核投影、公共 worker 失败/重试和 U2/Admin 隔离放进 live Redis/ARQ/browser 分享审核流程。
