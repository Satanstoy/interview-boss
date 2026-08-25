# InterviewBoss

中文 AI 面试备战平台。JD/面经 → 提取面试题 → LLM 分类打标聚类 → 口述级答案 + 模拟面试 + 知识图谱。

## 语言

**AI 评测系统（AI Evaluation System）**:
面向管理员的统一质量评测空间，用于评测 InterviewBoss 中的 Agent、Workflow 和 Pipeline，不直接面向普通用户。
_避免使用_: 仅模拟面试评测系统、通用 AI 评测平台

**评测目标（Evaluation Target）**:
一个可独立定义评测范围、输入、预期行为和质量结果的 Agent、Workflow 或 Pipeline。
_避免使用_: 被测 Agent（当目标不是 Agent 时）

**系统基线（System Baseline）**:
评测系统建立时对整个 InterviewBoss 行为状态的固定起点，用于后续判断目标版本的变化。

**评测系统 1.0 基线（Evaluation System 1.0 Baseline）**:
当前评测系统建设采用的初始冻结基线，包含当前系统基线、各评测目标的初始版本，以及按目标组织的完整评测版本 `1.0`。完整评测版本内部包含 Benchmark、评测协议、Judge、Harness、Candidate Simulator 和相关模型配置。`1.0` 表示可追溯的版本起点，不表示所有评测指标已经达到合格标准；后续变化产生新的目标版本或评测版本，不覆盖或重写 `1.0`。

**版本 Manifest（Release Manifest）**:
描述一个 Target Release 或 Evaluation Release 的不可变版本权威 JSON 快照：前者记录被测对象的行为配置，后者记录完整评测内容及评测侧运行配置。Manifest 包含代码、运行环境、模型、Prompt、Skill、工具、采样和其他会影响评测结果的配置，并通过内容摘要保证创建后不可静默修改。数据库只保存可查询索引和引用关系，不替代 Manifest 原文。

**版本草稿（Release Draft）**:
一个尚未发布、允许管理员编辑的 Target Release 或 Evaluation Release；它可以被校验、复制和继续修改，也可以用于探索性 Eval Run，但不能直接作为正式人工 A/B 的不可变版本依据。
_避免使用_: 可编辑 Release

**已发布版本（Published Release）**:
一个已经冻结、可被正式 Eval Run 和人工 A/B 绑定的不可变 Target Release 或 Evaluation Release；对其参数的任何改变都必须复制为新的版本草稿，不得原地覆盖。
_避免使用_: 线上版本（评测版本不等同于用户服务发布版本）

**评测配置显示名（Evaluation Configuration Display Label）**:
评测控制台面向管理员展示的中文字段名、分组名、说明和校验提示；它只负责可读性，底层 API、Manifest 和数据库继续使用稳定的英文字段与枚举。
_避免使用_: 用中文替换领域字段名

**结构化评测配置表单（Structured Evaluation Configuration Form）**:
管理员通过按版本类型和评测职责组织的中文字段表单编辑 Release Draft；常用参数直接展示，高级参数折叠，规范化 Manifest 原文只用于查看、审计和导出，不作为 1.0 的主要编辑入口。
_避免使用_: 原始 JSON 配置编辑器

**评测版本发布工作区（Evaluation Release Workspace）**:
评测控制台分别管理评测目标版本和按目标组织的完整评测版本；完整评测版本内部以中文配置分组呈现评测题集、评测规则、评分模型、模拟面试执行器和候选人模拟器，但这些分组不作为管理员单独维护的公开版本。
_避免使用_: 六类公开组件版本

**评测凭证引用（Evaluation Credential Reference）**:
Release Manifest 中对模型服务凭证来源的稳定标识，例如全局 LLM 凭证或 SiliconFlow Embedding 凭证；它不包含 API Key 明文，实际密钥由全局模型配置或运行环境提供。
_避免使用_: Release API Key

**执行镜像摘要（Execution Image Digest）**:
Release Manifest 中用于锁定实际运行容器的不可变 Docker image digest；系统同时记录 Git SHA 和配置摘要，分别追溯源码、运行环境和行为配置，正式 Benchmark 不使用可变的 `latest` 标签作为唯一执行依据。

**评测运行（Eval Run）**:
管理员针对一个具体评测目标版本和一个完整评测版本发起的一次完整评测执行记录；创建后锁定这两个版本及其规范化执行快照，并独立保存执行状态、原始轨迹和评分结果。

**评测批次（Eval Batch）**:
一组共享同一执行上下文的 Eval Run 或 Eval Run Item；批次级的评测目标版本、完整评测版本、运行环境、超时、重试、采样和并发规则必须一致。Case 输入、Replication 序号和按规则生成的 seed 属于 Item 级差异。

**评测 Item Attempt**:
同一个 Eval Run Item 的一次实际执行尝试，用于记录 Worker 崩溃、网络错误、超时等操作性重试；Attempt 不增加统计样本数，原始失败 Attempt 不被覆盖，Item 最终引用一个有效 Attempt。

**评测数据模型 1.0**:
评测领域使用独立的 `eval_runs`、`eval_batches`、`eval_items`、`eval_attempts`、`eval_events` 和 `eval_artifacts` 数据对象；通用 `jobs` 只承载 ARQ 投递和 Worker 生命周期，不替代评测领域状态。

**评测失败分类（Eval Failure Class）**:
用于决定 Attempt 是否可重试以及重试哪一层的标准化失败类型；临时基础设施失败、目标行为失败、Harness 契约失败和 Judge 阶段失败必须分开处理，不能统一按“再跑一次”处理。

**评测 Artifact（Evaluation Artifact）**:
评测执行产生的不可变原始证据或派生报告，包括完整对话轨迹、SSE/工具轨迹、Judge 输入输出和聚合报告；数据库保存 Artifact 的索引、路径、类型、大小和 digest，Artifact 原文存储在受控文件或对象存储中。

**Artifact 保留策略（Artifact Retention Policy）**:
按 Artifact 来源和用途决定保留期限的不可变策略；官方 Benchmark、有效评测证据和人工 A/B 证据长期保留，临时失败日志和未晋升的生产采样按 TTL 清理，清理不得破坏历史 Eval Run 的核心证据链。

**评测数据基础脱敏（Pragmatic Eval Redaction）**:
1.0 对生产采样和长期评测 Artifact 采用基础脱敏边界，优先移除明显的姓名联系方式、用户标识和 URL 等字段；默认使用合成 Fixture，不承诺企业级 DLP，也不引入独立隐私基础设施。

**对比组（Comparison Group）**:
用于管理员 A/B 对比的关联对象；它将两个或多个拥有独立生命周期的 sibling Eval Run 关联起来，要求它们共享同一 Batch 执行上下文，并明确记录各自唯一不同的 target release。

**评测队列（Eval Queue）**:
专门承载评测父任务、Case/Replication 子任务、Judge 和聚合任务的异步队列及 Worker Pool，与用户服务队列隔离资源、并发、限流和故障域；评测队列中的任务仍以数据库记录为事实来源。

**按需评测 Worker（On-demand Eval Worker）**:
消费 Eval Queue 的短生命周期 Worker；在存在待处理 Eval Run 时按需启动，以低并发执行并在队列清空后退出，不为偶发评测长期占用小服务器资源。队列、数据库任务状态和事件日志在 Worker 退出后继续保留。

**Compose Eval Worker**:
1.0 部署中的独立 Docker Compose `eval-worker` 服务，使用 `eval` profile 和专用 ARQ queue 配置，由宿主机 launcher 以 `run --rm` 按需启动；它与用户任务的常驻 `worker` 服务分开定义、分开限制资源和分开重启策略。

**Eval Worker Launcher**:
运行在宿主机上的轻量调度器，负责发现待处理或需要恢复的 Eval Run、获取单实例启动锁并按需拉起 Compose Eval Worker；它不执行评测逻辑，也不由 FastAPI 请求直接驱动。

**评测控制台（Evaluation Control Plane）**:
面向管理员的前端控制界面，用于管理评测目标版本和完整评测版本、发起和监控 Eval Run、查看回归与稳定性结果，以及进入人工 A/B 评测；它不是普通用户使用的产品功能页面。

**评测中心（Evaluation Center）**:
评测控制台在应用侧栏中的管理员分组标题；分组下以唯一的“评测结果工作台”为主要入口，将原测评可视化与评测结果合并展示，再按“版本与评测集、测评实验、人工 A/B”提供支撑性流程入口，运行详情作为结果工作台中的路由下钻，不单独占用侧栏 Tab。
_避免使用_: 再增加一层评测中心内部导航；把测评可视化和评测结果拆成两个管理员主入口

**可恢复评测进度流（Resumable Eval Progress Stream）**:
由持久化的 `eval_run_events` 驱动的管理员 SSE 进度流；每个事件具有单调序号，支持通过 `Last-Event-ID` 断线重放。SSE 连接断开不改变 Eval Run 状态，取消必须通过独立的管理员操作完成。

