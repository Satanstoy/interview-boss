# 验收矩阵与证据要求

属于[主规格](README.md)。所有数据必须使用内存或临时目录SQLite、隔离Redis namespace和本地stub模型，不向生产数据库写入、不使用真实付费模型。

测试固定主体：U1普通用户id=101、U2普通用户id=102、A管理员id=201；固定岗位P1/P2；每个用例独立建库。鉴权用测试依赖覆盖，业务层不能mock为直接成功。API结果和数据库关系都必须断言，不能只断言200。

## 1. 二十项逐条验收

### AC-001 → UR-001：结果定位

Given U1在面经第2页、筛选P1，上传到P2的任务结束。When点击“查看面经”。Then按有权限的interview_id定位，显示岗位切换提示，取得正确页并高亮目标；后台自动完成不强迫用户离开当前页。目标已删除时显示“面经已删除”，不跳到其他记录。

测试：新增`frontend/tests/e2e/upload-task-center.spec.js`。断言目标row ID、页码、岗位标签，不只截屏。

### AC-002 → UR-002：真实分页

Given P1有121条授权面经，另有U2私人面经和P2记录。When请求created_at_desc第1页20条。Then最晚记录在首位，total=121，无U2/P2内容；同时间戳按id稳定排序。换招聘季后COUNT与items同口径；切排序/筛选回第1页。JD等共享DataTable页面维持原分页行为。

测试：`backend/tests/pipeline/test_interview_server_pagination.py`、上述前端文件。

### AC-003 → UR-003：四格提交策略

分别运行U1/private、U1/share、A/private、A/share，覆盖新job和旧SSE入口。U1/share必须先生成本人私人面经与一份待审快照，公共题数量不增；A/private owner=A，A/share显式公共审批记录，未处理完成前不公开。客户端伪造owner_id/is_admin无效；target=invalid返回400。

测试：`backend/tests/pipeline/test_upload_policy.py`。至少8个入口组合+2个非法输入用例。

### AC-004 → UR-004：费用与配置

上传处理开始前，服务端必须根据认证主体和目标库解析必须预检的scope；每个工作阶段开始前，再根据审核状态解析该阶段唯一的调用scope。任务先持久化原稿和`credential_preflight`步骤，再由后端用最小ping验证所选provider/model实际可连接；不能只检查“存在一段Key”、不能只测配置表，也不能拿另一scope配置代测。私人预检必须走严格的本人配置解析，不能调用会在缺少用户Key时返回global配置的通用读取器。预检结果绑定provider/model/config_fingerprint，不存Key、认证头或敏感错误正文。每次ping作为独立调用记账；常规自动化测试只使用本地stub，不连接真实供应商。

覆盖以下scope矩阵：

| 操作 | 处理阶段 | 必须预检及记账的配置 |
|---|---|---|
| U1/private | 提交预检及私人提取、分类、匹配、答案 | U1 的 user 配置 |
| A/private | 提交预检及私人提取、分类、匹配、答案 | A 的 user 配置 |
| A/share | 提交预检及公共导入全阶段 | global/system 公共配置 |
| U1/share | 提交前目标库预检 | global/system 公共配置 |
| U1/share | 私人暂存及审核前的私人处理 | U1 的 user 配置；提交启动前也必须预检 |
| U1/share | 批准审核投影后的公共聚类/标签 | global/system 公共配置，必须重新预检 |

每格都要验证“正确scope连通→只使用该scope”和“正确scope缺失/401/模型404/不可连通、另一scope有效→仍阻断”的正反例。包括管理员私人配置缺失但global有效、管理员公共配置缺失但其个人配置有效，两个方向都不得fallback。公共目标的global预检失败时，即使是普通用户分享且user配置有效，也必须在开始提取前停为needs_action；原稿、同一root和失败预检记录保留，不派发提取/分类等模型工作，并显示这是待管理员修复的系统配置阻塞。修复正确scope后从同一root恢复，只处理未完成阶段。普通用户share在审核后必须重新探测global；探测失败时不得调用用户Key或发布未处理题目。个人配置解密异常不得fallback。额度耗尽停止新调用且保留成果；恢复不能绕过当天配额。模型调用超时记录unknown而非假定免费。

