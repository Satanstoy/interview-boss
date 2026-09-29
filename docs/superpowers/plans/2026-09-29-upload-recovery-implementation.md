# 面经上传恢复改造执行计划

状态：Draft，依赖[主spec](../specs/2026-09-29-upload-recovery/README.md)接受后实施。该计划不是已完成记录，不授权现在运行生产迁移。仅主agent执行；不要因文件较多自行启动子agent。

## 0. 接手约定

- 必读主spec、contracts、acceptance，先理解import/attempt/job的区别。
- 每个勾选项是2–5分钟的最小操作目标；遇到一个函数/fixture超过5分钟，按一个分支或一个断言拆开，在执行记录追加具体子项。不要把一整阶段标成“一步”。
- 测试先红再绿：红必须因目标业务断言失败，不是ImportError、无DB或fixture坏了。修改前先让测试能正确抵达目标路径。
- 每个稳定逻辑单元验证后提交，遵守git-commit-push-hygiene；不要每个一行步骤都提交，也不要积累整套重构再提交。
- 不扩大范围到部署脚本、全站UI重做或其他LLM功能；这些目录存在既有改动时保留。
- 所有新公共函数带明确参数，不从隐式全局当前岗位/当前用户推导owner、scope或payer。
- 本计划指定职责，不要求照抄未验证的整文件代码；具体实现必须以现有schema和调用方为准。关键算法以contracts为准，禁止自由改变状态语义。

## 1. 文件职责图

| 文件 | 动作 | 单一职责 |
|---|---|---|
| backend/app/models/upload_contracts.py | 新建 | policy、snapshot、错误和review DTO；拒绝未知敏感字段 |
| backend/app/services/upload_policy.py | 新建 | 四格角色/目标→owner、凭据和审核意图 |
| backend/app/db/migrations/upload_recovery.py | 新建 | root、attempt、checkpoint、调用账本、scope租约和jobs增量 |
| backend/app/db/migrations/upload_resolution.py | 新建 | 原题关联、发布投影/版本与队列增量 |
| backend/app/db/migrations/__init__.py | 修改 | 追加迁移注册，不修改已发布迁移 |
| backend/app/services/upload_repository.py | 新建 | 事务内root、attempt、checkpoint和幂等读写；不自行调用模型 |
| backend/app/services/upload_lifecycle.py | 新建 | 创建/恢复/聚合根状态，复用job_lifecycle |
| backend/app/services/upload_credentials.py | 新建 | 本链路严格scope配置、预算、调用账本 |
| backend/app/services/job_lifecycle.py | 修改 | 领取代次、fencing检查、复用现有outbox；兼容旧job |
| backend/app/services/llm_quota.py | 修改 | 提取不commit的事务预留接口，保留旧wrapper行为 |
| backend/app/services/question_resolution.py | 新建 | 原题与规范题关联及失效操作 |
| backend/app/routers/upload_imports.py | 新建 | 根任务列表/快照/恢复/SSE/运维白名单 |
| backend/app/routers/submit.py | 修改 | 双入口共用接受服务；legacy retry解析root |
| backend/app/routers/bank_build.py | 修改 | 旧job读取内容权限及协议适配 |
| backend/app/worker.py | 修改 | 从阶段检查点执行，不再每次无条件跑全图 |
| backend/app/worker_cluster_tasks.py | 修改 | root关联、租约验证、续调、逐题结果和答案 |
| backend/app/worker_scheduled.py | 修改 | pending对账、scope续调及恢复资料保留 |
| backend/app/agents/submit/{extract,classify,graph,persist_personal,persist_public}.py | 修改 | 节点输入显式策略；完整提取；持久化由统一事务服务接管 |
| backend/app/db/operations.py | 修改 | 将submit写入拆出可复用的conn事务版，wrapper向后兼容 |
| backend/app/services/pipeline/{queue,batch,writer}.py | 修改 | v2根任务队列、scope/fence、原子resolution写入；不先删后算 |
| backend/app/services/clustering/matcher.py | 修改 | 显式匹配三态及输出校验，不吞异常为新题 |
| backend/app/services/public_contributions.py | 修改 | 审核投影、CAS、真实发布、逐题恢复和清单投影 |
| backend/app/routers/public_contributions.py | 修改 | 严格review模型、expected_revision、retry入口 |
| backend/app/routers/data.py、interview.py、db/queries.py | 修改 | 统一可见性、服务端分页、mine引用、结果定位 |
| backend/app/asgi.py | 修改 | 注册根任务路由和兼容开关 |
| backend/scripts/backfill_upload_recovery.py | 新建 | dry-run优先历史关联，不自动重放 |
| frontend/src/services/dataApi.js、masterBankApi.js、api/index.js | 修改 | 新契约、幂等键、审核投影接口 |
| frontend/src/composables/useSubmitJobs.js | 修改 | 以import_id持久化、快照/连接状态分离 |
| frontend/src/services/http.js | 修改 | 非终态EOF、finally释放；保持其他SSE调用方兼容 |
| frontend/src/composables/useAuth.js | 修改 | 登出清理任务单例/连接，不删除后台任务 |
| frontend/src/components/business/UploadTaskCenter.vue | 新建 | 常驻任务列表、失败恢复和结果跳转 |
| frontend/src/components/business/StagingPanel.vue、AdminReview.vue | 修改 | 接受/校验反馈及审核投影预览/编辑 |
| frontend/src/components/SiteHeader.vue | 修改 | 顶部任务摘要入口 |
| frontend/src/layouts/AuthenticatedLayout.vue、views/InterviewView.vue | 修改 | 挂载中心、打开结果定位、保持浏览上下文 |
| frontend/src/composables/useMasterBankData.js、components/common/DataTable.vue | 修改 | 面经server分页，共享表默认行为兼容 |