**评测目标版本（Evaluation Target Release）**:
某个 Agent、Workflow 或 Pipeline 在特定代码、工作流、Prompt、工具和被测对象模型配置下的不可变行为快照；不同目标分别维护版本，不因其他目标或评测配置变化而自动改版本。

**完整评测版本（Evaluation Release）**:
面向一个评测目标的完整评测内容不可变快照，包含 Benchmark、评测协议、Judge、Simulator Harness、Candidate Simulator、Embedding/Retrieval 和相关模型参数；它与被测目标版本独立维护，但一次 Eval Run 必须一对一绑定一个目标版本和一个完整评测版本。
_避免使用_: 评测组件版本、评测配置包

**评测版本作用域（Evaluation Release Scope）**:
完整评测版本按评测目标类型组织，例如 `interview-eval@1.0`、`experience-extraction-eval@1.0` 和 `resume-analysis-eval@1.0`；同一目标类型的多个 Target Release 可以复用同一完整评测版本，以保证回归和 A/B 的公平性。它不绑定某一个具体 Target Release，不同目标类型不能混用。

**评测行为配置归属（Evaluation Behavior Ownership）**:
会改变产品正常行为的代码、Workflow、Prompt、工具和被测对象模型属于 Target Release；决定“如何测”的 Benchmark、协议、Judge、Harness、Candidate Simulator、评测侧模型及其参数属于 Evaluation Release。一次评测的主版本边界只有这两个 Release。

**评测运行快照（Eval Run Snapshot）**:
Eval Run 创建时由后端解析并固化 Target Release、Evaluation Release 及其全部有效配置，至少包含两个 Manifest、Git SHA、配置摘要、模型标识与参数、随机种子策略、运行时限制和可获得的镜像摘要；执行、重试、恢复和重放只读取该快照，不重新读取可变草稿或全局默认配置。

**可评测草稿（Runnable Draft）**:
允许管理员用当前草稿启动探索性 Eval Run，以便快速验证配置；结果必须明确标记为 Draft Run，不能用于正式回归门禁或人工 A/B。发布后生成的 Published Release 才能进入正式比较。

**Target Adapter**:
评测目标接入 AI Evaluation System 的统一执行适配器，负责准备 Case、执行已锁定的 Target Release 和将原始结果转换为标准 Observation；它不负责决定 Benchmark 量规、Judge 结论或管理员聚合策略。

**Evaluation Observation**:
Target Adapter 输出的最小标准执行结果外壳，包含生命周期状态、时间、契约违规和 Artifact 引用；目标类型特有的 transcript、tool trace、提取结果或分析报告放在版本化的 `payload` 中，不强迫所有目标共享完整字段。

**Case Evidence View（Case 证据视图）**:
面向管理员复核一个 Benchmark Case 一次执行表现的完整证据集合，关联冻结的 Case 输入、Harness/Target Observation、确定性断言、Judge 结果、Attempt 和 Artifact；它不是 Target Adapter 的原始内部结果。

**证据契约版本（Evidence Contract Version）**:
标识 Case Evidence View 中字段语义和兼容边界的版本；同一版本内字段含义保持稳定，破坏性变化必须产生新版本。

**公共证据外壳（Common Evidence Envelope）**:
Case Evidence View 中所有评测目标共享的稳定部分，描述 Run、Item、Case、执行状态、Observation、评分、Attempt 和 Artifact 引用；它不承载目标类型专属输出。

**目标专属证据 Payload（Target Evidence Payload）**:
Case Evidence View 中按目标类型版本化的结果部分，统一分为 `output`、`trace` 和 `metrics` 三类；不同目标可以拥有不同的具体内容，但不能改变公共证据外壳。

**按需 Case 证据（On-demand Case Evidence）**:
Run 列表只提供 Case 摘要，管理员选中 Case 后才读取完整 Case Evidence View；人工 A/B 与 Run 详情使用同一份按需证据。

**评测状态轴（Evaluation Status Axes）**:
Eval Item 的执行状态、Observation 契约状态、Hard Gate 状态、Judge 状态和质量状态分别表达不同事实；它们不能被一个含义混合的状态字段替代。

**目标 Payload 注册表（Target Payload Registry）**:
记录每个评测目标的 `target_payload` 结构、`payload_schema_version` 和 output/trace/metrics 字段语义的权威目录；当前覆盖面试、面经提取、JD 提取、简历分析和题目分类。

**管理员专属 Harness 上下文（Admin-only Harness Context）**:
只对评测管理员开放的 Case 执行上下文，包括行为注入、评测契约和其他非候选人可见信息；展示时必须与候选人可见输入分区并完成敏感信息脱敏。

**评测 API 契约校验（Evaluation API Contract Validation）**:
后端通过类型化响应模型约束 Case Evidence View，前端在 API 边界校验版本和字段；不兼容响应必须显式进入契约错误状态，不能静默显示空白。

**Harness 表现分布（Harness Outcome Distribution）**:
将一组 Eval Item 按执行完成度、契约有效性、Hard Gate 和质量结果归入互斥状态，用于在 Run、Experiment 和结果总览中直观展示整体表现；它不是单一完成百分比。

**评测进度分布（Evaluation Progress Distribution）**:
由后端按评测协议阈值计算的 `passed`、`poor`、`failed` 和 `pending` Item 数量及总数；不同目标的分布分别计算，前端不自行推导质量颜色。

**评测结果焦点（Evaluation Result Focus）**:
评测控制台优先呈现质量结论、失败定位和可执行的证据下钻；配置、版本、运行控制和原始技术细节按层级收纳，不能与核心结果争夺首屏注意力。

**评测结果工作台（Evaluation Results Workspace）**:
管理员查看评测质量结论、Harness 表现分布、按结果档位分区的 Case 列表和证据下钻的唯一主工作区；它合并原“测评可视化”和“评测结果”页面，不再把两者作为平级入口。结果档位至少分为失败、不佳、通过、未完成/处理中，失败和不佳优先呈现，通过内容可以降级或折叠。

**评测侧栏入口（Evaluation Sidebar Entries）**:
评测结果工作台、版本与评测集、测评实验和人工 A/B 是管理员评测控制台的侧栏入口；结果工作台负责看结论，其他入口负责配置、发起或复核，不通过结果页面内的重复导航替代侧栏。

**版本与评测集（Releases and Benchmark Suites）**:
管理员查看和绑定一次评测所需的 Target Release、Evaluation Release、Harness/Candidate Simulator 版本与 Benchmark Suite 的配置工作区；它们共同回答“测谁、用什么 Harness、用哪套评测集”，不拆成两个重复的侧栏入口。

**业务语义展示（Business-facing Evaluation Language）**:
评测结果工作台面向管理员使用贴近业务且克制的人话，而不是直接暴露后端枚举、内部字段名或 Harness 实现术语；主界面只需清晰展示业务指标名、数值、单位和状态，阈值以简短形式就近展示，详细解释、技术字段名和原始 JSON 只出现在 Tooltip 或按需展开的审计详情中。

**Harness 指标解释层（Harness Metric Interpretation Layer）**:
目标 Payload 注册表为每个 Harness 指标维护业务名称、业务定义、单位、好坏方向、阈值来源、结果状态文案和不可用原因；前端主界面按精简的业务指标模型展示，不自行把 `tool_metrics`、`hard_gate_status` 等内部字段翻译成不稳定的中文。

**目标指标字典（Target Metric Dictionary）**:
在评测结果工作台实现前，先为 `interview`、`experience_extraction`、`jd_extraction`、`resume_analysis` 和 `question_tagging` 固定核心指标清单、中文名称、单位、阈值、状态语义、展示顺序和主/次级层级；每个 target 首屏最多展示 3–5 个核心指标，其余指标按需进入详情。

**Harness/Target 双层结果（Harness and Target Outcome Layers）**:
结果工作台分别展示 Harness 执行表现（例如评测约束、硬性要求、工具/意图执行）与 Target 业务结果（例如结构化抽取完整度、简历分析质量或题目分类质量），不把两者混成一个无法解释的总分。

**主要失败原因（Primary Failure Reason）**:
Case 列表只展示影响结果的主要失败原因，保证管理员可以快速定位；Case 证据详情保留全部失败原因、断言、Attempt、Artifact 和原始审计信息。

**人工对比评测（Human Pairwise Review）**:
管理员在相同评测输入下比较两个评测目标版本，并记录维度化偏好、平局或共同失败的人工评测结果。

**固定基准集（Fixed Benchmark Suite）**:
由不可变的基准案例组成、用于版本回归和发布判断的评测集合；它与会持续变化的生产采样集分开维护。

**初始模拟面试 Benchmark**:
当前评测框架已有 12 个模拟面试场景组成的初始固定基准集；每个场景需要固化为 Benchmark Case，并补齐 Expected Behavior、Hard Assertions、Quality Rubric 和 Replication Policy 后，才能进入 `interview-eval@1.0` 的正式版本门禁。

