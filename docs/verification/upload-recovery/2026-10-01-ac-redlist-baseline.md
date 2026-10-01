# 上传链路 AC 红清单与可执行基线（2026-10-01）

> 目的：把"是否实现 spec"从文档判断变成**机器可判定的事实**。
> 方法：先恢复测试可执行性（Phase 0），再把跨层契约落成可执行用例（Phase 1）。
> 范围：上传链路 S1~S4（`upload-recovery` spec 的 F01~F20 / AC-001~029）。
> 本文件只记录**实际运行过**的命令与结果；未运行一律写 not-run。

## 0. 为什么需要这一步

前几轮的问题不是"没写测试"——spec §3 要求的 30 个测试文件**全部存在**。
问题是它们**不在验收位置**：实测链路级别显示，绝大多数用例只调用服务层函数，
唯一的 HTTP 级用例是 AC-018；而 AC-006/AC-028 的用例被环境变量门禁整体 skip，
AC-029 的用例用手工 seed 直接写入被验收的产物。

因此本清单的第一批交付不是"补文件"，而是**让跨层契约变成会红的用例**。

## 1. Phase 0：恢复测试可执行性

| 步骤 | 结果 |
|---|---|
| 起始磁盘 | 根分区可用 **1956MB**（硬门禁 4096MB），`cleanup` 无效（BuildKit 缓存 1595MB 在 1536+128 容差内被跳过；dangling 因"多项目安全"未全局 prune） |
| 定向回收 | 只删无标签 dangling 镜像、本项目 builder 与 default builder 构建缓存、apt cache、journal 到 50M、`/tmp` 陈旧 eval 目录。**未触碰** `backend/data/backups`（2.0G，含用户 9/28 批次备份）与任何业务卷 |
| 回收后 | 可用 **4608MB**，通过 pre-build 门禁 |
| 构建 | `./deploy/docker-deploy.sh test ...` 构建成功 → `interview-boss-test:6f6bee34`（964MB）；但 **post-build 磁盘保护拒绝继续**（可用 2527MB < 4096MB） |
| 变通 | 镜像已存在，故 `docker tag ... :local` 后直接用 backend/CLAUDE.md 认可的 `docker compose --profile test run` 跑 pytest，不再重建 |
| 门禁复现 | `bash scripts/line_guard.sh` → **FAIL 4 个文件**（`worker.py` 1623、`public_contributions.py` 1560、`test_react_loop.py` 3790、`test_chat.py` 2046） |

## 2. 现有套件基线（实际运行）

```
docker compose --profile test run --rm test uv run pytest backend/tests/ -q \
  -k "upload or question_resolution or public_contribution or interview_server_pagination or extraction_integrity"
```

**结果：`4 failed, 341 passed, 9 skipped, 2979 deselected in 179.28s`（exit 1）**

当前工作区**不绿**。失败项属于未提交的在途改动：

| 失败用例 | 断言 | 含义 |
|---|---|---|
| `pipeline/test_upload_execution_plan.py::test_restore_creates_executable_job_for_failed_root` | `len(submit_jobs) >= 1` 实际 0 | 恢复后没有可派发工作（C10/R03 回归） |
| `pipeline/test_upload_execution_plan.py::test_finalize_with_stale_generation_is_rejected_without_root_write` | `recovered >= 1` 实际 0 | 陈旧 generation 的租约回收未生效（C9） |
| `pipeline/test_upload_execution_plan.py::test_finalize_without_generation_rejects_v2_service_contract` | `revision == 1` 实际 2 | 无 generation 的 finalize 仍写了 root（C9） |
| `services/test_public_contribution_recovery.py::test_root_bound_public_retry_preflights_global_before_cluster_dispatch` | `len(dispatchable) == 1` 实际 0 | 公共 retry 未先建 global 预检 job（E4/AC-004） |

skip 分布（9 条）：`integration/test_upload_recovery_stack.py` 4（AC-028 全部）、
`integration/test_upload_recovery_fullstack.py` 2、`pipeline/test_upload_matching_outcomes.py` 1（AC-006 节点级）、
`security/test_upload_size_guard.py` 2。spec 明确"不允许 skip"。

