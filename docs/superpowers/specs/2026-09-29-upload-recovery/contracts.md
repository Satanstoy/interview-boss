# 数据、执行和接口契约

本文属于[主规格](README.md)，状态与主规格一致。所有新字段名先在仓库查重；名称冲突时迁移设计中明确映射，不并存两个同义字段。

## 1. 存储增量

### 1.1 `upload_imports`：稳定业务任务

| 字段 | 类型/约束 | 用途 |
|---|---|---|
| id | TEXT PRIMARY KEY，UUID | import_id |
| requester_id | INTEGER NOT NULL，FK users | 谁提交，不因重试改变 |
| idempotency_key | TEXT NOT NULL | 客户端一次提交的随机键 |
| request_hash | TEXT NOT NULL | 服务端规范化输入hash，含图片字节hash、目标、岗位、招聘季 |
| target_intent | CHECK private/share | 用户意图；不是最终公共写权限 |
| source_type | CHECK interview/jd/auto | auto识别后记录resolved_type |
| resolved_type | TEXT nullable | 识别出的类型 |
| position_id | FK job_positions nullable | 接受时岗位ID；历史无法映射时nullable |
| position_name | TEXT NOT NULL | 接受时岗位名称快照 |
| input_version | INTEGER NOT NULL DEFAULT 1 | 输入修订版本 |
| pipeline_version | TEXT NOT NULL | 写入时固定实现版本 |
| policy_json | TEXT NOT NULL | 服务端策略；不存Key |
| payload_json | TEXT NOT NULL | 原稿/图片或受限对象引用，v1允许现有base64格式 |
| status | TEXT NOT NULL | 根状态，见主规格 |
| current_attempt_no | INTEGER NOT NULL DEFAULT 0 | 当前恢复批次 |
| interview_id | FK interview nullable | 入库后稳定引用 |
| contribution_request_id | FK public_contribution_requests nullable | share申请 |
| revision | INTEGER NOT NULL DEFAULT 1 | 根快照单调版本 |
| error_code/error_message | TEXT nullable | 脱敏错误，不存原始HTTP认证头 |
| created_at/updated_at/completed_at | UTC timestamp | 返回统一ISO8601 UTC |
| payload_expires_at | UTC timestamp nullable | 完成后90天；未完成不自动失去恢复材料 |

唯一约束`UNIQUE(requester_id,idempotency_key)`。同键同hash返回同一个根任务；同键不同hash返回409 `IDEMPOTENCY_CONFLICT`。相同内容但不同键不自动跨用户去重，也不能泄露他人已上传；同scope同URL重复沿已有规则返回可解释冲突，能关联本人原任务时返回其import_id。

### 1.2 `upload_attempts`：一个业务任务的恢复批次

字段：`id INTEGER PK, import_id FK, attempt_no INTEGER, status TEXT, requested_by FK users, created_at, completed_at`。

- UNIQUE(import_id,attempt_no)。
- status仅`active/completed/failed/superseded`。
- partial UNIQUE(import_id) WHERE status='active'。
- 一个active attempt可包含多道题的并行工作；不能把“一个活跃尝试”误解成全系统只跑一个job。
- 退避中的工作仍属于active attempt；单纯再次点击恢复返回该attempt，不重置退避或绕过配额。
- 所有计算工作停止且需人工干预时关闭该attempt为failed；根任务可为needs_action/partial_failed/failed。审核等待不保持active attempt。

### 1.3 复用`jobs`，不新建第二套任务队列

新增nullable字段：`root_import_id FK upload_imports`、`upload_attempt_id FK upload_attempts`、`work_key TEXT`、`lease_generation INTEGER NOT NULL DEFAULT 0`。旧jobs允许上述引用为NULL。

v2 work_key例：`credential_preflight:initial:v1`、`credential_preflight:public:v1`、`extract:document:v1`、`classify:document:v1`、`cluster:root:v1`、`answer:public:456:v1`。每个root/job_type/work_key最多一个pending/queued/running job，使用partial unique index兜底，retry可新建failed历史行之后的尝试。