**目标专属 Benchmark 内容（Target-specific Benchmark Content）**:
为一个评测目标或同类目标定义的固定基准集；模拟面试、面经提取和简历分析分别维护自己的案例和量规，并放入各自的 Evaluation Release，不能将不同目标的指标混在一个结果中聚合。

**Scenario**:
描述测试意图、面试行为模式或失败模式的场景族；它可以包含多个不同输入和候选人行为的 Benchmark Case，不直接等同于一次执行样本。

**基准案例（Benchmark Case）**:
带有输入快照、预期行为和评测维度的最小评测单元，可被不同评测目标版本重复执行和比较。

**预期行为（Expected Behavior）**:
基准案例对结果应满足的事实、动作、边界和质量要求的集合，不等同于唯一标准文本。

**结构化 Case 契约（Structured Case Contract）**:
Benchmark Case 中可机器读取的评测定义，至少分离 `facts`、`actions`、`boundaries`、`quality_requirements`、`hard_assertions`、`rubric` 和可选 `reference_answer`，用于分别驱动确定性校验、LLM Judge 和人工评测。

**Case 输入 Snapshot（Case Input Snapshot）**:
Benchmark Case 使用的简历、JD、候选人画像、对话初始状态、工具夹具和其他输入上下文的不可变快照；Case 只能引用带内容摘要的 Snapshot，不在运行时读取可变用户数据或外部当前状态。

**Candidate-visible Context Boundary**:
Candidate Simulator 只接收候选人在真实面试中可见的白名单上下文；Expected Behavior、Hard Assertions、Quality Rubric、Judge 配置和其他评测元数据属于 Harness/Judge 私有上下文，禁止进入 Simulator 输入、工具参数或系统提示词。

**评测隔离运行空间（Eval Isolation Space）**:
用于执行 Eval Target 的轻量隔离数据和工具环境，复用应用代码与 Compose 基础设施，但使用独立数据库或 namespace、测试身份、Artifact 根目录和工具夹具，禁止写入真实用户数据和生产副作用。

**硬断言（Hard Assertion）**:
对结构、权限、安全、工具契约或必需事实进行可判定校验的评测要求；失败时可以直接阻断案例通过。

**质量量规（Quality Rubric）**:
用于评价正确性、完整性、深度、自然度或证据质量等开放式表现的维度化标准。

**评测评分流水线（Evaluation Scoring Pipeline）**:
按 Harness 合约校验、Hard Assertions、LLM Judge、结果聚合的顺序处理有效 Observation；Harness 无效时终止该 Item，Agent 行为触发硬断言失败时仍可继续 Judge 以保留质量诊断。

**评测裁判配置（Judge Configuration）**:
完整评测版本内部用于执行评测判断的一组不可变裁判配置，包含 Judge Model、Prompt、温度、结构化输出约束和评分规则；它决定评测结果如何产生，历史结果通过对应的完整评测版本追溯，不作为管理员单独发布的公开版本。

**端到端面试评测（Interview E2E Evaluation）**:
对一场完整多轮模拟面试的整体质量评估，综合候选人输入、面试官输出、工具轨迹、状态推进和最终收口；单步评测用于诊断，不替代端到端结论。

**E2E 重复评测组（E2E Replication Group）**:
在相同评测目标版本、完整评测版本和基准案例下重复执行多场端到端面试，并将这些运行作为一个稳定性统计单元。

**模拟器 Harness 配置（Simulator Harness Configuration）**:
完整评测版本内部用于编排和观测 Candidate Simulator 的不可变评测基础设施配置，至少包含运行器、对话状态推进、工具与环境夹具、超时与重试策略、随机性配置、轨迹采集和输入组装规则；它与 Candidate Simulator 配置分开分组，但不作为管理员单独维护的公开版本。

**Candidate Simulator 配置（Candidate Simulator Configuration）**:
完整评测版本内部用于生成候选人行为的不可变模拟器配置，包含模拟器模型、System Prompt、候选人画像、回复策略、工具配置和采样参数；它与被测评测目标版本分开记录，并随完整评测版本整体更新。

**评测稳定性指标（Evaluation Stability Metrics）**:
描述重复评测组整体水平和波动性的统计结果，包括典型质量、离散程度、失败率和关键门禁状态，不只使用单次分数或均值。

**评测协议（Eval Protocol）**:
完整评测版本内部的执行协议：每个 Benchmark Case 默认执行 5 次 Replication；当结果接近 Suite 门槛或波动超过协议阈值时，通过独立扩展 Batch 增加到 10 次。协议同时定义超时、重试预算、聚合方式、质量权重和通过门槛，不作为管理员单独维护的公开版本。

**生产采样集（Production Sample Set）**:
从真实使用中脱敏采样形成、用于发现分布变化和新问题的评测集合；它不直接作为固定版本回归的唯一依据。

**面试空间（Interview Workspace）**:
用户用于查看、复盘和继续其面试记录的统一空间。

**面试记录（Interview Record）**:
用户在一次面试经历中产生的上下文、问答和分析结果的完整记录。

**外部导入面试记录（Imported Interview Record）**:
在 InterviewBoss 外完成、于面试结束后提交给 InterviewBoss 的完整面试记录；它保留来源标识，但在面试空间中与原生面试记录统一呈现。

**面试记录来源（Interview Record Origin）**:
标识一条面试记录是在 InterviewBoss 内原生产生，还是由外部客户端导入。

**结构化面试回合（Structured Interview Turn）**:
一次有明确顺序的面试提问与候选人回答，允许关联 InterviewBoss 题目和分析证据。

**原始面试记录（Raw Interview Transcript）**:
外部客户端提交的完整面试原文，是导入记录的不可变证据，不因后续结构化或分析而改写。

**导入草稿（Import Draft）**:
尚未完成接收和分析、因此还未发布到面试空间的外部面试记录。

**可恢复导入（Resumable Import）**:
导入失败后可以依据服务端返回的任务和分块状态继续传输，不需要从头重新提交整份记录。

**导入任务（Import Job）**:
承载一次外部面试记录接收、校验和分析过程的独立对象，其生命周期不依赖某个 MCP 会话。

**导入分块（Import Chunk）**:
外部面试记录在传输过程中的可校验片段，具有稳定顺序标识；相同内容的重复分块不改变导入结果。

**导入分析（Import Analysis）**:
InterviewBoss 对已完整接收的外部面试记录进行结构化、题目关联、评分和报告生成的过程；完成前不代表正式面试记录已经发布。

**导入分析重试（Import Analysis Retry）**:
在已完整接收的导入内容上重新执行分析，不重新提交或修改原始面试记录。

**外部问题（External Question）**:
导入面试记录中无法可靠关联到 InterviewBoss 题库的问题；它只属于当前面试记录，不等同于公共题库题目。

**练习历史（Practice History）**:
用户通过独立练习答题流程产生的题目、回答和评分记录；面试记录导入不会自动写入练习历史。

**面试表现统计（Interview Performance Statistics）**:
针对模拟面试记录中的阶段、覆盖、回答和报告进行的统计，与独立练习题统计分开。

**题目关联（Question Linkage）**:
结构化面试回合与 InterviewBoss 题库题目的关系，只有经过 InterviewBoss 校验后才成立；未通过校验的回合保留为外部问题。

**题目出现（Question Occurrence）**:
某条面经或面试记录中实际出现的一次原始题目事实；它保留 `interview_id`、明细记录和原始题面，不等同于题库中的规范题目或聚类。

**题库聚类（Question Cluster）**:
用于练习、检索和统计的规范题目单元；它拥有明确的作用域、所有者、生命周期和代表题面，并通过题目关联连接一个或多个题目出现。

**个人题命中公共题规则（Personal-to-Public Canonical Rule）**:
个人上传的题目如果命中已审核公共题，公共题是唯一 canonical 题，不创建个人副本；个人记录只保存对该公共题的关联及用户自己的练习/答案数据。

**公共发布申请（Public Promotion Request）**:
用户将自己的个人题目或题目出现提交到公共题库的独立申请；申请以快照进入公共匹配/聚类和审核流程，不通过个人题库重建隐式修改公共题库。

**公共化申请不等于分享（Promotion Is Not Sharing）**:
本领域不提供个人题的通用分享授权、分享链接或协作副本；个人题进入公共题库只能通过公共发布申请，经过审核和公共聚类后才对公共用户可见。

**公共数据贡献申请（Public Contribution Request）**:
用户将个人面经或 JD 提交给公共数据构建流程的申请；面经和 JD 共用申请、审核和审计边界，但分别进入题目聚类或岗位结构化流水线。

**公共 JD 结构化贡献（Public JD Structured Contribution）**:
公共化 JD 默认只贡献经过审核和脱敏的岗位要求、技术栈或能力标签等结构化结果，不公开原始 JD 文本。

**公共贡献快照（Public Contribution Snapshot）**:
用户提交公共化申请时形成的不可变内容版本；它是管理员审核和公共处理的共同输入，不随个人面经或 JD 后续编辑而变化。

**外部分析（External Analysis）**:
由 GPT 或其他外部客户端随面试记录提交的评分、总结和建议；它可以被保存和展示，但不是 InterviewBoss 的官方分析结论。