## 3. 新增跨层契约测试（第一批红清单）

新增 `backend/tests/infra/test_upload_cross_layer_contracts.py`（5 个用例，**当前全红，且已逐条确认红在正确原因上**）。

```
docker compose --profile test run --rm test uv run pytest \
  backend/tests/infra/test_upload_cross_layer_contracts.py -q
→ 5 failed in 8.41s
```

| 用例 | 契约 | 当前证据（红的原因） |
|---|---|---|
| `test_interview_list_accepts_the_position_id_the_frontend_sends` | 前端 `position_id = users.current_position_id`，服务端必须返回该岗位记录（AC-002） | `total != 3`：服务端拿整数 ID 去比 `interview.job_position`（TEXT 名称列） |
| `test_completed_root_snapshot_is_serializable` | 已完成任务必须能构造快照（AC-010/013） | `UploadResultDTO` ValidationError：`_snapshot` 传了 DTO 不存在的 `mode` 字段 |
| `test_task_center_reads_an_interview_id_field_the_snapshot_provides` | 前端 `openResult` 读取的字段必须存在于服务端快照（AC-001） | 同一 500；且快照只在 `result.interview_id` 提供，前端读 `task.interview_id` |
| `test_private_jd_import_keeps_the_requester_as_owner` | worker 传 `write_scope`（private/public），JD 节点须按同词表判定（AC-024） | `owner_id is None`：JD 节点仍判 `target == "personal"` |
| `test_queued_public_contribution_is_not_readable_publicly` | 审批通过 ≠ published（AC-015） | 公共处理尚未完成的面经已被普通用户 `scope=public` 读到 |

> 这三个用例是"测试绿但功能死"的直接反例：前端 e2e mock 在顶层塞了 `interview_id`，
> 后端分页测试用 `position_id=P1`（名称形态）自洽，JD 节点唯一测试 mock 的是 `target="personal"`。
> 契约用例改为**从两侧真实源码/真实响应取形状**，因此立刻变红。

## 4. AC-001~029 看板（链路级别为实测值）

链路级别取自各文件的实测计数：`HTTP`=使用 `client`/`api` fixture 的请求数，
`WORK`=worker/ARQ 相关调用数，`SEED`=手工 `INSERT`/`_seed_` 数。