`parent_job_id`继续用于运行血缘，不能再作为整个任务族唯一去重依据。批量共享job无法用一个root表达多根任务时，本期禁止新v2批次跨root合并；保留旧批次逻辑仅消费root_import_id IS NULL的遗留队列，避免错误归属。

jobs本身是事务outbox：创建实体/步骤结果时同事务INSERT pending jobs+payload；COMMIT之后才best-effort通知ARQ。无需额外引入Kafka或另一个通用outbox框架。

### 1.4 `upload_stage_results`：步骤检查点

字段：`id PK, import_id FK, stage TEXT, unit_key TEXT, input_version INTEGER, pipeline_version TEXT NOT NULL, status TEXT, result_json TEXT, output_hash TEXT, error_code TEXT, retryable INTEGER, job_id FK jobs, created_at, updated_at`。

UNIQUE(import_id,stage,unit_key,input_version)。同一root的pipeline_version固定；pipeline_version列用于校验，不在普通恢复时改变。stage：`credential_preflight/extract/classify/persist/resolve/answer/review/publish`；unit_key：`initial:<scope>`或`public:<scope>`（预检）、`document`、`detail:<id>`或`canonical:<scope>:<id>`。

status：`pending/running/succeeded/skipped/failed/needs_action`。skipped必须有reason。result_json存结构化中间产物，不只保存百分比；extract保留完整提取题目和稳定ordinal；classify保留逐ordinal分类及taxonomy_version；persist保存interview_id与ordinal→detail_id映射。

只复用相同input_version/pipeline_version约定下的成功成果。普通恢复不改变已成功步骤的版本；新版管线不兼容旧检查点时阻塞为`PIPELINE_VERSION_UNSUPPORTED`，不要偷偷从头执行。

### 1.5 原题与规范题关系

`questions_detail`新增nullable `import_id FK upload_imports, source_ordinal INTEGER`；UNIQUE(import_id,source_ordinal) WHERE import_id IS NOT NULL。ordinal来自完整提取结果，过滤不能重新编号导致重试写错题。

新增`question_resolutions`：`id PK, detail_id FK, occurrence_scope TEXT, occurrence_owner_id FK users nullable, canonical_id FK question_bank nullable, canonical_scope TEXT nullable, status TEXT, taxonomy_version TEXT, pipeline_version TEXT, input_version INTEGER, confidence REAL nullable, decided_at, invalidated_at, reason TEXT`。

- occurrence_scope仅private/public；private必须owner非NULL，public必须NULL。
- status为matched/created/needs_review/failed/invalidated；matched/created必须canonical_id非NULL。
- 每detail最多一个未invalidated的当前resolution；partial UNIQUE(detail_id) WHERE invalidated_at IS NULL。
- private occurrence只可关联本人私人canonical或已published公共canonical；public occurrence只可关联公共canonical。
- 数据库跨表scope约束用服务写入校验+必要触发器/事务测试保证，不能仅靠前端选项。
- 个人命中公共题不改公共sources/frequency。`mine`包含本人原题引用的公共canonical，用`EXISTS`去重；仅本人能看到自己的来源关联。
- 公共canonical软删除/重聚类时在同事务invalidated对应resolution，原题不删除；重新进入待关联状态，历史练习/笔记ID通过redirect保留。v1不自动跨类别强行匹配。

### 1.6 队列和scope串行

`analysis_queue`新增nullable root_import_id、job_id及lease_generation、locked_until、claimed_at；现有owner_id保留。唯一键至少包含(detail_id,scope,pipeline_version)，将现有仅detail_scope的唯一约束迁移为能区分显式重分析版本的约束；迁移前先报告重复，不能盲删。

新v2 dequeue必须筛选root_import_id+岗位+owner，且JOIN未删除的原文/明细；公共还要有有效批准投影。不同root可能写同一公共聚类池，因此新增`upload_scope_leases(scope_key PK, holder_token, generation, locked_until)`；scope_key是`position_id:public`或`position_id:user:<owner_id>`。

共享池模型决策到写入期间必须拥有scope租约，心跳续租；实际写入再验证generation。不得把长LLM调用包在SQLite写事务内。scope租约可让计算暂时串行，先保证正确性；以后优化候选快照并发需单独设计。

