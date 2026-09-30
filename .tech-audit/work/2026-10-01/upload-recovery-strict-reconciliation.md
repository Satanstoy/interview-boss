# Upload-Recovery Spec 严格对账（2026-10-01）

> 目的：按用户要求"继续仔细分析 spec 的各项要求，看看是不是真正的对齐，而不是虚假的对齐"。
> 方法：回归 spec（`docs/superpowers/specs/2026-09-29-upload-recovery/{README,contracts,acceptance}.md`），
> 派出前后端两个只报代码事实的子代理采集调用点，Lead 对**每个决定性结论做独立二次验证**
> （grep/读源码，不信任单一份报告）。本报告只记录代码证据，与 NUMBER 无关。
> 结论分级：✅ 真正对齐 / ⚠️ 部分对齐（有实现但有缺口）/ ❌ 未对齐（helper 存在但未接入，或默认路径不可达）。

## 0. 一句话结论

**这不是虚假对齐，但也不是 spec 对齐——而是"V2 功能默认关闭、仅 V2=1 时部分成立"的条件对齐。**
生产部署（docker-compose 未设置 `UPLOAD_RECOVERY_V2`）下，上传入口全部走旧路径，前端已改造成
V2 的界面（任务中心/幂等提交/needs_action）在旧路径下**看不到任何 V2 任务**；V2=1 开启后，
仍有多处契约缺口（节点级凭据 scope、预检记账、匹配三态、阶段快照、公共路径 resolution 等）。

---

## 1. 决定性发现（虚假对齐核心，已独立验证）

### 1.1 `UPLOAD_RECOVERY_V2` 默认 OFF，且全仓只有一处 gate
- `backend/app/core/config.py:48`：`UPLOAD_RECOVERY_V2 = os.environ.get("UPLOAD_RECOVERY_V2", "0") == "1"`
- 全仓生产代码仅 `backend/app/routers/submit.py:141,467` 两处分支使用。
- `docker-compose.yml` 与 `deploy/` 无任何地方设 `UPLOAD_RECOVERY_V2=1` → **生产部署默认关闭 V2**。
- contracts §兼容层-9 要求"灰度 feature flag 默认 off；先跑迁移和隔离回归，再前后端共同启用"——
  从字面看默认 off 符合，**但**前端已发版成 V2 界面（见 1.2），"前后端共同启用"从未发生，
  处于"后端 off、前端 on"的错配状态，即：前端新界面长期指向不存在的 V2 数据。

### 1.2 V2=0 时前端上传/任务中心的真实行为（已独立验证）
- V2=0 时 `POST /api/submit-jobs` 走 `_create_job()`（submit.py:534 起）：只 INSERT jobs+payload，
  **不读 Idempotency-Key**（函数签名接受 header 但 legacy 分支不消费）、不写 `upload_imports`、
  无 policy/预检/检查点。
- 前端 `submitUploadWithIdempotency`（useSubmitJobs.js:356）先 `fetchUploadImportByKey(key)`，
  命中才复用——V2=0 时 `upload_imports` 无行 → 永远 404 → 每次都是"新建"，**幂等语义完全失效**；
  POST 后再查 by-key 依然 404（因为没有行可查），"响应丢失恢复"分支永不触发。
- 前端任务中心 `loadUploadTasks` → `GET /api/upload-imports`（v2 表）→ V2=0 时表空 → **任务中心空白**，
  StagingPanel 提交后 attachJob 订阅的是旧 `jobs/{id}/stream`。用户看到的仍是旧上传 SSE，看不到"任务中心"。
- `_legacy_sse_via_accept_service`（V2=1 时旧 SSE 入口走统一接受服务）；V2=0 时 `submit-stream-v2`
  仍 **直接 `stream_submit_graph(input_state)`**（submit.py:152-154）→ 违反 contracts §8
  "禁止保留两套可写图执行入口"。两套可写入口并存：V2 worker 图 + 旧 SSE 直启图。

### 1.3 worker 分流无隔离（contracts 兼容层-10）
- worker dispatcher（worker_scheduled.py:200）统一按 `SUBMIT_IMPORT_JOB_TYPE` 分发到
  `submit_import_task`；该函数靠 `job_row["root_import_id"]` 有无决定走 V2 还是 legacy 逻辑
  （worker.py:652-656）。不存在"v2 任务只能由兼容 worker 执行"或"禁止交给旧 worker"的隔离——
  因为只有一个 worker 函数，V2 与 legacy 混在同一处理函数内按行分流。
