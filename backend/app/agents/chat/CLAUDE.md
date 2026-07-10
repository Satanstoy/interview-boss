# Chat Agent — 面试 Chatbot

纯 async pipeline（替代 LangGraph StateGraph）：记忆召回 → 上下文构建 → 意图分类 → ReAct 循环 → 记忆提取。

## 流程

```
run_chat() → _step_load_context → _step_classify (writes ClassifyResult fields) → _react_loop (reads state) → _persist_active_skills → save_mcp_session_async → _step_extract_memory
```

## 文件职责

| 文件 | 职责 |
|------|------|
| `pipeline.py` | 入口点：`run_chat()` + pipeline steps（`_step_load_context`、`_step_classify`、`_step_extract_memory`、`_persist_active_skills`、`_initial_state`）+ 事件累积（thinking/steps/insights → done metadata）+ MCP session 持久化 + 所有子模块的 re-export（向后兼容） |
| `react_loop.py` | ReAct 循环核心：`_react_loop()`、`Budget`/`StopRun`、`validate_tool_call()`、trace 日志、事件发射；空回答 + 计划题场景 yield error 事件而非机械 fallback |
| `answer.py` | 答案生成与质量：`OutputDeduplicator`、`GenerationError`（替代机械题干 fallback）、`_stream_final_answer()`、`_enforce_question_plan_on_text()`、`_rewrite_transition_with_llm()`（LLM 自然过渡重写）、fallback 响应、内部 marker 过滤 |
| `question_plan.py` | 题目计划管理：`_maybe_create_question_plan(force_candidate=)`、`_select_question_for_plan()`、`InterviewLedger`、重复追问保护（含 `_count_consecutive_similar_user_answers()` 候选人重复检测）、已问题列表构建 |
| `stop_policy.py` | 产品级停止策略：32 条后覆盖完整进入反问，44 条后强收口，56 条后硬停止；候选人重复回答检测（3 次切方向，5 次结束）；避免只靠 prompt 判断何时结束 |
| `turn_controller.py` | 显式路由决策：`decide_turn_action(state)` 根据 closing_stage、counter_question、收尾信号、requires_bank_question 等状态字段决定 turn_action（closing_summary/bank_question/answer_counter_question/natural_followup）和 question_intent，解决 E2E 中的 proper_end、long_session_senior、early_close_guard 问题 |
| `summary.py` | 面试总结：`InterviewSummary`、`_generate_structured_summary()`、`_forced_closing_response()`、`_generate_end_interview_response()` |
| `metadata.py` | Basis 追踪与元数据：`_build_react_metadata()`、`_infer_selected_question()`、`_extract_company()`/`_extract_round()` |
| `trace.py` | 前端可展示的 reasoning/tool/skill trace 结构化摘要：安全参数白名单、工具结果预览、公开思考摘要和 done metadata 合并 |
| `coverage_config.py` | 面试阶段枚举和岗位/难度覆盖阈值；可根据高置信 rhythm profile 调整阈值 |
| `coverage_events.py` | 覆盖率事件归一化：把 selected question、MCP/题库来源和 conversation-only 自然追问转成 `metadata.coverage_events`，供下一轮 API 入口的 ledger/stop policy 使用 |
| `rhythm_profile.py` | 从有权限的 approved 面经中学习题型分布和阶段转换；必须按 owner/status/job_position/deleted_at 过滤 |
| `interview_state.py` | 基于 `InterviewLedger` 构建可序列化 `interview_state` 快照，不替代 ledger |
| `graph.py` | 兼容层，委托给 `pipeline.run_chat` |
| `nodes.py` | 节点实现（recall、build_context、stream、extract）、面试阶段判定、`build_react_system_prompt()` 注入 runtime state |
| `state.py` | ChatState TypedDict，含分类阶段写入的结构化路由字段 |
| `prompts.py` | 系统提示词（含面试阶段协议、状态字段说明）、记忆提取提示词 |
| `classify_result.py` | `ClassifyResult` Pydantic 模型：分类节点结构化输出（含 Phase 1 语义信号扩展：candidate_act、asked_counter_question、needs_clarification、needs_new_dimension、confidence、evidence 等） |
| `turn_contract.py` | `TurnContract` Pydantic 模型 + `TurnPlanner` 确定性策略：读取结构化事实输出本轮契约（Phase 1 旁路观测，不影响现有输出） |
| `writers/closing_writer.py` | 自然收尾语生成：不含结构化总结，由 closing_writer 生成，summary_writer 生成总结（Phase 2 两阶段收尾） |
| `writers/__init__.py` | Writer registry：导出 closing_writer 等 |
| `tool_strategy.py` | `ToolStrategy` + `compute_tool_strategy(state)`：基于状态字段推导工具策略 |
| `routing.py` | 纯函数条件边：`should_record_retrieval_gap`、`should_topic_shift` 等 |
| `context_builder.py` | 上下文拼接（记忆 + 简历 + JD + 历史消息） |
| `budget.py` | Token 预算管理（控制上下文长度） |
| `tools.py` | ReAct tool schemas and tool execution entrypoint；执行时委托 `app.services.interview_tools`；不组装 envelope；`search_questions` 只可基于统一 envelope 的 `items` 做 LLM rerank 后同步 state |
| `tool_gateway.py` | Tool input/output contracts, envelope normalization, and tool error metadata |
| `output_guardrails.py` | Output validation: closing summary structure, counter question grounding, context grounding (prevents interviewer from introducing entities not mentioned by candidate) |
| `skills/base.py` | shared Skill/SkillRegistry/SkillResourceIndex 兼容导出 |
| `skills/builder.py` | chat-specific skill catalog 包装 + shared build_skill_prompt() |
| `skills/loader.py` | shared SKILL.md 文件加载器兼容导出 |
| `skills/defaults.py` | get_default_registry() — 从 SKILL.md 文件加载所有 skill |
| `skills/{skill-name}/SKILL.md` | 标准 Agent Skill package 定义（标准 frontmatter + Markdown 指令，可选 resources/scripts/assets） |

