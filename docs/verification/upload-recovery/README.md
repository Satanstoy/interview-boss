# 上传恢复改造：实施追踪与验证证据

对应 [主 spec](../../superpowers/specs/2026-09-29-upload-recovery/README.md)、
[执行计划](../../superpowers/plans/2026-09-29-upload-recovery-implementation.md)。

规则：**未运行的步骤必须写 not-run**，不能写 passed；既有失败与新增回归分开记录。

> **2026-09-30 复审修正（代码基线 `8c810733`）**：原表把若干 helper/服务单测通过记作整项通过，不能成立。当前实际状态以本节下方 §2、§6 及[复审报告](../../analysis/2026-09-30-upload-recovery-spec-reconciliation.md)为准。§3～5b 保留历史命令与开发记录，不代表整条实际调用链已经验收。原问题的机器可读对账见 [reconciliation.tsv](../../../.tech-audit/work/2026-09-30/reconciliation.tsv)。本轮仅 mock UI 8 passed；后端 Docker 测试被构建前磁盘门禁阻断，pytest 未启动；真实 AC-028/029 未完成。


## 1. 基线（2026-09-29）

| 项 | 值 |
|---|---|
| HEAD（开工时） | `138bfda6` docs(ops): record 2026-09-28 upload batch cleanup |
| 分支 | `codex/frontend-ui-hierarchy-cleanup` |
| remotes | `origin` (github)、`gitee` |
| 迁移最高版本 | 120（`clear_db_confirmations`），121/122 空闲 |
| 工作区既有改动 | 仅 4 个 untracked（`.tech-audit/work/…`、`backups`、`docs/specs/2026-09-23-frontend-ui-hierarchy-cleanup.md`）与本任务新增文件 |
| 生产数据写入 | 无（本任务所有测试走内存/临时库） |

## 2. 需求状态表（2026-09-30 复审）

`open`：实际路径仍有原问题；`partial`：部分已接入但整个 AC 未完成；`implemented_not_retested`：实际代码已接入，本轮未复测。完整 spec 不能标 passed。

| Finding | AC | 当前状态 | 已实现 | 仍未对齐 |
|---|---|---|---|---|
| F01 | AC-001 | partial | 新增location接口和前端query消费 | 完整任务结果未接且岗位名称被当ID并仍本地分页（R04,R09） |
| F02 | AC-002 | partial | 后端过滤排序分页支持total | 页面仍无参取第一页100条再本地切片（R09） |
| F03 | AC-003 | partial | 提交入口新增服务端四格policy | payload和worker未传审核意图管理员公共仍直写approved（R02） |
| F04 | AC-004 | partial | 接受入口使用严格个人配置读取 | 没有真实模型预检与预检job普通share未先检查global实际节点仍旧凭据读取（R01） |
| F05 | AC-005 | open | 新增resolution服务和表 | 实际持久化路径不写resolution公共命中关联仍缺失（R05） |
| F06 | AC-006 | open | 新增三态匹配helper | 实际match_new_questions仍把异常归入unmatched（R05） |
| F07 | AC-007 | open | 新增补单和cron | 真实入队无root且补单analysis_batch未注册dispatcher（R06） |
| F08 | AC-008 | open | 新增阶段表repository和事务函数 | 真实graph未使用检查点实体保存和下游入队仍分离（R03） |
| F09 | AC-009 | open | 新增build_thread_id helper | 真实graph仍使用用户加秒级时间（R03） |
| F10 | AC-010 | partial | 新任务中心支持EOF重连与查询失败保留 | 旧提交订阅未传isTerminal且旧恢复查询失败仍清缓存（R08） |
| F11 | AC-011 | open | 新增状态聚合helper和任务历史UI | worker只完成jobs不更新root与子工作聚合前端仍5秒移除旧job（R04） |
| F12 | AC-012 | open | 新增generation fencing服务 | 实际worker未用且实际队列仍按created_at回收（R06） |
| F13 | AC-013 | partial | 新增快照和错误预算模型 | GET缺allowed_actions等字段旧SSE仍旧协议重试预算未贯穿实际调用（R04,R08） |
| F14 | AC-014 | partial | 面经审批路由已接严格审核字段投影 | 真实嵌套snapshot默认字段读取不对岗位丢失JD走错物化（R11） |
| F15 | AC-015 | partial | 新增失败子项恢复HTTP入口 | 发布仍用旧队列完成判断失败再批准可重建实体恢复未派发（R10） |
| F16 | AC-016 | open | 新增按published明细刷新清单helper | 实际发布未调用且v2物化无同URL查找复用（R10） |
| F17 | AC-017 | partial | 新恢复入口约束单active attempt | 恢复不建可执行job旧retry仍只查直接子任务并不绑定root（R03） |
| F18 | AC-018 | open | 新root接口owner隔离和运维白名单 | 旧通用job stream仍允许admin读取任意私人result（R07） |
| F19 | AC-019 | partial | 原优缺点黑名单删除已改为保留标记 | 真实extract未接schema字符串拆单字和非字符串静默丢失仍可能发生（R05） |
| F20 | AC-020 | implemented_not_retested | approve与withdraw实际路由已接BEGIN IMMEDIATE及revision CAS | 本轮后端复测被Docker磁盘门禁阻断不新增passed证据（-） |