不要为了表格新增所有文件后再一次性接线；按下述依赖逐段实现。测试路径以acceptance为准。若现有服务已有完全相同职责，允许扩展原文件而不新建，但必须在交付记录写清映射，不能另保留一套重名逻辑。

## 2. 阶段A：建立可执行边界与测试隔离

**文件**：现有测试conftest、新upload_contracts.py、upload_policy.py、test_upload_policy.py。

- [ ] 记录git status、HEAD、branch、remote；将20个F/UR/AC复制到实施追踪表，全部Open。
- [ ] 读取实际最新迁移序号和jobs/schema；记录121/122是否仍可用。
- [ ] 加测试DB连接防护fixture：只允许内存或本测试临时目录，访问backend/data直接抛错。
- [ ] 写四格policy期望表，一个测试只验证一种身份/目标。
- [ ] 写客户端伪造is_admin/owner/scope和无效target的反例。
- [ ] 运行`test_upload_policy.py`确认目标断言为红。
- [ ] 实现纯policy resolver：返回write_scope、owner_id、credential_scope、payer、request_public_review；不含DB/模型调用。
- [ ] 写DTO未知字段拒绝和snapshot枚举测试，再实现严格模型。
- [ ] 重跑policy测试，确认所有组合通过；记录未接入入口，不能宣称share已修复。

**门槛**：AC-003的策略部分通过；只定义规则，尚不改变生产默认入口。

## 3. 阶段B：schema和事务基础

**文件**：两份新迁移、upload_repository.py、job_lifecycle.py；新增`backend/tests/infra/test_upload_recovery_migrations.py`。

- [ ] 写空库迁移、旧schema升级、重复运行3个测试。
- [ ] 分别新增upload_imports、upload_attempts、upload_stage_results结构与唯一约束，每张表独立测试。
- [ ] 新增jobs root/attempt/work_key/generation字段，验证旧NULL行可用。
- [ ] 新增question_resolutions和details ordinal，验证跨owner关系被拒绝。
- [ ] 新增审核projection/revision和队列租约字段；升级现有scope唯一约束前检查重复并输出报告。
- [ ] 新增调用账本和scope租约结构；补FK/索引检查。
- [ ] 实现事务版repository create_or_get_import，不内部commit。
- [ ] 写同key同hash复用、不同hash409、跨用户同key互不干扰测试，逐一实现。
- [ ] 写root活跃attempt唯一测试与stage成功结果唯一测试，再实现事务辅助函数。
- [ ] 注册迁移，验证旧公共数据可见性尚不改变。

