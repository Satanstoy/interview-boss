# Chat Agent — 面试 Chatbot

纯 async pipeline（替代 LangGraph StateGraph）：记忆召回 → 上下文构建 → 意图分类 → ReAct 循环 → 记忆提取。

## 流程

```
run_chat() → _step_load_context → _step_classify → _react_loop → _persist_active_skills → _step_extract_memory
```

## 文件职责

| 文件 | 职责 |
|------|------|
| `pipeline.py` | 入口点：`run_chat()` + pipeline steps（`_step_load_context`、`_step_classify`、`_step_extract_memory`、`_persist_active_skills`、`_initial_state`）+ 所有子模块的 re-export（向后兼容） |
| `react_loop.py` | ReAct 循环核心：`_react_loop()`、`Budget`/`StopRun`、`validate_tool_call()`、trace 日志、事件发射 |
| `answer.py` | 答案生成与质量：`OutputDeduplicator`、`_stream_final_answer()`、`_enforce_question_plan_on_text()`、fallback 响应、内部 marker 过滤 |
| `question_plan.py` | 题目计划管理：`_maybe_create_question_plan()`、`_select_question_for_plan()`、重复追问保护、已问题列表构建 |
| `summary.py` | 面试总结：`InterviewSummary`、`_generate_structured_summary()`、`_forced_closing_response()`、`_generate_end_interview_response()` |
| `metadata.py` | Basis 追踪与元数据：`_build_react_metadata()`、`_infer_selected_question()`、`_extract_company()`/`_extract_round()` |
| `graph.py` | 兼容层，委托给 `pipeline.run_chat` |
| `nodes.py` | 节点实现（recall、build_context、stream、extract）、面试阶段判定 |
| `state.py` | ChatState TypedDict |
| `prompts.py` | 系统提示词（含面试阶段协议）、记忆提取提示词 |
| `context_builder.py` | 上下文拼接（记忆 + 简历 + JD + 历史消息） |
| `budget.py` | Token 预算管理（控制上下文长度） |
| `tools.py` | ReAct tool schemas and tool execution entrypoint；执行时委托 `app.mcp_server.interview_tools` |
| `tool_gateway.py` | Tool input/output contracts, envelope normalization, and tool error metadata |
| `skills/base.py` | shared Skill/SkillRegistry/SkillResourceIndex 兼容导出 |
| `skills/builder.py` | shared build_skill_prompt()/build_skill_catalog() 兼容导出 |
| `skills/loader.py` | shared SKILL.md 文件加载器兼容导出 |
| `skills/defaults.py` | get_default_registry() — 从 SKILL.md 文件加载所有 skill |
| `skills/{skill-name}/SKILL.md` | 标准 Agent Skill package 定义（标准 frontmatter + Markdown 指令，可选 resources/scripts/assets） |

## 核心模式

- **流式输出**：通过 SSE yield 每个 chunk
- **Thinking 支持**：`stream_llm_messages(yield_thinking=True)` 支持 DeepSeek reasoning_content 和 Anthropic ThinkingBlock，事件类型：`thinking_start` → `thinking` → `thinking_done` → `chunk`
- **记忆系统**：`chat_memories` 表存储用户长期记忆，每次对话自动召回
- **Token 预算**：`budget.py` 控制上下文窗口大小，优先保留最近消息
- **面试流程**：开场(自我介绍) → 提问(一次一题) → 收尾(反问)，由 `_determine_interview_phase()` 根据消息数自动切换
- **开场白**：创建对话时 `chat_service.generate_opening_message()` 自动生成，零 LLM 成本
- **岗位驱动 RAG**：`context_builder.build_interview_context()` 返回 `(context, position)`，`job_position` 存入 state，`fts_retrieve()` 按岗位过滤题目检索
- **Skills 系统**：`skills/` 目录实现 Progressive Disclosure — Layer 1 只常驻标准 metadata（`name`/`description`）和 InterviewBoss runtime metadata，Layer 2 `SKILL.md` body 通过 `load_skill` 按需注入，Layer 3 `references/`/`scripts/`/`assets/` 仅索引并按需读取。每个 skill 是标准 Agent Skill package；InterviewBoss 私有策略放在 `metadata.interview-boss.*`，不要新增 `skill-pack.yaml`。

## 质量保护机制

- **结束意图硬路由**：`intent == 'end_interview'` 时跳过 ReAct 循环，不调用工具，直接生成总结
- **重复追问保护**：`_count_consecutive_similar_questions()` 检测连续相似追问，超过 2 次注入 system prompt 硬约束
- **selected_question 绑定**：单候选 + token overlap 时自动绑定，避免弱相关 search 结果被强绑
- **Tool Gateway 契约**：`load_skill` / `search_questions` / `draw_questions` / `select_question` 统一返回 `ok/tool/items|selected_question/metadata/error` envelope；`tools.py` 保持 ReAct schema 与 JSON 转发，同时保持 `retrieved_questions` 和 SSE retrieved 兼容
- **Agent 可调用的 4 个工具**：`load_skill`、`search_questions`、`draw_questions`、`select_question`。`select_question` 允许 Agent 显式从候选题中绑定下一题，但通常由 `search/draw` 后的默认选择逻辑自动完成
- **题目计划绑定**：出新题场景会从候选题中本地选择 `selected_question`，生成 `next_question_plan` 注入最终生成；偏离计划时触发一次 repair，仍失败则使用确定性 fallback。Agent 显式调用 `select_question` 会覆盖默认选择
- **完整回答后强制候选题**：`interview_question + answer_complete=True + 无候选题` 时，即使在 `project-deep-dive` 模式也必须先调用 `search_questions`，避免直接追问跳过 selected_question/question_plan 绑定
- **后端 MCP 执行边界**：4 个工具的实际执行集中在 `app.mcp_server.interview_tools`，`tools.py` 只负责 ReAct schema 与 JSON 转发；同一工具层通过 `/mcp` 暴露给后端内嵌 MCP app，支持 `session_id` 跨调用状态持久化

## 模块依赖图

```
pipeline.py ──→ react_loop.py ──→ answer.py ──→ nodes.py
    │               │                 │
    │               ├──→ question_plan.py (自包含)
    │               ├──→ summary.py ──→ llm.py
    │               ├──→ metadata.py ──→ nodes.py, db.connection
    │               └──→ tools.py, llm.py
    ├──→ nodes.py, context_builder.py
    └──→ chat_service, memory_recall_service
```

- `question_plan.py` 是自包含模块（仅依赖标准库 + state）
- `pipeline.py` 通过 re-export 保持所有子模块符号的向后兼容

## 修改后必做

1. 运行 `docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q`
2. 更新本文件
