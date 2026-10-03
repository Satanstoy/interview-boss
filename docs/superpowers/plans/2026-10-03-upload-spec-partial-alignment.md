# 上传恢复 spec 部分项：根因分析与 TDD 收敛计划

**状态：** 实施中；AC-007 已补真实隔离 Redis/ARQ 消费证明；AC-008 已修复提取检查点提交边界和失败流清理；AC-009/017 已补并发接受、跨代恢复与 UI attempt 复用证据；本轮未部署。
**基线：** 审计记录提交 `77d29fb1`；已部署产品修复提交 `3a2020b6`。
**规范：** 已接受 ADR-0048；`docs/superpowers/specs/2026-09-29-upload-recovery/` 当前仍为 Draft。
**目标：** 对审计中 17 个“部分”AC逐项确认根因、补上对应红绿测试，只在测试证明产品行为错误时修改实现；所有 AC 都有可复查证据后再更新状态。

关联材料：

- [全量审计与 AC 矩阵](../../verification/upload-recovery/2026-10-02-spec-audit.md)
- [现有上传恢复计划](2026-10-02-upload-spec-alignment.md)
- [AC 验收契约](../specs/2026-09-29-upload-recovery/acceptance.md)
- [数据与队列契约](../specs/2026-09-29-upload-recovery/contracts.md)

## 结论摘要

17 个 partial 不代表 17 个已确认的产品 bug。现有证据包含三类情况：

1. **已有后端实现和回归，缺少页面或真实运行链路的证明**，例如 AC-001/002/010/028/029。
2. **测试本身没有真正执行它声称执行的情景**，AC-008 的“重启”测试就是已确认的例子。
3. **实现或契约边界还没有相应的负向/并发/保留期测试**，例如 AC-025/026/027。

建议按“测试可信度 → 持久队列与恢复 → 页面状态与请求边界 → 旧数据和保留期 → 公共审核真实全栈”顺序实施。先补最小红灯；若正确测试在当前代码上已绿，记录为测试/审计闭环，不为制造代码差异而改实现。

## 根因分析

| 根因 | 证据 | 影响 AC | 判断 |
|---|---|---|---|
| RC-1：验收要求跨越浏览器、API、SQLite、Redis/ARQ、worker，但已部署镜像的 real-stack runner 只覆盖通用 smoke 和个人上传 worker 停启 | `scripts/real_stack_smoke.sh` 依次运行 `real-stack-smoke.spec.js` 和 `upload-recovery-real-stack.spec.js`；后者只提交私人面经并重启 worker，没有公共申请或管理员审核 | 001、010、014 的实栈证明，028、029 | 已确认的覆盖边界；不是实现 bug 的证明。 |
| RC-2：一个测试把“新连接”写成了原连接读取 | `backend/tests/pipeline/test_upload_stage_recovery.py::test_stage_checkpoint_survives_restart_and_is_reused` 创建了 `conn2`，但 `get_stage_result` 仍传 `conn`；两个连接还各自使用独立 `:memory:` 数据库 | 008 | 已确认的测试缺陷。该用例不能证明进程/连接重启后从持久存储恢复。 |
| RC-3：队列测试验证了 SQLite job 生成与轮转，没有验证数据库提交与 Redis/ARQ handoff 的恢复闭环 | `test_upload_queue_reconciliation.py` 用内存 SQLite 直接调用 `reconcile_pending_buckets`；它不验证 Redis 暂不可用后的真实投递和 worker 消费 | 007、008、028、029 | 已确认的测试层级缺口。实现是否有丢任务 bug，需要真实 Redis 反例决定。 |
| RC-4：不少状态契约在 service 层或 mock API 中分别测试，缺少断线、响应丢失、换账号、恢复按钮到服务端状态的一条可见闭环 | 当前已有 `test_upload_status_projection.py`、`test_upload_stream_contract.py`、`test_upload_submit_api.py` 及 mock Playwright；这些分别证明局部规则，不等于真实浏览器走完整网络生命周期 | 001、010、011、013、017、021、022、026 | 已确认的证据边界；特定状态是否有实现问题仍需新增反例。 |
| RC-5：审计结论与后续实现存在时间差 | AC-002 旧审计文字引用了“前端本地分页”的历史复审结论；当前 `InterviewView.vue` 传 `server-total` 并在换页调用 `loadInterviewPage`，后端也有 121 条、权限过滤和稳定排序测试 | 002 | 已确认的报告陈旧风险。当前应把问题写成“页面与 API 联动未活验”，不能继续把本地分页当已确认缺陷。 |
| RC-6：旧客户端、源数据变化和长期保留是跨版本/跨时间问题，常规当前态 fixture 不会自然触发 | 当前有 JD legacy、源删除兼容、retention 服务测试；审计缺口是旧对象完整操作、入队后源状态变化、老任务结果 UI 的组合验收 | 024、025、026 | 覆盖设计缺口；不预设要改迁移或清理实现。 |
| RC-7：响应式和可访问性缺少明确的自动验收矩阵 | 当前 task-center 有键盘/aria 基础断言，但没有按 AC 固定 375/1440 两种宽度验证焦点稳定、状态播报与所有动作可达 | 027 | 已确认的验收缺口。 |