**命令**：`.venv/bin/python -m pytest -q backend/tests/infra/test_upload_recovery_migrations.py`。
**门槛**：AC-021/023存储部分通过；不得运行生产--apply。

## 4. 阶段C：凭据、预算与接受原稿

**文件**：upload_credentials.py、llm_quota.py、submit.py、upload_lifecycle.py、upload_imports.py、asgi.py。

- [ ] 写user缺Key但global有效的测试，期望needs_action且0外部调用。
- [ ] 在本链路新增strict resolver；保留其他调用方现有fallback，不全局替换。
- [ ] 写解密失败和401按scope报错测试，再实现错误映射。
- [ ] 提取quota不commit核心；旧check_and_record wrapper继续负责原有commit，跑原配额回归。
- [ ] 写账本+配额预留原子性及unknown调用测试，实现事务记录。
- [ ] 写分块文件上限、非图片拒绝、空文件列表测试，修接受入口校验。
- [ ] 实现原稿/root/首个job同事务落库，Redis异常仍返回202。
- [ ] 绑定两个上传入口到同一接受服务；旧SSE适配只创建后订阅，禁止自己启动graph。
- [ ] 返回稳定import_id/幂等键/status_url，注册by-key查询的授权和路由优先级。

**命令**：acceptance第1组，以及新增`backend/tests/pipeline/test_upload_acceptance.py`。
**门槛**：AC-003/004/021/022通过；feature flag仍默认off。

## 5. 阶段D：checkpoint、恢复与fencing

**文件**：upload_repository/lifecycle、job_lifecycle、worker、submit graph与节点、db/operations。

- [ ] 将AC-008的“提取提交后重启”做成一个失败测试。
- [ ] 实现extract StageResult保存和复用，使用稳定ordinal，不先改其他阶段。
- [ ] 将classify结果保存同样接入；保存taxonomy版本，恢复不重新选择全局岗位。
- [ ] 从submit_interview_txn拆出接受conn且不commit的内部函数，原wrapper调用它保证老测试兼容。
- [ ] 写“面经+details+下游job任一步异常全部回滚”的测试，实现单事务提交。
- [ ] 写同秒两root不同输入测试，改thread_id并停止依赖MemorySaver恢复。
- [ ] 写A→B→C后retry(A)返回C的红测试，实现root解析和attempt唯一事务。
- [ ] 写两个连接同时恢复，只一个active attempt的测试；实现冲突读取已有结果。
- [ ] 给job claim/touch/complete增加generation兼容参数，v2写入必须提供；旧job兼容路径分开。
- [ ] 写旧generation提交业务数据被拒绝的测试，在业务提交事务内检查fence。
- [ ] 增加独立心跳任务及finally清理；取消/失租后禁止提交，但不假称远端请求已取消。
- [ ] 补剩余3个故障点测试，逐点确认不重复实体。

**命令**：acceptance第2组和已有`backend/tests/services/test_job_lifecycle.py`。
**门槛**：AC-008/009/012/017全部通过；只修改jobs状态却未保护业务写入视为失败。

## 6. 阶段E：原题完整性、关联和队列

**文件**：extract、matcher、question_resolution、pipeline queue/batch/writer、worker_cluster_tasks、worker_scheduled、db/queries。

