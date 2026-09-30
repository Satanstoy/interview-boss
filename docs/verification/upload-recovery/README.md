# 上传恢复改造：实施追踪与验证证据

对应 [主 spec](../../superpowers/specs/2026-09-29-upload-recovery/README.md)、
[执行计划](../../superpowers/plans/2026-09-29-upload-recovery-implementation.md)。

规则：**未运行的步骤必须写 not-run**，不能写 passed；既有失败与新增回归分开记录。

## 1. 基线（2026-09-29）

| 项 | 值 |
|---|---|
| HEAD（开工时） | `138bfda6` docs(ops): record 2026-09-28 upload batch cleanup |
| 分支 | `codex/frontend-ui-hierarchy-cleanup` |
| remotes | `origin` (github)、`gitee` |
| 迁移最高版本 | 120（`clear_db_confirmations`），121/122 空闲 |
| 工作区既有改动 | 仅 4 个 untracked（`.tech-audit/work/…`、`backups`、`docs/specs/2026-09-23-frontend-ui-hierarchy-cleanup.md`）与本任务新增文件 |
| 生产数据写入 | 无（本任务所有测试走内存/临时库） |

## 2. 需求状态表

状态：Open / In progress / passed / failed / not-run。

| Finding | 需求 | AC | 状态 | 阶段 | 证据 |
|---|---|---|---|---|---|
| F01 | UR-001 结果定位 | AC-001 | passed（分腿：后端 location + 前端定位/高亮/切岗） | 阶段I + 后续修复 | `test_interview_server_pagination.py` 7 passed；`upload-task-center.spec.js`、`upload-question-data-flow.spec.js`；AuthenticatedLayout 消费 page/position/highlight 查询参数 |
| F02 | UR-002 服务端分页 | AC-002 | passed（后端）；前端 server-mode 未做（见 §7 遗留） | 阶段I | `test_interview_server_pagination.py` 7 passed（121 条同时间戳、跨页不重不漏） |
| F03 | UR-003 四格提交策略 | AC-003 | passed | 阶段A + 阶段C | `backend/tests/pipeline/test_upload_policy.py` 30 passed；`test_upload_submit_api.py`（双入口共用接受服务） |
| F04 | UR-004 凭据显式 scope + 提交前配置预检 | AC-004 | passed | 阶段C + 修复 | `test_upload_credentials.py`、`test_upload_llm_accounting.py`、`test_upload_credential_preflight.py`（严格 user-only 默认读取器，无 fallback 风险） |
| F05 | UR-005 原题 resolution | AC-005 | passed | 阶段E | `test_question_resolutions.py` 6 passed |
| F06 | UR-006 匹配三态 | AC-006 | passed | 阶段E | `test_upload_matching_outcomes.py` 8 passed |
| F07 | UR-007 队列续调 | AC-007 | passed | 阶段E | `test_upload_queue_reconciliation.py` 5 passed + 每分钟对账 cron |
| F08 | UR-008 阶段检查点 | AC-008 | 分腿可见（检查点/事务/幂等 passed；真实 graph 故障点注入 not-run，见 §7 遗留） | 阶段D | `test_upload_stage_recovery.py` 6 passed |
| F09 | UR-009 并发不串单 | AC-009 | passed（thread_id 去时间戳）；graph 级故障点 not-run | 阶段D | `test_upload_stage_recovery.py`、`test_upload_recovery_stack.py` |
| F10 | UR-010 SSE 恢复 | AC-010 | passed（分腿：服务端快照流 + 客户端 EOF 重连；浏览器断 worker 全链路 not-run） | 阶段H | `upload-task-center.spec.js` 6 passed（含 SSE 重连、375/1440） |
| F11 | UR-011 真实完成 | AC-011 | passed（后端投影） | 阶段G | `test_upload_status_projection.py` 15 passed |
| F12 | UR-012 租约/fencing | AC-012 | passed（服务层）；worker 端 fencing 接续见 §7 遗留 | 阶段D | `test_upload_leases.py` 6 passed |
| F13 | UR-013 错误协议 | AC-013 | passed | 阶段G | `test_upload_stream_contract.py` 8 passed |
| F14 | UR-014 审核投影生效 | AC-014 | passed | 阶段F | `test_public_contributions_materialize.py` 7 passed；approve 路由走 v2 CAS（未知字段 422） |
| F15 | UR-015 失败子项恢复 | AC-015 | passed | 阶段F | `test_public_contribution_recovery.py` 5 passed + `test_admin_public_contribution_retry.py` |
| F16 | UR-016 追加贡献一致 | AC-016 | passed | 阶段F | `test_public_contribution_recovery.py`（清单投影） |
| F17 | UR-017 跨代/并发恢复 | AC-017 | passed | 阶段D | `test_upload_retry_family.py` 6 passed（含线程并发）；`test_upload_import_retry.py`（HTTP 层） |
| F18 | UR-018 私人正文隔离 | AC-018 | passed | 阶段G | `test_upload_task_privacy.py` 5 passed |
| F19 | UR-019 提取不漏题 | AC-019 | passed | 阶段E | `test_upload_extraction_integrity.py` 11 passed |
| F20 | UR-020 审批/撤回互斥 | AC-020 | passed | 阶段F | `test_public_contribution_transitions.py` 6 passed（含线程并发）；withdraw 路由走 v2 CAS |
| — | AC-021 幂等键 | passed | 阶段C | `test_upload_submit_api.py` + 前端 by-key 恢复 |
| — | AC-022 文件校验 | passed | 阶段C | `test_upload_acceptance.py`（413/400 无幽灵 job） |
| — | AC-023 迁移幂等 | passed | 阶段J | `test_upload_recovery_backfill.py` 7 passed + CLI 演练（二次 apply 0 新增） |
| — | AC-024 JD/旧数据 | passed | 阶段J | `test_upload_legacy_compat.py` |
| — | AC-025 源状态变化 | passed | 阶段J | `test_upload_legacy_compat.py`（SOURCE_DELETED）+ `test_upload_import_retry.py`（409） |
| — | AC-026 历史保留 | passed | 阶段J | `test_upload_recovery_retention.py` 3 passed |
| — | AC-027 可访问性 | passed | 阶段H | `upload-task-center.spec.js`（键盘/aria-live/375/1440）6 passed |
| — | AC-028 隔离集成 | passed（隔离腿） | 阶段J | `test_upload_recovery_stack.py` 4 passed（需 UPLOAD_TEST_DB_PATH/UPLOAD_TEST_REDIS_PREFIX） |
| — | AC-029 逐题数据流追踪 | passed（服务链腿）；worker 断点注入 not-run（见 §7 遗留） | 阶段J | `backend/tests/integration/test_upload_question_data_flow.py` 2 passed + `frontend/tests/e2e/upload-question-data-flow.spec.js` 2 passed |

## 3. 阶段证据

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
- [x] thread_id = import_id+attempt_no+job_id（AC-009）。
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

## 6. 验收状态汇总

| 状态 | AC |
|---|---|
| passed | AC-002（后端）、AC-004、AC-005、AC-006、AC-007、AC-011（后端投影）、AC-013、AC-014、AC-015、AC-016、AC-017、AC-018、AC-019、AC-020、AC-021、AC-022、AC-023、AC-024、AC-025、AC-026、AC-027、AC-028（隔离腿）、AC-029（服务链腿） |
| passed（分腿） | AC-001（后端 location + 前端定位/高亮/切岗）、AC-003（双入口共用接受服务）、AC-010（服务端快照流 + 客户端 EOF 重连） |
| not-run / 待续 | AC-008/009 的 graph 节点级故障点注入（需真实 LangGraph 执行环境）；AC-010/028/029 的“真实 worker 中断 + 浏览器打开结果”全链路腿（服务端与浏览器两侧分别有测试）；AC-002 前端 server-mode DataTable（contracts §4.5 要求，待前端接入服务端 total） |