**系统性根因：** 现有实现已经有多个坚实的局部测试，但缺少“每个 AC 的规范条款 → 所在层 → 可复现反例 → 真实证明层级”的一致追踪；因此 mock 通过、服务函数通过、真实 Redis/浏览器通过曾被混在一张状态表里。实施时必须继续区分这三种证据。

## 方案比较与推荐

| 方案 | 做法 | 代价与风险 | 结论 |
|---|---|---|---|
| A. 只补 unit/mock | 快速补齐状态和 UI 期望 | 仍不能证明 DB/Redis handoff、管理员审核和 worker 重启；会保留当前最大证据盲区 | 不推荐作为完成方案 |
| B. 分层 TDD，公共链路做一条部署镜像隔离实栈 | 单测锁状态不变量；API/SQLite/Redis 测并发和 handoff；mock 浏览器锁 UI 边界；一个 U1/Admin/U2 的真实隔离旅程覆盖公共发布和恢复 | 需要扩展 runner 和可控 stub；每层只承担自己能证明的部分 | **推荐** |
| C. 把所有 17 项都改成 real-stack 浏览器 E2E | 每个 AC 都从 UI 起跑 | 运行慢、失败定位差；数据库迁移、精确状态边界和并发 CAS 不适合只靠浏览器验证 | 不推荐 |

推荐的完成证据：后端确定性测试覆盖数据不变量；真实隔离 Redis/ARQ 覆盖跨资源和进程恢复；Playwright mock 覆盖 UI 错误状态；部署镜像上的少量 real-stack 旅程覆盖 AC-028/029 和关键用户链。**生产环境只做部署和只读健康探针，任何业务数据流测试都在 disposable stack 中运行。**

## 实施顺序与 TDD 工作包

每个工作包按同一规则执行：新增一个最小反例 → 运行指定单测并确认红灯（若当前代码已经通过，则记录为“测试缺口已补、无需产品代码修改”）→ 只对证实失败的实现做最小修改 → 原红灯变绿 → 扩大相邻回归 → 更新 AC 证据。不得删除失败断言来换取全绿。

### Task 0：锁定 spec 状态与 AC 追踪基线

**Files:**

- Update: `docs/verification/upload-recovery/2026-10-02-spec-audit.md`
- Reference: `docs/superpowers/specs/2026-09-29-upload-recovery/README.md`
- Reference: `docs/superpowers/specs/2026-09-29-upload-recovery/acceptance.md`

- [ ] 把 17 个 partial 列成 `AC → requirement → 当前测试 → 缺少证据 → 本计划 task` 追踪表。
- [ ] 将 AC-002 的旧“前端本地分页”措辞改为历史发现；当前缺口写为“浏览器换页/筛选与服务端 API 联动未活验”。
- [ ] 明确 AC-008 当前测试的 `conn2` 错接是测试缺陷，不能作为进程重启证据。
- [ ] 对每项标 `implementation bug / test gap / stale audit / draft decision`，禁止把未调查项默认标为代码 bug。
- [ ] 实施前由 spec 责任人确认 Draft 的 AC 是否仍作为预期行为；已接受 ADR-0048 始终优先。

**验证：** `git diff --check`；人工核对 17 项各出现一次且映射到后续 task。此步骤不跑产品测试。

