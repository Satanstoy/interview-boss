# 上传恢复 spec 与问题 TSV 复审（2026-09-30）

审查对象：`8c810733`，分支 `codex/frontend-ui-hierarchy-cleanup`。范围为上传、个人/公共题库、审核、恢复、查询与 AC-001～029；本次本人审查，没有派发子 agent。没有修改业务代码、操作生产数据库或重做用户已处理的 28 日数据清理。

**结论：不能关闭原问题 TSV，也不能宣布完整 spec 验收通过。** 多数新模块停留在辅助函数和服务层测试，实际 worker、旧上传界面及发布回调仍运行旧路径。原 TSV 的 F19 黑名单删除已修；F20 审批/撤回互斥已接实际路由。本轮未重新运行后端测试，因此 F20 标为 `implemented_not_retested`；F19 的完整 AC 仍缺实际节点结构校验。F14 面经审核显式编辑已生效，但真实快照结构、岗位继承和 JD 审核仍有问题。

基准：9 月 29 日 TSV 共 20 条，其中前 13 条与 9 月 28 日重复，不能按 33 条计算。原 TSV 保留历史；本轮对应关系在 [reconciliation.tsv](../../.tech-audit/work/2026-09-30/reconciliation.tsv)，按根因合并后的 12 项发现见 [findings.tsv](../../.tech-audit/work/2026-09-30/findings.tsv)。`open` 表示真实路径仍存在原问题，`partial` 表示已有部分实际修复但未满足整个 AC，二者均不能关闭。不是按测试文件是否存在判定修复。

## 1. 实际验证范围

| 验证 | 本轮结果 | 能证明什么 |
|---|---|---|
| 最新提交、工作区及真实调用链审查 | 完成 | 下列断点来自实际入口/worker/持久化路径；不是仅凭函数名推测 |
| AST 调用点清单 + 全文搜索反证 | 完成 | 12 个关键 helper 在 `backend/app` 无直接调用；另人工检查动态入口及原路径 |
| Playwright 任务中心 + 逐题流程两个文件 | **8 passed，24.8s，exit 0** | 仅模拟接口的 UI 行为；日志仍有未模拟 GET 的 localhost:8000 拒绝连接 |
| Docker 后端定向回归 | **not-run，测试脚本 exit 1** | 构建前磁盘门禁：2948 MB < 4096 MB；pytest 未启动，不是业务断言失败 |
| 真实 API + SQLite + Redis + worker + 浏览器 | **not-run，且现有 AC-028/029 测试内容不完整** | 无法以已有服务层/模拟接口测试替代 |
| 生产数据回填、线上配置和模型供应商探测 | 未执行 | 本报告评估源码，不能推断线上已部署或完成迁移 |

本轮命令：

```bash
# 从仓库根目录执行；在构建前被磁盘预检阻断
./deploy/docker-deploy.sh test -q \
  -k 'upload or question_resolutions or public_contribution or interview_server_pagination or extraction_integrity' \
  --ignore=backend/tests/integration/test_upload_recovery_stack.py

cd frontend
npx --no-install playwright test tests/e2e/upload-task-center.spec.js \
  tests/e2e/upload-question-data-flow.spec.js --reporter=line

# 只解析源码，不导入应用、不连接数据库
cd ..
python3 .tech-audit/work/2026-09-30/trace_calls.py
```

原始日志在本地 `.tech-audit/work/2026-09-30/{targeted-tests,frontend-tests}.log`，遵守仓库规则不提交日志。[调用点证据](../../.tech-audit/work/2026-09-30/callsite-evidence.json)及生成脚本随本报告保存。AST 仅枚举直接名称/属性调用，调用链结论同时由源码人工核对支持，不能单独把零调用等同于不可达。

## 2. 原 20 条逐项结论

