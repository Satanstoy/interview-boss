# ADR-0050：面试回合运行轨迹使用可恢复的持久化事件流

**Status:** accepted

模拟面试需要让用户看到每个回合正在执行什么，并在 SSE 断线后完整恢复动作节点、公开思考轨迹和最终回复。为此，`TurnRun` 的运行轨迹采用追加式持久化事件流；SSE 只负责实时传输和重放，不作为唯一事实来源。

## 决策

1. 每个 `TurnRun` 都有独立、可重放的运行事件序列，事件至少具备 `turn_run_id`、单调 `sequence`、事件类型、阶段、时间、Schema 版本和事件 payload。
2. 事件流保存用户可见的结构化动作事件、公开思考轨迹、工具执行摘要和最终回复片段；`Session`/`Ledger` 仍保存跨回合事实，运行轨迹不替代面试状态事实。
3. SSE 事件携带可恢复的事件 ID；客户端断线后按最后序号继续请求，服务端补发缺失事件。已完成回合也必须能够重放完整轨迹，而不能只重放最终文本。
4. 前端将一个 `TurnRun` 呈现为双层可折叠运行卡片：运行时自动展开，完成后折叠为耗时摘要；动作节点和其公开思考轨迹分别支持展开，并在思考内容区域设置独立高度和滚动边界。
5. 现有质量保护中“ReAct 文本不直接对用户可见”的约束由本 ADR 的公开思考轨迹决策取代；流程裁决、状态提交、输出校验和权限边界仍然有效。
6. SSE 断开不取消后台 `TurnRun`；只有独立的用户取消操作才能终止回合。取消后的输入修订创建新的回合，原回合及其已产生事件保持不可变。
7. 输入修订通过 `revision_of_turn_id` 关联原回合；原回合、事件和 CoT 永远不被覆盖。前端可以默认折叠被修订回合，但必须保留查看入口。
8. 只有经过校验并成功执行 `CommitTurn` 的回合才能推进 `Ledger`；取消、失败或被修订的 `TurnRun` 只保留运行轨迹，不产生正式覆盖、深度、已问或收尾事实。
9. CoT 以 `reasoning_segment` 形式分段持久化；每个 segment 先成功写入事件流并获得序号，再通过 SSE 发送。客户端重连按已确认序号重放 segment，不要求数据库为每个 token 生成一条事件。
10. 原始 CoT 默认折叠展示，但用户可以主动展开查看；默认折叠不影响后端持久化、断线恢复和历史重放。
11. 原始 CoT 的默认访问者是面试记录拥有者；共享、导出和公开展示不包含原始 CoT，管理员与评测系统通过独立授权访问审计轨迹。
12. 事件存储以 `TurnRun` 为边界；每个回合拥有独立的单调事件序列，会话级时间线通过回合顺序和引用汇总。
13. `ContextPack` 默认只持久化 `context_manifest`；完整 Prompt 原文作为受保护调试 Artifact 按需保存，不作为 Session 或 Ledger 的普通字段。
14. SSE 使用统一事件信封和有限事件类型：`turn.started`、`action.started`、`action.updated`、`action.completed`、`reasoning.segment`、`assistant.delta`、`turn.completed`、`turn.cancelled`、`turn.failed`、`heartbeat`。事件至少携带 `turn_run_id`、`sequence`、`action_id`、时间、Schema 版本和 payload。
15. 单个面试回合只使用 ARQ、数据库和 SSE 三种执行设施：ARQ 负责任务调度，数据库保存回合状态与事件，SSE 负责实时订阅；不再额外引入独立队列或状态编排系统。
16. 一个 `TurnRun` 表示一条用户输入到对应最终面试官回复或明确终态的执行单元；同一 `Session` 同时只允许一个活跃回合。
17. `TurnRun.status` 与 `TurnRun.phase` 分离：status 表示生命周期，phase 表示当前执行位置。状态事件和阶段事件都进入回合事件流。
18. 创建回合时先在数据库事务中写入回合、初始事件和 dispatch 记录，事务提交后再投递 ARQ；不对数据库和 Redis 做不可原子的同步双写。
19. SSE 采用至少一次投递语义；数据库序号是权威顺序，前端按 `turn_run_id + sequence` 去重，重连可以重复收到已确认事件。
20. Worker 基础设施失败时在同一个 `TurnRun` 下增加 `attempt_no` 并恢复或重试，不创建新的用户回合；只有输入修订才通过 `revision_of_turn_id` 创建新回合。
21. 取消和完成通过数据库原子终态竞争决定结果；先成功提交的终态生效，另一方不得覆盖已提交终态。
22. 下一轮 ContextPack 默认只读取 Session、Ledger、已提交 Transcript、当前输入和必要长期记忆；取消、失败或修订回合的 CoT 不作为默认面试上下文。
23. 前端运行卡片运行时自动展开，终态后折叠为耗时摘要；动作节点和 CoT 独立展开，CoT 使用独立滚动和最大高度，用户离开底部时不被强制滚动。
24. 事件携带可由服务端执行的 `visibility` 属性；前端不能自行扩大事件可见范围。拥有者可查看公开 CoT，管理员和评测系统通过独立授权查看审计内容。
25. 用户界面只展示语义动作节点；低层函数、数据库操作和内部重试属于审计轨迹，不作为默认动作列表。
26. CoT segment 必须关联 `action_id`，可以通过 `parent_action_id` 表达动作层级；不允许产生无法归属的自由浮动 CoT。
27. 最终 assistant 话术拥有独立生命周期事件 `assistant.started`、`assistant.delta`、`assistant.completed`，与 CoT 轨迹分开；`turn.completed` 只在事实提交后产生。
28. heartbeat 只用于 SSE 保活，不写入业务事件表；业务事件 sequence 才是恢复依据。
29. CoT 和 assistant delta 可以在服务端和前端批量合并后渲染，以控制响应式更新频率，但持久化顺序和内容不能被合并逻辑破坏。
30. 生成中途失败时保留部分回合轨迹，但不生成正式 assistant 消息、不推进 Ledger；前端提供重试和输入修订入口。
31. 用户取消后，在旧回合写入 `cancelled` 或 `completed` 终态前不创建新回合；输入框可以提前编辑，但提交必须等待旧回合终态。
32. 历史会话初次只加载消息、运行摘要和动作摘要；完整事件与 CoT 通过展开动作懒加载。
33. 删除面试记录时，TurnRun、事件、CoT 和调试 Artifact 进入同一删除/保留策略；彻底删除不得留下无法解释的孤立轨迹。
34. `turn_runs` 保存状态、阶段、尝试、最新序号、当前动作、时间、修订关系和 Ledger 提交状态等当前快照；完整历史只存于追加式事件流。
35. `turn_run_events` 只追加、不原地修改或删除；通过 `(turn_run_id, sequence)` 唯一约束保证事件顺序和幂等。
36. 状态快照、事件和必要 Ledger 变更在同一数据库事务中提交；只有事务成功后才允许向 SSE 发送对应事件。
37. ARQ 使用确定性 `turn_run_id` 作为逻辑任务 ID；重复投递由 ARQ 唯一性和 Worker 数据库状态校验共同防止重复执行。
38. Worker 领取回合时写入租约、Worker 标识和心跳；租约过期的回合可以恢复或重试，不依赖 HTTP 连接存活。
39. 取消采用协作式语义：数据库先记录 `cancel_requested`，Worker 在动作边界和流式读取中检查，并尽力取消外部模型请求。
40. 同一 Session 允许多个已授权只读 SSE 订阅者，但始终只有一个 Worker 执行回合；所有订阅者消费同一事件序列。
41. 页面刷新或设备切换通过读取 TurnRun 快照并从最新 sequence 续订，不重新发起模型调用。
42. 重试以语义动作作为最小安全边界；动作级重试失败后在同一 TurnRun 下创建新 attempt，不生成新的用户回合或重复正式回复。
43. 长期记忆提取在 `CommitTurn` 成功后异步执行；取消和失败回合不产生长期记忆，记忆提取失败不回滚已经提交的面试事实。
44. 所有运行事件查询都执行 Session 拥有者鉴权；CoT、工具参数和 Artifact 不通过仅凭 `turn_id` 的接口暴露。
45. 用户可见投影对密钥、Token 和其他敏感工具字段进行脱敏；完整原始审计数据与用户可见轨迹分开存储并使用独立权限。
46. CoT、工具结果和候选人内容以安全纯文本或白名单 Markdown 展示，不能将不可信内容直接作为 HTML 执行。
47. CoT 和事件 Artifact 默认与面试记录使用同一保留和删除策略，回收、彻底删除和恢复必须保持关联对象一致。
48. 事件 envelope 与 payload 分别携带版本号；客户端对未知事件降级或忽略，破坏性语义变化升级协议版本。
49. SSE 继续使用现有带认证的 `fetch + ReadableStream`，在其上增加 Last-Event-ID 和重连，不改用无条件信任浏览器 EventSource。
50. 事件采用 `(turn_run_id, sequence)` 等关键索引独立存储，不把无限增长的完整轨迹塞入单条 JSON 记录。
51. 测试必须包含 Redis 投递失败、Worker 崩溃、SSE 断线、重复事件、重复 ARQ job、取消/完成竞态、编辑重发和页面刷新恢复。
52. 用户可见轨迹与系统内部观测指标使用不同投影；用户看到动作、CoT 和耗时，系统另行记录 token、延迟、重试、队列等待和写入耗时。
53. 新 Harness 通过 feature flag 和 kill switch 分阶段上线，异常时关闭新路径但不修改或重写旧会话数据。
54. 创建回合接口返回 `202` 和 `turn_id`，SSE 订阅独立建立；创建请求不等待模型执行完成。
55. SSE 统一使用固定事件 envelope，包含 `event_id`、`turn_run_id`、`sequence`、`type`、`action_id`、`phase`、时间、Schema 版本和 payload。
56. 重连同时支持 `Last-Event-ID` 和 `after_sequence`，以兼容标准 SSE 语义和现有认证 `fetch` 客户端。
57. 前端通过独立 `useTurnRunStream` 负责连接、重连、去重和事件归并，ChatView 只负责展示与交互。
58. `action.started` 创建动作节点，`action.updated` 按 `action_id` 更新，`action.completed` 关闭；事件顺序不能被前端追加逻辑改变。
59. assistant 输出在 `turn.completed` 前属于 provisional 状态；只有 assistant 完成和事实提交都成功后，才写入正式 Transcript。
60. 输入编辑进入独立编辑态，提交后创建新用户消息和新 TurnRun，旧消息和旧回合保持不可变。
61. 取消 UI 具有“停止生成—正在停止—已停止/已完成”三态；终态确认前不能提交新回合。
62. SSE 重连状态对用户可见；达到自动重试上限后提供手动重连，但不自动取消后台 TurnRun。
63. 后端 Pydantic/OpenAPI Schema 是事件契约唯一来源，前端 reducer、文档和测试不得自行定义冲突字段。
64. Harness 使用固定语义动作枚举：`observe_answer`、`propose_intent`、`policy_gate`、`retrieve_evidence`、`write_response`、`validate_output`、`commit_turn`。
65. PolicyGate 的候选提议和最终裁决都进入运行轨迹；用户看到语义摘要，拥有者可展开查看允许展示的完整思考过程，但最终动作以后端裁决为准。
66. 原始 CoT 只来自模型原生 reasoning channel；模型不提供该能力时只展示结构化动作进度，不伪造思考文本。
67. 每次模型调用保存 provider、model、Prompt/Skill/Context 版本、attempt、耗时、Token、finish reason 等私有 provenance，用于审计和评测。
68. TurnRun 和动作分别拥有超时、模型调用数、工具调用数、reasoning segment 数和输出 Token 预算；预算耗尽必须产生明确失败或降级事件。
69. 上下文压缩摘要不是 Ledger 正式事实，而是带版本和 hash 的派生 Context Artifact。
70. `CommitTurn` 使用 `ledger_version` 做乐观并发校验；版本冲突拒绝覆盖并要求重新读取最新事实。
71. 每个 attempt 的 assistant 输出独立作为 provisional 内容；失败 attempt 不能重复写入正式 assistant 消息。
72. 回合终态事件顺序固定为 `assistant.completed`、`CommitTurn`、Ledger 更新、`turn.completed`；只有 `turn.completed` 表示回合正式完成。
73. TurnRun、事件和 Ledger 使用同一数据库事务边界；面试任务使用独立的 `interview-turn` ARQ queue name，但不引入新的队列技术。
74. 同一 Session 同时只能拥有一个有效 Worker 租约；数据库条件更新或唯一约束负责防止并发执行。
75. 租约过期或 Worker 异常退出写入 `worker_lost` 事件，并从最近安全动作恢复或创建新 attempt，不删除原轨迹。
76. 长 CoT 的事件索引和动作摘要长期可查，完整 segment 可以归档为 Artifact；历史展开时按需加载。
77. Token、时间或成本预算耗尽必须产生用户可理解的终止事件，并保留部分轨迹及重试/编辑入口。
78. 备用模型只能在 Session 配置允许时启用；切换模型必须创建新 attempt 并记录完整 provenance。
79. 旧会话缺少完整事件时只兼容展示已有消息和 metadata，不伪造动作、CoT 或事件 sequence。
80. 运行质量指标至少覆盖首事件延迟、首 token 延迟、总耗时、SSE 恢复时间、事件重复/丢失、Worker 恢复、取消响应和持久化失败率。
81. 上线验收同时覆盖后端事件契约/恢复测试和前端运行卡片/编辑/断线/多设备交互测试。

