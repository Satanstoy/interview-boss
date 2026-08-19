# 评测中心（Eval 子系统）深度审查 — 2026-08-18

**仓库**: InterviewBoss · **Stack**: Python/FastAPI + SQLite + ARQ/Redis · Vue 3 SPA
**HEAD**: ca6231f9 (2026-08-18) · **范围**: 单套 Eval、Experiment 一键全跑、Run 证据、质量/执行区分
**审查结论**: codex 消息里"当前真正缺的主要是……"大多已在当前代码实现；真正的问题是 4 个功能性 bug/缺口 + 若干小项。

## 一、codex 提议现状核对（逐条对照真实代码）

| codex 提议 | 现状 | 结论 |
|---|---|---|
| 1. 新增 capabilities API，前端不再硬编码 | `GET /api/admin/evals/capabilities` 已实现（`routers/admin_evaluation.py:374-453`），`EvaluationTargetPicker.vue` 已读后端 `can_run`/case_count/reason | ✅ 已实现 |
| 1b. 线上旧构建显示"待接入" | 当前 nginx 镜像已包含 `EvaluationExperimentsView`（含 capabilities、运行全部 Eval、查看证据），"待接入"仅存在于硬编码回退路径 | ⚠️ 需强刷/确认浏览器缓存 |
| 2. 单套 Eval 完整闭环（自动选择 release、Case 数、Judge、创建后端跳转、Run ID 恢复、失败重跑） | 前端 `EvaluationExperimentsView.vue` + `EvaluationRunView.vue` 已全部实现 | ✅ 已实现 |
| 2b. "执行 1 Case Smoke" 入口 | 前端的创建按钮始终全量执行；后端 `CreateEvalRunRequest.case_keys` 支持但前端从不传 | ❌ 缺失 |
| 2c. 创建前成本/耗时警告 | 无 | ❌ 缺失 |
| 3. Run 详情看证据（输入快照/transcript/工具轨迹/tool intent/Hard Gate/Judge/混合分/Attempt） | `GET /runs/{id}/items/{item_id}` 已实现，前端证据抽屉已渲染 case/item/attempts/artifacts | ✅ 已实现（但有证据读取问题，见 B4） |
| 3b. artifacts 查询 API | 无独立 `/artifacts` 端点；artifacts 内嵌在 item 响应，且 `eval_artifacts` 生产零写入 → 索引恒空 | ❌ 死脚手架 |
| 4. Experiment 父级模型（一键全跑、子 Run、SSE、取消、总进度、分类汇总） | `eval_experiments/eval_experiment_runs/eval_experiment_events`（migration 095）+ 路由 + `EvaluationExperimentView.vue` 已实现 | ✅ 已实现 |
| 4b. `GET /experiments` 列表端点 | 无列表端点（只有 POST /experiments + GET /{id}）；前端也列的是 runs 而非 experiments | ❌ 缺失 |
| 5. 区分"执行完成"与"质量通过" | `_quality_status()`（router:226-244）+ 前端 `quality_status` 徽章已实现 | ✅ 已实现（"执行已完成/质量未通过"双态） |
| 6. 验收标准 | Smoke、成本警告、experiment 列表、artifact 内容未达标；其余基本满足 | ⚠️ 部分 |

**一句话**：codex 报告对应的是旧快照；当前工作树+已部署 nginx 里，方案的大部分主体已落地，剩余是 4 个真实缺陷 + 少量补全项。

## 二、🔴 / 🟡 发现

### D14-1 🔴 重跑失败 Case 在 1 小时内会静默失效（ARQ job-id 复用）
- **位置**: `app/evaluation/queue.py:24-35`（enqueue 固定 `_job_id=f"eval-run-{run_id}"`）+ `routers/admin_evaluation.py:1179-1273`（retry-failed 原样复用同一 job id）
- **问题**: ARQ `enqueue_job` 对同一 `_job_id` 会在 `job_key`/result_key（`keep_result=3600s`）仍存在时返回 `None` 而非抛错。首次执行完成后 result_key 保留 1 小时，用户看到失败立即点"重跑失败 Case"时 enqueue 返回 `None`，但路由代码仍将 run 置为 `queued` 并写 `run.queued` 事件（`dispatch_error` 保持 None）→ **Redis 里根本没有 job，run 永久卡在 queued**。
- **修复**: retry 时使用递增的 job id（如 `f"eval-run-{run_id}-{attempt}"`），或 enqueue 返回 None 时回查/回滚状态并报 dispatch_error；补一条 ARQ 返回 None 的回归测试。

### D14/D12-2 🟡 created 状态的孤儿 Run 无法恢复
- **位置**: 路由 create_run / create_experiment 的 enqueue 失败路径 + retry_failed 的守卫（`run["status"] not in {"failed","completed","cancelled"}` → 409）
- **问题**: 创建时 Redis 抖动导致 enqueue 抛错，run 停留在 `created`（此时 failed_items=0），而 `retry-failed` 要求 failed>0 且 status 为终态 → 该 Run 没有任何重投/重试入口，成为死数据；Experiment 子 run 若在入队中途断连同样卡死。
- **修复**: 提供 `created` → requeue 端点（或允许 retry-failed 处理 created+pending），并补 frontend 提示 dispatch_error。