- [ ] 用四道含“优缺点”的固定题写红测试；去掉静默子串删除，保留类型标记和counts。
- [ ] 给提取结果增加严格schema/ordinal检查，拒绝字符串当题目数组。
- [ ] 写matched/no_match/failed三态测试；逐个修401、漏ID、跨scope候选分支。
- [ ] 写私人引用公共题不改公共sources/frequency测试，实现resolution写入。
- [ ] 删除私人预匹配“命中后丢掉但不记关系”的行为，统一最终决策入口。
- [ ] 将resolution、canonical、sources更新放同事务，模型前不清旧成果。
- [ ] 给v2 dequeue加入root、岗位、owner、有效源筛选，旧队列仅消费NULL root。
- [ ] 实现scope租约领取/心跳/写入校验，测试两个root同公共池不重复创建。
- [ ] 写7私人+11公共多批场景，实现批后续调。
- [ ] 写无job残余队列场景，实现60秒reconciler幂等补单。
- [ ] 写连续公共输入时私人桶仍能执行的测试，采用最早可用轮转。
- [ ] 接入mine视图EXISTS关联及canonical失效处理；补私有来源不泄露回归。

**命令**：acceptance第3组、提取完整性测试及既有scope回归。
**门槛**：AC-005/006/007/019通过；禁止用“所有题都建成私人新题”绕过关联。

## 7. 阶段F：审核、发布与删除竞争

**文件**：public_contributions service/router、upload_contracts、所有公开读取谓词。

- [ ] 将审计E1改成期望公开company已删除的红测试；保留原始snapshot断言。
- [ ] 写审核投影builder，严格allow-list与null删除语义；前后预览复用该函数。
- [ ] 物化仅接收reviewed_projection，禁止内部重新读取source原值补敏感字段。
- [ ] 写跨申请item_id和未知字段拒绝测试。
- [ ] 写approve/withdraw双连接交错测试，先取得写事务再读状态或CAS。
- [ ] 将状态、事件、staging投影和公共工作写入同事务；测试任一点失败回滚。
- [ ] 写失败明细复用不能published测试，分开retry与approve入口。
- [ ] 实现有效resolution→published门槛；答案成功不是发布门槛，但属于根任务完成要求。
- [ ] 写同URL追加B题的投影测试，事务刷新questions_list，失败B不能提前展示。
- [ ] 收敛面经/experiences/题库/搜索/统计/来源/抽题/MCP的v2公共可见性；逐调用方验证兼容旧approved。
- [ ] 删除原文/源失效前后用generation检查，避免后台复活已删除内容。

**命令**：acceptance第4组，另跑受影响公开查询消费者的现有测试。
**门槛**：AC-014/015/016/020/024/025通过；不得先上线审核UI再补后端投影。

## 8. 阶段G：快照与隐私API

**文件**：upload_lifecycle、upload_imports router、bank_build router、worker结果适配。

- [ ] 写聚合状态优先级表的参数化测试，逐一实现running/queued/needs_action/partial_failed/review/completed。
- [ ] 为本root关联聚类/答案子工作；不以submit job completed替代根完成。
- [ ] 写U1私有marker对U2/A所有接口不可见测试。
- [ ] 替换通用admin正文豁免；新增运维allow-list DTO并测试禁止字段集合。
- [ ] 实现列表、by-key、详情、retry端点，权限在开始StreamingResponse前检查。
- [ ] 实现snapshot SSE、revision及15秒心跳；旧job端点保持兼容但不泄露正文。
- [ ] 写401和429不同恢复行为及nested retry预算测试，统一错误DTO。
- [ ] 检查日志，无原文、图片、Key、认证header；不把原始异常字符串直接返回客户端。

**命令**：状态投影、stream契约、privacy和调用记账测试。
**门槛**：AC-011/013/018通过。

## 9. 阶段H：前端任务中心与审核体验

**文件**：useSubmitJobs、http、useAuth、UploadTaskCenter、StagingPanel、SiteHeader、AuthenticatedLayout、AdminReview、API适配。

- [ ] 先写SSE正常EOF后重连测试，修改连接finally清理和非终态判断。
- [ ] 写恢复500不清任务、乱序revision不覆盖测试，再实现。
- [ ] 以import_id取代UI job_id主键，job_id仅作诊断字段。
- [ ] 写退出换账号测试，加入连接/计时器清理和按用户缓存。
- [ ] 实现常驻任务中心列表、空/加载/错误状态和分页，不丢已完成历史。
- [ ] 仅按allowed_actions显示按钮；失败阶段有具体原因与结果入口。
- [ ] 上传表单生成并保存Idempotency-Key，响应丢失先by-key查询，不直接新建。
- [ ] HTTP400/413保留草稿；202不因Redis排队慢标失败。
- [ ] 审核页加入最终投影预览、排除项、字段清空、expected_revision；冲突提示刷新。
- [ ] 顶部摘要链接任务中心，禁止完成5秒后销毁唯一结果。
- [ ] 验证375/1440及键盘焦点，记录截图和AC-027结果。