**导入记录生命周期（Imported Record Lifecycle）**:
外部面试记录从导入草稿、完成分析到正式发布的完整生命周期；未完成草稿会过期，正式记录由用户负责删除。

**导入任务归属（Import Job Ownership）**:
导入任务和由其产生的面试记录只属于创建任务时认证的 IB 用户，不接受外部客户端指定其他用户。

**面试续接（Interview Continuation）**:
用户基于已完成的外部导入记录开启的一场新的 InterviewBoss 原生面试；它与来源记录关联，但拥有独立的问答和状态生命周期。

**导入请求幂等性（Import Request Idempotency）**:
同一个外部请求标识只对应一个导入任务；不同请求标识代表用户有意提交新的面试经历，即使内容相同也不自动合并。

**面试记录读取（Interview Record Access）**:
用户或经授权的面试代理可以查看其面试记录摘要、报告和续接入口；完整原始记录只有在明确请求时才读取。

**面试上下文快照（Interview Context Snapshot）**:
面试记录创建时固定的岗位、公司、轮次、招聘季、JD 和简历版本，用于保证历史分析的依据不会随用户资料变化而漂移。

**报告版本（Report Version）**:
基于同一面试记录的一次完整分析结果；最新成功版本是当前官方报告，历史版本保留用于复盘和比较。

**单轮回答评估（Turn Evaluation）**:
针对一次候选人回答形成的结构化质量、能力维度、证据、缺失点和后续动作判断。

**面试报告评分（Interview Report Scoring）**:
基于多轮回答证据、题目难度、能力覆盖和岗位要求形成的面试级综合评价，不是单轮分数的简单平均。

**面试策略决策（Interview Strategy Decision）**:
GPT 基于当前面试状态和已加载的节奏 skill 对下一步面试动作作出的判断，例如追问、澄清、换题或结束。

**状态事实（Interview State Fact）**:
由 InterviewBoss 保存并作为面试真实依据的记录，例如已问问题、当前阶段、回答状态、覆盖事件和状态版本。

**面试回合推进（Interview Turn Advance）**:
GPT 在一次调用中提交候选人回答和面试策略决策，InterviewBoss 原子保存事实、校验动作并推进面试状态的过程。

**面试动作（Interview Action）**:
面试策略决策使用的受约束动作，例如澄清、追问、切换维度、抽取题库题或结束面试；动作名称属于稳定协议。

**候选人控制指令（Candidate Control Instruction）**:
候选人明确提出的结束、跳过、切换方向等面试控制意图；它的优先级高于默认面试节奏，但仍需形成可追踪的面试事件。

**即时回合评估（Provisional Turn Evaluation）**:
GPT 在面试进行中基于当前回答提供的即时结构化评价；它用于反馈和节奏决策，不等同于 InterviewBoss 的官方报告结论。

**官方面试报告（Official Interview Report）**:
InterviewBoss 基于完整面试记录异步生成并版本化的最终分析结果。

**面试结束（Interview Closure）**:
面试记录保存最后一个回合并封存、随后进入官方报告分析的生命周期动作；提前结束会保留覆盖不完整的事实。

**面试 Skill 版本（Interview Skill Version）**:
一场面试开始或续接时确定的节奏、评估、记录和导入规则版本，用于保证同一面试过程中的指导和复盘可追溯。

**面试状态版本（Interview State Version）**:
面试状态事实的单调递增版本，用于判断一次 GPT 策略决策是否基于最新状态，避免并发或重试覆盖较新的回合。

**不可信面试内容（Untrusted Interview Content）**:
导入的面试原文、简历和外部分析等仅供 InterviewBoss 和 GPT 分析的用户数据，不具有系统指令、工具权限或状态变更权限。

**原生记录投影（Native Record Projection）**:
外部导入分析成功后，在用户的原生面试记录模型中形成可查看记录的过程；导入草稿和传输过程不等同于原生面试记录。

**MCP 面试读权限（MCP Interview Read Scope）**:
允许当前认证用户通过 MCP 读取候选人画像、面试记录、报告、状态和题库信息的权限。

**MCP 面试写权限（MCP Interview Write Scope）**:
允许当前认证用户通过 MCP 创建或改变导入任务、面试回合、续接面试和结束状态的权限。

**全局模型配置（Global Model Config）**:
管理员统一配置的 LLM 与 embedding 参数，存于 `user_profile` 表（全局单例，无 owner）。
_避免使用_: 系统配置（歧义，per-user 配置也属配置）

**全局 LLM 配置（Global LLM Config）**:
`user_profile` 的 `llm_*` key；per-user 未配置时回退到它。
_避免使用_: 主模型配置

**per-user LLM 配置（User LLM Config）**:
`user_llm_config` 表的每用户记录；优先级高于全局 LLM 配置。

**embedding 配置（Embedding Config）**:
`user_profile` 的 `embedding_*` key；模块级 env 常量兜底，`reload_embedding_config()` 从 DB 热加载覆盖。

**全量重算（Embedding Recompute）**:
更换 embedding 模型后，重编码所有未删除题的向量并更新 `embedding_model`/`embedding_dim` 列；失败时回滚已更新行，保证"全成功或全不动"。
_避免使用_: 向量刷新（语义含糊）

**过渡窗口（Transition Window）**:
embedding 配置 reload 生效到全量重算完成之间的阶段；期间依赖 embedding 的检索/聚类暂不可用或失真，其余功能不受影响。

**测试连接（Connectivity Test）**:
用提交的配置探测 LLM/embedding 服务连通性，不保存配置。

**公开思考轨迹（Public Reasoning Trace）**:
面试进行中向用户展示的模型分析、行动选择和工具执行过程；它属于面试体验的一部分，与最终面试官话术和后台审计记录分开表达。
_避免使用_: 内部推理（当内容确实面向用户展示时）

**回合运行轨迹（Turn Run Trace）**:
一次面试回合从理解候选人回答到生成最终面试官话术期间形成的可查看过程记录；它包含公开思考轨迹和动作节点，但不等同于跨回合保留的面试状态事实。

**可恢复回合运行轨迹（Resumable Turn Run Trace）**:
即使实时连接中断，用户仍可从上次位置继续查看同一面试回合已经产生的运行过程，并在回合完成后重放完整轨迹；连接中断本身不代表回合取消。

**回合取消（Turn Cancellation）**:
用户主动终止正在执行的面试回合；它与网络连接中断不同，会保留已产生的回合运行轨迹，并允许用户重新编辑输入后发起新的回合。

**输入修订（Turn Input Revision）**:
用户基于已取消或已完成回合修改原始输入后形成的新面试回合；修订不会篡改原回合的事实和运行记录。

**回合事实提交（Turn Fact Commit）**:
一次面试回合经过校验并正式写入面试事实的动作；只有成功提交的回合才能推进 `Ledger`，取消或被修订的运行轨迹不属于正式面试事实。

**公开思考片段（Reasoning Segment）**:
公开思考轨迹中按连续生成过程切分、可独立持久化和重放的一段内容；它不是单个 token，也不是最终面试官话术。

**默认折叠思考轨迹（Collapsed Reasoning by Default）**:
公开思考轨迹默认以收起状态呈现，用户主动展开后才能阅读完整内容；默认折叠只改变展示方式，不减少轨迹保存或恢复能力。

**公开思考轨迹访问边界（Public Reasoning Trace Access Boundary）**:
面试记录拥有者可以查看原始 CoT；共享、导出和公开展示默认不包含原始 CoT，管理员和评测系统通过独立授权访问审计轨迹。

**回合事件流（Turn Run Event Stream）**:
以单个 `TurnRun` 为边界、按服务端单调序号记录回合执行过程的事件序列；会话级时间线通过多个回合的顺序和引用汇总，不把所有运行过程平铺到 Session 中。

**上下文清单（Context Manifest）**:
记录一次模型调用选择了哪些上下文块、使用何种版本、顺序、权限和预算的可审计清单；它支持重建和校验 ContextPack，但不等同于完整 Prompt 原文。

**SSE 事件信封（SSE Event Envelope）**:
所有回合流式事件共享的稳定外层结构，至少包含回合标识、事件序号、动作标识、时间、Schema 版本和事件 payload。

**单回合执行设施（Turn Execution Infrastructure）**:
由 ARQ、数据库和 SSE 共同管理单个面试回合的执行、状态和实时展示；不额外引入另一套队列或状态系统。

**执行单元（Turn Execution Unit）**:
从一条候选人输入开始，到对应的最终面试官回复或明确终态结束的一次 `TurnRun`；整场面试由多个执行单元组成。

**执行尝试（Turn Attempt）**:
同一个 `TurnRun` 因基础设施失败而产生的一次 Worker 执行尝试；尝试增加序号但不创建新的用户回合，只有输入修订才创建新的 `TurnRun`。

**单活跃回合（Single Active Turn）**:
同一面试 Session 同时最多存在一个可执行的 `TurnRun`；新的输入必须等待、取消或修订当前回合后才能提交。