### Task 1：修复 AC-008 重启测试的证明缺陷，并测阶段崩溃点

**Files:**

- Test: `backend/tests/pipeline/test_upload_stage_recovery.py`
- Test: `backend/tests/integration/test_upload_recovery_stack.py`
- Possible implementation, only if a new test is red: `backend/app/services/upload_repository.py`、`backend/app/worker.py`、对应持久化事务函数

- [x] 把 `_db()` 改为接收临时文件路径；writer 和重启后的 reader 打开同一个 SQLite 文件。
- [x] 成功写入 `extract` checkpoint 后关闭 writer 连接，再只用 `conn2` 读取；移除同一 `:memory:` 数据库的假重启。
- [x] 先单跑 checkpoint 测试，确认它确实由第二连接读取持久数据；再跑整个 stage recovery 文件。
- [x] 在 extract 节点成功返回后注入下一节点 classify 故障；新 worker attempt 必须从已提交 checkpoint 恢复且提取 LLM 物理调用仍为 1 次。
- [x] 在面经/detail 事务尚未提交时关闭 writer 连接；新连接确认整笔写入回滚。
- [x] 在 outbox 已提交后注入首次 ARQ handoff 失败；下一次 dispatcher 从 SQLite 补投到隔离 Redis，队列仅一个目标 job。
- [x] 在 answer 外部模型已返回后注入业务写入失败；恢复重试可承担额外调用成本，最终只留一份答案结果。
- [x] 各边界使用新连接、新 attempt 或下一轮 dispatcher/worker 恢复，并断言成功业务成果不重复、extract checkpoint 复用。
- [x] 对红灯只改对应边界；当前确认的实现问题已修复，其余结果只补测试。

**运行：**

```bash
cd backend
ALLOW_RFC2544_BENCHMARK_RANGE=1 PYTHONPATH=. ../.venv/bin/pytest -q --tb=short \
  tests/pipeline/test_upload_stage_recovery.py \
  tests/integration/test_upload_recovery_stack.py \
  tests/integration/test_upload_recovery_fullstack.py
```

**初始测试可信度红绿证据：** 先只把 `get_stage_result` 的参数改为新连接，隔离内存库下得到 **1 failed**（checkpoint 为 `None`）；随后改用同一临时 SQLite 文件、关闭旧连接后读取，定向用例 **1 passed in 1.58s**。该用例本身只是测试 fixture 的假重启缺陷；后续正确故障注入另行证明了生产 checkpoint 边界缺陷，见下。

**AC-008 新增红绿证据：** 正确的 extract 故障注入先得到 **1 failed**：分类节点失败后，已完成的 extract 行被 failure aggregator 改成 `failed`，恢复无法复用。现在 extract 节点成功返回时，在独立事务内按当前 `lease_generation` 保存结构化结果；`SubmitState` 明确透传该 fence。另一个 SQLite 连接读到已提交的 `succeeded` checkpoint，恢复后提取调用仍为 1 次。失败路径还复现了 async SSE generator 的 `Task exception was never retrieved`，让 worker 排空错误事件而不是提前 `break` 后消失。答案故障注入另测出 root-bound answer job 的聚合函数导入路径错误；修正后 worker 能处理持久化失败并重试。未提交事务关闭连接、新连接确认无部分写入。定向回归 `test_upload_stage_recovery.py` + `test_upload_recovery_fullstack.py`：**14 passed in 13.75s**。

**AC-007/008 合并回归：** 在专用临时 Redis 容器、临时 SQLite 和独立 ARQ namespace 下运行 stage recovery、queue reconciliation/root wiring、recovery stack、fullstack 共 5 个测试文件：**31 passed in 32.30s**，22 条现有 deprecation/configuration warnings；不连接生产 Redis/数据库。

### Task 2：让 AC-007 队列对账证明 DB→Redis/ARQ 的最终投递

**Files:**

- Test: `backend/tests/pipeline/test_upload_queue_reconciliation.py`
- Test: `backend/tests/pipeline/test_upload_queue_root_wiring.py`
- Test: `backend/tests/infra/test_arq_real_redis_integration.py`
- Possible implementation, only if a new test is red: `backend/app/services/upload_queue.py`、`backend/app/worker_enqueue.py`、对应 reconciler 调度代码