**命令**：新两份Playwright文件、`npm run build`；HTTP通用SSE既有消费者回归。
**门槛**：AC-010/011/014/027前端部分通过。

## 10. 阶段I：面经列表与结果定位

**文件**：data router、useMasterBankData、DataTable、InterviewView、AuthenticatedLayout。

- [ ] 写121条含同时间戳的API分页测试，建立一致COUNT/WHERE/ORDER。
- [ ] 实现授权内location接口，使用同一排序谓词，不透露无权目标存在性。
- [ ] DataTable增加server模式；测试默认模式其他页面不变。
- [ ] 面经列表绑定服务端total/page，删除客户端再次排序和slice。
- [ ] 筛选/岗位/排序变化重置页码，避免陈旧响应覆盖新筛选。
- [ ] 结果按钮依据location切页和高亮；自动完成仅更新提示，不抢用户页面。

**命令**：interview_server_pagination测试及upload-task-center前端用例。
**门槛**：AC-001/002通过。

## 11. 阶段J：迁移演练与最终集成

**文件**：backfill_upload_recovery.py、retention、测试fixtures、integration test、验证记录。

- [ ] 新增迁移dry-run脚本，只读临时样本库输出counts/冲突ID/manifest hash。
- [ ] 用A→B→C、断链、循环、无interview_id、跨owner等样本验证不猜测。
- [ ] 实现`--apply --manifest`，只在manifest未变化时事务应用；重复运行0新增。
- [ ] 调整retention，保护未完成/失败恢复资料，完成老任务只清大正文。
- [ ] 准备本地模型stub和隔离Redis；test fixture显式注入临时DB，拒绝生产路径。
- [ ] 实现AC-028跨API/worker/浏览器流程，至少一次杀worker后恢复。
- [ ] 实现AC-029逐题数据流集成测试：固定5个ordinal和分类/标签stub，覆盖私人暂存、审核排除1题与投影编辑、4题公共resolution/publish及单题失败恢复；输出不含敏感原文的ID trace映射。
- [ ] 跑acceptance列出的新测试和范围内旧回归；已有失败与新回归分开报告。
- [ ] 自行review全部改动：每个F→代码→测试→证据能对应，检查敏感数据和破坏性迁移。
- [ ] 生成灰度/回退操作说明；没有授权不要执行生产--apply或部署。
- [ ] 汇总20项需求与29项AC状态，全部通过后才请求将spec标记Implemented。

历史脚本建议CLI（实现后才可用）：

```bash
.venv/bin/python backend/scripts/backfill_upload_recovery.py --database /tmp/upload-recovery-test.db --dry-run --report /tmp/upload-recovery-manifest.json
.venv/bin/python backend/scripts/backfill_upload_recovery.py --database /tmp/upload-recovery-test.db --apply --manifest /tmp/upload-recovery-manifest.json
.venv/bin/python -m pytest -q backend/tests/integration/test_upload_recovery_stack.py
```

**门槛**：AC-021至AC-029完整通过。每项未通过写明确阻塞，不以“功能大体可用”结束。

## 12. 提交与交接

推荐按A/B、C、D、E、F、G、H、I、J的验证边界提交；若一个阶段超过8–12文件或稳定改动约500–1000行，在通过相关测试的更小逻辑单元检查点提交。`git diff --check`、检查暂存文件列表和密钥内容后提交。未授权push则仅本地commit。

交接记录至少包含：当前HEAD、已完成阶段、20项需求状态、29项AC结果、执行命令/日志、迁移是否仅dry-run、剩余基线变更、上线开关状态。禁止把未运行测试记为通过。