### 1.7 调用记录与费用

新增`upload_llm_calls(id PK, root_import_id FK, stage, unit_key, call_key UNIQUE, credential_scope, payer_type, payer_user_id nullable, provider, model, config_fingerprint, status, input_tokens nullable, output_tokens nullable, started_at, finished_at, error_code nullable)`。

call_key识别一次物理外部尝试；重试是新call_key并记录关联步骤。status包括reserved/succeeded/failed/unknown。只记录配置指纹，不记录Key或原始认证头。供应商可用性预检的最小ping也写此账本，stage=`credential_preflight`、tokens按实记、payer与预检scope一致，不能绕过配额；配置缺失时不发网络请求、不虚构调用记录。

user调用使用现有每日调用配额，先增加不自行commit的事务接口，允许配额预留和call记录原子提交。禁止在外层业务事务里调用当前会内部commit的`_increment_usage`。global调用记system，不伪装成管理员私人消费；增加按system+day的调用计数，复用同样的原子预算判断。

v1建议配置：UPLOAD_MAX_LLM_CALLS_PER_IMPORT=200；UPLOAD_SYSTEM_DAILY_CALL_LIMIT=1000；测试覆盖参数化小值。它们是运行保护值，不宣称等于金额预算，项目所有者可在部署配置覆盖。user同时受现有DAILY_LLM_CALL_LIMIT约束。

外部请求已发出但响应丢失时记录unknown，不承诺供应商“精确扣费一次”。重复计算可能发生，但业务写入必须幂等；UI/运维应能看到重复调用成本。禁止把网络超时直接当未消费并无限退还额度。

## 2. 核心执行算法

### 2.1 接受上传

1. 校验认证、target枚举、岗位、输入类型、文件数量/MIME/字节上限；非法值返回明确400/413，不静默改target。
2. 对图片分块读取并累计大小；先检查可用的UploadFile.size；不能先读完整大文件再拒绝。不支持格式明确报错，不能跳过所有文件后仍创建空任务。
3. 服务端计算policy与request_hash，不做任何模型处理。通过policy确定必须预检scope：私人目标为提交者user；公共目标必须包括global/system；普通用户公共申请若私人暂存阶段需要user模型，还要包括提交者user。个人scope必须由严格的本人配置读取器解析；禁止使用缺失时回退global的通用配置函数。
4. BEGIN IMMEDIATE：查幂等键；新建根任务、attempt、payload，并按policy为每个必需scope创建独立、持久的`credential_preflight` job；COMMIT。配置缺失也必须保留根任务和对应预检job，置为可恢复的`needs_action`，不能因预检失败回滚已接受的上传。此时不得派发提取/分类/聚类工作。重复同键请求返回同一root和现有预检job，不另发探测。
5. 每个`credential_preflight`先用短事务按scope预留配额并写`reserved`调用账本，COMMIT后在事务外执行最小连通性ping；不得持SQLite写锁等待网络。每次结果再用短事务更新调用账本状态并保存该scope预检结果/配置指纹：所有必需scope通过后才原子创建首个业务job；任一失败则root进入needs_action、记录阻塞scope和允许动作，且不创建业务处理job。ping响应丢失记`unknown`，不能当作免费或已成功。普通用户公共上传因global失败时显示等待管理员修复，不能要求用户改个人Key。
6. 返回202含稳定import_id、job_id、status、revision和status_url；`job_id`可以是尚待执行的预检job。缺少配置时可直接返回可恢复`needs_action`；真实provider探测异步完成后再更新状态。ARQ不可用仍保留任务，不返回“上传失败”诱导用户生成另一幂等键。

### 2.2 步骤执行和fencing