| 原问题 | 当前状态 | 还缺什么 | 复审项 |
|---|---|---|---|
| F01 结果定位 | partial | 任务结果未贯通，岗位参数类型不一致，定位页仍只是本地切片 | R04/R09 |
| F02 100 条截断 | partial | 后端已支持分页，前端仍仅取第一页 100 条 | R09 |
| F03 四格提交 | partial | 普通 share 审核意图没有进入 worker；管理员公共直写缺审计闭环 | R02 |
| F04 凭据/预检 | partial | 没有真实可用性探测，实际模型调用没有贯穿 scope/payer | R01 |
| F05 公共命中关系 | open | `record_resolution` 没接真实题目写入 | R05 |
| F06 失败误判新题 | open | 实际匹配仍将异常加入 unmatched | R05 |
| F07 队列续调 | open | root 未传入队列；新 job 类型没有派发/执行接续 | R06 |
| F08 检查点恢复 | open | 实际 graph 不读写阶段检查点；保存与入队仍分事务 | R03 |
| F09 同秒串单 | open | graph 仍使用用户 ID + 秒级时间 | R03 |
| F10 SSE 恢复 | partial | 新任务中心改善，旧提交订阅和恢复仍保留原缺陷 | R08 |
| F11 真实完成 | open | worker 未聚合根任务与下游工作；新 root 状态不推进 | R04 |
| F12 租约/fencing | open | 实际 worker 未接 generation；实际队列仍看 created_at | R06 |
| F13 统一协议 | partial | GET/SSE 字段不一致，错误及重试预算未贯通 | R04/R08 |
| F14 审核投影 | partial | 面经显式编辑生效；默认字段取错快照层级，JD 路径回归 | R11 |
| F15 失败贡献恢复 | partial | retry 接口存在，但实际发布仍用旧逻辑、恢复未完整派发 | R10 |
| F16 同 URL 追加 | open | 新物化无查重合并，刷新清单 helper 未接发布 | R10 |
| F17 跨代重试 | partial | 新接口只有 attempt；旧 retry 仍只看直接子任务 | R03 |
| F18 私人正文隔离 | open | 旧 job stream 的管理员越权读取仍在 | R07 |
| F19 提取丢题 | partial | 原黑名单缺陷已修；实际提取结构校验、ordinal 与计数仍未对齐 | R05 |
| F20 审批/撤回竞态 | implemented_not_retested | 实际路由已接 CAS/写事务；本轮后端复测受环境阻断 | — |

## 3. 需要修正的实际调用链

以下 R01～R12 对应本轮 findings.tsv，severity 均为 3。影响各不相同，建议修复顺序见末节。

### R01 · D10：预检只判断配置存在，实际使用的凭据仍可能不同

`upload_lifecycle.py:346` 只调用同步配置解析器，没有 provider/model ping，也没有 `credential_preflight` job。普通用户 share 的 policy 首阶段为 user，入口只检查 user，未按最新 AC-004 先检查公共 global。审批 `finalize_public_contribution_approval` 也没有 global 重新探测。

更关键的是，`agents/submit/extract.py:57,66` 仍调用 `get_llm_client_for_user(user_id)` 和旧重试器。即使管理员公共导入在入口检查了 global，提取仍按管理员 user_id 选择配置。`reserve_llm_call` 没有实际调用，账本/预算单测不能证明真实费用归属。入口 strict user-only 读取的修复有效，但只解决了接受阶段的一部分问题。

修改要求：先持久化 root 和原稿；创建可恢复的预检工作；private 验 user，public 目标先验 global，普通 share 另验首阶段 user；以本地模型 stub 验证 401/404/timeout。失败不派发提取，更新 `needs_action`；配置修复后同 root 恢复。所有模型阶段使用服务端策略解析出的 scope/payer，不再自行从 actor_id 猜配置；公共批准后重查 global。

### R02 · D4：四格策略在执行时丢失

`upload_lifecycle.py:318` 的 payload 没有 `request_public_review`；`worker.py:566` 构建 graph 输入也没传 policy/root/attempt/审核意图。`persist_personal.py:194` 却仅在 `state.request_public_review` 为真时创建贡献申请，因此普通 share 只会按私人路径保存。管理员公共路径 `persist_public.py:24` 则直接写 `approved`，没有 spec 要求的显式公共导入审批审计与处理中发布隔离。

修改要求：worker 按 root 读取完整服务端 policy，所有初次执行和恢复复用它；不要靠增加一个前端字段补洞。普通 share 在同一事务内保存私人来源与审核快照；管理员 share 留公共导入审计记录。用四种身份/目标组合真正跑到 worker 后查归属、审核、可见性与模型调用 scope。

### R03 · D14：恢复没有恢复执行，检查点和唯一执行标识未接入

`restore_upload`（`upload_lifecycle.py:202`）仅查/建 active attempt、改 attempt_no，未生成任何待执行 job/payload，未复查配置、未推进 status/revision。HTTP retry 路由原样返回；失败任务即使得到 200，也不因此继续处理。已失败 job 的 attempt 也没有真实完成/失败收尾路径。

`graph.py:146` 仍用 `MemorySaver`，`:164` 仍使用用户＋秒级时间作为 thread_id。新增 `build_thread_id`、`save_stage_result/get_stage_result` 均未被生产路径调用。`persist_public.py:32` 的实体提交和后面的 `enqueue_questions` 仍分开。旧 `submit.py:665` retry 仅检查直接 child，创建的新 job 不带 root/attempt，仍可绕过活跃后代。