- 好处：legacy job 兼容执行（root_import_id NULL → root/policy 空 → 纯旧行为路径仍走通）。
- 问题：V2 表的保护只对 V2 job 生效；无法证明"开启后 legacy 与 v2 双轨不会错乱"，且没有观测项区分。

---

## 2. V2=1 时已真正对齐的部分（✅，含独立验证）

| 项 | 证据 | 独立验证 |
|---|---|---|
| accept 统一入口：稳定 import_id + 幂等 + policy 落库 | upload_lifecycle.accept_upload；submit.py:467 V2 分支 | ✅ 读源码确认 |
| 预检 job 真实探测（models.list pending ping）+ needs_action 阻塞 | credential_preflight.py:225-249 build_bare_client | ✅ |
| worker 按 root 读 policy 贯穿 share 意图 | worker.py:615-645 _load_root_context | ✅ |
| 恢复重建可派发 work + 旧 retry 绑定 root | upload_lifecycle.restore_upload；routers/submit.py retry | ✅ |
| 根状态聚合 + 快照统一（allowed_actions） | finalize_attempt_and_aggregate_root；upload_imports._snapshot | ✅（字段有占位，见 §3.5） |
| F08 检查点复用（成功阶段结果持久化 + 短路不重跑 LLM） | worker.py:662-694 + extract/classify 短路 | ✅ 子代理+读码 |
| F09/F12 lease_generation fencing（claim 递增 + 根聚合强校验） | worker.py:582,591 + upload_lifecycle.py:297-310 | ✅ 子代理+读码 |
| 旧 job 接口 owner-only 越权修复 | bank_build.py（is_admin 分支删除 + 404） | ✅ 上轮已验 |
| 前端幂等提交/草稿保留/needs_action 不 resetForm 的实现 | useSubmitJobs.js:356, StagingPanel.vue:245-260 | ✅ 子代理 |
| 前端任务中心按钮由 allowed_actions 驱动、无暂停 | UploadTaskCenter.vue:253, upload_status.py:79-108 | ✅ 子代理 |
| SSE 退避 1/3/10s+抖动、15s 轮询兜底 | http.js:555-560, UploadTaskCenter.vue:99-133 | ✅ 子代理 |
| 查看结果定位（页码/岗/高亮 query 消费） | AuthenticatedLayout.vue:650-685 + DataTable highlight | ✅ 子代理 |
| 面经列表循环拉全（服务端 total → 循环取页） | useMasterBankData.js:103-131 | ✅ 子代理（但见 §3.1） |

## 3. 未对齐 / 部分对齐（V2=1 下仍成立的契约缺口）

### 3.1 面经列表仍"前端假分页"（contracts §4.5 未满足）❌
- `DataTable.vue` 全 client 模式：`:total-count="rows.length"`（:5）、`:total="rows.length"`（:130）、
  totalPages=ceil(rows.length/pageSize)、paginatedRows=rows.slice —— **仍以 rows.length 为 total 且前端 slice**。
- 服务端 `interviewTotal`（useMasterBankData.js:83 赋值）**无任何消费方**（grep 全仓 0 引用），
  layout 解构/provide 均不含它，未传给 DataTable。
- 影响：功能上"数据全量拉取所以分页可用"，但这是以全量拉取掩盖分页，spec 明确禁止
  （契约 4.5："不再以 rows.length 作为总数或再次 slice 分页；共享 DataTable 增加 server 模式"）。

### 3.2 节点级凭据 scope 未接入（R01/README 二对二表格）❌
- worker input_state 已传 `credential_scope`（worker.py:760），但 extract.py:66 / classify.py 仍调用
  `get_llm_client_for_user(user_id)` **不读 state["credential_scope"]**；
  `tag_questions_batch` → submit_service.py:159 同样默认 user scope（llm.py 有 llm_scope 参数未传）。
- 影响：管理员公共导入（global 预期）的 extract/fill/tag 实际仍用提交者本人凭据；
  普通用户 share 审核后公共聚类也仍用其 user 凭据 —— 违反"公共阶段用 global、绝不用提交者 Key"。

### 3.3 预检不做调用记账 / 不存指纹（contracts §2.1.5 未满足）❌
- `credential_preflight.py` 成功只写 stage result `{"provider":..,"latency_ms":..}`，**丢弃**
  probe 返回的 model 与 config_fingerprint（:244-246），且**不写 upload_llm_calls 账本**。