1. 根据job_id原子claim，lease_generation递增，得到本次唯一fence；holder不能只用PID。
2. 读取根输入、scope和成功检查点；核实当前实体仍可处理；根据持久授权决定公共写入，不信任旧payload.is_admin。
3. 取得policy要求的scope租约；业务模型job开始前确认该阶段scope预检成功、配置指纹未变；预检最多复用120秒，指纹改变或超时则重新预检。任何user→global或global→user处理阶段切换必须重新预检，不受120秒缓存影响。预检必须实际验证正确provider/model连通可用，不能把配置字段非空当成可用。scope配置缺失、无效、解密失败、鉴权失败或模型不可用时进入needs_action，保留已完成成果且不运行后续工作。不能切换到其他scope兜底。探测的最小ping记录为独立账本调用并计入相应scope预算。
4. 事务外调用模型；由独立心跳续job/scope lease，间隔30秒；建议lease=120秒，测试用可注入时钟。
5. BEGIN IMMEDIATE：检查job_id、generation、有效租约、scope lease、输入版本和删除标记。任意不匹配ROLLBACK，旧worker不得写业务表。
6. 同事务写本步骤成果、下游pending工作、聚合revision，再标本job完成；COMMIT后通知ARQ。
7. 异常统一分类；自动重试不超过3次物理尝试/步骤，第1、2次失败后分别退避30、60秒（第3次失败后不再排下一次）；401/权限/输入/额度不自动重试。

固定语义：阶段成功与下游安排不存在“保存成功但没有任何后续任务记录”的缝隙。提取后保存检查点即允许进程重启；LangGraph MemorySaver只作单次运行缓存，不能作为恢复依据。thread_id使用import_id+attempt_no+job_id，不使用秒时间戳。

普通用户share任务有scope边界：提交时先预检目标global/system公共模型，且在私人暂存/分类/匹配前预检并使用提交者user scope；管理员批准审核投影后，公共聚类/标签按global/system scope重新预检和记账。不能沿用提交时的global预检结果，也不能在任何global预检失败时回退到提交者配置。管理员直接公共导入从首个模型阶段起使用global/system scope；管理员私人导入使用管理员自己的user scope。用户scope预检不能使用`get_user_llm_config`这类缺省时回退global的通用读取路径；必须覆盖真实上传默认解析器在user配置缺失、global有效时仍阻断的回归。

### 2.3 匹配与写入

`match_new_questions`返回每个输入ordinal的显式结果：matched(canonical_id)、no_match、failed(error_code,retryable)。模型返回漏题/重复ID/越界ID属于结构错误，不当no_match。

规则：同类别无候选允许no_match；模型调用失败只能failed；分类不同但相似不自动强并；scope不匹配立即拒绝写入。保存resolution和新canonical、来源投影在一个写事务内，检查fence与输入版本。

删除既有来源/旧聚类贡献不得在LLM调用前不可逆提交。重新分析先计算新结果，成功后同事务替换关联；失败保留旧可用成果并标识陈旧。

本期答案工作只为本次首次创建的规范题建立。命中已有规范题且已有答案时记录reuse_existing_answer；已有规范题无答案时记录existing_canonical_answer_outside_import，展示“引用已有题，答案暂缺”，不把它计为本次生成成功。公共规范答案补齐仍可走现有独立维护任务，不能每个引用root重复触发。用户个性化答案属于另外的私人任务。

### 2.4 恢复同一业务任务

事务伪算法：

```text
BEGIN IMMEDIATE
  authorize(requester, root_import)
  resolve_legacy_job_to_root()
  if active_attempt_exists: return existing attempt after COMMIT
  if no_failed_or_blocked_work: return current snapshot after COMMIT
  validate_required_configuration_and_budget()
  if still_blocked: retain needs_action; return actionable conflict after COMMIT
  create next attempt number under root unique constraint
  select only failed/blocked/missing work with unchanged input version
  insert missing jobs using stable work_key
  update root current_attempt_no, revision and status
COMMIT
notify ARQ best effort
```

对A→B→C历史链中的任何job发retry都先解析root，不能只查询parent_job_id=A的直接子项。不会因手动retry重置已成功阶段或让已运行任务重复。

### 2.5 队列续调与对账

- 一批完成后先持久化下一批工作再结束本次调度责任；同root剩余pending不能只等下一次上传。
- 每60秒reconciler扫描合法pending桶，给无活跃job的桶建立幂等job。要同时考虑root、owner、岗位及版本。
- 超时用locked_until，不用created_at。过期job恢复后旧generation写入必须失败。
- 每次选桶按最早可用时间轮转，不能永远选数量最多的公共桶。测试设置连续公共流量，私人桶也必须在有限轮次被选中。
- 孤儿、被删除原文、不再有效的批准投影转可解释blocked/invalidated并终止空转，不偷偷删除证据。