端到端验收还必须证明生产解析路径的负向反例：数据库中U1没有私人配置而global配置有效时，真实`resolve_upload_credentials(..., credential_scope="user")`及上传入口均返回user scope的needs_action，不读取/使用global模型。仅向resolver注入`user_config_loader`的单元测试不够，因为它绕过了默认配置读取器。

测试：`backend/tests/services/test_upload_credentials.py`、`test_upload_llm_accounting.py`、新增`backend/tests/pipeline/test_upload_credential_preflight.py`。覆盖实际默认user配置读取器与真实上传入口；本地stub provider控制ping成功/401/404/超时。adapter/调用账本记录预检和模型处理的scope、payer、config_fingerprint、call_key；断言失败的预检不创建业务处理job。不得连接真实供应商或依赖真实密钥。

### AC-005 → UR-005：私人引用与归属

U1原题命中公共Q：保留私人detail和resolution，个人canonical不增，公共来源/频次不变；mine视图显示Q但只有U1能看私人来源。U2看不到U1关联。公共Q失效后原题保留、resolution失效并可重新关联。不同cat2允许独立私人题，不强行改公共分类。

测试：`backend/tests/services/test_question_resolutions.py`，补`test_public_personal_scope_contract.py`。

### AC-006 → UR-006：判断失败不等于新题

模型401、超时、遗漏new_id、返回其他scope的canonical_id各自验证。Then不创建新canonical，不记no_match；结构错误有限修复，失败保留可恢复步骤。真正无候选才允许no_match后创建同scope题。

测试：`backend/tests/services/test_upload_matching_outcomes.py`。

### AC-007 → UR-007：残余队列被推进

同时创建U1私人7条和公共11条，batch_size=5，另一公共root持续入队。Then每个合法桶都被选中；完成后没有有pending但无job的root。模拟COMMIT后ARQ不可用，reconciler下一周期创建/投递恰好一个工作。孤儿来源转明确阻塞，不循环空跑。

测试：`backend/tests/pipeline/test_upload_queue_reconciliation.py`，使用可控时钟和至少3个root；断言有限轮次内U1得到执行，不只断言队列计数。

### AC-008 → UR-008：故障点恢复

分别在提取checkpoint提交后、面经事务提交后、下游job提交后/ARQ通知前、答案外部调用后/保存前终止执行，再启动新worker恢复。Then原稿、面经、每个ordinal明细、resolution均不重复；成功提取不再调用；未知外部调用可有额外成本但不能重复业务成果。事务未提交的写入全部回滚。

测试：`backend/tests/pipeline/test_upload_stage_recovery.py`。至少4个故障点，用真实临时SQLite事务，不把persist函数mock掉。

### AC-009 → UR-009：并发输入不串单

同用户在同一固定时间提交内容A/B，模型返回不同公司/题干。Then各root仅关联自己的interview/detail，thread_id不同，任何结果不混入另一任务。显式固定系统时间以保证能击中旧秒级ID设计。

测试：`backend/tests/pipeline/test_upload_stage_recovery.py`。

### AC-010 → UR-010：连接恢复

SSE发running后正常EOF、不发error：客户端重连且GET快照收敛；恢复列表返回500：原任务仍显示断线；收到revision=8再收7：不回退；仅心跳不增长进度。退出U1登录U2后U1卡片/结果/计时器均不残留。不同标签页同root恢复不会重复执行。

测试：前端`upload-task-center.spec.js`。分别模拟EOF、500、乱序、换账号；不得仅在mock返回done的happy path截图。

### AC-011 → UR-011：真实完成

导入已保存，聚类未完成：root不能completed。10题中8题答案成功2题失败：结果可打开，失败数=2，按错误类别显示partial_failed或needs_action；恢复只调用2题。已有公共答案可跳过且写明原因。完成超过5秒仍能从任务历史找到。

测试：`backend/tests/services/test_upload_status_projection.py`及前端任务中心。

### AC-012 → UR-012：旧worker不可写