## 抽题工具与 Skill 系统的 Harness 2.0 兼容边界

82. 现有题库搜索、加权抽题、岗位/题型过滤、去重、私有题库隔离和权威题目重载能力继续复用；它们通过 `QuestionBroker` 适配为 Harness 2.0 的 `retrieve_evidence` 能力，不直接成为新的持久化状态字段或新的队列系统。
83. `QuestionBroker` 的输入来自 `TurnPlan`、`PolicyGate` 和当前 `Ledger` 快照，输出为带题目标识、来源、选择理由、约束命中情况和权威数据摘要的类型化候选集或题目选择结果。题库工具不得直接把临时候选写成 Ledger 正式事实。
84. Harness 2.0 不向模型暴露自由调用的 `search_questions`、`draw_questions`、`select_question` 和 `load_skill` 路由。模型可以提出主题、题型或证据偏好，但是否检索、抽题和绑定下一题由后端 PolicyGate 裁决。
85. `select_question` 不再以模型提交的 `candidate_index` 作为最终事实来源；服务端根据候选集、Ledger 去重、覆盖约束和权威重载结果完成选择。题目在 TurnRun 中先作为临时选择，只有 `CommitTurn` 成功后才写入 Ledger。
86. 现有题目工具内部的 LLM rerank 不再作为隐藏的工具副作用；如果保留，必须成为可审计的 `retrieve_evidence` 子动作，并记录独立的模型调用 provenance、预算和结果摘要。
87. 现有 `SKILL.md` 内容、标准 Agent Skill 目录和渐进式资源加载方式继续复用；Skill 通过 `SkillResolver` 根据 Session、Ledger 和 TurnPlan 确定性选择，并作为带权限和版本信息的 `ContextPack` ContextBlock 注入模型调用。
88. 每个可注入 Skill 必须具备稳定的 `skill_key`、显式 `skill_version`、Harness 兼容声明和 `content_hash`。Skill 版本与 hash 必须进入 Context Manifest 和模型调用 provenance；不能继续用不存在的 `Skill.version` 回退为固定字符串 `1`。
89. Skill 可以提供面试风格、追问模式、评估关注点和表达约束，但不能直接修改 Ledger、推进面试阶段、授权工具、绕过 PolicyGate 或替代 Validate/CommitTurn。关键词触发和 `strategy_rules` 只作为 Resolver 的候选建议或上下文约束。
90. 现有 ReAct loop 保留为 Harness 1.0 兼容路径和 Harness 2.0 的受限证据子程序；2.0 中它只能读取 ContextPack、分析回答、请求受控证据并产生原生 reasoning segment，不能直接决定最终动作、写入 Ledger 或提交正式回复。
91. `interview-harness@2.0` 发布必须同时冻结 QuestionBroker、SkillResolver、Prompt/Skill manifest、事件协议和前端运行轨迹能力；新 Eval 默认绑定 2.0，旧会话继续按 1.0 或已有 provenance 展示，不伪造 2.0 事件、Skill 版本或题目事实。
92. QuestionBroker 选出题目后必须写入当前 `TurnRun.question_plan` 和临时 evidence，并由 `ContextAssembler` 生成下一次模型调用的 `QuestionSelectionContextBlock`；不得停留在 Broker 内部，也不得伪造模型从未发出的 tool call。
93. `QuestionSelectionContextBlock` 同时包含候选人可见的题目核心与受保护的来源、选择理由、权威校验和内部评估信息；Writer 可以自然改写题面，但不得替换题目主题、引入另一个题目或泄露受保护信息。
94. 题目绑定由服务端通过 `TurnRun.question_plan.question_id` 与 Validator 结果完成；Writer 不需要把题目 ID 输出到候选人可见话术。只有绑定检查通过且 `CommitTurn` 成功后，题目才进入 Ledger 的已问事实和 coverage event。
95. QuestionBroker 无结果时，PolicyGate 最多批准一次显式记录的 draw fallback；再次无结果则向 ContextPack 注入 `retrieval_miss`，Writer 走安全自然追问，不能隐式循环调用任意题库工具。
96. 每次 Broker 请求、候选结果、选题、fallback、ContextPack 重建和 Writer 继续调用都必须产生可恢复动作事件；它们属于同一个 TurnRun，不创建额外领域状态对象。
97. 正常追问固定为 `AnswerObserver/Propose` 加 `InterviewerWriter` 两阶段模型调用；ReAct 只参与第一阶段的受限证据探索，不能直接产生最终用户话术。
98. QuestionBroker 默认由后端确定性选出一张最终 QuestionCard，完整候选集只进入受保护审计轨迹；候选超过阈值或排序不稳定时，才允许一次显式且有独立 provenance 的 LLM rerank。
99. Writer 只接收最终 QuestionCard，不接收完整候选集；题卡必须提供 `canonical_text`、`allowed_focus`、`forbidden_focus` 和 `allow_natural_rewrite`，Writer 可改写表达但不得更换主题。
100. 题目绑定由服务端保存的 `TurnRun.question_plan.question_ref.id` 与 Validator 结果完成，Writer 不需要把题目 ID输出到候选人可见话术；Validator 必须检查题目核心覆盖、禁止主题和单题约束。
101. Writer 偏离题卡时最多执行一次窄范围 repair；repair 仍失败则当前 attempt 失败，不允许借机重新选题或无限调用 Broker。
102. 检索未命中时最多执行一次显式 `search -> draw` fallback；仍未命中则注入 `retrieval_miss`，Writer 生成安全的非题库追问，所有 fallback 都进入事件流。
103. Broker action 使用 `turn_run_id + action_id` 幂等；Worker 重试必须复用已持久化的候选/选题结果，不能因为随机抽题再次改变题目。
104. Writer 生成后、CommitTurn 前必须再次进行 authoritative question check；题目失效时当前 attempt 失败并重新执行 Broker，不静默替换题目。
105. 题目只有在 Writer、Validator 和 CommitTurn 全部成功后才写入 Ledger 的正式已问事实；检索、选中和 provisional assistant 输出均不推进 Ledger。
106. 模型供应商负责实际 Prompt/KV Cache 的存储、匹配和 TTL；Harness 不在 Redis 或数据库中维护第二套 Prompt Cache，也不把缓存命中作为业务正确性的前提。
107. 调用身份分为四类：`client_request_id` 用于 HTTP 重试幂等，`turn_run_id + action_id` 用于回合动作恢复与重试，`stable_prefix_hash` 用于本地稳定前缀审计，`provider_prompt_cache_key` 用于供应商缓存路由；四者不得混用。
108. LLM 请求固定为 `[Stable Agent Prefix] → [Turn Base] → [Call Suffix]`；同一 TurnRun 内 Turn Base 冻结，调用之间只改变最后的 Call Suffix，动态用户输入、题卡、Ledger 版本、时间戳和修复反馈不得出现在稳定缓存前缀之前。
109. `stable_prefix_hash` 至少由 Agent key、Harness 版本、provider、model、固定 Prompt、固定工具/Schema 和 Prompt Schema 版本规范化计算，不包含用户输入、TurnRun、Action、题目 ID、Ledger 版本或随机数；`provider_prompt_cache_key` 使用稳定 Agent/Harness/模型/前缀/隐私范围组合，不使用请求级随机标识。
110. Provider Adapter 按供应商能力映射缓存配置：支持显式断点的供应商在稳定前缀末尾设置断点，只支持自动缓存的供应商保持固定前缀，不支持缓存的供应商只记录稳定前缀指纹。每次调用记录 cached tokens、cache write tokens、命中/未命中和供应商 request id。
111. Prompt Cache 未命中只影响延迟和成本，不得改变 TurnRun、Ledger、SSE 恢复、ARQ 重试、题目选择或 CommitTurn 的业务结果。
112. Stable Agent Prefix 只包含通用面试规则、输出协议、隐私边界和固定 Schema，不包含用户信息、当前 Ledger、题目、Skill 正文或时间戳。
113. Turn Base 在 TurnRun 创建时冻结，包含本轮输入、Ledger 快照、历史摘要和初始 Skill 解析结果；同一 TurnRun 后续调用不得重新排序、裁剪或替换 Turn Base。
114. 支持显式断点的 Provider Adapter 在 Stable Agent Prefix 末尾设置缓存断点，Turn Base 和 Call Suffix 均位于断点之后。
115. 稳定前缀只含公共规则时 provider cache key 可使用全局范围；包含租户或私有岗位资料时使用租户范围，不默认使用 TurnRun ID 做缓存隔离。
116. 同一 TurnRun 的同一 attempt 固定 provider 和 model；模型 fallback 必须创建新 attempt，重新计算 stable prefix hash 和 provider cache key。
117. 第二阶段才确定的额外 Skill 只追加到 Call Suffix，不修改 Stable Agent Prefix 或已经冻结的 Turn Base。
118. Harness 2.0 不根据当前状态增删模型工具；QuestionBroker、SkillResolver 和 PolicyGate 在模型外执行，模型工具 Schema 保持固定。
119. 缓存观测至少记录 stable prefix 一致率、provider cache key 一致率、cached tokens、cache write tokens、命中/未命中和同一 TurnRun 内各阶段的前缀复用率；缓存命中不设为业务硬门槛。