**至少一次事件投递（At-least-once Event Delivery）**:
事件持久化只产生一个权威序号，但网络重连可能重复投递；客户端按 `turn_run_id + sequence` 去重，而不是要求传输层 exactly-once。

**事件可见性（Event Visibility）**:
描述运行事件允许哪些角色读取的权限属性；拥有者可查看公开思考轨迹，管理员和评测系统按独立授权查看审计内容，前端不能自行扩大可见范围。

**语义动作节点（Semantic Action Node）**:
面向用户解释回合进展的高层动作，例如理解回答、确认方向、检索题目、生成回复和校验回复；它不等同于每个内部函数或数据库操作。

**部分回合轨迹（Partial Turn Trace）**:
回合在失败或取消前已经产生的消息片段、动作和 CoT；它可以用于查看和诊断，但不代表已提交的面试事实或正式 assistant 回复。

**回合快照（Turn Run Snapshot）**:
`TurnRun` 当前可快速读取的生命周期、阶段、尝试、序号、动作、租约和提交状态；它是事件流的当前读模型，不替代完整事件历史。

**Worker 租约（Worker Lease）**:
Worker 领取回合后在数据库中维护的有限有效期执行权；租约过期表示执行者可能失联，回合可以进入恢复或重试流程。

**动作级重试（Action-level Retry）**:
以当前语义动作作为最小边界的有限重试；重试属于同一 `TurnRun` 的新 attempt，不重复创建用户可见回合。

**提交后记忆提取（Post-commit Memory Extraction）**:
只有回合事实成功提交后，才异步从该回合提取长期记忆；它不阻塞当前回复，也不接受取消或失败回合为来源。

**用户可见轨迹投影（User-visible Trace Projection）**:
按拥有者权限、脱敏规则和 UI 需要从完整运行事件生成的可展示视图；它与包含内部指标和受保护原始数据的审计投影分离。

**运行轨迹 Artifact（Run Trace Artifact）**:
从事件流归档出的完整 CoT、工具和调试证据文件；它受独立访问控制和保留策略管理，不作为单条消息的 JSON 元数据保存。

**事件协议版本（Event Contract Version）**:
事件 envelope 和 payload 的兼容版本标识；新客户端可以忽略未知事件，破坏性语义变化必须升级版本。

**临时 assistant 输出（Provisional Assistant Output）**:
在回合最终提交前已经通过流式事件展示的候选面试官话术；它可以被失败或取消终止，只有正式终态后才成为 Transcript 中的 assistant 消息。

**回合流状态归并器（Turn Stream Reducer）**:
前端按事件序号和动作标识将 SSE 事件归并为一个 `TurnRun` 展示状态的逻辑；它负责去重和恢复，不负责改变后端事实。

**事件契约单一来源（Single Event Contract Source）**:
由后端 Schema 定义事件类型、版本和 payload，前端 reducer、API 文档和测试均依据该契约，不自行猜测字段。

**模型调用来源记录（Model Invocation Provenance）**:
描述一次模型调用所使用的 provider、model、Prompt/Skill/Context 版本、尝试、耗时、Token 和结束原因的审计信息；它用于复现和评测，不等同于用户可见话术。

**临时 assistant 输出（Provisional Assistant Output）**:
在回合最终提交前已经通过流式事件展示的候选面试官话术；它可以被失败或取消终止，只有正式终态后才成为 Transcript 中的 assistant 消息。

**原生思考流（Native Reasoning Stream）**:
模型供应商明确提供的 reasoning channel 或 reasoning token 流；普通回复文本不得被伪装为原始 CoT。

**回合事实提交版本（Turn Commit Version）**:
`CommitTurn` 写入 Ledger 时使用的 Ledger 版本；版本冲突意味着回合不能静默覆盖较新的面试事实。

**Worker 丢失（Worker Lost）**:
回合执行租约过期或 Worker 异常退出而未产生终态的运行故障；它触发恢复或新 attempt，不直接删除或伪造回合结果。

**旧会话兼容轨迹（Legacy Trace Compatibility）**:
旧会话没有新 Harness 完整事件时，对已有消息和 metadata 做兼容展示，不补造不存在的动作、CoT 或 sequence。

**运行质量指标（Run Quality Metrics）**:
衡量回合首事件延迟、生成延迟、恢复、重复、丢失、取消和持久化成功率的内部指标集合；它与用户可见运行轨迹分离。

**模拟面试 Harness 2.0（Interview Harness 2.0）**:
采用 `Session`、`Ledger`、`TurnRun`、`ContextPack` 和可恢复回合事件流的新模拟面试 Harness 发布身份；正式评测使用不可变的 `interview-harness@2.0` Release，不以当前默认配置或数据库最新记录代替。

**抽题适配器（Question Broker）**:
将现有题库搜索、加权抽题、去重、岗位/题型过滤、私有题库隔离和权威题目重载能力适配为 Harness 2.0 的受控 `retrieve_evidence` 能力；它是服务模块，不是新的持久化字段、队列或状态系统。

**题目临时选择（Provisional Question Selection）**:
题目在检索和选择阶段属于当前 TurnRun 的临时证据；只有 `CommitTurn` 成功后才写入 Ledger，取消、失败和修订回合不能把临时题目变成正式已问事实。

**Skill 解析器（Skill Resolver）**:
依据 Session、Ledger 和 TurnPlan 确定性选择 Skill，并把 Skill 指令作为带权限、版本和 hash 的 ContextPack ContextBlock 注入模型调用；关键词匹配只能提供候选建议。

**Skill 来源记录（Skill Provenance）**:
一次模型调用实际使用的 Skill key、Skill version、Harness 兼容声明和 content hash；它必须进入 Context Manifest 与模型调用 provenance，不能用固定默认版本冒充真实 Skill 版本。

**Harness 2.0 兼容适配层（Harness 2.0 Compatibility Adapter）**:
把现有 ReAct 工具和 Skill 实现接入 `PolicyGate → QuestionBroker/SkillResolver → ContextPack` 的适配边界；底层题库和 Skill 内容可以复用，但模型自由选工具、直接修改 ChatState 和隐藏式副作用不属于 2.0 合同。

**受限 ReAct（Bounded ReAct）**:
Harness 2.0 中保留的 ReAct 子程序，只负责分析回答、请求受控证据和产生原生 reasoning segment；它不能直接裁决最终面试动作、推进 Ledger 或提交正式回复。

**Harness 1.0 兼容模式（Harness 1.0 Compatibility Mode）**:
旧 ReAct 编排作为 feature flag 控制的历史路径继续运行；新 Eval 默认冻结 `interview-harness@2.0`，旧会话按已有版本展示，不补造 2.0 轨迹或事实。

**选题上下文块（Question Selection Context Block）**:
QuestionBroker 选出题目后，由 ContextAssembler 生成并注入下一次 ReAct/Writer 模型调用的上下文块；它包含可自然改写的题面和约束，并将来源、选择理由、权威校验和内部评估信息置于受保护区域。

**服务端观察注入（Server Observation Injection）**:
服务端执行 QuestionBroker 后，将结构化结果作为同一 TurnRun 的 observation/evidence 追加到下一次 ContextPack，而不是伪造模型从未发出的 tool call；它使题库结果真正参与后续 Writer 决策并保留可恢复审计链。

**题目绑定校验（Question Binding Validation）**:
Validator 对照 TurnRun.question_plan 检查 Writer 话术是否仍覆盖已选题目的 allowed focus、没有切换主题或泄露内部信息；题目 ID由服务端 metadata 绑定，不要求出现在候选人可见文本中。

**检索未命中降级（Retrieval Miss Fallback）**:
题库无结果时由 PolicyGate 最多批准一次显式记录的备用抽题；仍无结果则向 ContextPack 注入 retrieval_miss，Writer 生成安全自然追问，不隐式无限重试题库。

**题卡回注（Question Card Re-entry）**:
QuestionBroker 选出的最终 QuestionCard 写入当前 TurnRun 的 question_plan/evidence，再由 ContextAssembler 生成 QuestionSelectionContextBlock，注入同一回合下一次 ReAct/Writer 调用；它不是新的领域状态对象，也不是伪造的模型 tool call。

**单题 Writer 输入（Single-card Writer Input）**:
InterviewerWriter 只接收服务端最终选中的一张题卡，而不是完整候选集；题卡包含 canonical_text、allowed_focus、forbidden_focus 和 allow_natural_rewrite，候选集只进入受保护审计轨迹。

**题目绑定校验（Question Binding Validation）**:
Validator 对照 TurnRun.question_plan.question_ref.id 检查 Writer 话术是否覆盖选题核心、没有切换主题、没有泄露内部信息并且只提出一个主要问题；题目 ID由服务端 metadata 绑定，不要求出现在候选人可见文本中。

**题卡修复上限（Question Repair Limit）**:
Writer 偏离已选题目时最多执行一次窄范围 repair；修复仍失败则当前 attempt 失败，不重新选题、不无限调用 Broker。