- [x] 保留当前 service 测试对 bucket 幂等、轮转公平和 orphan blocked 的断言。
- [x] 新增真实隔离 Redis namespace 测试：对账持久化 bucket job，经真实 dispatcher 写入 Redis，再由真实 ARQ worker 消费；只有聚类服务计算 stubbed。
- [x] 单独验证首次 Redis handoff 失败时 job 留在 SQLite outbox，后续 dispatcher 真实补投且 Redis 里只有一个匹配 ARQ job。
- [ ] 推进可控时钟到下一次 reconciliation，断言同一合法桶最终恰好一个 ARQ job 被接受并由 worker 消费。当前恢复用例只证明真实入队；正常路径的 reconciled worker 用例证明真实消费。
- [ ] 持续加入公共流量，断言私人桶在契约规定的有限轮次内被选中；现有轮转测试重复选择静态 bucket 集合，尚未覆盖动态持续流量。
- [ ] 重复运行 reconciler/dispatcher 并检查 Redis 恢复后不重复业务执行、不创建第二个活跃 `work_key`。当前分别覆盖 reconciler 幂等、dispatch 去重；跨失败恢复到消费的一体化重复执行断言仍待补。
- [ ] 只修复新增实测失败的 dispatch/reconciliation 分支。

**本轮红绿证据：** 新增 `test_reconciled_cluster_bucket_is_dispatched_and_consumed_by_arq_worker`。首轮 **1 failed** 是测试覆盖掉本地 job id 后最终断言报 `IndexError`；修正测试变量后，在临时 Redis 容器、临时 SQLite 和唯一队列前缀下 **1 passed in 2.57s**。测试真实执行 SQLite reconciler、dispatcher、Redis 入队和 ARQ worker 消费；`cluster_batch` 计算 stubbed，因此不声称验证 embedding/聚类算法。未发现 AC-007 生产实现缺陷。

**运行：**

```bash
cd backend
ALLOW_RFC2544_BENCHMARK_RANGE=1 PYTHONPATH=. ../.venv/bin/pytest -q --tb=short \
  tests/pipeline/test_upload_queue_reconciliation.py \
  tests/pipeline/test_upload_queue_root_wiring.py \
  tests/infra/test_arq_real_redis_integration.py
```

### Task 3：补 AC-009 / AC-017 的并发提交和跨代 retry 端到端反例

**Files:**

- Test: `backend/tests/pipeline/test_upload_stage_recovery.py`
- Test: `backend/tests/pipeline/test_upload_retry_family.py`
- Test: `backend/tests/pipeline/test_submit_job_retry.py`
- Test: `backend/tests/pipeline/test_upload_submit_api.py`
- Test: `frontend/tests/e2e/upload-task-center.spec.js`
- Possible implementation, only if a new test is red: `backend/app/services/upload_lifecycle.py`、`backend/app/routers/upload_imports.py`、`frontend/src/components/business/UploadTaskCenter.vue`

- [x] 用固定时钟和两个 SQLite 连接并发提交内容完全不同的 A/B；断言 import/job/attempt/thread IDs 不同、时间戳相同且请求 payload 不串 root。真实 worker 的 interview/detail/source ordinal 仍由单 root 全链路覆盖，尚未将 A/B 一起跑过两个 worker。
- [x] 建 A→B→C 的 legacy job 链，从 A、B 两个独立连接并发调用 retry，断言都解析到同一 root 和同一 active attempt。
- [x] 断言成功阶段 checkpoint 保持原 ID（AC-008 fullstack restart 测试）；同一 `work_key` 最多一个 pending/queued/running job（retry family 测试）。
- [x] 让 retry API 返回 `created_attempt=false`，通过 Playwright 确认显示“已有恢复任务正在继续处理未完成步骤”，不显示创建新任务的文案。
- [x] 并发接受和并发恢复均使用两个独立 SQLite 连接；恢复测试从 A、B 两个历史 job 入口发起。

**运行：**

```bash
cd backend
ALLOW_RFC2544_BENCHMARK_RANGE=1 PYTHONPATH=. ../.venv/bin/pytest -q --tb=short \
  tests/pipeline/test_upload_stage_recovery.py \
  tests/pipeline/test_upload_retry_family.py \
  tests/pipeline/test_submit_job_retry.py \
  tests/pipeline/test_upload_submit_api.py
```