120. **生产只保留一个 Interview Agent**：Harness 2.0 不拆分多个互相传递自然语言的生产 Agent，只维护一个 `interview-agent`，通过固定调用模式分别执行观察提案、回复生成、回复修复和输出校验。
121. **调用模式由 Harness 决定**：模型不能自行生成或切换下一个 `call_mode`；Harness 根据当前状态和上一步结构化结果选择调用模式。
122. **固定 Agent 主流程**：标准流程为 `observe_propose → policy_gate → retrieve_evidence（可选且有界）→ write_response → validate_output → commit_turn`。
123. **一次调用只做一个语义动作**：一次模型调用不得同时隐式推进多个业务阶段；需要继续时由 Harness 追加新的 action，并保留前一次调用的不可变结果。
124. **CoT 不作为事实源**：CoT、解释和中间草稿可用于用户展示、审计和调试，但不能直接改变 Ledger、Transcript 或阶段状态；只有结构化提案、PolicyGate 和 CommitTurn 具备业务写入资格。
125. **Agent 只读上下文**：Agent 通过 ContextPack 读取 Session、Ledger 和当前 TurnRun 的只读快照，不直接修改完整 Session；所有状态变更仍由 Harness/CommitTurn 执行。
126. **证据 ReAct 有界**：`retrieve_evidence` 仅用于题目结果注入后的受限补充，最多允许一次继续调用；SkillResolver 在模型外执行，Agent 只能读取激活的 Skill ContextBlock，不能自行加载 Skill 或改变阶段。
127. **临时输出与显式失败分离**：Writer 输出可在 Validator/CommitTurn 前作为临时内容流式展示，但只有两者成功后才成为正式 Transcript；失败、超时或预算耗尽时保留 Action、CoT 和临时轨迹，TurnRun 显式失败且不推进 Ledger、不静默改变主题或阶段。
128. **调用结果使用固定联合 Schema**：每种 `call_mode` 使用固定的结构化结果 Schema；响应外层至少包含 `schema_version`、`call_mode`、`turn_run_id`、`action_id`、`attempt`、`status` 和模式对应的 payload。模型不能通过自然语言返回下一模式。
129. **观察与提案合并为一次调用**：`observe_propose` 同时产出 observation、evidence gaps、intent、question strategy 和 risk flags；观察进入不可变轨迹，结构化 proposal 交给 PolicyGate，不拆成两个隐式模型调用。
130. **PolicyGate 纯代码执行**：PolicyGate 读取 Session 配置、Ledger 快照、Agent proposal、Broker 结果、预算和安全/阶段约束，固定输出 `allow`、`deny`、`repair`、`fallback` 或 `fail`，不再调用 LLM，也不能被模型绕过。
131. **QuestionBroker 按需触发**：仅在需要题库绑定、覆盖明确考察维度、必须换题或 PolicyGate 要求权威题卡时触发；普通自然追问不触发题库。
132. **Validator 代码优先、模型兜底**：先执行 Schema、单问题、题卡绑定、主题边界、敏感信息和预算检查；只有语义不确定时才允许一次窄范围 Validator 调用，Validator 只能返回问题，不能直接改写事实。
133. **非法 Schema 只允许一次修复**：Harness 保存原始响应和解析错误，最多执行一次 Schema repair；修复仍失败则 TurnRun 显式失败，不把自然语言降级为动作。
134. **重放与新尝试分离**：网络中断、Worker 崩溃或响应未确认时复用同一 `action_id` 幂等重放；模型已返回但结果非法、超时或质量不合格时创建新的 action/attempt，旧结果不可覆盖。
135. **预算按调用模式隔离**：TurnRun 总时长、单动作超时、证据继续次数、repair 次数、reasoning token 和 assistant token 分别受预算约束；预算耗尽必须产生明确事件并终止或降级。
136. **取消以提交事务为边界**：流式阶段立即停止读取，action 边界不再启动新 action；CommitTurn 进入数据库事务后不可取消，取消后的 provisional 输出不能成为正式 Transcript。
137. **Agent 不自行恢复**：重试、repair、重新 Broker、fallback 或失败终止全部由 Harness 固定状态机决定；Agent 只能返回当前调用结果，不能自行决定继续次数、切换阶段或更换题目。
138. **调用模式使用固定 payload**：每个 `call_mode` 只接受对应的固定 payload Schema；未知字段只能进入审计 Artifact，不参与业务决策。
139. **动作提案使用固定枚举**：Agent 提案只能使用预定义的 `ask_followup`、`move_topic`、`clarify_answer`、`retrieve_question`、`finish_interview` 等动作类型，不能新增动作类型或直接控制 `call_mode`。
140. **题卡结果服务端追加**：QuestionBroker 结果以不可变的 `QuestionSelectionContextBlock` 追加到同一 TurnRun 的 ContextPack 末端，包含题目、允许/禁止范围、来源、选择理由和权威校验，不伪造模型 Tool Call。
141. **Writer 不得修改计划**：Writer 只能生成候选人可见话术及有限表达 metadata，不能修改主题、深度、阶段、Ledger 或 QuestionCard；计划变化必须重新经过提案和 PolicyGate。
142. **决策链串行**：`observe_propose → PolicyGate → QuestionBroker（可选）→ write_response → validate_output → CommitTurn` 串行执行；日志、指标和 Artifact 压缩等非决策任务可以并行。
143. **Reasoning 与回答分通道**：`reasoning.delta` 与 `assistant.delta` 使用独立 channel 和 action_id，共享全局 sequence；前端可以并行渲染，服务端按 sequence 持久化。
144. **软失败与硬失败分离**：Validator 的 `soft_failure` 最多触发一次 repair，`hard_failure` 直接导致失败；Writer 不能通过文本隐式结束面试或切换阶段。
145. **TurnRun 终态有限化**：终态固定为 `completed`、`failed`、`cancelled`、`timed_out` 和 `budget_exhausted`，每个终态必须携带 `terminal_reason`，终态后不再追加业务动作。
146. **结束和阶段变化需要状态机授权**：结束面试或切换阶段必须同时经过结构化提案、PolicyGate 和 Harness 状态机，不能由 Writer 文本或 CoT 隐式触发。
147. **评测记录完整 provenance**：Eval 固定模型采样配置和供应商支持的随机种子；每次调用记录 Harness、模型、供应商、采样、Prompt/Schema/Skill hash、ContextPack hash 和 QuestionBroker 结果 hash，生产模式的随机性也不得隐藏。
148. **Schema 版本分层**：事件 envelope、各 `call_mode` payload 和 Harness 发布版本分别维护版本；兼容变化只能增加可选字段，破坏性变化必须升级对应版本。
149. **ContextPack 携带快照版本**：ContextPack 必须包含 `session_version`、`ledger_version`、`turn_run_version` 和 `context_pack_hash`；CommitTurn 使用乐观并发校验，过期快照不得强行提交。
150. **Evidence 来源分级**：Evidence 标注为 `candidate_input`、`broker_authoritative`、`skill_constraint`、`model_observation` 或 `provider_output`；模型 observation、confidence 和 CoT 不能直接成为 Ledger 事实。
151. **候选人事实必须经过提交链**：候选人回答中的事实必须经过结构化提案、PolicyGate、Validator 和 CommitTurn 后才能进入正式状态，原始回答、模型观察和 Ledger 事实分开保存。
152. **PolicyGate 冲突优先级固定**：安全与生命周期优先于事实和题目绑定，事实和题目绑定优先于覆盖与面试配置，覆盖与配置优先于自然度与表达风格。
153. **Provider 错误类型化恢复**：网络中断/Worker 崩溃复用同 action 重放，429/临时 5xx 有界重试，Schema 错误最多一次 repair，内容策略拒绝进入显式失败或允许的 fallback，上下文超限显式失败且不得静默裁剪 Turn Base。
154. **取消与提交条件竞争**：CommitTurn 与取消请求使用数据库条件更新；先成功者决定结果，两者不能同时成功，前端状态不得取代数据库终态。
155. **结束动作不新增 Agent 模式**：`finish_interview` 是结构化提案动作，继续使用既有 PolicyGate、Writer、Validator 和 CommitTurn；总结、评估和长期记忆在提交成功后异步执行。
156. **CoT 原始层与展示层分离**：`raw_reasoning_artifact` 只来自供应商原生 reasoning channel，用于审计；`user_visible_reasoning_projection` 可脱敏、分段或摘要，但不得伪造 reasoning。
157. **置信度只影响路由**：Agent confidence 只能决定正常继续、澄清或显式失败等 Harness 路由，不能直接改变 Ledger、绕过 PolicyGate 或成为正式事实。
158. **Session 配置按回合冻结**：岗位、语言、难度、面试模式和题目策略在 TurnRun 创建时冻结到 Turn Base；中途修改只影响下一个 TurnRun。
159. **长会话摘要是派生 Artifact**：摘要只在新 TurnRun 创建前生成，带版本和 hash，不是 Ledger 事实；当前 TurnRun 内不得压缩、重排或替换 Turn Base。
160. **候选回答先分类**：回答统一归类为 `no_answer`、`partial_answer`、`unclear_answer`、`off_topic` 或 `answered`；无回答和不清晰回答不能直接推进覆盖，偏题处理由 PolicyGate 决定。
161. **跳题必须经过 PolicyGate**：候选人要求跳题时 Agent 只能提出 `skip_question` 意图，是否跳过由 Session 配置、题目必要性、覆盖情况和预算决定。
162. **自然语言停止不等于 UI 取消**：UI 取消直接进入取消协作流程；候选人的暂停/停止话术先作为交互意图识别，再由 PolicyGate 决定暂停、结束或继续。
163. **编辑创建新回合**：编辑旧输入创建新的 UserMessage 和 TurnRun，并记录 `revision_of_turn_id`；旧回合的 `superseded` 仅为不可变关系/展示状态，不是新的执行终态，不能再次提交 Ledger。
164. **SSE 按回合隔离**：客户端和服务端按 `session_id`、`turn_run_id`、`sequence`、`event_id` 处理事件；旧回合晚到事件不能污染当前消息或新 TurnRun。
165. **无原生 reasoning 时不伪造**：Provider 不支持原生 reasoning channel 时只展示结构化动作进度，`raw_reasoning_artifact` 为空，不生成假 CoT。
166. **运行中版本失效创建新 attempt**：Skill 或题库版本失效时保留旧 attempt，创建新 attempt 并重新计算 Context/Skill hash，不能静默替换原 attempt 内容。
167. **评估异步且只读正式事实**：CommitTurn 成功后异步生成总结、能力评估、覆盖报告和反馈；评估结果不能反向修改已提交的 Transcript 或 Ledger。
168. **Agent 使用统一 response envelope**：所有调用统一包含 `schema_version`、`call_mode`、`turn_run_id`、`action_id`、`attempt`、`status`、`payload`、`usage` 和 `provenance`，payload 按调用模式使用固定 Schema。
169. **ObserveProposePayload 字段固定**：观察调用必须返回回答分类、观察、证据缺口、意图、结构化动作提案、题目策略、风险标记和 confidence；confidence 只能参与路由。
170. **PolicyGate 输出由后端控制**：PolicyGate 固定输出 decision、approved action、拒绝原因、约束、题目要求和后端决定的 next call mode；模型不能通过同名字段切换调用模式。
171. **Writer Payload 只表达话术**：Writer 只能返回候选人可见文本、语言、语气、问题数量和题目引用，不能返回计划、Ledger 更新、阶段切换或工具指令。
172. **Validator 问题码固定**：Validator 问题使用 `code`、`severity`、`message`、`field` 和 `repairable` 字段；前端可将错误码映射为友好文案，Harness 按错误码决定 repair 或失败。
173. **Provider 响应统一归一化**：Provider Adapter 将供应商响应统一为 reasoning segment、assistant text、structured output、finish reason 和 provider metadata，Harness 不直接依赖供应商特有字段。
174. **Action 保存统一时序和预算**：每个 action 保存开始、首 token、完成、超时、Token 用量、重试次数和预算快照，前端、指标和 Eval 使用同一事实。
175. **ContextPack hash 必须确定性**：固定字段/数组顺序、空值规则、Unicode 规范化以及时间/随机字段排除规则；相同输入必须产生相同 ContextPack hash。
176. **响应按三层保存**：保存 `raw_provider_response`、`normalized_agent_result` 和 `user_visible_projection` 三层数据，审计、Harness 和 SSE 分别使用对应层，层之间不得互相覆盖。
177. **Eval 支持 recorded replay**：`recorded_replay` 直接读取已保存的 Provider 响应和工具结果，不重新调用模型，用于验证 Harness、PolicyGate、Validator、CommitTurn 和 SSE 的确定性。
178. **原始 Provider 响应加密**：`raw_provider_response` 加密保存，仅拥有者和审计权限可读；普通聊天接口只返回用户可见投影。
179. **轨迹统一保留删除**：CoT、Prompt、候选人回答、工具结果和评估结果与面试记录绑定同一保留/删除策略，删除时不得留下孤立 Agent 轨迹。
180. **SSE 前置脱敏**：原始层保留严格权限，进入 SSE 前生成脱敏投影；密钥、Token、Cookie、内部 URL、供应商凭证和敏感候选人数据不得进入用户投影。
181. **Prompt provenance 分层保存**：默认保存 Prompt/Context 的 hash 和版本，完整 Prompt Artifact 仅在调试/审计权限下单独保存，不混入普通 Agent 结果。
182. **SSE delta 可去重**：每个 delta 携带 `event_id`、`turn_run_id`、`action_id`、`channel`、`sequence` 和 `delta_index`；客户端按稳定标识去重，不能重复拼接文本。
183. **事件表 sequence 权威**：乱序或缺失 SSE 事件由前端暂存并通过重连补齐，事件表 sequence 是唯一持久化顺序，不以到达时间重排。
184. **无结构化结果视为 Schema failure**：Provider 只返回普通文本而无结构化结果时最多一次 repair，不能从普通文本猜测动作、题目或 Ledger 更新。
185. **Replay 先校验环境 hash**：Recorded replay 必须校验 Harness、Prompt/Schema、Skill、ContextPack、Provider/model 和采样配置 hash；关键 hash 不匹配时标记为不可比对。
186. **人工接管必须审计**：人工只能执行 retry、cancel、mark_failed、approve_provisional 或 create_revision 等显式动作，并记录操作者、原因和时间，不能修改原始轨迹或伪造模型输出。
187. **Harness 灰度与 kill switch**：按租户、Session、Provider/model 和 Harness 版本提供启停与灰度；关闭新 Harness 只影响新 TurnRun，不修改旧会话、历史事件或 provenance。
188. **候选人输入是不可信区块**：候选人内容只进入 `candidate_input` ContextBlock，不能进入 System Prompt，也不能被当作 Harness 指令、Skill、Policy 或工具授权。
189. **上下文来源有固定优先级**：Harness/System 规则 > Session 配置 > PolicyGate 约束 > Skill 约束 > QuestionCard > 候选人输入 > 模型解释；低优先级文本不得覆盖高优先级规则。
190. **外部内容只能提供证据**：QuestionCard、岗位描述、Skill、外部资料和 Provider 工具结果都必须带来源标记；它们不能改变 Harness、PolicyGate、Ledger、权限或阶段。
191. **工具结果不是指令**：Provider 工具结果只作为带来源和 hash 的 evidence，必须经过 Schema 校验与 PolicyGate，工具结果中的自然语言不能改变流程。
192. **模型不具备资源加载权**：模型不能自行拼接 Prompt、加载 Skill、访问外部资源或执行工具；资源由服务端解析并以受控 ContextBlock 注入。
193. **Evidence 规模有界**：每个 evidence block 限制字节数、嵌套深度、条目数、引用数和注入次数；超限必须显式失败，不得静默无限扩展 ContextPack。
194. **租户私有上下文隔离**：私有 Skill、题库、岗位资料和 Prompt 不得进入全局 Prompt Cache、其他租户 ContextPack 或共享 hash 命名空间，cache scope 必须匹配隐私范围。
195. **Prompt Injection 进入 Eval**：评测覆盖候选人、题库、Skill、工具结果、岗位描述、跨 TurnRun 和跨租户注入场景。
196. **Injection 评测检查执行边界**：安全评测不仅检查话术，还必须检查越权工具调用、Ledger 污染、阶段切换、Prompt 泄露和跨租户访问。
197. **注入内容不能授予权限**：任何“忽略规则”“调用工具”“跳过验证”或“读取其他租户数据”的文本都只能作为普通 evidence，不能改变 Harness 或权限边界。
198. **Eval 分为硬门槛和软评分**：硬门槛覆盖越权工具调用、Prompt 泄露、Ledger 污染、非法阶段切换、错误题目绑定和未校验正式回复；软评分覆盖自然度、相关性、覆盖、难度适配、连续性和体验，硬门槛失败即判定回合失败。
199. **质量指标定义随版本冻结**：固定记录题目绑定、Ledger 正确性、Policy 合规、重复题、覆盖进展、repair、硬失败、首 token、回合完成和 SSE 恢复指标，指标定义随 Harness 版本管理。
200. **Golden Trace 覆盖关键边界**：固定覆盖正常、不完整、偏题、拒答、跳题、结束、多语言、检索未命中、Provider 超时、Schema 错误、Prompt Injection、编辑重发和 SSE 恢复。
201. **Judge 与生产 Agent 分离**：Judge 只读取正式 Transcript、Ledger 和事件轨迹，输出评分和理由，不能修改生产事实或运行状态。
202. **Judge 评价 CoT 但不以 CoT 为准**：Judge 可以评价 reasoning 轨迹，但结构化 Action、PolicyGate、Validator、CommitTurn 和正式 Transcript 优先于 CoT。
203. **失败样本保存最小复现包**：失败样本至少保存 Session、TurnRun、Ledger、ContextPack、Provider 响应、Action、PolicyGate、Validator、SSE 序列及版本 hash，供 recorded replay 使用。
204. **关键运行环境变化必须重跑 Eval**：Harness、Prompt、Skill、Provider、model、sampling config 或 reasoning 能力任一变化，都必须重新运行关键 Golden Trace。
205. **Shadow Eval 不写正式事实**：线上 Shadow Eval 可以异步比较候选实现，但不能写入正式 Ledger、Transcript 或用户 SSE。
206. **发布门槛覆盖五个维度**：功能、安全、一致性、体验和质量必须同时达标；核心指标回归时禁止扩大灰度。
207. **回归阈值必须可执行**：核心硬门槛必须为零违规或低于明确安全阈值，软指标相对基线恶化超过版本配置阈值时自动阻止发布。
208. **Action 状态固定**：Action 只允许 `pending`、`started`、`streaming`、`waiting`、`completed`、`failed`、`cancel_requested` 和 `cancelled`。
209. **Attempt 状态固定**：Attempt 只允许 `active`、`succeeded`、`failed` 和 `superseded`，失败尝试不可覆盖。
210. **Action 与 Attempt 分离**：Action 表示语义动作，Attempt 表示执行尝试；两者分别使用 `(turn_run_id, action_id)` 与 `(action_id, attempt_no)` 标识。
211. **Action 唯一键由数据库保证**：Action 使用 `(turn_run_id, action_id)` 唯一约束，Attempt 使用 `(action_id, attempt_no)` 唯一约束。
212. **Response envelope 字段固定**：统一包含 `schema_version`、`call_mode`、`turn_run_id`、`action_id`、`attempt`、`status`、`payload`、`usage`、`provenance` 和 `errors`。
213. **ContextPack Builder 纯函数化**：ContextPack 由 Stable Prefix、Frozen Turn Base 和 Call Suffix 的纯函数构造，不在 Builder 中隐式读取数据库或调用模型。
214. **ContextBlock 元数据固定**：每个 ContextBlock 携带 `block_id`、`block_type`、`source`、`content_hash`、`visibility` 和 `sequence`。
215. **无动作使用显式状态**：没有下一步动作时返回 `no_op` 或 `await_user_input`，不能使用空 payload 或空文本表达。
216. **预算快照版本化**：预算来自版本化 Harness Config，并在 TurnRun 创建时冻结，不能由 Agent 节点自行修改。
217. **CommitTurn 输入最小化**：CommitTurn 只接收已校验回复、题目绑定、Ledger patch、Transcript patch、TurnRun ID 和 Ledger version。
218. **SSE envelope 固定**：事件统一包含 event、Session、TurnRun、sequence、type、channel、Action、phase、时间、Schema 和 payload 字段。
219. **事件类型注册化**：业务事件必须来自固定注册表，客户端对未知事件降级或忽略，不猜测未知语义。
220. **事件与 Outbox 同事务**：运行状态、业务事件和 Outbox 在同一数据库事务中写入，Outbox Publisher 提交后再推送 SSE。
221. **SSE 重连双游标**：支持 `Last-Event-ID` 和 `after_sequence`，冲突时从服务端计算的最小未确认 sequence 补发。
222. **历史事件独立回放**：提供按 TurnRun 和 sequence 查询历史事件的接口，SSE 只负责实时推送和连接恢复。
223. **Heartbeat 不入业务事件表**：Heartbeat 只用于连接保活，不占用业务 sequence。
224. **SSE 不拥有任务生命周期**：连接断开不取消 Worker，SSE 只是观察通道，重连从事件 sequence 恢复。
225. **多设备只读订阅**：允许多个授权订阅者消费同一事件序列，但同一 Session 同时只有一个有效 Worker。
226. **SSE 背压有界**：Reasoning/Assistant delta 可批量合并，业务事件不可丢失；慢客户端断开后通过 sequence 补偿，不无限缓存内存。
227. **取消接口只写请求**：取消 API 只写入 `cancel_requested`，Worker 在流式读取、Action 边界和 CommitTurn 前检查，不由接口直接杀 Worker。
228. **TurnRun 是顶层运行卡片**：前端一个 TurnRun 对应一个顶层运行卡片，内部包含 Action、Reasoning、Evidence 和 Output。
229. **运行卡片双层折叠**：顶层 TurnRun 卡片嵌套 Action 卡片，Action 内再展示 Reasoning、Evidence 和 Output。
230. **当前 Action 自动展开**：新 Action 开始时自动展开，前一 Action 自动折叠；用户手动展开状态优先于自动行为。
231. **CoT 展示高度有界**：CoT 使用固定最大高度和内部滚动，不能无限撑高消息列表。
232. **Reasoning/Assistant 并行投影**：两个通道可并行展示，但必须有明显视觉区分，Reasoning 不能被视为正式回复。
233. **Provisional 输出显式标记**：Validator/CommitTurn 前的文本显示待校验状态，失败时标记未提交，成功后才转为正式消息。
234. **停止 UI 状态固定**：停止按钮依次显示停止生成、正在停止、已停止/已完成，提交停止请求后不能重复发送。
235. **编辑展示为新版本**：编辑后的输入作为新消息分支展示，旧输入标记已修订，旧 TurnRun 可查看但不能继续执行。
236. **断线状态可见**：前端显示重连中、已恢复、后台仍运行和需要手动重连等状态，不因断线自动创建新回合。
237. **失败状态提供明确动作**：前端区分可重试、可编辑重发、已取消、已超时、预算耗尽和系统失败，并提供对应入口。
238. **API 按生命周期分离**：创建、查询、事件、取消和修订使用独立 API；创建不等待模型完成，订阅不触发重复执行。
239. **事件和 Artifact 只追加**：事件表、Action、Attempt 和 Artifact 保持追加式写入，不原地覆盖历史轨迹。
240. **关键唯一约束落数据库**：数据库保证 TurnRun sequence、Action、Attempt 和 client request 的唯一性，不能只依赖应用代码。
241. **ARQ 职责保持单一**：ARQ 只负责触发和重试 Worker，数据库负责权威状态、事件和 Action，Redis 不承担第二套业务队列事实。
242. **Worker 从安全边界恢复**：已完成 Action 跳过，未确认 Action 重放，失败 Action 创建新 Attempt，已提交 CommitTurn 不得重复提交。
243. **端到端故障矩阵固定**：测试覆盖正常完成、Provider/Worker/ARQ 故障、SSE 断线乱序、取消竞态、编辑、多设备、题库/Skill 失效和 Prompt Injection。
244. **测试分层执行**：必须覆盖单元、状态机、数据库事务、Provider Adapter、Worker/ARQ、SSE、前端 reducer、浏览器 E2E 和 Recorded Replay Eval。
245. **旧会话保持 1.0 provenance**：旧 Harness 会话按已有版本展示，不补造 2.0 Action、CoT 或 sequence；新 TurnRun 才使用 2.0。
246. **发布验收清单固定**：发布前检查 Agent 状态、Context hash、Prompt Cache、SSE、取消/编辑、安全、Replay、性能成本和前端交互。
247. **设计确认后冻结**：上述合同确认后进入数据模型、API、Harness、SSE、前端、Eval 和灰度实现，不再继续扩展架构方向。

## 后果

运行轨迹会增加存储量、事件版本兼容、敏感信息保护和保留策略的要求；但它提供了可审计、可恢复且不依赖最终消息重建的用户体验。后续实现必须继续确定事件粒度、CoT 分片策略、压缩/归档规则以及运行中恢复时的服务端状态检查。