| 跨层 AC | 当前结论 |
|---|---|
| AC-021 | partial：后端幂等原语已有，真实前端提交未使用草稿幂等 helper |
| AC-022 | partial：输入校验已有；needs_action 响应仍清空前端草稿 |
| AC-023 | not-run（本轮）：保留历史回填服务/CLI 证据，本轮未复跑、未 apply 生产 |
| AC-024 | open：JD 经 v2 approve 进入面经物化和题目队列；旧 retry 未统一 |
| AC-025 | partial：helper 有部分删除检查，真实执行提交前状态/版本校验未贯通 |
| AC-026 | implemented_not_retested（保留策略局部）：本轮未复测，长期失败队列恢复仍需覆盖 |
| AC-027 | mock UI 8 passed 中包含相关用例；真实接口集成未验收 |
| AC-028 | open / not-run：现有测试没有真实 API、Redis 和 worker 联合执行 |
| AC-029 | open / not-run：现有服务测试手填中间产物，前端只验 mock 和跳转 URL |

## 3. 阶段证据（历史开发记录，当前关闭状态见 §2）

### 阶段A：可执行边界与测试隔离

- [x] 基线记录：见上表。
- [x] 迁移序号核对：最高 120，121/122 可用（`backend/app/db/migrations/__init__.py`）。
- [x] 测试 DB 防护 fixture：`backend/tests/conftest.py::_guard_against_production_db`
  （autouse；`sqlite3.connect` 指向 `backend/data` 即失败；允许 `:memory:`/临时目录）。
- [x] 四格 policy 期望表：`backend/tests/pipeline/test_upload_policy.py`（每身份/目标一例，api/legacy_sse 双入口）。
- [x] 伪造 `is_admin/owner_id/credential_scope` 反例 + 非法 target 5 例。
- [x] 红→绿：先跑出 28 个业务断言失败（非 ImportError），实现后 30 passed。
- [x] 严格 DTO：未知字段拒绝、allow-list、空白规范化为 None、source_url http(s) 校验、快照/错误枚举。
- [x] 未接入入口：本阶段只定义规则，`submit.py` 尚未改用 policy（F03 保持 In progress，未宣称修复）。

命令与结果：

```bash
.venv/bin/python -m pytest -q backend/tests/pipeline/test_upload_policy.py
# 30 passed in 0.10s

.venv/bin/python -m pytest -q backend/tests/pipeline/test_upload_policy.py \
  backend/tests/infra/test_db_contextvars.py backend/tests/infra/test_worker_cron_jobs.py \
  backend/tests/pipeline/test_import_and_position.py backend/tests/security/test_email_auth.py \
  backend/tests/security/test_email_required.py
# 82 passed in 28.06s

.venv/bin/python -m pytest -q backend/tests/pipeline backend/tests/security backend/tests/infra
# 675 passed, 2 failed, 4 skipped
```

防护 fixture 暴露并修复的真实隔离缺陷（此前这些测试会连生产库 `backend/data/interview-boss.db`）：

| 文件 | 缺陷 | 修法 |
|---|---|---|
| `tests/infra/test_db_contextvars.py` | 连接工厂测试打开 DB_PATH | monkeypatch DB_PATH 到 tmp_path |
| `tests/security/test_email_auth.py`（7 例） | 邮箱服务读写生产验证码表 | 注入 `app_db_isolation` |
| `tests/security/test_email_required.py` | 绑定邮箱读生产表 | 同上 |
| `tests/pipeline/test_import_and_position.py`（2 例） | 直接查生产表结构/数据 | 同上 |
| `tests/infra/test_worker_cron_jobs.py` | cron 观测写生产执行记录 | 同上 |
| `tests/services/clustering/test_reupload_after_soft_delete.py`（14 例） | 每个测试前后在生产库建删 interview/jd/questions_detail/users | 同上（注意：`_cleanup_test_data` 必须依赖隔离 fixture，否则执行顺序不保证） |