## 3. 审核投影、发布和并发

### 3.1 审核请求结构

保留现有approve URL，替换无约束review_fields为严格模型；旧字段若传入未知内容返回422，不能静默忽略。

```json
{
  "expected_revision": 3,
  "excluded_item_ids": [12],
  "review_fields": {
    "source": {"company": null, "round": "一面", "focus": "数据库", "source_url": null},
    "items": [{"item_id": 11, "question": "说明数据库索引的工作原理"}]
  }
}
```

字段缺省：题干/分类继承该项快照；面经company/round继承source快照并默认公开；source_url及JD company/salary仍需管理员显式确认字段值才公开。null表示删除公开字段，不能回落到原始值；空字符串规范化为null。source_url若非空仅允许经过来源URL校验的http(s)。禁止修改requester_id、owner_id、原始snapshot或往审核对象添加任意DB列。

面经source允许company/round/focus/difficulty/season/source_url；items允许question/cat1/cat2/tags/difficulty，ID必须属于申请。岗位从源冻结，不允许在approve中偷偷换岗位。JDsource只允许job_title/tech_stack/bonus/position及明确确认的company/salary/source_url，不公开raw source正文/联系人；与ADR的结构化公开原则一致。

新增request revision及review_projection_json；投影含schema_version、最终source和items、排除项及原因、审核人、时间、hash。审批预览和物化共用同一构造函数；修改题干/分类后公共流水线使用新投影重新处理，原私人数据不修改。

### 3.2 原子状态转移

approve/withdraw/reject在**读取当前状态前**BEGIN IMMEDIATE，并校验expected_revision。UPDATE WHERE id=? AND revision=? AND status IN(允许集合)，rowcount!=1返回409 `STATE_CONFLICT`；随后同事务写事件和公共待处理工作。不要“事务外先读，事务内无条件写”。

允许：pending_review/changes_requested→approved_for_processing或withdrawn/rejected。failed技术状态不重新approve，使用公共处理retry入口；重复approve同revision/同投影可返回已有结果，不同投影返回409要求新审核版本。

withdraw成功后不能留下这一申请新建的可执行公共工作。已经批准返回409，不能假装撤回；本期不新增“处理中强制取消”。已published内容的来源撤销沿现有管理员复核规则，不能硬删公共canonical。

### 3.3 真正发布

批准创建staging公共投影而不是普通用户可见的approved面经全文。每个item必须持有当前有效public resolution才从processing转published。存在public_detail_id不是成功证据。

相同URL/相同明细已存在时查其实际resolution：成功可复用；failed/pending继续订阅或恢复该工作，不能直接published。关联申请用显式request item→detail→resolution，不把URL当所有权。

同事务重建公共面经questions_list，来源为published且未删除的items/details。多申请共享明细用EXISTS去重。一个明细仍pending时不能因为另一条题成功就提前出现在清单。

所有公开读取路径必须收敛公共可见性谓词：面经列表、experiences、题库、搜索、统计、来源展示、抽题及MCP。兼容旧公共数据：无新发布元数据的旧approved记录保持原口径；新v2记录必须检查发布门槛。

## 4. API契约

### 4.1 端点

| 接口 | 行为 |
|---|---|
| POST /api/submit-jobs | multipart；新增Idempotency-Key；返回202稳定import_id。兼容job_id |
| GET /api/upload-imports | 本人任务分页；status可选；默认created_at DESC,id DESC |
| GET /api/upload-imports/{id} | 本人完整快照；非本人404，包括管理员 |
| GET /api/upload-imports/{id}/stream | 本人SSE快照；非本人在响应流前404 |
| POST /api/upload-imports/{id}/retry | 恢复剩余工作，返回根任务快照及created_attempt布尔 |
| POST /api/submit-jobs/{job_id}/retry | 旧适配器：解析root后调用同一服务；无可靠root时needs_action |
| GET /api/jobs/{job_id}与/stream | 私人结果仅本人；公共治理job按公共权限；不得通用admin豁免 |
| GET /api/admin/upload-operations | 运维白名单分页，不返回正文、公司、文件名或原始错误 |
| POST /api/admin/public-contributions/{id}/retry | 仅批准后的失败公共子项，复用同一投影，不改审核状态 |
| GET /api/data/interview | 新增sort、season、position_id、scope和分页，旧响应items/total保留 |
| GET /api/data/interview/{id}/location | 同样授权/筛选/排序条件，返回所在page与目标岗位；不存在/无权限404 |