```bash
cd frontend
./node_modules/.bin/playwright test --config tests/playwright.config.js \
  tests/e2e/upload-task-center.spec.js
```

**本轮红绿证据：** 新增 A/B 并发接受后，固定时间戳和不同 payload 断言在隔离 SQLite 下 **1 passed in 1.58s**；两个连接从 A、B 历史 job 并发恢复的 retry family 与 submit API 回归 **23 passed in 18.83s**。AC-007/008 相关 stage/reconcile/worker/fullstack 集成回归在 disposable Redis 与 SQLite 下 **31 passed in 32.13s**。并发恢复的第一轮失败是 fixture 没有先提交 A→B→C 种子链，修正 fixture 提交后通过，不是产品缺陷。`created_attempt=false` 的浏览器测试先复现了 UI 一律播报“恢复请求已提交”的状态误导；现在按响应标志使用“已有恢复任务正在继续处理未完成步骤”。任务中心整份 mock API Playwright **13 passed in 28.1s**。浏览器回归不代表真实部署/真实 API 验收。fullstack fixture 也改为每个 worker 线程单独打开同一临时 SQLite 文件，避免测试把跨线程并发压在一条连接上；AC-008 三个 fullstack 场景 **4 passed in 7.86s**。仍未覆盖两个并发 root 各自完整 worker 产物的交叉隔离，后续须补或保留为未验证。

### Task 4：补 AC-010 / AC-011 / AC-013 的客户端状态收敛测试

**Files:**

- Test: `frontend/tests/e2e/upload-task-center.spec.js`
- Test: `backend/tests/services/test_upload_status_projection.py`
- Test: `backend/tests/infra/test_upload_stream_contract.py`
- Possible implementation, only if a new test is red: `frontend/src/composables/useSubmitJobs.js`、`frontend/src/components/business/UploadTaskCenter.vue`、`backend/app/routers/upload_imports.py`、对应 snapshot/error policy

- [ ] SSE 在非终态 EOF 后断开：断言客户端重连并以服务端 snapshot 收敛。
- [ ] 恢复 GET 返回 500：断言保留断线任务与已知结果，不清卡片、不显示成功。
- [ ] 先收到 revision 8 再收到 7：断言状态和计数不回退；心跳不能增加完成数。
- [ ] U1 登出后再以 U2 登录：断言 U1 卡片、SSE、计时器和私有结果缓存均清掉。
- [ ] 10 题 8 成功/2 失败：断言 root 为契约规定的 partial 状态，显示正确数量，只提供 `retry_failed_steps`，恢复只调两道失败题。
- [ ] 覆盖 401 单次停止、429 总尝试数不超过 3、结构修复共用预算，并断言 snapshot 不含原文/key。
- [ ] 旧 SSE 入口只订阅同一 root；不启动另一份 graph/job。

**运行：**

```bash
cd backend
ALLOW_RFC2544_BENCHMARK_RANGE=1 PYTHONPATH=. ../.venv/bin/pytest -q --tb=short \
  tests/services/test_upload_status_projection.py \
  tests/infra/test_upload_stream_contract.py
```

```bash
cd frontend
./node_modules/.bin/playwright test --config tests/playwright.config.js \
  tests/e2e/upload-task-center.spec.js
```

### Task 5：补 AC-021 / AC-022 的丢响应、幂等和输入草稿闭环

**Files:**

- Test: `backend/tests/pipeline/test_upload_submit_api.py`
- Test: `frontend/tests/e2e/upload-task-center.spec.js` 或新增 `frontend/tests/e2e/upload-submit-recovery.spec.js`
- Test: `scripts/real_stack_smoke.sh`（仅在需要把新真实网络丢响应场景加入 runner 时）
- Possible implementation, only if a new test is red: `frontend/src/composables/useSubmitJobs.js`、上传表单组件、`backend/app/routers/submit.py`