`app_db_isolation` 另修一个隐蔽问题：测试期间**新导入**的模块会拷贝被替换的
`get_db_connection`/`run_db` 引用，teardown 后仍指向已关闭的测试库，导致后续测试回退生产库。
现在 teardown 后有 `_sweep_modules_imported_while_patched` 兜底改回规范引用。

### 阶段B：schema 与事务基础

- [x] 空库迁移、旧 schema 升级、重复运行 3 类测试（`tests/infra/test_upload_recovery_migrations.py`）。
- [x] `upload_imports`（UNIQUE(requester_id, idempotency_key)）、`upload_attempts`
      （UNIQUE(import_id, attempt_no) + partial UNIQUE(import_id) WHERE status='active'）、
      `upload_stage_results`（UNIQUE(import_id, stage, unit_key, input_version)），逐表测试。
- [x] jobs 增量：`root_import_id`/`upload_attempt_id`/`work_key`/`lease_generation`，
      旧行保持 NULL 可用；v2 在途 job 部分唯一索引 `uq_jobs_v2_work_active`。
- [x] `question_resolutions`（每 detail 一个当前 resolution 的 partial UNIQUE、scope CHECK、
      matched/created 必须有 canonical）与 `questions_detail.import_id/source_ordinal` 唯一。
- [x] 审核 `revision`/`review_projection_json`/`projection_hash`；`analysis_queue` v2 归属与租约字段，
      升级前先统计重复并告警，不盲删。
- [x] `upload_llm_calls`（call_key UNIQUE）与 `upload_scope_leases`（scope_key PK + generation + locked_until）。
- [x] repository：`create_or_get_import`（同键同 hash 复用 / 同键不同 hash 抛 `IdempotencyConflict` /
      跨用户互不干扰）、`create_attempt`、`save_stage_result`、`get_import_by_key`；**内部不 commit**
      （有测试证明外层 ROLLBACK 会带走根任务）。

命令与结果：

```bash
.venv/bin/python -m pytest -q backend/tests/infra/test_upload_recovery_migrations.py
# 红：17 failed（新表/新列不存在、repository 骨架）→ 绿：18 passed
```

迁移版本：121 `upload_recovery_core`、122 `upload_resolution`（基线最高 120，未改动已发布迁移）。
未运行生产 `--apply`：迁移只在测试内存库执行。

### 阶段C：凭据、预算与记账（进行中）

- [x] 注入 user/global loader 时，user 缺 Key 而 global 有效 → `MODEL_CONFIG_MISSING`（scope=user、action=configure_user_model），不调用注入的global_loader。
- [x] 修复并验证生产默认路径：`_default_user_loader`改用 strict user-only 读取
      （`get_strict_user_llm_config`），本人无行/无 Key/解密失败一律 None，
      global 有效时实际入口仍阻断（`test_upload_credential_preflight.py`）。
- [x] user 配置解密失败同样不回退，且错误信息不泄露配置内容。
- [x] global scope 不借用用户私钥（user_loader 未被调用）；非法 scope 直接 ValueError。
- [ ] 新增持久化`credential_preflight` job；private目标探测user、public目标先探测global；U1/share还需探测首阶段user；任一必需scope失败时不派发提取job。
- [ ] 最小provider/model ping、scope账本/配额和审核后global重新探测待实现；需通过stub测试401、404、超时、配置变更及从原root恢复。
- [x] 解析结果只暴露 `config_fingerprint`，`api_key` 不进 repr/model_dump（测试断言）。
- [x] `llm_quota.reserve_call` 事务内预留（不 commit）；旧 `_increment_usage` wrapper 保持 commit 语义
      （`test_llm_quota.py`/`test_llm_quota_concurrency.py` 回归通过）。
- [x] `reserve_llm_call` 账本 + 用户配额同事务原子；回滚一起回滚（测试用 BEGIN/ROLLBACK 验证）。
- [x] 配额不足抛 `QUOTA_EXCEEDED` 且不写账本；同一 `call_key` 重复登记抛 `CallLedgerConflict`；
      响应丢失可记 `unknown`；system 付费不占用用户日配额。