### D14-3 🟡 get_run_item 证据读取活表而非冻结快照
- **位置**: `routers/admin_evaluation.py:1064-1138`（`case` 从 `eval_benchmark_cases` 当前行取 input_snapshot/contract）
- **问题**: 双轴模型下执行端用 `eval_runs.snapshot_json` 冻结快照（executor `case_snapshots`），但取证 API 返回的是 `eval_benchmark_cases` **当前** 行。Case 后续被编辑/停用（active=0）时，历史 Run 的证据展示与实际执行的输入不一致，违背 ADR 0022/0024 不可变上下文。
- **修复**: 对 `evaluation_release_id` 非空的 Run，item 的 case 输入/契约改从 `snapshot_json.cases` 取；补 Case 编辑后证据不漂移的回归测试。

### D9/D1-4 🟡 eval_artifacts 是死脚手架（生产零写入）
- **位置**: migration `evaluation.py:181-192` 建表；唯一 INSERT 在测试里（`test_admin_evaluation_api.py:209`）；生产/executor 从不写。
- **问题**: 前端"Artifact 索引"与"单个 Artifact 中查看"文案恒为空；真实证据（transcript/工具轨迹/Judge 原文）寄生在 `eval_attempts.raw_observation_json`/`eval_items.result_json` 里，judge 原文（raw response）实际未保存（judge.py 只存 parsed 结果）。
- **修复**: 二选一——item 完成时把关键证据物化为 artifact 落盘并暴露内容端点；或删表+删 UI 文案并对齐"证据在 Attempt 快照中"。

### D12/D15-5 🟡 缺 GET /experiments 列表 & Experiment 无法从历史进入
- **位置**: 路由无 `GET /api/admin/evals/experiments`；前端历史仅列 runs
- **修复**: 新增 experiments 列表端点（limit/status），ExperimentView/Results 加实验历史入口。

### D12/D14-6 🟡 SSE/GET 实验详情在只读路径上写库
- **位置**: `experiment_events` 与 `GET /experiments/{id}` 每 0.5s 调用 `_refresh_experiment`，内部执行 UPDATE + commit（并可能 append event）。
- **问题**: 只读 GET/SSE 带写副作用；多浏览器/多标签同时轮询时写放大且可能产生竞态（同一 sequence 并发计算 → UNIQUE 冲突 500）。该部分业务逻辑也全在 router（1316 行，接近红线区）。
- **修复**: 派生状态改惰性读，或在变化时才写并加锁/幂等；把 `_refresh_experiment` 等编排下沉到 service/control-plane。

### D15-7 🟢 无 Smoke（1 Case）与成本/预计执行量提示
- 后端已支持 `case_keys` 但前端从不传；加"执行 1 Case Smoke"按钮并展示 replication×case 的预计执行量与成本估算。

### D9-8 🟢 归档 legacy suite 仍保留 12 个 active case
- 线上 `eval_benchmark_suites` id=1（release 2，`benchmark_suite@1.0`，status archived）仍带 12 个 active case；`sync_builtin_benchmarks` 只归档 release 未清理其 case。capabilities 按 evaluation release 计数不受影响，但 schema 存在冗余活性记录（live 总 active case=39 vs catalog 期望 27）。

## 三、已确认良好的部分
- 双轴模型（target+evaluation release + snapshot 冻结）与 legacy 兼容读取实现扎实；capabilities 返回结构完整（adapter/release/case/reason）。
- 质量/执行双态拆分（`_quality_status`）在 run、experiment、列表三端一致；Judge 失败不会被硬门禁吞掉（scoring 注释明确"不因硬断言失败隐藏 Judge"）。
- Run SSE 断线恢复（Last-Event-ID + after_sequence）、取消、retry-failed 的基础流均已打通；测试覆盖充分（`test_admin_evaluation_api.py` 704 行等）。
- Eval worker 已上线且 heartbeat/launcher/timer 就绪；线上已有 5 类 published target+evaluation release 与 Experiment #1 真实运行（3/39 case 完成，5 个子 run 入队），并非"待接入"。

## 四、建议修复里程碑
| 项 | 里程碑 | 工作量 |
|---|---|---|
| D14-1 intjob 碰撞 | M-eval-retry-jobid | 2h（含回归测试） |
| D14-3 快照取证 | M-eval-evidence-snapshot | 2-4h |
| D14-2 created 恢复 | M-eval-created-requeue | 2h |
| D9-4 artifacts 落地或删除 | M-eval-artifacts-cleanup | 半天 |
| D15-5/6/7 列表+SSE 只读+Smoke | M-eval-frontend-polish | 1 天 |