旧客户端缺Idempotency-Key：适配层生成键并返回，明确无法保证响应丢失后跨请求去重；新前端必须在用户开始一次提交时生成并持久保存键，重发复用。服务端响应丢失后的恢复：提供`GET /api/upload-imports/by-key/{key}`仅本人查询；查无记录才重发同键请求。

静态路由`by-key`须注册在动态`{id}`前。部署窗口内旧客户端可用，但完整恢复承诺只对新客户端成立；不能凭内容hash代替用户提交意图。

### 4.2 快照示例

```json
{
  "import_id": "demo-import-001",
  "revision": 9,
  "status": "needs_action",
  "target_intent": "private",
  "attempt_no": 1,
  "review_status": null,
  "stage": "answer",
  "progress": {"unit": "questions", "completed": 8, "total": 10},
  "counts": {"extracted": 10, "retained": 10, "excluded": 0, "needs_review": 0, "resolved": 10, "answered": 8},
  "result": {"interview_id": 123, "position_id": 1, "question_ids": [456, 457]},
  "error": {"code": "MODEL_AUTH_INVALID", "message": "请更新个人模型配置后继续", "retryable": false, "action": "configure_user_model", "scope": "user"},
  "allowed_actions": ["open_result", "configure_user_model", "retry_after_configuration"],
  "updated_at": "2026-09-29T00:00:00Z"
}
```

示例progress只代表answer阶段，不与根任务completed混同。review_status可以是pending_review/queued/published/rejected/withdrawn/failed；值映射保留原有申请语义。

运维白名单只返回import_id、job_type、scope、status、stage、attempt_no、耗时、脱敏error_code、next_retry_at、配置scope/provider/model；不返回payload、saved_data、result_json、来源URL、题干、图片、个人Key信息。

### 4.3 SSE

每次订阅立即返回完整snapshot；`event: snapshot`、`id: <revision>`、data为上述快照。每15秒发送注释心跳。快照轮询更新间隔不超过2秒，不为每次心跳增加revision。

v1不实现持久事件重放日志：断线后使用新完整快照收敛，Last-Event-ID只作版本提示；客户端忽略小于等于已有revision的业务更新。授权变化需重新订阅时重新鉴权；不能只相信本地缓存。

EOF且根任务不是completed/failed/partial_failed/needs_action/waiting_review时重新连接；网络断开显示“连接中断，后台任务继续”。等待审核/人工操作关闭SSE后在任务中心可见时每15秒GET，重新打开任务或窗口重新获得焦点时立即GET获取新状态。重连1、3、10秒退避，上限30秒加抖动；恢复API失败保留已有任务，不把失败当空列表。

退出账号abort全部连接、清单例、取消计时器，localStorage按用户分区；不删除服务器任务。正常关闭读取也在finally释放controller。服务端业务error记录在snapshot，避免与连接异常混用。

### 4.4 错误分类

| code | 自动重试 | 根状态/动作 |
|---|---|---|
| MODEL_AUTH_INVALID / MODEL_CONFIG_MISSING | 否 | needs_action；user scope返回`configure_user_model`；global scope的管理员任务返回`configure_system_model`；普通用户公共任务返回`wait_for_global_model`和`retry_after_configuration`，不能引导用户修改私人Key来绕过 |
| PERMISSION_REVOKED / SOURCE_DELETED | 否 | needs_action，解释权限/源状态，不擅自恢复删除 |
| QUOTA_EXCEEDED | 否 | needs_action，显示reset_at或预算调整入口 |
| UPSTREAM_RATE_LIMIT / UPSTREAM_TIMEOUT / UPSTREAM_UNAVAILABLE | 最多3次 | 退避queued；耗尽后failed/partial_failed |
| MODEL_OUTPUT_INVALID | 最多2次格式修复调用，计入总3次上限 | 再失败保留原文，不能当no_match |
| STATE_CONFLICT / IDEMPOTENCY_CONFLICT | 否 | HTTP409，刷新快照，不覆盖他人决定 |
| LEGACY_MAPPING_AMBIGUOUS | 否 | needs_action，人工确认映射 |