- `reserve_llm_call`/`complete_llm_call`（upload_credentials.py:194/268）生产**零调用点**。
- 契约要求"每次 ping 独立记账……绑定 provider/model/config_fingerprint"（AC-004）→ 未实现。

### 3.4 ERROR_POLICY 无 scope 维度（contracts §4.4 未满足）❌
- upload_retry_budget.py:22-33：MODEL_AUTH_INVALID / MODEL_CONFIG_MISSING 均为
  `action="configure_user_model"`、`scope="user"` —— 无 global 分支。
- 契约要求 global scope：管理员 → `configure_system_model`；普通用户公共 → `wait_for_global_model`
  + `retry_after_configuration`。唯一 scope 感知处在 upload_credentials.py:151-163（不在 ERROR_POLICY 表）。

### 3.5 阶段快照 counts/review_status 是占位（AC-013/contracts §2.1.3 未满足）❌
- `upload_imports._stage_counts`（:47-62）按**阶段检查点行数**统计：extracted=total_done、
  retained=total_done、excluded=count_values.get("excluded",0)（该 key 从不提供→恒 0）、
  needs_review=0 硬编码、resolved/answered=非 extract/classify 的 succeeded 行数 —— 非逐题统计。
- 仅 SSE stream 传 counts（:316）；list/by-key/detail/retry 快照 counts 默认全 0。
- `review_status` 恒 None：`upload_imports.contribution_request_id` 列**全库零写入**，
  finalize 内 review_status 计算（upload_lifecycle.py:343-350）依赖它 → 恒空；快照从不传该字段。

### 3.6 匹配三态未接入真实节点，模型失败被当 unmatched（AC-006 未满足）❌
- `match_outcomes`（matcher.py:721-891，含 failed + strict 漏答→MODEL_OUTPUT_INVALID）**生产零调用**。
- persist_personal 节点用两态 `match_new_questions`；`match_new_questions` 在模型异常时
  整组归 `still_unmatched`（matcher.py:969-972）→ 401/超时/网络错与"真正无候选"无法区分。
- upload_resolution_link 支持 failed 三态，但 matched 数据源是两态结果 → failed 只覆盖
  "无匹配且 write_unmatched=False"，不覆盖"模型失败"与 no_match 后才允许建同 scope 题的决策。
- 队列异步成新题路径（operations.py:657-661）绕过节点决策，AC-006 反例（401/超时不得建 canonical）未封闭。

### 3.7 公共路径无 resolution / 无审计 / contribution_request_id 不落根（AC-015/README admin 列 未满足）❌
- persist_public_node：非 admin 直接 PermissionError、admin 直写 approved（submit_interview_txn_tag_only）、
  不写 upload_stage_results、不调 link_details_to_import（公共明细无 resolution）。
- `upload_imports.contribution_request_id` 只读不写；root 表 never 关联其公共化申请（worker 在 graph 后
  新建 request 但不回写 root 行）。
- `audit_public_import` 只是 policy 布尔（upload_policy.py:202）→ worker 用它算 is_admin；**无任何审计落库函数**。
- 影响：AC-003/README 第 3 节"管理员显式公共导入视为记录了审批的公共处理"没有审计记录实体。

### 3.8 analysis_queue 超时回收仍按 created_at（contracts §2.5 未满足）❌
- queue.py:141-145 `_recover_stuck_processing`：`WHERE status='processing' AND created_at < now-30min`；
  表已有 `locked_until` 列（migrations/upload_resolution.py:95）未用；dequeue 只写 processed_at。
- 契约："超时用 locked_until，不用 created_at"（§2.5）→ 未满足。

### 3.9 enqueue_questions 首轮 root_import_id 落 NULL（AC-007 收尾依赖兜底）⚠️
- 8 个生产调用点**无一显式传 root_import_id**；全靠 queue.py:67-79 从 questions_detail.import_id 兜底。
- 该列唯一写入点在 upload_resolution_link（persist_personal 内 enqueue **先于** link、公共节点从不 link）
  → 首轮入队 root NULL，恢复轮才回填。AC-007"每个合法桶都被选中"在首轮对 root 归属失效。