- [ ] 浏览器真实 POST 到隔离 API；测试代理让服务端完成提交后丢弃响应，浏览器用相同 idempotency key 恢复并得到同一个 import_id。
- [ ] 断言同用户同 key/同 hash 只有一个 root、一个有效初始 dispatch；同 key 不同 hash 返回 409。
- [ ] U2 用 U1 的 key 查询仍为 404；响应、toast 和日志不泄露 U1 的任务信息。
- [ ] 对 400、413 和不支持的文件类型断言草稿内容仍在，错误字段可读，SQLite 中没有幽灵 root/job；超大文件路径不整份读入内存。
- [ ] 先检查既有 API 幂等测试是否已证明每个不变量；只为缺失的浏览器/传输反例补新测试。

**运行：**

```bash
cd backend
ALLOW_RFC2544_BENCHMARK_RANGE=1 PYTHONPATH=. ../.venv/bin/pytest -q --tb=short \
  tests/pipeline/test_upload_submit_api.py
```

```bash
cd frontend
./node_modules/.bin/playwright test --config tests/playwright.config.js \
  tests/e2e/upload-submit-recovery.spec.js
```

新加真实丢响应测试后，用 `REAL_STACK_REUSE_BUILT_IMAGES=1 ./scripts/real_stack_smoke.sh` 验证同一部署构建镜像上的接受与恢复；若场景不在 smoke runner，给 runner 增加显式测试入口，不能把 mock 结果记成 AC-021 活体验收。

### Task 6：验证 AC-001 / AC-002 的页面定位和服务端分页联动

**Files:**

- Test: `frontend/tests/e2e/upload-task-center.spec.js`
- Test: 新增 `frontend/tests/e2e/interview-pagination.spec.js`（如没有已有等价 spec）
- Test: `backend/tests/pipeline/test_interview_server_pagination.py`
- Possible implementation, only if a new browser test is red: `frontend/src/views/InterviewView.vue`、`frontend/src/composables/useMasterBankData.js`、`frontend/src/components/common/DataTable.vue`、`backend/app/routers/data.py`

- [ ] 用 121 条授权 P1 面经、U2 私人行、P2 行验证 `total`、页边界、稳定排序、权限和岗位过滤。
- [ ] 浏览器换页/排序/招聘季/每页数量时断言 URL/API 查询参数与当前页数据一致；筛选或 page size 改变后页码回 1。
- [ ] 核实当前 `server-total` 实现与 API 契约；若测试通过，只把 AC-002 状态从“部分”更新为“回归覆盖”，不改分页实现。
- [ ] 用户原在 P1 第 2 页时上传 P2 任务：后台完成不强迫导航；用户点击“查看面经”后按 location 切 P2、正确页并高亮目标。
- [ ] 目标已删除/无权读取时显示明确状态，不跳到同页其他记录。

**运行：**

```bash
cd backend
ALLOW_RFC2544_BENCHMARK_RANGE=1 PYTHONPATH=. ../.venv/bin/pytest -q --tb=short \
  tests/pipeline/test_interview_server_pagination.py
```

```bash
cd frontend
./node_modules/.bin/playwright test --config tests/playwright.config.js \
  tests/e2e/interview-pagination.spec.js tests/e2e/upload-task-center.spec.js
```

### Task 7：补 AC-024 / AC-025 / AC-026 的旧数据、源变更与历史保留边界

**Files:**

- Test: `backend/tests/pipeline/test_upload_legacy_compat.py`
- Test: `backend/tests/pipeline/test_upload_import_retry.py`
- Test: `backend/tests/infra/test_upload_recovery_retention.py`
- Test: `frontend/tests/e2e/upload-task-center.spec.js`
- Possible implementation, only if a new test is red: `backend/app/services/upload_lifecycle.py`、`backend/app/worker.py`、`backend/app/routers/upload_imports.py`、前端任务历史/结果显示组件

- [ ] 从未带 v2 元数据的旧 JD、旧 approved 公共面经和 legacy job 起跑，断言 JD 不进入聚类；重复兼容读取/恢复不生成第二次业务成果。
- [ ] job 排队后分别删除原文、退休岗位、改变分类/流水线版本，再执行 worker：断言提交前重新验证，任务按契约阻塞/要求显式重分析，不复活原文、不覆盖已有成功版本。
- [ ] 用可控时钟越过 90 天边界运行 retention：active/failed 的恢复 payload 保留；completed 的 payload 可按契约清理，但摘要、任务历史和结果入口保留。
- [ ] 浏览器打开已完成老任务；payload 已清时显示明确“不可从零恢复”信息，不呈现可误点的恢复动作。
- [ ] 保留迁移与回填第二次运行幂等的既有测试；遇到歧义只报告、不猜测重放。