队列创建于1小时前但刚被领取：不能立即回收。worker A领取generation=1后租约失效，B领取generation=2，A再提交canonical/resolution：写入被拒绝，业务表无A结果。长调用时心跳续租；心跳失败停止提交。测试不能只检查jobs.complete返回false。

测试：`backend/tests/services/test_upload_leases.py`；用两个SQLite连接和可控时间。

### AC-013 → UR-013：错误与重试预算

pending/running/needs_action/completed均使用同一snapshot协议。401只一次请求即停；429自动尝试总计不超过3；模型结构错误修复计入相同上限。旧SSE消费者仍得到兼容事件，但不独立启动另一条图。日志含关联ID，不含Key、原稿或认证头。

测试：`backend/tests/infra/test_upload_stream_contract.py`、`test_upload_llm_accounting.py`。

### AC-014 → UR-014：公开等于审核投影

原快照company=PRIVATE、URL带可识别来源，审核company=null、source_url=null并修改题干。Then审核预览=最终public字段，原快照未修改，普通用户看不到原company/URL。提交未知字段或其他申请item_id返回422/400且无写入。旧UI必须能预览实际投影，不再空参数盲批。

测试：补`backend/tests/services/test_public_contributions_materialize.py`及新增`frontend/tests/e2e/public-contribution-review.spec.js`。JD同样验证删掉敏感字段后不回落到source。

### AC-015 → UR-015：失败子项恢复

公共申请两题，一题有成功resolution，另一题有public_detail但聚类失败。When恢复。Then只处理后一题；成功前申请不能published，完成后两题都具有合法resolution。重复approve不把失败明细存在性当完成；无新增INSERT也必须能恢复已有失败工作。

测试：`backend/tests/services/test_public_contribution_recovery.py`。

### AC-016 → UR-016：追加贡献保持一致

同URL第一次发布题A，第二次发布题B。Then公共面经投影A/B各出现一次；B处理失败时清单只有A，恢复完成才出现B。排除/删除B后清单、来源、统计同步，不跨owner删除同URL私人题。

测试：`backend/tests/services/test_public_contribution_recovery.py`。

### AC-017 → UR-017：跨代与并发恢复

A失败→B失败→C活跃，从A或B再次恢复均返回C所属active attempt，不新建D。两个连接同时retry根任务只创建一个attempt。活跃attempt允许不同题答案并行，但同work_key只有一个活跃job。返回created_attempt=false可被前端正确解释。

测试：补`backend/tests/pipeline/test_submit_job_retry.py`，新增`test_upload_retry_family.py`。

### AC-018 → UR-018：私人正文隔离

U1私有上传带独特marker。U2与A分别访问GET root、root SSE、旧jobs SSE和重试结果：不得获取marker；非本人正文端点404。A运维端点仅返回白名单字段。A审核U1主动提交的快照合法，但不能据此访问U1其他私人root。私有HTTP错误也不能回显原稿。

测试：`backend/tests/security/test_upload_task_privacy.py`。直接检查序列化响应全文中marker不存在。

### AC-019 → UR-019：不静默漏题

输入Redis持久化优缺点、线程池优缺点、个人优缺点、TCP握手四题。Then完整提取结果保留4个ordinal，技术两题不得删除；个人优缺点可标HR题，但本期默认保留。模型输出null/数字/重复ordinal通过schema拒绝或明确标待确认，不能迭代字符串为单字题。counts守恒。

测试：`backend/tests/pipeline/test_upload_extraction_integrity.py`。

### AC-020 → UR-020：审批与撤回互斥

两个数据库连接强制交错approve和withdraw读取/写入。Then只有一个成功：撤回胜出无公共投影/可执行队列；批准胜出撤回409且状态不显示withdrawn。重复请求不追加重复事件或公开实体。事务失败回滚状态、事件与工作。

测试：`backend/tests/services/test_public_contribution_transitions.py`，不能只用单连接顺序调用。

## 2. 跨层门槛