### 3.10 resolved_type（contracts §1.1 auto 识别）未接入 ❌
- `accept_upload`/repository 有 resolved_type 参数但生产调用从不传；submit router 硬编 `source_type="interview"`。
- "auto 识别后记录 resolved_type" 无落点。

---

## 4. 验收矩阵（acceptance.md）逐条对应

| AC | 内容 | 对账 |
|---|---|---|
| AC-001 结果定位 | 前端 query 消费真实 | ✅（切岗无 toast，仅列表重拉，偏差小） |
| AC-002 真实分页 | 服务端 total 循环拉全 | ⚠️ 数据拉全但 DataTable 仍 client 分页（3.1） |
| AC-003 四格提交策略 | accept+policy+8 组合 | ⚠️ V2=1 时成立；V2=0 不存在；审计缺（3.7） |
| AC-004 费用与配置 | 预检+记账+scope | ❌ 预检无记账/指纹（3.3），节点级 scope 未接（3.2） |
| AC-005 私人引用归属 | resolution 三态+可见性 | ⚠️ 三态实现存在但节点数据源两态（3.6） |
| AC-006 判断失败≠新题 | 401/超时不得建 canonical | ❌ 失败归 unmatched，与 no_match 不区分（3.6） |
| AC-007 残余队列推进 | 桶全选+reconciler | ⚠️ 首轮 root NULL（3.9）；recovery 轮 OK |
| AC-008 故障点恢复 | 检查点+不重复 | ✅（F08 测试 4 故障点隔离验证） |
| AC-009 恢复不重复成果 | 幂等/attempt | ✅ |
| AC-010 任务中心 | 前端实现 | ✅（但 V2=0 任务中心空，见 1.2） |
| AC-011 根状态聚合 | finalize+revision | ✅ |
| AC-012 generation fencing | claim 递增+拒写 | ✅（recover 不递增的窗口间隙为次要缺口） |
| AC-013 快照一致 | counts/result/allowed_actions | ⚠️ counts 是检查点行数占位（3.5） |
| AC-014 JD/面经分派 | 审批按 source_type | ✅（V2=1；V2=0 无此路径） |
| AC-015 发布按 resolution | 公共发布 resolution 驱动 | ❌ 公共路径无 resolution（3.7） |
| AC-016 同 URL 复用 | 公共物化复用 | ✅（V2=1） |
| AC-017 恢复可工作 | restore 建 job | ✅ |
| AC-018 旧接口 owner 隔离 | 静态+SSE | ✅ |
| AC-019 提取完整性 | schema/ordinal/黑名单 | ✅（V2=1） |
| AC-020 approve/withdraw CAS | BEGIN IMMEDIATE+revision | ✅（未复测，见 5） |
| AC-021~029（跨层） | 幂等、任务中心、分页、公共化、恢复 | ⚠️ AC-028/029 隔离测试存在；AC-029 真实链路 1 条腿；AC-028 真实 redis 腿 not-run |

## 5. 未执行项（环境受限，如实 not-run）

- Docker test-runtime 完整复跑：根分区 2.9G < 4G 硬门禁，deploy 脚本拒绝构建（不可绕过）。
- AC-028 真实 ARQ+Redis 栈腿：无 test-profile redis 服务，未跑。
- AC-020（approve/withdraw CAS）本轮未复测，保持上轮结论。

## 6. 结论与建议

1. **必须先决策灰度开关**：要么开启 `UPLOAD_RECOVERY_V2=1`（并完成 §3 缺口），
   要么前端回退到旧界面；当前"前端 V2 界面 + 后端 V2 off"是明确的错配交付，用户实际体验
   是任务中心空白、幂等提交失效——这正是用户担心的"虚假对齐"形态。
2. **真实缺口清单**（按影响排序）：3.2 节点级 scope、3.3 预检记账/指纹、3.4 ERROR_POLICY scope
   维度、3.5 快照 counts/review_status、3.6 匹配三态、3.7 公共 resolution/审计、3.1 DataTable
   server 模式、3.8 locked_until、3.9 enqueue root、3.10 resolved_type。
3. 本报告未修改任何代码/测试；前 20 项 reconciliation.tsv 标记的"passed"需按本报告重新分级，
   建议写入 `.tech-audit/work/2026-10-01/reconciliation-v2.tsv` 后再逐项修复。

证据来源：本会话两个事实采集子代理（前端 10 问/后端 12 问）+ Lead 独立二次验证的 grep/读码；
未使用推测性描述；所有结论可回查文件:行号。