修改要求：恢复事务内规划同 root 的未完成/失败 work_key 并写可派发工作，不重新做成功阶段；旧 retry 解析根任务后调用同一服务。graph 从 root/attempt/job 生成唯一 ID，模型阶段先读检查点，成功后按版本写检查点；业务实体、resolution、下游工作同事务。用真实 worker 在保存前后中断并恢复，断言成功阶段调用次数与实体 ID 不变。

### R04 · D15：根任务不推进，任务中心收到的快照缺按钮和结果

`worker.py:522` 只调用 `complete_job`。生产代码没有调用 `aggregate_status`，也没有 worker 更新 `upload_imports.interview_id/status/revision` 的路径；新增 root 可停在最初的 queued，即使旧 job 已完成。

`routers/upload_imports.py:28` 的列表/详情/retry 快照没有 `allowed_actions/stage/progress/counts/result`；新任务中心按 allowed_actions 渲染按钮，终态任务不订阅 SSE，所以不能期待 SSE 补齐缺字段。SSE 路径又采用另一 DTO，`:220` 把所有 succeeded 阶段行数当作 answered，并非逐题答案数。

修改要求：完成/失败/审核/重试均在持久化事务中聚合根任务并递增 revision；列表、详情、by-key、retry、SSE 使用同一完整快照构造器，按实际问题单元统计 counts。最终读取下游聚类/标签/答案结果后才完成，保存面经不等于全流程完成。

### R05 · D9：逐题关系和匹配错误处理没有进入真实节点

`persist_personal.py:107` 仍调用旧 `match_new_questions`，该函数在 `matcher.py:970` 将异常整组加入 unmatched。新三态 `match_outcomes` 与 `record_resolution` 没有生产调用，公共命中的私人来源仍缺可追溯关系；模型判断失败仍可能进入新题路径。

F19 原黑名单已改保留标记，这是实际修复。但 `extract.py:76` 仍直接迭代模型输出：清单是字符串会被拆成字符，混入 null/数字会静默过滤，计数仍称 excluded=0。`normalize_extracted_questions` 只在测试等路径使用；真实节点未做同等校验。

修改要求：在实际 extract 节点统一校验并固化 ordinal；detail 写入 import_id/source_ordinal；匹配失败持久化可恢复失败，不生成新 canonical；每道保留题的 public/private canonical 都写有效 resolution。验收要从真实上传生成这些记录，禁止由 fixture 代替被测节点写结果。

### R06 · D14：补单不能被执行，旧超时回收仍会误回收

`pipeline/queue.py:70` 的实际入队不写 root_import_id；`upload_queue.py:40` 的补单仅扫描 root 非空行，漏掉真实上传产生的队列。即使补出 job，`:94` 写入类型为 `analysis_batch`，而 `job_lifecycle.py:28` 的 dispatcher 注册类型不含它，且无对应有效 payload/执行适配。

`pipeline/queue.py:107` 仍按 created_at 回收 processing，领取时间和创建时间混用。实际 `worker.py:513` 仍用旧 claim；`claim_job_with_generation/assert_job_fence` 未接到 worker 及业务提交，阶段事件才 touch 也不能替代长模型调用期间的独立心跳。

修改要求：真实入队传 root/scope/position/work_key；桶 job 注册派发与执行器，批次结束及定时对账都推进剩余桶。领取、心跳、业务提交和回收使用同一 generation/locked_until 规则。用多 owner、多岗位、大于 batch_size 的真实队列测试排空与旧 worker 写入拒绝。

### R07 · D5：旧 SSE 仍向管理员暴露他人私人结果

`routers/bank_build.py:33` 的 SQL 仍是 `(? = 1 OR created_by = ?)`；`:62` 将完整 jobs.result 返回管理员。submit worker 会把提取结果写入 jobs.result，因此知道 job_id 的管理员仍可通过 `/api/jobs/{job_id}/stream` 读取他人私人正文。新 root 的 owner-only 接口不能补上这个旧入口。

修改要求：所有可返回正文/题目/结果的旧 job 接口也做内容归属校验；运维权限只给白名单元数据。补该真实路由的负向测试，使用私人 marker 检查整个响应体，不能只测 `/api/upload-imports`。

### R08 · D15：界面实际提交没有使用新恢复协议