| ID | 条件 | 必须证明 |
|---|---|---|
| AC-021 | 同幂等键网络重发/响应丢失 | 同用户同hash一个root；不同hash409；U2不能用同键查U1任务 |
| AC-022 | 文件校验400/413 | 输入草稿保留，无幽灵job；超限文件不完整读入内存；不支持文件不静默跳过 |
| AC-023 | 迁移与回填运行两次 | 实体/attempt数量第二次不增；歧义列入报告，不能猜测重放 |
| AC-024 | JD与无新元数据旧数据 | JD不进聚类；旧approved公共数据可见；旧客户端适配不重复执行 |
| AC-025 | 原文删除/岗位退休/分类升级 | 当前运行在提交前发现源状态变化；普通恢复不重置已成功版本；不复活删除内容 |
| AC-026 | 历史与保留清理 | 活跃及失败恢复payload不被90天清理；完成老任务仍有结果入口，无payload时明确不可从零恢复 |
| AC-027 | 可访问性 | 375/1440宽度、键盘操作、焦点稳定、按钮名称和aria状态可读 |
| AC-028 | 完整隔离集成 | 真实API+临时SQLite+隔离Redis+worker+本地模型stub，上传→审核→断worker→恢复→浏览器打开正确结果 |
| AC-029 | 面经题目数据流追踪 | 同一份普通用户分享面经，从上传、私人保存、逐题分类/匹配，到管理员审核、公共聚类/标签和结果读取，逐题身份与数据一致；注入单题失败后恢复不重复成功成果 |

AC-028属于隔离集成E2E，不宣称验证真实供应商模型质量。另行真实供应商smoke需明确费用授权，不是默认自动执行命令。

### AC-029：单份面经逐题数据流追踪

**Given** U1提交一份选择“申请公共化”的面经，含5道内容彼此可区分的题目；本地模型stub按稳定ordinal返回固定分类和标签。至少一道审核保留题命中已发布公共规范题，其余保留题创建或关联到正确scope的规范题。测试不连接真实模型或生产数据。

**When** 通过真实HTTP入口接受任务，由worker完成提取、私人保存、逐题分类与匹配；管理员从5道题中排除1道，并批准一个对来源字段做脱敏、对一道保留题题干做编辑的审核投影；公共处理继续执行。在一题公共聚类时注入可控失败，终止并重启worker，再由任务恢复入口继续处理。

**Then** 测试必须用真实临时SQLite中的记录和实际授权读取API，逐项断言以下数据链：

1. 一次客户端幂等键只对应一个稳定`import_id`；根任务、attempt和job归属一致，任务policy记录U1、share意图、私人预处理scope及审核要求，不能靠客户端`is_admin`或目标字段推导权限。持久化`credential_preflight` job先探测目标global/system配置及U1的user配置；两者成功才创建提取job。调用账本和预检记录证明审核前私人阶段由U1付费；管理员批准后公共工作开始前重新探测global/system scope并由其付费。单独注入“初始global无效、U1有效”时必须停在needs_action且没有提取/分类等处理job；修复后从同一root恢复。后续再注入global失效时必须停止公共工作，不fallback；不得在测试trace或日志输出Key。
2. 5道输入题分别保留唯一且稳定的ordinal；提取结果、分类检查点、私人`questions_detail`、`question_resolutions`能按ordinal一一追溯。每题的`cat1`、`cat2`和标签必须等于stub的预期值；已匹配公共题的私人resolution指向公共canonical，但不得修改公共来源、频次或内容。
3. 管理员批准前，私人面经和审核快照存在，公共读取接口看不到该申请的待发布内容，公共canonical数量不因私人预处理增加。审核投影的脱敏字段和修改题干成为后续公共处理的唯一输入；不得从原始snapshot回填已清空字段。
4. 公共处理时，4个保留的审核item与公共detail、当前有效public resolution及公共canonical一一对应；scope、题目文本、分类和标签与获批投影及stub结果一致。被排除的ordinal不进入公共处理或清单；未完成resolution的题不标记published。
5. 注入失败的ordinal在首次运行中显示明确失败，不能被当成no_match、不能创建错误canonical或发布错误标签；任务状态不能提前显示全部完成，首次公共投影只包含3道成功题。恢复后只重跑失败工作，已成功的提取/保存/分类/resolution ID保持不变；最终公共面经清单恰有4道保留题，私人原稿仍有5道题，且没有重复detail、canonical来源或标签。
6. 普通用户只读到获批公共投影；U2不能读取U1的私人原文/来源；管理员审核能力不等于读取U1其他私人任务。测试产出可读的逐题trace映射：`input ordinal → stage result → private detail/resolution → contribution item/review projection → public detail/resolution → canonical`，映射中只包含测试ID和非敏感字段。