- [x] 接受入口文件校验（分块上限、非图片拒绝、空文件列表）：`test_upload_acceptance.py`。
- [x] 原稿/root/首个 job 同事务落库 + 两个入口绑定同一接受服务：`accept_upload` +
      `test_upload_acceptance.py`/`test_upload_submit_api.py`。
- [x] `import_id`/幂等键/status_url/by-key 查询：`upload_imports.py` + `test_upload_submit_api.py`。

命令与结果：

```bash
.venv/bin/python -m pytest -q backend/tests/services/test_upload_credentials.py \
  backend/tests/services/test_upload_llm_accounting.py
# 红：13 failed（骨架）→ 绿：15 passed

.venv/bin/python -m pytest -q backend/tests/services/test_llm_quota.py \
  backend/tests/services/test_llm_quota_concurrency.py backend/tests/services/test_practice_history.py \
  backend/tests/infra/test_upload_recovery_migrations.py \
  backend/tests/services/clustering/test_reupload_after_soft_delete.py
# 47 passed（配额重构无回归）
```

### 阶段D：检查点、恢复与 fencing（进行中）

- [x] 租约 fencing：`claim_job_with_generation` 递增 `lease_generation`；旧代次业务提交抛
      `JobFenceError`（→STATE_CONFLICT），业务表不留痕；心跳只对当前代次续租。
- [x] 回收只看 `locked_until`：创建 1 小时但刚领取的任务不会被误回收（AC-012 部分）。
- [x] 恢复族（AC-017）：任意历史 job 沿血缘解析根任务；并发恢复只有一个 active attempt
      （另一方 `created_attempt=false`）；同 work_key 不重复建活跃 job。
- [x] `submit_interview_in_conn` 拆分：面经+明细+下游写入单事务，异常整体回滚（AC-008 部分）。
- [x] 阶段检查点复用：extract 结果按 (stage, unit_key, input_version) 唯一，重启后复用。
- [ ] 仅 `build_thread_id` helper 实现 import_id+attempt_no+job_id；实际 graph 仍使用用户＋秒级时间，AC-009 未完成（2026-09-30 复审）。
- [ ] 提取/分类检查点接入真实 graph 节点（模型调用前后故障点测试）——未开始。
- [ ] 租约心跳独立任务 + finally 清理——未开始。
- [ ] 剩余故障点（答案外部调用后/保存前等）——未开始。

命令与结果：

```bash
.venv/bin/python -m pytest -q backend/tests/services/test_upload_leases.py
# 6 passed
.venv/bin/python -m pytest -q backend/tests/pipeline/test_upload_retry_family.py
# 6 passed
.venv/bin/python -m pytest -q backend/tests/pipeline/test_upload_stage_recovery.py
# 6 passed
.venv/bin/python -m pytest -q backend/tests/pipeline backend/tests/db backend/tests/interview
# 250 passed（submit_interview_txn 拆分无回归）
```

顺带修复：迁移破坏性备份此前**总是备份生产库路径**（迁移测试库时会误碰生产库），
改为备份正在迁移的库；schema 文档生成器对 git 环境不敏感，freshness 检查恢复可用
（`docs/architecture/schema.md` 已按迁移 121/122 重新生成）。

**既有失败（与本任务无关，单独记录，未修）**：

| 测试 | 失败原因 | 判定 |
|---|---|---|
| `tests/infra/test_docker_config.py::test_cleanup_supports_dry_run_and_aggressive` | 断言 `docker-deploy.sh` 含 `DEPLOY_PRUNE_HOST_ARTIFACTS`，脚本已改写 | 既有失败 |
| `tests/infra/test_schema_docs_freshness.py::test_schema_freshness_check_passes` | `git` 报 dubious ownership（运行环境），schema 文档过期 | 既有/环境失败 |

## 4. 历史遗留记录（非本任务，但已知）

- 生产库 `email_verification_codes` 有 15 行 `@example.com` 测试数据（2026-09-28 05:31–05:59 由旧测试运行写入）。
  防护 fixture 已阻止再次发生；清理需另行授权（软删/删除 + 备份 + 验证）。


### 阶段G/H/I/J：快照协议、前端、分页、迁移与集成