**Broker 幂等结果（Idempotent Broker Result）**:
QuestionBroker action 以 turn_run_id 与 action_id 幂等；Worker 重试复用已持久化的候选和选题结果，避免随机抽题因基础设施重试而改变。

**权威题目复核（Authoritative Question Recheck）**:
Writer 生成后、CommitTurn 前再次确认选中题目仍可用；题目失效时重新执行 Broker 并保留原 attempt 轨迹，不静默替换题目。

**正式已问时点（Committed Asked Moment）**:
题目只有在 Writer、Validator 和 CommitTurn 全部成功后才进入 Ledger 正式已问事实；检索、选中和 provisional assistant 输出都不推进 Ledger。

**稳定前缀指纹（Stable Prefix Hash）**:
由 Agent key、Harness 版本、provider、model、固定 Prompt、固定工具/Schema 和 Prompt Schema 版本规范化计算的本地审计指纹；不包含用户输入、TurnRun、Action、题目、Ledger 版本、时间戳或随机数。

**供应商 Prompt Cache Key（Provider Prompt Cache Key）**:
传给支持该能力的模型供应商、用于相同稳定 Prompt 前缀路由和命名空间的稳定标识；它不是业务幂等键，也不用于查找或恢复 LLM 回复。

**调用身份分离（Call Identity Separation）**:
`client_request_id` 负责 HTTP 幂等，`turn_run_id + action_id` 负责执行动作恢复，`stable_prefix_hash` 负责 Prompt 审计，`provider_prompt_cache_key` 负责供应商缓存路由；四者不得混用。

**缓存断点（Prompt Cache Breakpoint）**:
稳定 Agent Prefix 的供应商缓存边界；Turn Base 和 Call Suffix 放在断点之后，确保本轮用户输入、题卡、Ledger 版本和修复反馈的变化不破坏稳定前缀复用。

**缓存命中非业务事实（Cache Hit Is Non-authoritative）**:
Prompt Cache 只优化模型调用延迟和成本；缓存未命中不能改变 TurnRun、Ledger、SSE 恢复、ARQ 重试、题目选择或 CommitTurn 结果。

**固定上下文三段式（Stable Prefix / Turn Base / Call Suffix）**:
每次模型调用按稳定 Agent 前缀、本轮冻结上下文和本次调用动态尾部构造；稳定前缀只放通用规则和 Schema，Turn Base 在 TurnRun 创建时冻结，题卡、阶段和修复反馈放在最后的 Call Suffix。

**Turn Base 冻结（Frozen Turn Base）**:
一次 TurnRun 的本轮输入、Ledger 快照、历史摘要和初始 Skill 解析结果；后续模型调用不能中途重新排序、裁剪或替换，避免破坏前缀复用和审计一致性。

**缓存范围隔离（Cache Scope Isolation）**:
稳定前缀只含公共规则时可使用全局 provider cache key；包含租户或私有岗位资料时使用租户范围；不默认使用 TurnRun ID做缓存隔离。

**缓存观测指标（Prompt Cache Observability）**:
记录稳定前缀一致率、供应商 cache key 一致率、cached tokens、cache write tokens、命中/未命中和同一 TurnRun 内的前缀复用率；缓存是性能优化，不设为业务硬门槛。

**单一面试 Agent（Single Interview Agent）**：Harness 2.0 的生产运行时只维护一个 `interview-agent`；观察提案、回复生成、回复修复和输出校验通过固定调用模式区分，不拆成多个互相传递自然语言的生产 Agent。

**固定 Agent 状态流（Fixed Agent State Flow）**：`observe_propose → policy_gate → retrieve_evidence（可选且有界）→ write_response → validate_output → commit_turn`；下一个调用模式由 Harness 选择，模型不能自行切换。

**单语义动作调用（One Semantic Action per Call）**：一次模型调用只完成一个语义动作；跨阶段推进必须由 Harness 创建新的 action，并保留前一调用的不可变结果。

**只读 Agent 上下文（Read-only Agent Context）**：Agent 只能从 ContextPack 读取 Session、Ledger 和当前 TurnRun 快照，不直接修改完整 Session；业务事实由结构化提案、PolicyGate 和 CommitTurn 写入。

**受限证据继续（Bounded Evidence Continuation）**：证据检索只允许在题目结果注入后最多继续一次；SkillResolver 在模型外运行，Agent 不能自行加载 Skill 或改变面试阶段。

**临时 Agent 输出（Provisional Agent Output）**：Writer 在 Validator 和 CommitTurn 成功前产生的流式文本只是临时展示，不是正式 Transcript；只有校验和提交成功后才成为正式回复。

**Agent 明确失败（Explicit Agent Failure）**：失败、超时或预算耗尽时保留已产生的 Action、CoT 和临时轨迹，将 TurnRun 标记为失败，不推进 Ledger，不静默改变主题、阶段或回复内容。

**固定 Agent 结果 Schema（Fixed Agent Result Schema）**：每种 `call_mode` 使用固定联合 Schema；外层至少包含 Schema 版本、调用模式、TurnRun、Action、attempt、状态和结构化 payload，非法自然语言不能直接成为动作。

**观察提案合并调用（Combined Observe and Propose）**：`observe_propose` 一次同时产出观察、证据缺口、意图、题目策略和风险标记；观察用于审计，结构化提案交给 PolicyGate。

**纯代码 PolicyGate（Deterministic Policy Gate）**：PolicyGate 基于 Session、Ledger、提案、题库结果、预算和安全/阶段约束确定性输出允许、拒绝、修复、降级或失败，不调用 LLM。

**按需题库触发（Demand-driven Question Broker）**：只有需要题库绑定、覆盖维度、换题或权威题卡时才调用 QuestionBroker；普通自然追问不触发题库。

**代码优先 Validator（Code-first Validator）**：先执行 Schema、题卡绑定、单问题、主题边界、敏感信息和预算检查；语义不确定时最多执行一次窄范围 Validator 调用。

**非法 Schema 修复上限（Schema Repair Limit）**：模型结果解析失败时保留原始响应和错误，最多执行一次 Schema repair；仍失败则 TurnRun 显式失败，不把自然语言降级执行。

**动作重放与新尝试（Replay versus New Attempt）**：基础设施未确认响应时复用 `action_id` 幂等重放；已返回但非法、超时或质量不合格时创建新的 action/attempt，旧轨迹不可覆盖。

**Agent 分层预算（Per-mode Agent Budgets）**：TurnRun 总时长、单动作超时、证据继续、repair、reasoning token 和 assistant token 都有独立上限；耗尽必须产生明确事件。

**提交事务取消边界（Commit Cancellation Boundary）**：流式阶段和 action 边界可以停止；CommitTurn 进入数据库事务后不可取消，取消后的 provisional 输出不能成为正式 Transcript。

**Harness 驱动恢复（Harness-driven Recovery）**：Agent 不自行决定重试、repair、重新抽题、切换阶段或 fallback；所有恢复路径由 Harness 固定状态机选择并记录。

**固定 Agent Payload（Fixed Agent Payload）**：每个 `call_mode` 只接受对应的固定结构化 payload；未知字段只能进入审计 Artifact，不参与业务决策。

**固定动作提案（Enumerated Action Proposal）**：Agent 提案只能使用预定义动作枚举，例如追问、转题、澄清、检索题目和结束面试，不能新增动作类型或直接控制调用模式。

**题卡上下文追加（Question Card Context Append）**：QuestionBroker 结果由服务端作为不可变 `QuestionSelectionContextBlock` 追加到同一 TurnRun 的 ContextPack 末端，不伪造模型 Tool Call。

**Writer 计划只读（Read-only Writer Plan）**：Writer 只能生成候选人可见话术及有限表达 metadata，不能修改主题、深度、阶段、Ledger 或 QuestionCard。

**串行决策链（Serial Decision Chain）**：观察、PolicyGate、题库、写作、校验和提交按固定顺序执行；只有日志、指标和 Artifact 压缩等非决策任务可以并行。

**Reasoning/回答双通道（Dual Output Channels）**：`reasoning.delta` 与 `assistant.delta` 分离持久化，共享全局 sequence；前端可并行渲染，不能混淆二者的生命周期。

**软硬校验失败（Soft/Hard Validation Failure）**：可修复问题最多触发一次 repair，不可修复问题直接失败；Writer 不能通过文本隐式结束或切换阶段。

**有限 TurnRun 终态（Finite TurnRun Terminals）**：TurnRun 只允许 `completed`、`failed`、`cancelled`、`timed_out` 和 `budget_exhausted` 等终态，并要求记录终止原因。

**状态机授权结束（State-machine Authorized Completion）**：结束面试或切换阶段必须经过结构化提案、PolicyGate 和 Harness 状态机，不能由 Writer 文本或 CoT 隐式触发。

**评测调用 Provenance（Evaluation Call Provenance）**：评测固定采样配置和可用随机种子，并记录 Harness、模型、供应商、Prompt/Schema/Skill、ContextPack 和题卡结果 hash；生产随机性也必须可追溯。