**运行：**

```bash
cd backend
ALLOW_RFC2544_BENCHMARK_RANGE=1 PYTHONPATH=. ../.venv/bin/pytest -q --tb=short \
  tests/pipeline/test_upload_legacy_compat.py \
  tests/pipeline/test_upload_import_retry.py \
  tests/infra/test_upload_recovery_retention.py
```

```bash
cd frontend
./node_modules/.bin/playwright test --config tests/playwright.config.js \
  tests/e2e/upload-task-center.spec.js
```

### Task 8：按 AC-027 验收任务中心的窄屏、键盘和读屏状态

**Files:**

- Test: `frontend/tests/e2e/upload-task-center.spec.js`
- Possible implementation, only if a new accessibility assertion is red: `frontend/src/components/business/UploadTaskCenter.vue`、`frontend/src/views/InterviewView.vue`、相关 CSS

- [ ] 在 375px 与 1440px 两个 viewport 分别运行相同任务卡片、审核态、needs_action、partial_failed 场景。
- [ ] 全流程仅用键盘打开中心、聚焦任务、触发合法 action、关闭中心；焦点不丢到页面顶端。
- [ ] 断言按钮可访问名称、状态使用 `aria-live="polite"`/`role="status"`，心跳不持续抢焦点。
- [ ] 断言窄屏下任务状态与允许动作仍可见和可操作，无横向溢出遮住关键按钮。
- [ ] 只修复被具体断言证明的布局/语义问题。

**运行：**

```bash
cd frontend
./node_modules/.bin/playwright test --config tests/playwright.config.js \
  tests/e2e/upload-task-center.spec.js
```

### Task 9：把 AC-028 / AC-029 合成一条公共分享审核真实栈旅程

**Files:**

- Test: 新增 `frontend/tests/e2e/public-contribution-real-stack.spec.js`
- Test: `backend/tests/integration/test_upload_question_data_flow_worker.py`（保留快速 DB trace 测试，不用真实 Redis 替代所有单测）
- Update: `scripts/real_stack_smoke.sh`
- Update if deterministic failure control needs it: `e2e/stub-llm/provider.py`
- Update if failure artifacts need a stable format: `scripts/` 下的 real-stack trace assertion helper
- Possible implementation, only if the live test is red: `backend/app/routers/public_contributions.py`、`backend/app/services/public_contributions.py`、`backend/app/worker_cluster_tasks.py`、前端审核/任务中心调用层

- [ ] 扩展 disposable Compose run，确保临时 SQLite volume、独立 Redis、worker、nginx 和本地 stub 全属于唯一项目名；runner 退出时清理 volume。
- [ ] 用 U1 浏览器从真实 `/api/submit-jobs` 提交 5 道可区分题目的 share；由真实 worker 完成私人预处理和任务投影。
- [ ] 用 admin 浏览器实际读取申请；排除 1 题、修改 1 题、清除来源敏感字段并批准；断言待审核投影此前不能被普通公共读取。
- [ ] 在临时库预置一条已发布 public canonical，让一条保留题命中它；断言公共正文、来源、频次不变，私人 resolution 指向同一 canonical。
- [ ] 在 stub 对另一条保留题的公共阶段注入一次确定性失败；断言状态是部分失败、失败 ordinal 可见、成功 item 的 IDs 和写入数不变。
- [ ] worker 停止时通过 UI/API 排入失败项恢复，然后重启同一 worker container；断言只恢复失败 ordinal，完成后公共端恰有 4 条获批题，排除题不出现。
- [ ] U2 尝试访问 U1 私人 root、原稿和 by-key 均被拒绝；admin 可以审核已提交快照，但读取 U1 其他私人 root 仍被拒绝。
- [ ] runner 导出 `ordinal → stage → private detail/resolution → review item/projection → public detail/resolution/canonical` trace；测试断言真实 DB 关系和 API 读结果，不以截图、HTTP 200 或 completed 单独判通过。
- [ ] 首次运行保留失败 compose logs、Playwright trace、trace JSON；通过后只保留非敏感摘要，确保临时数据库和 Redis volume 已删除。