- [x] AC-011 状态聚合 + allowed_actions（无虚构按钮）：`test_upload_status_projection.py` 15 passed。
- [x] AC-013 统一 snapshot 协议 + 3 次物理尝试预算（结构修复同预算）：`test_upload_stream_contract.py` 8 passed。
- [x] AC-018 私人正文隔离 + 运维白名单：`test_upload_task_privacy.py` 5 passed。
- [x] AC-001 后端 location 接口 + 前端查看结果定位（page/highlight）：`test_interview_server_pagination.py`、`upload-task-center.spec.js`。
- [x] AC-002 服务端分页/排序/筛选：`test_interview_server_pagination.py` 7 passed。
- [x] AC-003 双入口共用接受服务（旧 SSE 只创建后订阅，不自己跑 graph）：`test_upload_submit_api.py` 10 passed。
- [x] AC-010 快照 SSE（授权先于流、15 秒心跳、revision 事件 id）+ 客户端 EOF 退避重连：
      `upload-task-center.spec.js` 6 passed（含 SSE 重连、375/1440 视口）。
- [x] AC-023/024/025/026/028：见上表；CLI 演练输出记录在本节末尾。

前端验证命令与结果：

```bash
npm run build      # exit 0
npm run lint       # 0 errors, 38 warnings（阈值 38）
npm test           # 1 passed（smoke）
npx playwright test tests/e2e/upload-task-center.spec.js   # 6 passed
```

AC-028 演练命令：

```bash
UPLOAD_TEST_DB_PATH=/tmp/iboss-ac028.db UPLOAD_TEST_REDIS_PREFIX=iboss-test-<ts> \
  .venv/bin/python -m pytest -q backend/tests/integration/test_upload_recovery_stack.py
# 4 passed；无隔离变量时 4 skipped（拒绝启动）
```

AC-023 CLI 演练：

```bash
python backend/scripts/backfill_upload_recovery.py --database /tmp/iboss-backfill-test.db --dry-run --report /tmp/iboss-manifest.json
python backend/scripts/backfill_upload_recovery.py --database /tmp/iboss-backfill-test.db --apply --manifest /tmp/iboss-manifest.json
# 第二次 apply：imports_created=0, attempts_created=0, jobs_linked=0
```

**未做/超出本次范围（保留 not-run）**：

- AC-010 的“浏览器断 worker 恢复”全链路（真实 ARQ + 浏览器）：服务端/客户端两侧分别有测试，
  但真实 worker 中断演练未在本机执行，登记为 not-run。
- AC-028 的“浏览器打开正确结果”腿：由 `upload-task-center.spec.js` 的定位用例覆盖到 mock 层，
  真实后端 + 浏览器联合腿未跑，登记为 not-run。
- 旧 `submit-stream-v2` 在 v2 关闭时的原路径未改动（保持兼容）。


## 5. 最终回归（2026-09-29）

```bash
.venv/bin/python -m pytest -q backend/tests
# 1 failed, 3202 passed, 8 skipped, 14 deselected
# 唯一失败：tests/infra/test_docker_config.py::test_cleanup_supports_dry_run_and_aggressive
#   （断言 docker-deploy.sh 含 DEPLOY_PRUNE_HOST_ARTIFACTS；部署脚本早已改写，与本任务无关）

cd frontend
npm run build    # exit 0
npm run lint     # 0 errors, 38 warnings（阈值 38）
npm test         # 1 passed（smoke）
npx playwright test tests/e2e/upload-task-center.spec.js   # 6 passed
```

测试隔离治理（本次共修复 60+ 个用例）：防护 fixture（`sqlite3.connect` 指向
`backend/data` 即失败）暴露了 chat/服务层/分类等 20+ 个测试文件会静默读写生产库，
其中 `test_api_does_not_write_production_db` 甚至直接读生产库做断言。全部改为内存/临时库，
并保留其原始语义。这也意味着：**本次改造之前，跑测试本身就是生产数据风险**。

## 5b. 对齐修复后回归（2026-09-30）

在本次 spec 对齐修复（retry 路由、admin retry、v2 CAS 路由、严格 user-only 读取、
AC-029 测试）之后重新执行：

