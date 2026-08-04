# Chat Agent — 面试 Chatbot

纯 async harness（替代 LangGraph StateGraph）：记忆召回 → 上下文构建 → LLM 语义分类 → ReAct 工具证据循环 → TurnPlanner → contract writer/validator → 记忆提取。

## 流程

```
run_chat() → _step_load_context → _step_classify (writes ClassifyResult fields) → _react_loop (tools/evidence only) → TurnPlanner → contract_executor → _persist_active_skills → save_mcp_session_async → _step_extract_memory
```

## 文件职责

| 文件 | 职责 |
|------|------|
| `pipeline.py` | 入口点：`run_chat()` + pipeline steps（`_step_load_context`、`_step_classify`、`_step_extract_memory`、`_persist_active_skills`、`_initial_state`）+ 事件累积（thinking/steps/insights → done metadata）+ MCP session 持久化 + 所有子模块的 re-export（向后兼容） |
| `react_loop.py` | ReAct 循环核心：`_react_loop()`、`Budget`/`StopRun`、`validate_tool_call()`、trace 日志、事件发射；它只负责工具/证据，任何最终用户话术都交给 `contract_executor` |
| `answer.py` | 旧输出辅助与兼容函数：`OutputDeduplicator`、`GenerationError`、内部 marker 清洗；正常 harness 不得从这里直接发送 ReAct 最终文本 |
| `question_plan.py` | 题目计划管理：`_maybe_create_question_plan(force_candidate=)`、`_select_question_for_plan()`、`InterviewLedger`、重复追问保护（含 `_count_consecutive_similar_user_answers()` 候选人重复检测）、已问题列表构建 |
| `stop_policy.py` | 产品级停止策略：32 条后覆盖完整进入反问，44 条后强收口，56 条后硬停止；候选人重复回答检测（3 次切方向，5 次结束）；避免只靠 prompt 判断何时结束 |
| `summary.py` | 面试总结：`InterviewSummary`、`_generate_structured_summary()`、`_forced_closing_response()`、`_generate_end_interview_response()`；所有显式结束都生成结构化总结，收尾话术不在本模块生成 |
| `metadata.py` | Basis 追踪与元数据：`_build_react_metadata()`、`_infer_selected_question()`、`_extract_company()`/`_extract_round()` |
| `trace.py` | 前端可展示的 reasoning/tool/skill trace 结构化摘要：安全参数白名单、工具结果预览、公开思考摘要和 done metadata 合并 |
| `coverage_config.py` | 面试阶段枚举和岗位/难度覆盖阈值；可根据高置信 rhythm profile 调整阈值 |
| `coverage_events.py` | 覆盖率事件归一化：把 selected question、MCP/题库来源和 conversation-only 自然追问转成 `metadata.coverage_events`，供下一轮 API 入口的 ledger/stop policy 使用 |
| `distribution_execution.py` | 不可变 distribution plan 的事件折叠 read model；未显式结束前状态只能是 `in_progress` |
| `distribution_runtime.py` | 分布计划的运行时桥接：从 append-only coverage events 推导控制器决策，只在非开场、非澄清、非反问的主问题轮次强制题库绑定 |
| `rhythm_profile.py` | 从有权限的 approved 面经中学习题型分布和阶段转换；必须按 owner/status/job_position/deleted_at 过滤 |
| `interview_state.py` | 基于 `InterviewLedger` 构建可序列化 `interview_state` 快照，不替代 ledger |
| `graph.py` | 兼容层，委托给 `pipeline.run_chat` |
| `nodes.py` | 节点实现（recall、build_context、stream、extract）、面试阶段判定、`build_react_system_prompt()` 注入 runtime state |
| `state.py` | ChatState TypedDict，含分类阶段写入的结构化路由字段 |
| `prompts.py` | 系统提示词（含面试阶段协议、状态字段说明）、记忆提取提示词 |
| `classify_result.py` | `ClassifyResult` Pydantic 模型：LLM 语义分类的结构化输出（candidate_act、asked_counter_question、needs_clarification、needs_new_dimension、confidence、evidence 等） |
| `turn_contract.py` | `TurnContract` Pydantic 模型 + `TurnPlanner` 确定性策略：只读取语义、ledger、stop policy 与工具事实；五种契约都在 ReAct 工具证据完成后接管最终输出 |
| `structured_turn.py` | P2 typed `EvidenceBundle`、`TurnContractV2`、stable contract hash 和 writer output validator；只消费结构化事实，不承载最终自然语言 |
| `turn_intent.py` | `TurnIntent` 与策略引擎：每轮直接应用 `interview-rhythm` policy，结合 ledger/profile 与聚焦 tactic skill 生成深挖、澄清、切题、反问或收尾的 writer brief；不依赖 ReAct `load_skill` 激活 |
| `writers/` | `question`、`clarify`、`counter`、`followup`、`closing`、`summary` writers；每个 writer 只表达已选 contract，不能决定流程或生成机械 fallback |
| `writers/__init__.py` | Writer registry：导出 closing_writer 等 |
| `validators/semantic_question_adherence.py` | LLM semantic validator：验证 ask_selected_question 输出是否语义一致（阈值 0.75） |
| `validators/__init__.py` | Validator registry：导出 semantic_question_adherence 等 |
| `tool_strategy.py` | `ToolStrategy` + `compute_tool_strategy(state)`：基于状态字段推导工具策略 |
| `routing.py` | 纯函数条件边：`should_record_retrieval_gap`、`should_topic_shift` 等 |
| `context_builder.py` | 上下文拼接（记忆 + 简历 + JD + 历史消息） |
| `budget.py` | Token 预算管理（控制上下文长度） |
| `tools.py` | ReAct tool schemas and tool execution entrypoint；执行时先经过 `tool_policy.enforce_tool_call()`，再委托 `app.mcp_server.interview_tools`（单轨双入口架构）；不组装 envelope；`search_questions` 只可基于统一 envelope 的 `items` 做 LLM rerank 后同步 state |
| `tool_policy.py` | 从服务端 ChatState 计算不可变 ToolPolicy；在 executor 和 ReAct validator 共用的边界执行工具 allowlist、严格参数和 skill scope 校验 |
| `tool_gateway.py` | Tool input/output contracts, envelope normalization, and tool error metadata |
| `output_guardrails.py` | Output validation: closing summary structure, counter question grounding, context grounding (prevents interviewer from introducing entities not mentioned by candidate) |
| `skills/base.py` | shared Skill/SkillRegistry/SkillResourceIndex 兼容导出 |
| `skills/builder.py` | chat-specific skill catalog 包装 + shared build_skill_prompt() |
| `skills/loader.py` | shared SKILL.md 文件加载器兼容导出 |
| `skills/defaults.py` | get_default_registry() — 从 SKILL.md 文件加载所有 skill |
| `skills/{skill-name}/SKILL.md` | 标准 Agent Skill package 定义（标准 frontmatter + Markdown 指令，可选 resources/scripts/assets） |