**运行：**

```bash
REAL_STACK_REUSE_BUILT_IMAGES=1 ./scripts/real_stack_smoke.sh
```

验收依据直接使用 [AC-028/029](../specs/2026-09-29-upload-recovery/acceptance.md) 第 155～175 行。真实模型供应商不参与；stub 只用于确定性结果与可控故障。

### Task 10：汇总红绿证据、更新矩阵并执行部署门

**Files:**

- Update: `docs/verification/upload-recovery/2026-10-02-spec-audit.md`（或按实际日期另建复核记录）
- Update: `.tech-audit/work/2026-10-02/findings.tsv`
- Update: `docs/superpowers/plans/2026-10-03-upload-spec-partial-alignment.md`

- [ ] 按每个 AC 记录初始红灯、对应 commit、最终绿灯命令/计数/耗时/环境及证据边界。
- [ ] 只有契约必需的证明层通过才将 `partial` 改为 `通过（回归）` 或 `通过（隔离全栈）`；记录 `not-run` 和失败，不推断全绿。
- [ ] 把已确认修复的代码缺陷与纯测试缺口分列；活动 finding 只保留仍未通过的内容。
- [ ] 运行全量目标 backend regression、上传/审核前端 Playwright、静态检查及部署镜像 real-stack；生产环境仅做 root/health/image ID 的只读确认。
- [ ] 若实栈全绿，再按既有部署步骤更新 backend 并单独重启 worker；确认两者镜像相同、health 通过、备份存在。不得向生产库写验收数据。
- [ ] 根据 Draft 责任人的确认更新 spec 状态或记录批准的偏差；没有设计批准时不得把 Draft 标为 Accepted/Implemented。
- [ ] 每个已验证工作包做一个 focused commit；不要提交基线中未跟踪的 `.tech-audit/work/2026-08-28/`、`.tech-audit/work/2026-09-23/`、`backups` 或 `docs/specs/2026-09-23-frontend-ui-hierarchy-cleanup.md`。

**最低回归集合：**

```bash
cd backend
ALLOW_RFC2544_BENCHMARK_RANGE=1 PYTHONPATH=. ../.venv/bin/pytest -q --tb=short \
  tests/pipeline/test_interview_server_pagination.py \
  tests/pipeline/test_upload_stage_recovery.py \
  tests/pipeline/test_upload_queue_reconciliation.py \
  tests/pipeline/test_upload_retry_family.py \
  tests/pipeline/test_upload_submit_api.py \
  tests/pipeline/test_upload_legacy_compat.py \
  tests/services/test_upload_status_projection.py \
  tests/infra/test_upload_stream_contract.py \
  tests/infra/test_upload_recovery_retention.py \
  tests/integration/test_upload_question_data_flow_worker.py
```

```bash
cd frontend
./node_modules/.bin/playwright test --config tests/playwright.config.js \
  tests/e2e/upload-task-center.spec.js \
  tests/e2e/public-contribution-review.spec.js \
  tests/e2e/upload-question-data-flow.spec.js \
  tests/e2e/interview-pagination.spec.js \
  tests/e2e/upload-submit-recovery.spec.js
```

## Exit gate

- 17 个原 partial AC 每项都有唯一结果：通过、未通过或未运行；没有用“相关测试通过”代替契约对应场景。
- AC-002 经当前 server pagination 代码与浏览器联动测试重新定级；确认原审计是否过时。
- AC-008 的断言确实使用关闭旧连接后的同一 SQLite 文件，并覆盖四个 crash boundary。
- AC-007 证明 job 最终进入真实隔离 ARQ 队列并被 worker 消费；AC-028/029 证明真实 share → admin review → public worker recovery。
- 业务身份、逐题数据和 retry 关系在数据库与授权 API 中均有断言；U2/Admin 私人隔离有负向断言。
- 生产没有被行为验收脚本写入；部署只在所有候选镜像的隔离栈验证通过后执行，并单独确认 worker 镜像。
- 若任何必须场景仍红，AC 保持 partial，计划继续以新反例为入口，不把它记为完成。