## 核心模式

- **流式输出**：通过 SSE yield 每个 chunk；ReAct 工具/推理决策继续使用非流式 `llm_with_tools()`，但最终面向候选人的回复必须走 `_stream_final_answer()` 流式输出。工具决策或最终生成请求异常时只允许有限重试/返回 `error` 事件，不要用题库候选或模板话术伪造 fallback 回答。若完整文本校验、去重或题目计划修复后需要覆盖已流出的内容，发送 `chunk` + `replace=true`，路由和前端必须保留该字段
- **Thinking 支持**：`stream_llm_messages(yield_thinking=True)` 支持 MiMo/DeepSeek 的 `reasoning_content` 和 Anthropic ThinkingBlock，事件类型：`thinking_start` → `thinking` → `thinking_done` → `chunk`；`react_loop.py` 也会把 `llm_with_tools()` 非流式返回的 `reasoning_content` 桥接成同样的 thinking 事件，供前端展示“面试官推理”
- **Reasoning 语言约束**：`build_react_system_prompt()` 必须注入 `REASONING_LANGUAGE_GUARDRAIL`，要求面试官最终回复以及 MiMo/DeepSeek `reasoning_content` / 推理过程 / 工具调用分析都使用简体中文；技术名词、代码、库名和英文原文引用可保留英文
- **记忆系统**：`chat_memories` 表存储用户长期记忆，每次对话自动召回
- **Token 预算**：`budget.py` 控制上下文窗口大小，优先保留最近消息
- **面试流程**：开场(自我介绍) → 提问(一次一题) → 收尾(反问)，由 `_determine_interview_phase()` 根据消息数自动切换
- **开场白**：创建对话时 `chat_service.generate_opening_message()` 自动生成，零 LLM 成本
- **岗位驱动 RAG**：`context_builder.build_interview_context()` 返回 `(context, position)`，`job_position` 存入 state，`fts_retrieve()` 按岗位过滤题目检索
- **Skills 系统**：`skills/` 目录实现 Progressive Disclosure — Layer 1 只常驻标准 metadata（`name`/`description`）和 InterviewBoss runtime metadata，Layer 2 `SKILL.md` body 通过 `load_skill` 按需注入，Layer 3 `references/`/`scripts/`/`assets/` 默认只索引，不自动注入 prompt，也没有运行时读取工具。每个 skill 是标准 Agent Skill package；InterviewBoss 私有策略放在 `metadata.interview-boss.*`，不要新增 `skill-pack.yaml`。`always_active=true` 表示 registry 匹配始终命中；只有同时 `kind=tool-use` 的 skill（如 `interview-tool-use`）会在每次 ReAct 系统提示构建时自动注入完整 body（Layer 5.5），无需 Agent 显式调用 `load_skill`。
- **interview-tool-use**：`kind=tool-use` 的始终激活技能，指导 Agent 何时调用题库工具、如何解读信封、空结果降级、禁止泄露内部信号。body 通过 Layer 5.5 自动注入每次 ReAct 系统提示。`references/mcp-tool-envelope.md` 记录信封字段详细规范。