**测试**：新增`backend/tests/integration/test_upload_question_data_flow.py`，使用临时SQLite、隔离Redis和确定性模型stub，经过真实API、worker和公开读取查询；新增`frontend/tests/e2e/upload-question-data-flow.spec.js`验证用户提交、任务状态、恢复操作和最终题目/标签结果。测试必须断言逐题数据库关系，不能只检查HTTP 200、任务completed或页面截图。

## 3. 验证命令与证据

以下命令在实现了对应新测试后执行；新文件不存在表示步骤没完成，不能直接删掉命令。

```bash
.venv/bin/python -m pytest -q backend/tests/pipeline/test_upload_policy.py backend/tests/pipeline/test_upload_credential_preflight.py backend/tests/services/test_upload_credentials.py backend/tests/services/test_upload_llm_accounting.py
.venv/bin/python -m pytest -q backend/tests/pipeline/test_upload_stage_recovery.py backend/tests/services/test_upload_leases.py backend/tests/pipeline/test_upload_retry_family.py
.venv/bin/python -m pytest -q backend/tests/services/test_question_resolutions.py backend/tests/services/test_upload_matching_outcomes.py backend/tests/pipeline/test_upload_queue_reconciliation.py
.venv/bin/python -m pytest -q backend/tests/services/test_public_contributions_materialize.py backend/tests/services/test_public_contribution_recovery.py backend/tests/services/test_public_contribution_transitions.py backend/tests/security/test_upload_task_privacy.py
.venv/bin/python -m pytest -q backend/tests/pipeline/test_interview_server_pagination.py backend/tests/pipeline/test_upload_extraction_integrity.py backend/tests/services/test_upload_status_projection.py backend/tests/infra/test_upload_stream_contract.py
.venv/bin/python -m pytest -q backend/tests/pipeline/test_submit_job_retry.py backend/tests/pipeline/test_public_personal_scope_contract.py backend/tests/infra/test_question_bank_scope_invariants.py backend/tests/security/test_public_rebuild_answer_scope.py backend/tests/security/test_question_bank_source_projection_scope.py backend/tests/infra/test_db_retention.py
.venv/bin/python -m pytest -q backend/tests/integration/test_upload_question_data_flow.py
```

在frontend目录：

```bash
npx playwright test tests/e2e/upload-task-center.spec.js tests/e2e/upload-question-data-flow.spec.js tests/e2e/public-contribution-review.spec.js tests/e2e/jd-interview-submit.spec.js
npm run build
npm run lint
npm run type-check
```

先核对conftest是否确保所有DB连接走临时库；测试期间禁止应用启动时偷偷连接生产DB，新增SQL连接防护fixture。已有全仓type-check/E2E债务单独记录；新增受影响用例必须通过，不允许skip、删断言或调高全仓阈值掩盖回归。

新增`backend/tests/integration/test_upload_recovery_stack.py`作为AC-028入口，要求显式`UPLOAD_TEST_DB_PATH`临时路径和`UPLOAD_TEST_REDIS_PREFIX`独立随机前缀，否则拒绝启动。测试fixtures注入config.DB_PATH和连接工厂（不是假定生产配置会读取测试变量）；本地stub验证凭据scope，不出网。

执行证据写入`docs/verification/upload-recovery/`：每阶段命令、exit code、passed/failed/skipped数量、AC映射、schema迁移报告、浏览器关键截图。未运行写not-run及原因，不能写passed。正式回归断言修复后的期望行为，审计探针断言“缺陷存在”仅作参考。