总重试次数只由一个步骤执行层控制，LLM helper的内部重试必须纳入同一预算或关闭，禁止“外3次×内3次”不记账。

### 4.5 面经列表

sort仅created_at_desc/created_at_asc，SQL稳定次序`created_at DESC,id DESC`或对应ASC；NULL日期统一视为最旧。默认page_size=20，范围1..100；scope仅all/public/mine，授权先于筛选。

COUNT和items必须同一个查询条件/一致读快照；筛选排序都在SQL LIMIT前。前端传服务端total给DataTable，不再以rows.length作为总数或再次slice分页。共享DataTable增加server模式，默认维持其他页面原行为。

location接口按同一稳定排序计算rank/page；如果岗位筛选排除目标，返回authorized目标position_id与建议筛选，但不返回其他人的存在性。仅主动“查看结果”时调整筛选和页码。

## 5. 历史数据、安全迁移和发布

1. 本基线最高迁移120；建议新增121 upload recovery core、122 resolutions/public projections。实施时若版本被占用，取下一个未用版本并更新本文和测试；禁止改已发布迁移内容。
2. 先加nullable字段与新表，旧数据仍可读。对旧submit_import按parent链建立root；检测循环/断链/多活跃后代，不猜测，写dry-run报告。
3. completed job仅在result.interview_id存在且owner/岗位匹配时关联现存面经。缺关联或保存后失败的job标legacy_mapping_ambiguous，不自动重新提取。
4. 已有原题公共引用不按模糊文本自动回填。只有明细ID/明确来源关系可证明时回填；否则保留原始材料并待重新匹配。
5. 历史published贡献不能仅信状态回填resolution；核查公共明细与规范题关系。已公开但缺证据的条目标迁移待核对，不直接批量删除。
6. 迁移脚本默认dry-run，输出counts、候选ID、冲突原因，不输出题干/图片/Key。`--apply`必须有匹配的manifest hash，重复运行不增加实体或attempt。
7. 现存5029/5030只作为需检查的历史案例；部署时重新查询，不把当日pending快照当当前事实。若原文已保存，只修复失败/缺失步骤，不重新上传。
8. 清理策略：活跃、needs_action、partial_failed和failed恢复任务及被其引用的payload不被旧90天清理删除。completed超过90天仅清大payload/checkpoint正文，保留import摘要和结果引用；历史恢复材料缺失返回SOURCE_EXPIRED并提示重新提供，不能空跑。备份保留按既有政策记录。
9. 上传新入口统一走接受服务，不保留flag=off时的裸job/旧图写入分支。当前前端任务中心依赖v2根任务和by-key接口，禁用后端v2会造成前后端协议错配；回滚通过revert相应代码提交完成，不能靠关闭运行时flag切回另一条写路径。
10. 回滚时保留已创建的新表和字段；已接受的v2任务只能由理解其schema的兼容worker继续执行，或明确挂起等待再次部署，不能交给旧worker。禁止DROP新表或恢复旧数据库覆盖切换后用户数据。运维保留能理解新schema的worker镜像直至清空v2活跃队列。

发布观测至少包含：根任务各状态数量、最老pending年龄、无job队列桶数量、lease回收/旧fence拒绝数、恢复重复抑制数、401按scope、LLM物理调用/unknown数、resolution覆盖率。日志关联import_id/job_id/attempt_no/request_id，不打印原文或Key。

2026-10-10 用户确认：面经公司和面试轮次属于需要保留的业务元信息，管理员公共直导与审核通过均默认继承；显式 null/空串仍删除。此规则不追溯覆盖既有审核投影。