## 质量保护机制

- **结束意图硬路由**：`intent == 'end_interview'` 时跳过 ReAct 循环，不调用工具。若用户要求总结、评价、复盘、hiring signal、风险点或下一轮追问，通常走 `_generate_structured_summary()`；但短历史中出现“先别问/现在就结束/直接给是否通过”这类过早打断式请求，或“时间紧/先收尾/提前结束”这类证据不足的提前收尾请求时，`summary.py` 必须拒绝收尾并回到上一道关键问题继续取证。回答正文里夹带提前收尾请求时，`pipeline._apply_premature_close_guardrails()` 会在分类后、ReAct 前改走 `end_interview` 硬路由，禁止让 ReAct 自行收尾。只有单纯结束且证据量已经足够时才简短告别或总结。`end_interview` 不是 ReAct/MCP 工具；结束面试只能由 `intent=end_interview`、`stop_policy.py` 或持久化的 `closing_stage` workflow gate 触发。
- **自然停止策略**：`stop_policy.py` 是何时结束面试的代码级裁判：`>=32` 条消息且核心覆盖完整时先问候选人“你有什么想问我们的吗？”，候选人回应后生成结构化总结；`>=44` 条消息进入 strong-close，只允许补最后缺口或 HR/反问/收尾；`>56` 条消息才硬停止并直接总结。不要把 45 条消息重新改成硬停
- **重复追问保护**：`_count_consecutive_similar_questions()` 检测连续相似追问，超过 2 次注入 system prompt 硬约束
- **selected_question 绑定**：单候选 + token overlap 时自动绑定，避免弱相关 search 结果被强绑
- **coverage 事件先于快照**：每轮 API 入口的 `interview_state` / `stop_policy` 必须基于历史 assistant metadata 中的 `coverage_events` 作为优先事实源；本轮回复生成后再把新的 selected-question 或 conversation-only 自然追问归一化写入 `metadata.coverage_events`，下一轮生效，避免只在 done metadata 展示 coverage 而不参与运行时决策
- **conversation-only 评估锚点**：无 `selected_question` 的自然追问必须在 done metadata 写入 `assessment_focus` 和 `coverage_events`，记录 `question_source`、`question_source_reason`、`question_type`、`interview_state.current_phase`、`interview_state.next_focus` 和活跃技能，避免 E2E 只有文本、没有结构化评估依据；解释性回复和候选人反问回答不要记为 coverage
- **开场自然追问**：`_should_require_bank_question()` 是题库绑定时机的单一判断；开场自我介绍/早期背景说明后先基于项目和职责自然追问，不立即硬检索题库。`_build_tool_strategy()`、`_should_create_question_plan()` 和 retrieval gap 记录必须共用该判断
- **InterviewLedger 问题台账**：`_build_interview_ledger()` 优先读取 assistant metadata 的 `coverage_events`，再兼容 session notes、selected question 和 basis questions，汇总 `asked_question_ids`、题面、一级/二级分类计数、题型计数和近期主题 token；这是防止同题号/同题型/同主题重复追问和驱动 coverage/stop policy 的硬状态，不要只依赖 prompt 提醒。工具层排除重复候选题时使用 `_collect_question_exclusion_ids()`，它会额外纳入本轮和历史 metadata 中已展示的 `candidate_questions` / `retrieved_questions`，但不把候选曝光计入覆盖率。
- **Interview State 快照**：`run_chat()` 每轮从 conversation metadata 读取 `interview_config`（difficulty / coverage_thresholds / rhythm_profile），用 `InterviewLedger` 派生 `state["interview_state"]` 并注入短 `<interview_state>` prompt；done metadata 也会保存 `interview_state` 和 `observability`，供刷新后恢复。不要在快照里独立推进状态，ledger 仍是事实来源
- **中国互联网大厂 + full-loop harness**：`_build_big_tech_interview_harness_prompt()` / `_big_tech_next_focus()` 基于 `InterviewLedger` 派生当前覆盖度和下一优先评估维度（project_followup / knowledge_probe / algorithm_coding / system_design / behavioral），并注入 `build_react_system_prompt()`；默认面向国内候选人，节奏要覆盖项目深挖、八股基础、场景题/系统设计、手撕代码、HR/稳定性和反问；`_build_tool_strategy()` 必须尊重该推荐，缺 coding / system design / behavioral 信号时优先 `draw_questions(question_type=...)`，不要继续围绕同一项目检索
- **已问题过滤**：`_select_question_for_plan()` 会结合 `InterviewLedger` 与历史 assistant metadata / 旧话术正文提取的已问 ID/题面，优先选择未问过且未达到类别配额的候选；所有候选都已问过时才回退第一题并记录 `*_all_candidates_previously_asked`
- **自然话术兜底**：机械题干 fallback（`_format_bank_question_fallback`）已移除；LLM 重写失败时 `_enforce_question_plan_on_text` 抛出 `GenerationError`，`_fallback_react_answer` 在有候选题时也抛出 `GenerationError`。不要重新引入”好，XXX？”或固定前缀的机械题干
- **未授权总结保护**：非 `end_interview` 且 stop policy 未要求 close 的轮次，最终回答不能输出“面试总结/面试评价/整体表现/综合评分”等收尾报告；`answer.py` 必须拦截这类模型漂移并转成继续追问，避免上一轮过早结束请求污染下一轮。
- **Tool Gateway 契约**：`load_skill` / `search_questions` / `draw_questions` / `select_question` 统一返回 `ok/tool/items|selected_question/metadata/error` envelope；不要再读取旧 `questions` 字段。`tools.py` 保持 ReAct schema 与 JSON 转发，同时保持 `retrieved_questions` 和 SSE retrieved 兼容；`search_questions` rerank 成功时必须同步更新 envelope `items`、`metadata.result_count`、`state.retrieved_questions` 和 `state.candidate_questions`，rerank 失败时保留原工具结果
- **Agent 可调用的 4 个工具**：`load_skill`、`search_questions`、`draw_questions`、`select_question`。`select_question` 允许 Agent 显式从候选题中绑定下一题，但通常由 `search/draw` 后的默认选择逻辑自动完成。不要把 `end_interview`、总结、评估报告生成加入 `ALL_TOOLS` 或 `_ALLOWED_TOOL_NAMES`；closing workflow 在 ReAct 前/外由后端状态机裁决。
- **公开候选题预览**：SSE `retrieved`、done metadata 的 `retrieved_questions/candidate_questions`、以及 `tool_calls_trace.result_preview` 使用 `chat_constants.PUBLIC_QUESTION_PREVIEW_LIMIT` 统一控制，当前为 5；不要让工具显示的 result_count 与可展开预览数量再次脱节
- **题目计划绑定**：出新题场景会从候选题中本地选择 `selected_question`，生成 `next_question_plan` 注入最终生成；`should_retrieve=True` 且回答完整时，工具返回的候选题也必须绑定 plan，不能只检索不选题。偏离计划时触发一次 repair，仍失败则抛出 `GenerationError`。若 ReAct 已经成功 `draw/select` 并绑定了 `must_ask` 计划题，但最终模型返回空文本，`react_loop.py` yield error 事件（code=`empty_answer_plan_generation_failed`），不再用机械题干恢复。Agent 显式调用 `select_question(candidate_index=N)` 会覆盖默认选择（`selection_reason=”agent_explicit_selection”`），但若候选命中 `search_negative_terms` 则返回 `NEGATIVE_TERM_FILTERED` 错误 envelope，越界索引返回 `INDEX_OUT_OF_RANGE`。`question_type=algorithm_coding` 时只允许算法/手撕代码候选绑定 plan，不能用普通 RAG/项目题兜底。
- **检索建议缺口记录（非接管）**：`should_record_retrieval_gap(state)` 为 true 且本轮没有执行 `search_questions` / `draw_questions` 时，`react_loop.py` 只记录 `state["retrieval_gap"]`、`question_source=conversation` 和 `question_source_reason=retrieval_recommended_but_skipped`。不要在 ReAct 循环后注入额外系统消息、不要二次调用 LLM、不要由代码替模型执行题库工具；题库检索应通过本轮 `<tool_strategy>` 和常驻 tool-use skill 在主路径自然发生。
- **检索护栏边界**：`pipeline._apply_retrieval_guardrails()` 只在分类后修正过保守的结构化路由字段：候选人给出足够长、包含明确技术信号且已有 `search_query`/多关键词的回答时，可把 `answer_quality` 纠正为 `complete` 并打开 `should_retrieve`，让后续 `ToolStrategy` 和 tool-use skill 自然驱动工具调用。它不能直接调用 `search_questions`/`draw_questions`，也不能覆盖 `off_topic`、`repeated`、候选人反问或已有候选题的状态。
- **显式题型护栏**：`pipeline._apply_explicit_question_type_guardrails()` 只做结构化字段纠偏：用户明确说“手撕/代码题/写代码/算法题/coding”时写入 `question_type=algorithm_coding`、`should_retrieve=True`、`requires_bank_question=True`。随后由 `tool_strategy.py` 要求 `draw_questions(question_type='algorithm_coding')`，工具服务负责过滤候选；不要在该护栏里直接抽题或选题。
- **工具执行边界**：4 个工具的实际执行集中在 `app.services.interview_tools`；`tools.py` 只负责 ReAct schema、JSON 转发和 search rerank 后同步 state；`app.mcp_server.interview_tools` 只是兼容 adapter，外部 `/mcp` 入口由 `mcp_server/app.py` 转发到同一 service。内部 ReAct 不要 import `app.mcp_server.*`。
- **Context Grounding 防护**：`output_guardrails.check_context_grounding()` 检查面试官输出是否引入候选人未提及的实体（如凭空捏造的项目名）。提取输出中的专有名词/项目名，与候选人上下文（自我介绍、简历、历史回答）和题库题实体对比，过滤常见技术术语（Redis、Docker 等）避免误报。这是防止"事实漂移"的关键机制，由 OutputGuard 在输出到达用户之前调用。
- **Thinking/Steps/Tool Steps/Insights 持久化**：`run_chat()` 在事件循环中累积 `step`、`tool_step`、`thinking`、`insight` 事件，在 `done` 事件时合并进 metadata（兼容字段：`thinking`、`thinking_duration`、`steps`、`tool_steps`、`insights`；新结构化字段：`reasoning_trace`、`tool_calls_trace`、`skill_trace`）。`reasoning_trace.summary` 是公开摘要 fallback；当 `reasoning_trace.source == "model_reasoning"` 且 `thinking` 非空时，前端优先展示模型返回的 `reasoning_content` 作为“面试官推理”。`tool_calls_trace` 只保存白名单参数、耗时、结果数和短结果预览。thinking chunks 上限 `_MAX_THINKING_CHUNKS=50`，避免 metadata 膨胀。页面刷新后前端通过 `getMessages()` 可取回这些字段
- **内部 ReAct Session 持久化**：`run_chat()` 在 ReAct 循环结束后调用 `await save_mcp_session_async(session_id, state)`，与外部 MCP 路径统一。`session_id` 默认等于 `conversation_id`，存入 `ChatState.session_id`。`save_mcp_session_async` 有白名单过滤（`active_skills`、`retrieved_questions` 等），且只持久化 skill names，不持久化 `active_skill_instructions` 完整正文。

## 模块依赖图

```
pipeline.py ──→ react_loop.py ──→ answer.py ──→ nodes.py
    │               │                 │
    │               ├──→ question_plan.py (自包含)
    │               ├──→ summary.py ──→ llm.py
    │               ├──→ metadata.py ──→ nodes.py, db.connection
    │               └──→ tools.py, llm.py
    ├──→ turn_contract.py ──→ stop_policy.py (Phase 1: 旁路观测)
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
