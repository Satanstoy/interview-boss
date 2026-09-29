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
| F01 | UR-001 结果定位 | AC-001 | not-run | 阶段I | — |
| F02 | UR-002 服务端分页 | AC-002 | not-run | 阶段I | — |
| F03 | UR-003 四格提交策略 | AC-003 | In progress | 阶段A（policy 部分 passed） | `backend/tests/pipeline/test_upload_policy.py` 30 passed |
| F04 | UR-004 凭据显式 scope | AC-004 | In progress | 阶段C（解析/记账/配额 passed；接受入口未接入） | `backend/tests/services/test_upload_credentials.py`、`test_upload_llm_accounting.py` 15 passed |
| F05 | UR-005 原题 resolution | AC-005 | not-run | 阶段E | — |
| F06 | UR-006 匹配三态 | AC-006 | not-run | 阶段E | — |
| F07 | UR-007 队列续调 | AC-007 | not-run | 阶段E | — |
| F08 | UR-008 阶段检查点 | AC-008 | In progress | 阶段D（检查点/事务拆分 passed；graph 故障点未接） | `test_upload_stage_recovery.py` 6 passed |
| F09 | UR-009 并发不串单 | AC-009 | In progress | 阶段D（thread_id 已去时间戳） | `test_upload_stage_recovery.py` |
| F10 | UR-010 SSE 恢复 | AC-010 | not-run | 阶段H | — |
| F11 | UR-011 真实完成 | AC-011 | not-run | 阶段G | — |
| F12 | UR-012 租约/fencing | AC-012 | In progress | 阶段D（fence/回收/心跳 passed） | `test_upload_leases.py` 6 passed |
| F13 | UR-013 错误协议 | AC-013 | not-run | 阶段G | — |
| F14 | UR-014 审核投影生效 | AC-014 | not-run | 阶段F | — |
| F15 | UR-015 失败子项恢复 | AC-015 | not-run | 阶段F | — |
| F16 | UR-016 追加贡献一致 | AC-016 | not-run | 阶段F | — |
| F17 | UR-017 跨代/并发恢复 | AC-017 | passed | 阶段D | `test_upload_retry_family.py` 6 passed（含线程并发） |
| F18 | UR-018 私人正文隔离 | AC-018 | not-run | 阶段G | — |
| F19 | UR-019 提取不漏题 | AC-019 | not-run | 阶段E | — |
| F20 | UR-020 审批/撤回互斥 | AC-020 | not-run | 阶段F | — |
| — | AC-021 幂等键 | not-run | 阶段C | — |
| — | AC-022 文件校验 | not-run | 阶段C | — |
| — | AC-023 迁移幂等 | not-run | 阶段B | — |
| — | AC-024 JD/旧数据 | not-run | 阶段J | — |
| — | AC-025 源状态变化 | not-run | 阶段D | — |
| — | AC-026 历史保留 | not-run | 阶段J | — |
| — | AC-027 可访问性 | not-run | 阶段H | — |
| — | AC-028 隔离集成 | not-run | 阶段J | — |

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

- [x] user 缺 Key 而 global 有效 → `MODEL_CONFIG_MISSING`（scope=user、action=configure_user_model），
      **0 次系统配置读取**（测试断言 global_loader 未被调用）。
- [x] user 配置解密失败同样不回退，且错误信息不泄露配置内容。
- [x] global scope 不借用用户私钥（user_loader 未被调用）；非法 scope 直接 ValueError。
- [x] 解析结果只暴露 `config_fingerprint`，`api_key` 不进 repr/model_dump（测试断言）。
- [x] `llm_quota.reserve_call` 事务内预留（不 commit）；旧 `_increment_usage` wrapper 保持 commit 语义
      （`test_llm_quota.py`/`test_llm_quota_concurrency.py` 回归通过）。
- [x] `reserve_llm_call` 账本 + 用户配额同事务原子；回滚一起回滚（测试用 BEGIN/ROLLBACK 验证）。
- [x] 配额不足抛 `QUOTA_EXCEEDED` 且不写账本；同一 `call_key` 重复登记抛 `CallLedgerConflict`；
      响应丢失可记 `unknown`；system 付费不占用用户日配额。
- [ ] 接受入口文件校验（分块上限、非图片拒绝、空文件列表）——未开始。
- [ ] 原稿/root/首个 job 同事务落库 + 两个入口绑定同一接受服务——未开始。
- [ ] `import_id`/幂等键/status_url/by-key 查询——未开始。

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