`StagingPanel.vue:239` 仍 `createSubmitJob → attachJob(result.job_id) → resetForm`，没有调用新增 `submitUploadWithIdempotency`。如果 v2 返回 needs_action 且 job_id=null，这里仍按提交成功处理和清空草稿。草稿幂等键未用于实际提交，响应丢失不能靠新增未调用的 helper 去重。

旧 `useSubmitJobs.js:170` 调 getSSE 只传 signal，没有 `isTerminal`；`http.js:621` 仅传入该回调时才正常 EOF 重连。旧 `restoreActiveJobs` 查询失败后仍用空列表清理本地任务；done 后 5 秒移除仍在。新任务中心的修复不自动覆盖这些路径。

修改要求：实际提交、任务中心和恢复统一围绕 import_id；缺配置保留 root/草稿并展示正确 scope 的操作，响应丢失按相同幂等键查回。迁移旧job入口，缓存按用户隔离；失败查询保留已有任务。测试必须点击真实提交按钮并检查请求头、返回状态和任务卡片，不只预设列表。

### R09 · D15：列表仍截断，位置接口混用岗位名称与 ID

`useMasterBankData.js:75` 无参调用 `fetchInterviewData`，后者默认 page=1/page_size=100；DataTable 仍以 rows.length 当 total、本地 slice。后端已经从“最早 100 条”改为“最新 100 条”，新上传可见性有所改善，但完整分页仍未实现。

`data.py:1047` 将 `target.job_position`（名称字符串）作为 position_id 返回；`:414` 又将传入 position_id 直接与岗位名称列比较。`AuthenticatedLayout.vue:654` 将返回值 `Number(position)` 后切岗位。真实名称与 mock 的数字 1 不一致，跨岗位定位可能 404/切换失败。页面也未统一清理招聘季和排序等冲突筛选；location 页大小固定 20，与用户选定大小可不同。

修改要求：定义真正的岗位 ID/名称契约并在服务端转换；location 与列表使用相同筛选和 page_size。面经页面消费 server total/page，切筛选归 1，主动打开结果清冲突筛选；其他共用表格保留本地模式。使用 121 条、跨岗位、非默认页大小数据，从浏览器断言实际目标行可见。

### R10 · D14：公共贡献恢复和发布判断仍使用旧路径

新 retry 路由已存在，但 `retry_failed_public_items` 仅入队/改子项状态，路由未像审批统一入口那样调度聚类。实际 `enqueue_questions` 使用 INSERT OR IGNORE，`migrations/jobs.py:100` 的唯一索引覆盖同面经/明细/owner 的 failed 行；已有失败队列行不会新增，也没有 UPDATE 将其复位 pending。因此会出现 item 已 queued、原队列仍 failed 的假恢复。测试必须用已有 failed 队列行，而非只插入 failed item。

实际 worker 仍调用 `mark_public_contribution_queue_done`（`:1173`），直接把队列完成的 item 标 published，不验证当前 public resolution。`publish_items_with_resolutions` 和 `refresh_public_interview_projection` 均无生产调用。`approve_public_contribution_v2` 仍接受 failed 状态并重新物化，不能替代恢复同一批失败子项。

`materialize_public_interview_from_projection:483` 无条件 INSERT，不查复用同 URL 面经；因此旧“追加清单不更新”没有形成正确合并语义，改成重复实体也不是解决。新面经 questions_list 在批准时就包括所有保留项，而不是实际已发布项。

修改要求：保留审核决定和 projection_hash，技术失败只恢复失败子项，复用 queue/detail；派发可执行工作。成功发布以有效 public resolution 为准，与列表投影更新同事务；同 URL 追加到确定来源实体并验证无重复。批准与失败恢复分开。

### R11 · D14：新审批入口引入 JD 和来源字段回归

`approve_public_contribution_v2:629` 无条件调用面经物化，再写公共题目并进入分析队列。真实 JD 申请会生成一个 jd_document item（`:176`），所以并非空列表被安全 skip，而是被当作面经 item。`public_jd_id` 不会正确生成。这违反 AC-014/024。

此外，真实 snapshot 是 `{source: {...}, items: [...]}`（`:75,158`），而 `build_review_projection:378` 用 `snapshot.get(field)` 读取默认字段；未显式编辑的 focus/season/difficulty 等会丢失。`:629` 也未传岗位，面经物化 job_position 默认空；它会改变岗位隔离/筛选语义，不能按“默认所有岗位可见”掩盖丢失。

