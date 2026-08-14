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

**评测目标版本（Evaluation Target Release）**:
某个 Agent、Workflow 或 Pipeline 在特定代码、配置和评测依赖状态下的不可变行为快照；不同目标分别维护版本，不因其他目标变化而自动改版本。

**人工对比评测（Human Pairwise Review）**:
管理员在相同评测输入下比较两个评测目标版本，并记录维度化偏好、平局或共同失败的人工评测结果。

**固定基准集（Fixed Benchmark Suite）**:
由不可变的基准案例组成、用于版本回归和发布判断的评测集合；它与会持续变化的生产采样集分开维护。

**基准案例（Benchmark Case）**:
带有输入快照、预期行为和评测维度的最小评测单元，可被不同评测目标版本重复执行和比较。

**预期行为（Expected Behavior）**:
基准案例对结果应满足的事实、动作、边界和质量要求的集合，不等同于唯一标准文本。

**硬断言（Hard Assertion）**:
对结构、权限、安全、工具契约或必需事实进行可判定校验的评测要求；失败时可以直接阻断案例通过。

**质量量规（Quality Rubric）**:
用于评价正确性、完整性、深度、自然度或证据质量等开放式表现的维度化标准。

**评测裁判版本（Judge Release）**:
用于执行评测判断的一组不可变裁判配置快照；它决定评测结果如何产生，历史结果必须保留其对应的裁判版本。

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