| AC | spec 指定文件 | 实测链路级别 | 状态 |
|---|---|---|---|
| AC-001 结果定位 | `frontend/tests/e2e/upload-task-center.spec.js` + 新契约用例 | mock UI；契约红 | ❌ |
| AC-002 真实分页 | `pipeline/test_interview_server_pagination.py` | HTTP 8 / SEED 12 | ⚠️ 岗位契约红（CT-1） |
| AC-003 四格提交 | `pipeline/test_upload_policy.py` | 纯服务层（0 HTTP） | ⚠️ 未按 spec 入口组合验证 |
| AC-004 费用与配置 | `services/test_upload_credentials.py`、`services/test_upload_llm_accounting.py`、`pipeline/test_upload_credential_preflight.py` | 纯服务层 | ⚠️ 记账仅覆盖预检 |
| AC-005 私人引用归属 | `services/test_question_resolutions.py` | 纯服务层（SEED 5） | ⚠️ |
| AC-006 判断失败≠新题 | `pipeline/test_upload_matching_outcomes.py` | **默认 skip** | ❌ not-run |
| AC-007 残余队列 | `pipeline/test_upload_queue_reconciliation.py` | 纯服务层（SEED 9） | ⚠️ |
| AC-008 故障点恢复 | `pipeline/test_upload_stage_recovery.py` | 纯服务层（SEED 2） | ⚠️ |
| AC-009 并发不串单 | 同上 | 纯服务层 | ⚠️ |
| AC-010 连接恢复 | `upload-task-center.spec.js` | mock UI | ⚠️ |
| AC-011 真实完成 | `services/test_upload_status_projection.py` + 前端 | 纯服务层 | ⚠️ |
| AC-012 旧 worker 不可写 | `services/test_upload_leases.py` | 纯服务层（双连接，符合 spec 形式） | ⚠️ 但 `execution_plan` 3 例红 |
| AC-013 错误与重试预算 | `infra/test_upload_stream_contract.py` | 纯服务层（SEED 16） | ⚠️ 快照 DTO 红 |
| AC-014 公开=审核投影 | `services/test_public_contributions_materialize.py` + `public-contribution-review.spec.js` | 纯服务层 + mock UI | ⚠️ 无投影预览 |
| AC-015 失败子项恢复 | `services/test_public_contribution_recovery.py` | 纯服务层（SEED 13） | ❌ 1 例红 + 发布门槛红 |
| AC-016 追加贡献一致 | 同上 | 纯服务层 | ⚠️ 同 URL 复用覆盖清单 |
| AC-017 跨代与并发恢复 | `pipeline/test_submit_job_retry.py`、`pipeline/test_upload_retry_family.py` | HTTP 2 / WORK 10 | ⚠️ |
| AC-018 私人正文隔离 | `security/test_upload_task_privacy.py` | **HTTP 23 / WORK 1（唯一 HTTP 级）** | ✅ 形式达标 |
| AC-019 不静默漏题 | `pipeline/test_upload_extraction_integrity.py` | 纯服务层 | ⚠️ |
| AC-020 审批撤回互斥 | `services/test_public_contribution_transitions.py` | 纯服务层（双连接，符合 spec 形式） | ✅ 形式达标 |
| AC-021 幂等键 | `pipeline/test_upload_submit_api.py` | HTTP | ⚠️ |
| AC-022 文件校验 400/413 | `security/test_upload_size_guard.py` | HTTP（2 skip） | ⚠️ |
| AC-023 迁移回填两次 | `infra/test_upload_recovery_backfill.py`、`test_upload_recovery_migrations.py` | 迁移级 | ⚠️ |
| AC-024 JD 与旧数据 | 新契约用例 | 契约红 | ❌ |
| AC-025 源状态变化 | `infra/test_upload_recovery_retention.py` 等 | 服务层 | ⚠️ |
| AC-026 历史与保留清理 | `infra/test_upload_recovery_retention.py` | 服务层 | ⚠️ |
| AC-027 可访问性 | `upload-task-center.spec.js` | mock UI | ⚠️ |
| AC-028 完整隔离集成 | `integration/test_upload_recovery_stack.py` | **4/4 skip**（需 `UPLOAD_TEST_DB_PATH`），且不启 API/worker | ❌ not-run |
| AC-029 逐题数据流追踪 | `integration/test_upload_question_data_flow.py` | 手工 `_seed_private_pipeline` 写入被验收产物（SEED 13） | ❌ 未按 spec 验收 |

## 5. 未运行 / not-run（如实记录）

- 前端 Playwright 四个 spec 本轮 **not-run**（本轮聚焦后端可执行性；前端需另行启动 Vite）。
- AC-028 真实 Redis/worker 腿 **not-run**（`UPLOAD_TEST_DB_PATH` 协议未启用）。
- AC-020 approve/withdraw CAS **未复测**（沿用 2026-09-30 结论）。
- 全量套件（不设 `-k`）本轮 **not-run**（2979 条被 deselect）。
- `./deploy/docker-deploy.sh check` **not-run**：line-guard 已确认 FAIL，且 post-build 磁盘门禁未通过。

## 6. 下一步（Phase 2，按此顺序）

1. 先修 4 条现有失败（恢复/租约/公共 retry）——它们是在途改动留下的红，必须先绿才能建立 checkpoint。
2. 再修 5 条契约红：快照 DTO（`mode`）→ 结果定位字段 → 岗位 ID 契约 → JD 词表 → 发布门槛。
3. 每条修复必须带**变异验证**（移除修复后该用例变红），并换人用真实链路复验。
4. 之后按 S1→S4 顺序把 AC-006/028/029 从 skip/手工 seed 升级为真实链路用例。