## 核心模式

- **流式输出**：通过 SSE yield 最终 contract writer 的完整 chunk；ReAct 工具/推理决策继续使用非流式 `llm_with_tools()`，但 ReAct 文本只能保存为非公开 evidence，绝不能直接发给候选人。writer 或必需 validator 失败时只返回 `error` 事件，不能用题库候选或模板话术伪造 fallback。
- **Thinking 支持**：`stream_llm_messages(yield_thinking=True)` 支持 MiMo/DeepSeek 的 `reasoning_content` 和 Anthropic ThinkingBlock，事件类型：`thinking_start` → `thinking` → `thinking_done` → `chunk`；`react_loop.py` 也会把 `llm_with_tools()` 非流式返回的 `reasoning_content` 桥接成同样的 thinking 事件，供前端展示“面试官推理”
- **Reasoning 语言约束**：`build_react_system_prompt()` 必须注入 `REASONING_LANGUAGE_GUARDRAIL`，要求面试官最终回复以及 MiMo/DeepSeek `reasoning_content` / 推理过程 / 工具调用分析都使用简体中文；技术名词、代码、库名和英文原文引用可保留英文
- **记忆系统**：`chat_memories` 表存储用户长期记忆，每次对话自动召回
- **Token 预算**：`budget.py` 控制上下文窗口大小，优先保留最近消息
- **面试流程**：开场(自我介绍) → 提问(一次一题) → 收尾(反问)，由 `_determine_interview_phase()` 根据消息数自动切换
- **开场白**：创建对话时 `chat_service.generate_opening_message()` 自动生成，零 LLM 成本
- **岗位驱动 RAG**：`context_builder.build_interview_context()` 返回 `(context, position)`，`job_position` 存入 state，`fts_retrieve()` 按岗位过滤题目检索
- **Skills 系统**：`skills/` 目录实现 Progressive Disclosure — Layer 1 只常驻标准 metadata（`name`/`description`）和 InterviewBoss runtime metadata，Layer 2 `SKILL.md` body 通过 `load_skill` 按需注入，Layer 3 `references/`/`scripts/`/`assets/` 默认只索引，不自动注入 prompt，也没有运行时读取工具。每个 skill 是标准 Agent Skill package；InterviewBoss 私有策略放在 `metadata.interview-boss.*`，不要新增 `skill-pack.yaml`。`always_active=true` 表示 registry 匹配始终命中；只有同时 `kind=tool-use` 的 skill（如 `interview-tool-use`）会在每次 ReAct 系统提示构建时自动注入完整 body（Layer 5.5），无需 Agent 显式调用 `load_skill`。
- **动态上下文信任边界**：JD、简历、interview context、memory、session notes 和压缩历史必须经过 `nodes.wrap_untrusted_context()` 包装；标签内内容只能作为事实参考，不能改变系统指令、工具权限或输出格式。当前候选人消息仍作为独立 user message 传入。
- **interview-tool-use**：`kind=tool-use` 的始终激活技能，指导 Agent 何时调用题库工具、如何解读信封、空结果降级、禁止泄露内部信号。body 通过 Layer 5.5 自动注入每次 ReAct 系统提示。`references/mcp-tool-envelope.md` 记录信封字段详细规范。