**分层 Schema 版本（Layered Schema Versioning）**：事件 envelope、各 `call_mode` payload 和 Harness 发布版本分别管理版本；破坏性变化必须升级对应版本，不能靠模型猜测兼容。

**ContextPack 快照版本（Context Snapshot Version）**：ContextPack 携带 Session、Ledger、TurnRun 版本和自身 hash；CommitTurn 使用乐观并发校验，过期上下文不得强行提交。

**Evidence 来源分级（Evidence Provenance Class）**：候选人输入、题库权威结果、Skill 约束、模型观察和 Provider 输出使用不同来源标记；模型观察、confidence 和 CoT 不能直接成为 Ledger 事实。

**候选事实提交链（Candidate Fact Commit Chain）**：候选人回答中的事实必须经过结构化提案、PolicyGate、Validator 和 CommitTurn 才能进入正式状态，原始回答、模型观察和 Ledger 事实分开保存。

**PolicyGate 优先级（Policy Gate Precedence）**：安全与生命周期 > 事实和题目绑定 > 覆盖与面试配置 > 自然度与表达风格；低优先级规则不能覆盖高优先级约束。

**Provider 错误分类（Typed Provider Failure）**：网络、限流、Schema、内容策略和上下文超限分别走不同恢复路径；上下文超限不得静默裁剪冻结的 Turn Base。

**取消提交竞态（Cancel/Commit Race）**：取消请求与 CommitTurn 通过数据库条件更新竞争，先成功者决定回合结果，前端不能自行判定终态。

**结束动作复用（Finish Action Reuse）**：`finish_interview` 是既有 Agent 流程中的结构化提案，不新增生产 Agent 模式；总结、评估和长期记忆在提交成功后异步执行。

**CoT 原始与展示分层（Raw/Projected Reasoning）**：原生 reasoning 保存为 `raw_reasoning_artifact`，用户查看的是可脱敏、分段或摘要的展示投影，不能伪造 reasoning。

**置信度路由提示（Confidence as Routing Hint）**：confidence 只能影响继续、澄清或失败等 Harness 路由，不能直接改变 Ledger、绕过 PolicyGate 或成为正式事实。

**TurnRun 配置冻结（Frozen Turn Configuration）**：岗位、语言、难度、面试模式和题目策略在 TurnRun 创建时冻结到 Turn Base；中途修改只影响下一个 TurnRun。

**长会话派生摘要（Derived Long-context Summary）**：历史摘要只在新 TurnRun 创建前生成，带版本和 hash，是 Context Artifact 而非 Ledger 事实；当前回合内不压缩或重排。

**候选回答分类（Candidate Answer Classification）**：候选回答先归类为无回答、部分回答、不清晰、偏题或已回答，再由 Harness 决定澄清、追问、转题或继续。

**跳题 PolicyGate（Skip-question Policy Gate）**：跳题只是 Agent 提案意图，必须由配置、题目必要性、覆盖情况和预算共同裁决，不能由模型直接执行。

**自然停止意图（Natural Stop Intent）**：候选人说暂停或停止先作为交互意图识别，不等同于 UI 取消，最终由 PolicyGate 决定暂停、结束或继续。

**修订回合关系（Revision Turn Relation）**：编辑旧输入创建新 UserMessage 和新 TurnRun，并通过 `revision_of_turn_id` 关联；旧回合保留不可变轨迹，`superseded` 不是新的执行终态。

**SSE 回合隔离（Turn-scoped SSE Isolation）**：SSE 事件按 Session、TurnRun、sequence 和 event_id 隔离；旧回合晚到事件只能更新旧投影，不能进入新回合。

**Reasoning 能力降级（Reasoning Capability Fallback）**：Provider 没有原生 reasoning channel 时不伪造 CoT，只展示结构化动作进度。

**运行中版本失效（Runtime Version Invalidation）**：Skill 或题库版本失效时创建新 attempt，重新计算 Context/Skill hash，旧 attempt 轨迹保留且不可静默替换。

**异步评估投影（Async Evaluation Projection）**：总结、能力评估、覆盖报告和反馈在 CommitTurn 成功后异步生成，只读取正式 Transcript/Ledger，不反向修改面试事实。

**统一 Agent Response Envelope（Unified Agent Response Envelope）**：所有调用统一携带 Schema、调用模式、TurnRun、Action、attempt、状态、payload、usage 和 provenance；payload 按调用模式固定。

**ObserveProposePayload（ObserveProposePayload）**：观察调用固定返回回答分类、观察、证据缺口、意图、动作提案、题目策略、风险标记和 confidence；confidence 只参与路由。

**后端控制的 PolicyGate 输出（Backend-owned PolicyGate Output）**：PolicyGate 的决策、批准动作、约束和下一调用模式由后端生成，模型不能通过同名字段控制流程。

**Writer 话术 Payload（Writer Speech Payload）**：Writer 只返回候选人可见文本、语言、语气、问题数量和题目引用，不能修改计划、Ledger 或阶段。

**Validator 错误码（Validator Error Code）**：Validator 使用固定的 code、severity、message、field 和 repairable 字段，Harness 根据错误码决定修复或失败。

**Provider 响应归一化（Normalized Provider Response）**：Adapter 把不同供应商响应统一为 reasoning segment、assistant text、structured output、finish reason 和 provider metadata。

**Action 时序预算快照（Action Timing and Budget Snapshot）**：每个 action 保存开始、首 token、完成、超时、Token、重试和预算快照，前端、监控和 Eval 共用。

**确定性 ContextPack Hash（Deterministic ContextPack Hash）**：ContextPack 固定序列化顺序、空值规则、Unicode 规范化和时间/随机字段排除规则，相同输入必须得到相同 hash。

**三层 Agent 响应（Three-layer Agent Response）**：原始 Provider 响应、归一化 Agent 结果和用户可见投影分开保存，分别服务审计、Harness 和 SSE。

**Recorded Replay 评测（Recorded Replay Evaluation）**：评测可直接重放已保存的 Provider 响应和工具结果，不重新调用模型，用于验证 Harness 和事件链的确定性。

**原始 Provider 响应加密（Encrypted Raw Provider Response）**：原始响应加密保存，仅拥有者和审计权限可读，普通聊天接口只读取用户投影。

**轨迹统一保留删除（Unified Trace Retention）**：CoT、Prompt、候选人回答、工具结果和评估结果与面试记录绑定同一保留/删除策略，不留下孤立轨迹。

**SSE 前置脱敏（Pre-SSE Redaction）**：原始层严格保护，进入 SSE 前生成脱敏投影；密钥、Token、Cookie、内部 URL、供应商凭证和敏感候选人数据不得展示。

**Prompt Provenance 分层（Layered Prompt Provenance）**：默认保存 Prompt/Context hash 和版本，完整 Prompt Artifact 只对调试/审计权限开放。

**Delta 去重标识（Delta Deduplication Identity）**：SSE delta 通过 event、TurnRun、Action、channel、sequence 和 delta index 标识，前端重复收到时不得重复拼接。

**Sequence 权威顺序（Sequence Authoritative Ordering）**：事件表 sequence 是持久化顺序；乱序或缺失事件暂存并通过重连补齐，不按网络到达时间排序。

**结构化结果缺失（Missing Structured Result）**：Provider 仅返回普通文本而无结构化结果时视为 Schema failure，不能从自然语言猜测动作或事实。

**Replay 环境一致性（Replay Environment Match）**：Recorded replay 运行前校验 Harness、Prompt/Schema、Skill、ContextPack、Provider/model 和采样配置 hash，不匹配则不可比对。

**人工接管审计（Audited Human Takeover）**：人工接管只能执行预定义的 retry、cancel、mark_failed、approve_provisional 或 create_revision，并记录操作者、原因和时间。

**Harness 灰度开关（Harness Rollout Kill Switch）**：新 Harness 可按租户、Session、Provider/model 和版本灰度或关闭；关闭只影响新 TurnRun，不重写旧轨迹。

**不可信候选人输入（Untrusted Candidate Input）**：候选人内容只能进入 `candidate_input` 区块，不能成为 System Prompt、Harness 指令、Skill、Policy 或工具授权。

**Context 来源优先级（Context Source Precedence）**：Harness/System > Session 配置 > PolicyGate > Skill > QuestionCard > 候选人输入 > 模型解释；低优先级内容不得覆盖高优先级规则。

**外部 Evidence 不授予权限（Evidence Is Not Authorization）**：题卡、岗位描述、Skill、外部资料和工具结果只能提供带来源的证据，不能改变 Harness、PolicyGate、Ledger、权限或阶段。

**工具结果可信边界（Tool Result Trust Boundary）**：工具结果必须经过 Schema 校验和 PolicyGate，结果中的自然语言不能直接控制流程。

**模型资源加载隔离（Model Resource Loading Isolation）**：模型不能自行拼接 Prompt、加载 Skill、访问外部资源或执行工具，所有资源由服务端解析后注入 ContextPack。