修改要求：在共享 CAS/审核事务内按 source_type 分派受审投影物化，JD 只写 JD、显式跳过题目流程；使用真实嵌套 snapshot 的 source 读取允许继承的字段，敏感字段仍按显式公开规则；保留受服务端控制的岗位。用 `create_public_contribution_request → HTTP approve` 测试真实快照形状，而非手造扁平 snapshot。

### R12 · D3：已有“E2E”未证明要求的数据流

`test_upload_recovery_stack.py` 检查 Redis 前缀变量，但不连接隔离 Redis、不启动 API/worker；重启场景是手写检查点后直接调用 restore_upload。其同秒测试比较 helper 输出，没有运行实际 graph。

`test_upload_question_data_flow.py:192` 通过 `_seed_private_pipeline` 手动插入 detail/canonical/checkpoint/resolution；后续直接调用发布服务。它能验证部分服务组合，不能证明上传提取、分类打标和 worker 的连接关系。前端同名测试第一例只打开空任务中心，第二例预填失败/完成 mock，最后只验证 URL，没有上传或校验目标题目行与标签。

修改要求：保留这些服务测试，但不得记为完整 AC-028/029。新增隔离 HTTP→持久任务→Redis/worker→模型 stub→浏览器的流程，明确断 worker 再启动，逐题检查 5 道私人题、排除后 4 道公共题、失败时 3 道已发布题；恢复后成功阶段 ID/调用数不变，分类、标签、resolution、来源和可见性全部可追溯。拒绝用测试代码手填这些被验收产物。

与既有技术债 `D3-mocked-playwright-contract-drift` 有交叉，但这里的“AC-028/029 未执行实际上传链路”是本轮新增验收声明缺口，不是把全部旧前端测试债务重新记账。

## 4. AC-021～029 与已有数据

| 验收 | 本次结论 |
|---|---|
| AC-021 幂等键 | 后端原语存在；真实前端提交未接，同键失联恢复不能关闭 |
| AC-022 输入校验 | 后端校验代码存在；needs_action 成功响应仍清空前端草稿，跨层未完成 |
| AC-023 回填 | CLI、manifest、重复 apply 服务测试已有；本次没有复跑，也没有生产 manifest/迁移结果可作为本轮证明 |
| AC-024 JD/旧数据 | 新审批路由 JD 回归；旧 retry 未统一。已有单测只验证接受 JD 时队列暂为空，没执行后续审核 |
| AC-025 源状态 | 恢复 helper 检查部分源删除；真实 worker 提交前复查、岗位退休/分类版本变更未形成完整链路 |
| AC-026 保留清理 | root/job payload 保护已加入；本轮未复测，不能从中推断完整恢复有效。analysis_queue 的 30 日清理仍需纳入长期失败恢复验收 |
| AC-027 可访问性 | 本轮 mock UI 用例通过；不能代替真实接口下的按钮/焦点验收 |
| AC-028 隔离全栈 | 尚缺要求的真实 API/Redis/worker/浏览器联合执行 |
| AC-029 逐题数据流 | 已有服务组合测试，但实际上传→分类标签→审核→聚类→恢复链路未验收 |

仓库默认 `UPLOAD_RECOVERY_V2=0`（`core/config.py:48`）。本轮未读取线上配置，不能假定已经开启；即便开启，也仍有上述链路断点。已有数据回填须保留 dry-run/manifest/idempotent apply 证据，不能靠打开开关自动重放历史数据。用户已清理的 28 日三个批次保持原决定，不重新创建、恢复或清除。

## 5. 建议修复与复验顺序

| 批次 | 工作 | 可关闭条件 | 粗估 |
|---|---|---|---|
| A | R07 私人正文旧接口；R11 JD/投影回归 | 真实路由负向隐私测试、JD 审批只产生公共 JD、真实快照保留允许字段 | 1～2d |
| B | R01/R02/R03/R04 贯通任务执行 | 四格上传真实跑完、目标 scope 真实探测、失败配置后同 root 继续、状态可追溯 | 5～8d |
| C | R05/R06/R10 逐题持久化与公共发布 | 多桶排空、异常不造新题、逐题 resolution/标签正确、恢复不重复、发布清单一致 | 5～8d |
| D | R08/R09 前端接入 | 真实提交幂等、断线保留、跨页/跨岗位结果确实可见 | 2～3d |
| E | R12 完整验收与回填演练 | AC-028/029 用隔离全栈跑完，所有未执行项保留 not-run；再决定是否开 v2 | 2～3d |

粗估用于排顺序，存在共享工作，不能将每项简单相加当排期承诺。A/B 的缺陷应先处理；最终关闭原 TSV 必须关联修复提交和覆盖真实路径的测试证据。