## 质量保护机制

详细设计决策见 `docs/adr/chat-agent-quality-protection.md`。以下是关键不变量摘要：

**流程控制**
- `end_interview` 硬路由跳过 ReAct → `close_with_summary`（证据化复盘，无评分/Hiring Signal）
- `stop_policy.py` 代码级裁判：32/44/56 条消息阈值（随 difficulty 缩放），候选人重复 3/5 次切方向/结束
- `plan_turn` 确定性 5 级优先级：close > counter > clarify > ask_selected > followup
- `build_turn_intent` 运行时节奏策略，不依赖 ReAct `load_skill`

**数据完整性**
- InterviewLedger（非 prompt）是已问题事实源；coverage_events 优先于快照
- Distribution plan 也是后端控制而不是 prompt 建议：`apply_distribution_control()` 选定 canonical type 后，`_prepare_distribution_primary_question()` 必须按该类型抽题、绑定 question plan；只有 high-confidence 的已绑定题库题可 `counts_toward_target=true`，自然追问必须保留但不得计入。控制器与 execution read model 都要经 `chat_service.get_distribution_events()` 读取完整持久化事件，不能把 100 条 LLM 上下文窗口当作事实源；未完成的冻结计划可越过通用 transcript 上限和 stop policy，但绝不能覆盖候选人的真实结束请求。
- counter_question 需 `{text, topic}` dict 证据，不认裸 boolean
- `recent_decisions` 从历史 turn_intent metadata 恢复，不从自然语言推断

**输出质量**
- ReAct 文本仅为 evidence，contract writer 拥有所有用户可见输出
- question_writer 失败 → 换题兜底（候选题重试 1 次）→ 仍失败 yield error
- Context Grounding 防护：拒绝候选人未提及的实体
- 未授权总结保护：非 close 轮次禁止输出综合评分