**Evidence 大小上限（Evidence Size Bounds）**：Evidence block 限制字节数、嵌套深度、条目数、引用数和注入次数，超限显式失败而非无限扩展上下文。

**租户私有上下文隔离（Tenant-private Context Isolation）**：私有 Skill、题库、岗位资料和 Prompt 不进入全局 Prompt Cache、其他租户 ContextPack 或共享 hash 命名空间。

**Prompt Injection 评测（Prompt Injection Evaluation）**：Eval 覆盖候选人、题库、Skill、工具结果、岗位描述、跨 TurnRun 和跨租户注入，并检查工具越权、Ledger 污染、阶段切换、Prompt 泄露和跨租户访问。

**注入无权限语义（Injection Has No Authority）**：忽略规则、调用工具、跳过验证或访问其他租户数据的文本只能作为普通 evidence，不能改变 Harness 或权限边界。

**Eval 硬门槛与软评分（Hard Gates and Soft Scores）**：越权、Prompt 泄露、Ledger 污染、非法阶段切换、错误题目绑定和未校验回复属于硬门槛；自然度、相关性、覆盖、难度适配、连续性和体验属于软评分。

**版本化质量指标（Versioned Quality Metrics）**：题目绑定、Ledger 正确性、Policy 合规、重复题、覆盖、repair、硬失败、延迟和 SSE 恢复等指标定义随 Harness 版本冻结。

**Golden Trace 集（Golden Trace Set）**：固定覆盖正常、异常、拒答、跳题、结束、多语言、检索、Provider、Schema、Prompt Injection、编辑重发和 SSE 恢复场景。

**独立 Eval Judge（Independent Evaluation Judge）**：Judge 与生产 Interview Agent 分离，只读取正式事实和轨迹，不修改业务状态；评价 CoT 时结构化结果优先。

**失败最小复现包（Minimal Failure Reproduction Pack）**：失败样本保存输入、快照、ContextPack、Provider 响应、Action、PolicyGate、Validator、SSE 和版本 hash，支持 recorded replay。

**环境变化重测（Re-evaluate on Environment Change）**：Harness、Prompt、Skill、Provider、model、sampling 或 reasoning 变化均需重新运行关键 Golden Trace。

**Shadow Eval 只读（Read-only Shadow Evaluation）**：线上 Shadow Eval 只比较候选实现，不能写入正式 Ledger、Transcript 或用户 SSE。

**五维发布门槛（Five-dimensional Release Gate）**：功能、安全、一致性、体验和质量必须同时达标，核心指标回归时不扩大灰度。

**可执行回归阈值（Enforceable Regression Threshold）**：硬门槛使用零违规或明确安全阈值，软指标相对基线恶化超过版本配置阈值时自动阻止发布。

**固定 Action 状态（Fixed Action States）**：Action 只允许 pending、started、streaming、waiting、completed、failed、cancel_requested 和 cancelled。

**固定 Attempt 状态（Fixed Attempt States）**：Attempt 只允许 active、succeeded、failed 和 superseded，旧尝试不可覆盖。

**Action/Attempt 分离（Action Attempt Separation）**：Action 表示语义动作，Attempt 表示执行尝试，分别使用 TurnRun/Action 和 Action/attempt 编号标识。

**Action 数据库唯一性（Action Database Uniqueness）**：Action 和 Attempt 的唯一约束由数据库保证，不能只依赖应用层防重复。

**固定 Response Envelope（Fixed Response Envelope）**：Agent 调用统一携带 Schema、模式、TurnRun、Action、attempt、状态、payload、usage、provenance 和 errors。

**纯函数 ContextPack Builder（Pure ContextPack Builder）**：ContextPack 只由稳定前缀、冻结 Turn Base 和 Call Suffix 构造，不隐式读取数据库或调用模型。

**ContextBlock 元数据（ContextBlock Metadata）**：ContextBlock 携带 ID、类型、来源、hash、可见性和 sequence。

**显式等待状态（Explicit Await State）**：无下一步动作时使用 no_op 或 await_user_input，不用空 payload 表达。

**版本化预算快照（Versioned Budget Snapshot）**：预算来自版本化 Harness Config，并在 TurnRun 创建时冻结。

**最小 CommitTurn 输入（Minimal CommitTurn Input）**：CommitTurn 只接受校验后的回复、题目绑定、Ledger/Transcript patch、TurnRun ID 和 Ledger version。

**固定 SSE Envelope（Fixed SSE Envelope）**：所有 SSE 事件共享 Event、Session、TurnRun、sequence、type、channel、Action、phase、时间、Schema 和 payload 字段。

**事件类型注册表（Event Type Registry）**：业务事件必须来自固定注册表，客户端对未知事件降级或忽略。

**事务性 Outbox（Transactional Outbox）**：状态、事件和 Outbox 在同一事务写入，提交后由 Publisher 推送 SSE。

**SSE 双游标恢复（Dual Cursor SSE Recovery）**：SSE 同时支持 Last-Event-ID 和 after_sequence，服务端按最小未确认 sequence 补发。

**历史事件回放接口（Historical Event Replay API）**：SSE 之外提供按 TurnRun/sequence 查询事件的接口，用于恢复和审计。

**Heartbeat 非业务事件（Non-business Heartbeat）**：Heartbeat 只保活，不写事件表、不占业务 sequence。

**SSE 观察通道（SSE Observation Channel）**：SSE 断开不影响 Worker，重连从事件序列恢复。

**多设备只读订阅（Read-only Multi-device Subscription）**：多设备可以消费同一事件流，但同一 Session 只有一个有效 Worker。

**SSE 有界背压（Bounded SSE Backpressure）**：delta 可批量合并，业务事件不可丢失，慢客户端通过断开和 sequence 补偿恢复。

**取消请求事件（Cancel Request Event）**：取消接口只写 cancel_requested，由 Worker 在安全边界检查。

**TurnRun 顶层运行卡片（TurnRun Run Card）**：一个 TurnRun 对应一个顶层卡片，内部展示 Action、Reasoning、Evidence 和 Output。

**双层运行折叠（Dual-level Run Collapse）**：顶层运行卡片和内部 Action 卡片分别控制展开，内部再展示 reasoning/evidence/output。

**当前 Action 自动展开（Active Action Auto-expand）**：当前执行 Action 自动展开，完成后折叠，用户手动状态优先。

**CoT 高度上限（Bounded CoT Height）**：CoT 卡片有最大高度和内部滚动，避免占满消息列表。

**Reasoning/Assistant 双投影（Dual Reasoning Assistant Projection）**：两个通道可并行展示，但生命周期和视觉语义分离。

**Provisional UI 状态（Provisional UI State）**：未完成校验和提交的助手输出显示待校验，失败时显示未提交，成功后转正式消息。

**停止 UI 状态机（Stop UI State Machine）**：停止生成、正在停止、已停止/已完成是固定交互状态，防止重复取消。

**编辑版本分支（Edit Revision Branch）**：编辑输入创建新消息和新 TurnRun，旧版本只读保留。

**SSE 断线可见性（Visible SSE Disconnect State）**：重连中、已恢复、后台运行和需手动重连是明确前端状态，不自动创建新回合。

**失败动作投影（Failure Action Projection）**：前端区分重试、编辑重发、取消、超时、预算耗尽和系统失败，并显示对应动作。

**生命周期 API 分离（Lifecycle API Separation）**：创建、查询、事件、取消和修订 API 分离，创建不等待完成，订阅不触发执行。

**追加式事件与 Artifact（Append-only Events and Artifacts）**：事件、Action、Attempt 和 Artifact 只追加，不原地覆盖。

**数据库幂等约束（Database Idempotency Constraints）**：TurnRun sequence、Action、Attempt 和 client request 的唯一性由数据库保证。

**ARQ 单一职责（Single ARQ Responsibility）**：ARQ 只触发和重试 Worker，数据库保存权威状态，Redis 不形成第二套业务事实。

**安全 Action 恢复点（Safe Action Recovery Point）**：Worker 从最近安全边界恢复，已完成跳过、未确认重放、失败新 Attempt、已提交不重复。

**端到端故障矩阵（End-to-end Failure Matrix）**：固定测试正常、故障、断线乱序、取消竞态、编辑、多设备、版本失效和注入场景。

**分层测试矩阵（Layered Test Matrix）**：覆盖单元、状态机、事务、Provider、Worker/ARQ、SSE、前端 reducer、浏览器 E2E 和 Replay Eval。

**Harness 1.0 历史兼容（Harness 1.0 Historical Compatibility）**：旧会话保持原 provenance，不补造 2.0 轨迹，新回合才使用 2.0。

**发布验收清单（Release Acceptance Checklist）**：发布前统一检查 Agent、Context hash、Prompt Cache、SSE、取消/编辑、安全、Replay、性能成本和前端交互。

**Harness 2.0 设计冻结（Harness 2.0 Design Freeze）**：全部合同确认后进入实现，不再开放式扩展架构方向，只处理实现中发现的真实冲突。
