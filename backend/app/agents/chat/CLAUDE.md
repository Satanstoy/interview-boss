# Chat Agent — 面试 Chatbot

LangGraph 状态机：记忆召回 → 上下文构建 → LLM 流式回复 → 记忆提取。

## 流程

```
START → recall_memories → build_context → stream_reply → extract_memory → END
```

## 文件职责

| 文件 | 职责 |
|------|------|
| `graph.py` | StateGraph 定义、条件路由 |
| `nodes.py` | 节点实现（recall、build_context、stream、extract）、面试阶段判定 |
| `state.py` | ChatState TypedDict |
| `prompts.py` | 系统提示词（含面试阶段协议）、记忆提取提示词 |
| `context_builder.py` | 上下文拼接（记忆 + 简历 + JD + 历史消息） |
| `budget.py` | Token 预算管理（控制上下文长度） |
| `tools.py` | ReAct tool schemas and tool execution entrypoint |
| `tool_gateway.py` | Tool input/output contracts, envelope normalization, and tool error metadata |
| `skills/base.py` | Skill 基类 + SkillRegistry（Progressive Disclosure 架构） |
| `skills/builder.py` | build_skill_prompt() — 合并 active skills 指令为 prompt 片段 |
| `skills/loader.py` | SKILL.md 文件加载器（解析 YAML frontmatter + Markdown body） |
| `skills/defaults.py` | get_default_registry() — 从 SKILL.md 文件加载所有 skill |
| `skills/{skill-name}/SKILL.md` | 6 个 skill 定义文件（YAML frontmatter + Markdown 指令） |

## 核心模式

- **流式输出**：通过 SSE yield 每个 chunk
- **Thinking 支持**：`stream_llm_messages(yield_thinking=True)` 支持 DeepSeek reasoning_content 和 Anthropic ThinkingBlock，事件类型：`thinking_start` → `thinking` → `thinking_done` → `chunk`
- **记忆系统**：`chat_memories` 表存储用户长期记忆，每次对话自动召回
- **Token 预算**：`budget.py` 控制上下文窗口大小，优先保留最近消息
- **面试流程**：开场(自我介绍) → 提问(一次一题) → 收尾(反问)，由 `_determine_interview_phase()` 根据消息数自动切换
- **开场白**：创建对话时 `chat_service.generate_opening_message()` 自动生成，零 LLM 成本
- **岗位驱动 RAG**：`context_builder.build_interview_context()` 返回 `(context, position)`，`job_position` 存入 state，`fts_retrieve()` 按岗位过滤题目检索
- **Skills 系统**：`skills/` 目录实现 Progressive Disclosure — Layer 1 metadata 始终加载，Layer 2 instruction 按需注入，Layer 3 resources 条件触发。每个 skill 是一个目录 + `SKILL.md` 文件（YAML frontmatter + Markdown body），遵循 AgentSkills.io 规范。`SkillRegistry` 管理所有 skill，`build_skill_prompt()` 合并 active skills 指令

## 质量保护机制

- **结束意图硬路由**：`intent == 'end_interview'` 时跳过 ReAct 循环，不调用工具，直接生成总结
- **重复追问保护**：`_count_consecutive_similar_questions()` 检测连续相似追问，超过 2 次注入 system prompt 硬约束
- **selected_question 绑定**：单候选 + token overlap 时自动绑定，避免弱相关 search 结果被强绑
- **Tool Gateway 契约**：`search_questions` / `draw_questions` 通过 `tool_gateway.py` 返回统一 `ok/items/metadata/error` envelope，同时保持 `retrieved_questions` 和 SSE retrieved 兼容
- **题目计划绑定**：出新题场景会从候选题中本地选择 `selected_question`，生成 `next_question_plan` 注入最终生成；偏离计划时触发一次 repair，仍失败则使用确定性 fallback
- **完整回答后强制候选题**：`interview_question + answer_complete=True + 无候选题` 时，即使在 `project-deep-dive` 模式也必须先调用 `search_questions`，避免直接追问跳过 selected_question/question_plan 绑定

## 修改后必做

1. 运行 `docker compose exec backend uv run pytest backend/tests/chat/ -q`
2. 更新本文件