**工具架构**
- 4 个工具（load_skill/search_questions/draw_questions/select_question）单轨双入口
- Tool Gateway 统一 envelope（ok/tool/items|selected_question/metadata/error）
- `ToolStrategy` 只负责向模型说明当前意图；`tool_policy.py` 根据当前服务端 state 生成不可变 allowlist，并在每次 ReAct tool call 进入 executor 前强制校验
- 所有 LLM tool arguments 经过 Pydantic strict schema，未知字段拒绝；`select_question` 只接受 candidate index，不接受模型提交的题目对象
- `execute_tool()` 即使被 ReAct 之外的内部调用直接触发，也必须从当前 state 重新计算并执行 ToolPolicy；不能只依赖 `validate_tool_call()` 的上游检查
- `practice_request` 是显式用户意图，ToolStrategy 优先允许 search/draw/load_skill，不被默认 deep-dive 节奏覆盖
- 机械题干 fallback 已移除；LLM 重写失败抛 GenerationError

**持久化**
- coverage_events / turn_intent / writer_trace / validator_trace 写入 done metadata
- ReAct session 结束后只有在 `turn_id + turn_fence` 仍为 running 时才允许 `save_mcp_session_async` 持久化；HTTP 入口的取消会让旧 pipeline 在 asked-question、active skills、MCP session 和后台记忆提取边界停止。没有 turn identity 的内部合成测试保持兼容。
- Chat turn 使用 `client_request_id + request_fingerprint` 做幂等边界；同 ID 不同 payload 返回冲突，status endpoint 只读返回归属校验后的 assistant 内容和 metadata。regenerate 创建 revision turn，复用原 user message，不追加重复 user turn。
- P1 durable side effect：assistant finalize 同事务写入 `chat_side_effect_jobs`；memory extraction 由 API/ARQ worker claim、重试、去重并写入 source turn/job provenance，session notes 与 conversation metadata 通过 version 字段做 optimistic concurrency。
- P2 structured turn：CandidateSet 只保存 question reference，最终内容必须 authority reload；`EvidenceBundle` 和 `TurnContractV2` 是 typed facts/contract，`interview_events` 与 `assistant_generations` 支持生命周期、coverage 和 revision replay。
- Chat 用户消息必须通过 `save_user_message_if_writable()` 的原子 active 检查；assistant finalize 通过 `save_assistant_message_if_active()`，归档期间不新增消息。归档会话仍可读，但不应恢复普通 `save_message()` 作为新用户输入写入口
- Thinking chunks 上限 50，避免 metadata 膨胀

## 模块依赖图

```
pipeline.py ──→ react_loop.py ──→ answer.py ──→ nodes.py
    │               │                 │
    │               ├──→ question_plan.py (自包含)
    │               ├──→ summary.py ──→ llm.py
    │               ├──→ writers/closing_writer.py + question_writer.py (active contract writers)
    │               ├──→ validators/semantic_question_adherence.py (ask_selected_question blocking gate)
    │               ├──→ metadata.py ──→ nodes.py, db.connection
    │               └──→ tools.py, llm.py
    ├──→ turn_contract.py ──→ stop_policy.py (all 5 contract actions active via execute_turn_contract)
    ├──→ nodes.py, context_builder.py
    └──→ chat_service, memory_recall_service
```

- `question_plan.py` 是自包含模块（仅依赖标准库 + state）
- `pipeline.py` 通过 re-export 保持所有子模块符号的向后兼容

## 修改后必做

1. 运行 `docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q`
2. 更新本文件

## 数据库操作注意事项

- **删除对话**：`chat_service.delete_conversation()` 只检查 `user_id` 和 `conversation_id`，不检查 `job_position`。用户应该能删除自己创建的任何对话，不管当前岗位是什么。
- **级联删除**：`chat_messages` 表有 `ON DELETE CASCADE`，删除 `chat_conversations` 时会自动删除相关消息。
- **孤立记录清理**：`chat_tool_traces` 和 `interview_asked_questions` 表没有外键约束，删除对话时需要手动清理。