```bash
.venv/bin/python -m pytest -q backend/tests/pipeline backend/tests/services \
  backend/tests/security backend/tests/integration
# 16 failed, 1650 passed, 6 skipped, 14 deselected
# 失败全部在 tests/services/test_fts_service.py —— **既有的跨目录顺序污染**：
# 同一子集在修复前基线 ee59eaec 上同样失败 23 例（1620 passed），
# 本任务未引入任何新失败，反而修复了 7 例（23 → 16）。
# 污染根因：fts_service._idf_cache 是模块级缓存，pipeline/services/security/
# integration 同进程组合下先在别的 test_db 上计算，导致 FTS 用例读到陈旧词频。
# 该问题与上传恢复改造无关，单独记为既有缺陷，不在本任务范围外扩。

cd frontend
npm run build                          # exit 0
npm run lint                           # 0 errors, 38 warnings（阈值 38）
npx playwright test tests/e2e/upload-task-center.spec.js \
  tests/e2e/upload-question-data-flow.spec.js \
  tests/e2e/ui-title-hierarchy.spec.js  # 24 passed
```

## 5c. R01-R12 调用链修复后回归（2026-09-30 晚）

按复审 findings.tsv 的 R01-R12 贯通真实调用链之后：

```bash
# 后端四域组合（pipeline/services/security/integration）
.venv/bin/python -m pytest -q backend/tests/pipeline backend/tests/services \
  backend/tests/security backend/tests/integration
# 16 failed, 1682 passed, 7 skipped, 14 deselected
# 失败全部位于 test_fts_service + test_session_search —— **既有分支级跨文件
# 顺序污染**，已在修复前基线 ee59eaec 上复现完全相同集合（44 failed,
# 1135 passed，services 全目录单独验证）。本轮只减少污染（FTS 增加模块级
# _idf_cache 复位后 23→16），未引入任何新失败。

# 新增全栈链路（隔离协议，UPLOAD_TEST_* 门禁）
UPLOAD_TEST_DB_PATH=/tmp/r12.db UPLOAD_TEST_REDIS_PREFIX=r12 \
  .venv/bin/python -m pytest -q backend/tests/integration/test_upload_recovery_fullstack.py backend/tests/integration/test_upload_recovery_stack.py
# 6 passed：包含
#   - R12 真实 worker graph：accept → 预检 → 提取/分类/落库（import_id/
#     source_ordinal + resolution）→ 公共化审核物化 → 失败恢复；
#   - F08 检查点复用：恢复后的新 attempt 读取已成功 extract/tag 检查点
#     短路复用（LLM 调用计数不变、明细不重复）；
#   - F09/F12 租约 fencing：stale generation 根聚合被拒、不留痕
#     （3 个集成文件同进程连跑 8 passed，AC-029 已自包含隔离）。

cd frontend
npm run build                          # exit 0（R08/R09 接入幂等提交 + 服务端分页）
npx playwright test tests/e2e/upload-task-center.spec.js \
  tests/e2e/upload-question-data-flow.spec.js \
  tests/e2e/ui-title-hierarchy.spec.js  # 24 passed
```

## 6. 验收状态汇总（2026-09-30 复审修正）

> 下方基线为复审结论；2026-09-30 晚间专项修复后逐项推进情况已在
> 5c 与 `.tech-audit/work/2026-09-30/reconciliation.tsv` 更新，本节保留
> 复审时的原始诊断，5c 为修复后的最新状态。

- F01～F19 未满足各自完整 AC 的关闭条件（有实际部分修复，也有只新增 helper 的项目）。其中 F19 原黑名单删除已修，但实际节点结构校验未接。
- F20 的 approve/withdraw 已接写事务和 revision CAS；本轮后端复测未执行，不能新增 passed 证据。
- 新增明确回归：JD 审核进入面经/题目流程；真实嵌套快照默认字段及岗位传递不对。见报告 R11。
- AC-004 尚缺真实 scope 模型预检及所有模型阶段的显式凭据使用。
- AC-028/029 尚缺完整 API/Redis/worker/浏览器和逐题结果验收，不能称“仅剩中断演练”。

本轮实际验证：

```bash
./deploy/docker-deploy.sh test -q \
  -k 'upload or question_resolutions or public_contribution or interview_server_pagination or extraction_integrity' \
  --ignore=backend/tests/integration/test_upload_recovery_stack.py
# exit 1；磁盘门禁 2948 MB < 4096 MB，构建和 pytest 未启动

cd frontend
npx --no-install playwright test tests/e2e/upload-task-center.spec.js \
  tests/e2e/upload-question-data-flow.spec.js --reporter=line
# exit 0；8 passed (24.8s)；模拟接口，不能视为全栈通过
```

原报告的服务测试结果作为历史证据保留；当前需按[复审报告](../../analysis/2026-09-30-upload-recovery-spec-reconciliation.md)补实际调用链和对应回归后，再逐项关闭。
