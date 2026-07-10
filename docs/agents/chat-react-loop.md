# 模拟面试 Agent — ReAct Loop 架构详解

> 生成日期：2026-07-10
> 核心文件：`backend/app/agents/chat/react_loop.py`、`pipeline.py`、`tools.py`、`tool_strategy.py`

---

## 全景流程图

```
                         用户发送消息
                              │
                              ▼
               ┌──────────────────────────────┐
               │     run_chat() 入口           │
               │   pipeline.py:502            │
               │   AsyncGenerator[SSE事件]     │
               └──────────────┬───────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
   ┌──────────────┐  ┌──────────────┐  ┌──────────────┐
   │ _step_load_  │  │ _load_inter- │  │ _step_classify│
   │ context      │  │ view_config  │  │  (单次LLM)    │
   │              │  │              │  │              │
   │ · 历史消息    │  │ · 面试阶段   │  │ · 意图分类    │
   │ · 记忆摘要    │  │ · 覆盖度     │  │ · 关键词提取   │
   │ · 简历/JD    │  │ · 活跃技能   │  │ · 答案质量    │
   │ · 上下文压缩  │  │ · DB元数据   │  │ · 是否需要检索 │
   └──────┬───────┘  └──────┬───────┘  └──────┬───────┘
          │                 │                 │
          └─────────────────┴────────┬────────┘
                                     │
                              ┌──────▼──────┐
                              │  意图路由    │
                              │  (纯函数)    │
                              └──────┬──────┘
                      ┌──────────────┼──────────────┐
                      ▼                             ▼
             ┌────────────────┐            ┌────────────────┐
             │  intent ==     │            │  intent !=     │
             │  end_interview │            │  end_interview │
             │                │            │                │
             │ → 生成结构化    │            │                │
             │   面试总结      │            │                │
             │ → yield done   │            │                │
             └────────────────┘            └───────┬────────┘
                                                    │
                                                    ▼
                                    ┌───────────────────────────┐
                                    │   Pre-loop: Stop Policy   │
                                    │   stop_policy.py          │
                                    │                           │
                                    │  evaluate_interview_stop() │
                                    └─────────┬─────────────────┘
                                              │
                              ┌────────────────┼────────────────┐
                              ▼                ▼                ▼
                      ┌─────────────┐  ┌─────────────┐  ┌─────────────┐
                      │  continue   │  │ ask_candi-  │  │    close     │
                      │             │  │ date_question│  │             │
                      │  进入ReAct  │  │ "你有什么   │  │ 生成总结     │
                      │  Loop       │  │  问题想问？" │  │ yield done  │
                      └──────┬──────┘  └─────────────┘  └─────────────┘
                             │
                             ▼
        ╔═══════════════════════════════════════════════════════════════╗
        ║                   ReAct Loop (最多5轮)                       ║
        ║                   react_loop.py:432                          ║
        ║                                                             ║
        ║  ┌──────────────────────────────────────────────────────┐   ║
        ║  │ step = 0,1,2,3,4                                    │   ║
        ║  │                                                      │   ║
        ║  │  ┌─────────────────────────────────────┐             │   ║
        ║  │  │ ① Budget 检查                      │             │   ║
        ║  │  │   · tool_calls ≤ 10?               │             │   ║
        ║  │  │   · wall_time ≤ 30s?               │             │   ║
        ║  │  │   · 上一步加载了skill? → 重建prompt │             │   ║
        ║  │  └──────────────┬──────────────────────┘             │   ║
        ║  │                 ▼                                     │   ║
        ║  │  ┌─────────────────────────────────────┐             │   ║
        ║  │  │ ② llm_with_tools() — 非流式       │             │   ║
        ║  │  │                                      │             │   ║
        ║  │  │  输入: messages + ALL_TOOLS schemas  │             │   ║
        ║  │  │         + system prompt              │             │   ║
        ║  │  │         + tool_strategy XML注入      │             │   ║
        ║  │  └──────────────┬──────────────────────┘             │   ║
        ║  │                 │                                     │   ║
        ║  │        ┌────────┴────────┐                           │   ║
        ║  │        ▼                 ▼                           │   ║
        ║  │  ┌───────────┐   ┌──────────────┐                   │   ║
        ║  │  │ 有        │   │ 无 tool_calls │                   │   ║
        ║  │  │ tool_calls│   │               │                   │   ║
        ║  │  │           │   │ LLM选择直接   │                   │   ║
        ║  │  │ LLM选择   │   │ 回答用户      │                   │   ║
        ║  │  │ 先用工具   │   │               │                   │   ║
        ║  │  └─────┬─────┘   │ → BREAK       │                   │   ║
        ║  │        │         │   跳出循环     │                   │   ║
        ║  │        ▼         └──────┬────────┘                   │   ║
        ║  │  ┌──────────────┐       │                            │   ║
        ║  │  │ ③ 逐个执行   │       │                            │   ║
        ║  │  │   tool_call  │       │                            │   ║
        ║  │  │              │       │                            │   ║
        ║  │  │ for tc in    │       │                            │   ║
        ║  │  │ tool_calls:  │       │                            │   ║
        ║  │  │              │       │                            │   ║
        ║  │  │ a. 白名单校验 │       │                            │   ║
        ║  │  │    validate_ │       │                            │   ║
        ║  │  │    tool_call │       │                            │   ║
        ║  │  │              │       │                            │   ║
        ║  │  │ b. 循环检测   │       │                            │   ║
        ║  │  │    seen_tool │       │                            │   ║
        ║  │  │    _calls去重│       │                            │   ║
        ║  │  │              │       │                            │   ║
        ║  │  │ c. execute_  │       │                            │   ║
        ║  │  │    tool()    │       │                            │   ║
        ║  │  │    ↓         │       │                            │   ║
        ║  │  │  ┌─────────┐│       │                            │   ║
        ║  │  │  │ 4个工具: ││       │                            │   ║
        ║  │  │  │         ││       │                            │   ║
        ║  │  │  │load_skill││       │                            │   ║
        ║  │  │  │加载技能  ││       │                            │   ║
        ║  │  │  │指令到    ││       │                            │   ║
        ║  │  │  │system   ││       │                            │   ║
        ║  │  │  │prompt   ││       │                            │   ║
        ║  │  │  │         ││       │                            │   ║
        ║  │  │  │search_  ││       │                            │   ║
        ║  │  │  │questions││       │                            │   ║
        ║  │  │  │FTS5+LLM ││       │                            │   ║
        ║  │  │  │重排序    ││       │                            │   ║
        ║  │  │  │         ││       │                            │   ║
        ║  │  │  │draw_    ││       │                            │   ║
        ║  │  │  │questions││       │                            │   ║
        ║  │  │  │加权随机  ││       │                            │   ║
        ║  │  │  │抽题      ││       │                            │   ║
        ║  │  │  │         ││       │                            │   ║
        ║  │  │  │select_  ││       │                            │   ║
        ║  │  │  │question ││       │                            │   ║
        ║  │  │  │绑定选中  ││       │                            │   ║
        ║  │  │  │题目      ││       │                            │   ║
        ║  │  │  └─────────┘│       │                            │   ║
        ║  │  │              │       │                            │   ║
        ║  │  │ d. 结果追加到 │       │                            │   ║
        ║  │  │    messages  │       │                            │   ║
        ║  │  │              │       │                            │   ║
        ║  │  │ e. 裁剪：    │       │                            │   ║
        ║  │  │    search/draw│       │                            │   ║
        ║  │  │    只保留top3 │       │                            │   ║
        ║  │  └──────┬───────┘       │                            │   ║
        ║  │         │               │                            │   ║
        ║  │         ▼               │                            │   ║
        ║  │  ┌──────────────┐       │                            │   ║
        ║  │  │ ④ 清理旧工具  │       │                            │   ║
        ║  │  │   结果        │       │                            │   ║
        ║  │  │   (>5轮前的  │       │                            │   ║
        ║  │  │    压缩为1行) │       │                            │   ║
        ║  │  └──────┬───────┘       │                            │   ║
        ║  │         │               │                            │   ║
        ║  │         └───────┬───────┘                            │   ║
        ║  │                 │                                    │   ║
        ║  │            next step (或 BREAK)                      │   ║
        ║  └──────────────────────────────────────────────────────┘   ║
        ╚═════════════════════════╤═══════════════════════════════════╝
                                  │
                                  ▼
                    ┌──────────────────────────┐
                    │    Post-loop 处理         │
                    │                          │
                    │ 1. max_steps + 无答案？   │
                    │    → 强制合成LLM调用      │
                    │                          │
                    │ 2. 检索缺口观测           │
                    │    (该搜没搜 → 记metadata)│
                    │                          │
                    │ 3. 输出护栏               │
                    │    needs_output_repair()  │
                    │    → 修复LLM调用          │
                    │                          │
                    │ 4. 去重                   │
                    │    OutputDeduplicator     │
                    │    检查跨轮重复输出        │
                    │                          │
                    │ 5. _final_answer_events_  │
                    │    from_text() → chunk    │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                    ┌──────────────────────────┐
                    │    收尾                   │
                    │                          │
                    │ _persist_active_skills()  │
                    │ save_mcp_session_async()  │
                    │ _step_extract_memory()    │
                    │   (后台 fire-and-forget)  │
                    └────────────┬─────────────┘
                                 │
                                 ▼
                          yield SSE done
```

---

## 核心设计要点

### 1. 两层决策架构

```
外层 pipeline（线性）          内层 react loop（迭代）
─────────────────────         ─────────────────────
load_context                  LLM 自主决定：
  ↓                           · 要不要调工具？
classify (单次LLM)             · 调哪个？
  ↓                           · 结果够不够？
intent routing                · 还是直接回答？
  ↓                             ↓
stop_policy                   最多5轮，3重预算卡
  ↓
react_loop ─────────────────→ (内层)
  ↓
persist + extract_memory
```

### 2. Tool Strategy — 不是图边，是 Prompt 注入

```
compute_tool_strategy(state)     →   <tool_strategy> XML块
                                            ↓
根据 intent/quality/escalation          注入到 system prompt
判断该用哪些工具                          告诉 LLM "这轮应该/不应该用XX"
```

路由决策不是硬编码的 if-else 边，而是动态生成的提示词，让 LLM 在遵循引导的同时保留自主判断。

### 3. 四个工具的职责链

| 工具 | 职责 | 参数 |
|------|------|------|
| `load_skill` | 加载面试技能指令（自适应难度、算法编码、HR软技能等），加载后下一轮重建 system prompt | `skill_name` (enum) |
| `search_questions` | FTS5 全文搜索 + LLM 重排序，找相关题目 | `keywords`, `question_type` |
| `draw_questions` | 加权随机抽题（按难度/分类/主题） | `count`, `difficulty`, `cat1`, `cat2`, `topic` |
| `select_question` | 从候选列表中选定下一题 | `candidate_index` |

### 4. 三重安全预算

| 维度 | 限制 | 触发后果 |
|------|------|---------|
| `max_steps` | 5 轮 LLM 调用 | 强制合成已有结果输出 |
| `max_tool_calls` | 10 次工具执行 | 停止工具调用 |
| `max_seconds` | 30 秒墙钟时间 | 超时中断 |

加上**循环检测**（相同 `name+args` 签名去重）和**白名单校验**（只允许 4 个工具），确保 agent 不会失控。

### 5. 系统 Prompt 分层组装

`build_react_system_prompt(state)` 在 `nodes.py:1806`，按以下层级叠加：

| 层 | 内容 | 作用 |
|----|------|------|
| 1 | base prompt | JD模式/练习模式基础人设 |
| 2 | language guardrail | 强制中文输出（含推理） |
| 3 | classification state | 意图/答案质量/升级等级 |
| 4 | memory summaries | 候选人弱点/优势画像 |
| 5 | session notes | 面试过程中积累的笔记 |
| 6 | compressed context | 早期对话的压缩摘要 |
| 7 | interview snapshot | 当前阶段/下一焦点/覆盖度 |
| 8 | skill catalog | 可用技能元数据 |
| 9 | tool strategy | 本轮工具使用引导（XML注入） |
| 10 | big-tech harness | 大厂面试覆盖度驱动框架 |
| 11 | active skill instructions | 已加载的持久技能指令 |
| 12 | mid-loop skills | 本轮新加载的技能指令 |
| 13 | basis guidance | `[BASIS]` 元数据输出规范 |

**智能不在图结构里，在 prompt 里。**

---

## ChatState 字段概览

`backend/app/agents/chat/state.py` 定义了约 50 个字段的 `TypedDict`：

| 分组 | 关键字段 |
|------|---------|
| **Input** | `conversation_id`, `user_id`, `user_message`, `mode`, `jd_id`, `resume_text`, `model`, `bank_mode`, `difficulty` |
| **Memory** | `memories`, `memory_summaries`, `resume_summary`, `session_notes`, `interview_context` |
| **Context** | `message_history`, `compressed_context`, `recent_messages`, `budget_snapshot` |
| **Classification** | `intent`, `answer_complete`, `answer_quality`, `should_retrieve`, `transition_style`, `escalation_level`, `off_topic_streak`, `repetition_streak` |
| **RAG** | `keywords`, `search_query`, `retrieval_intent`, `retrieved_questions`, `candidate_questions`, `selected_question`, `question_source` |
| **Skills** | `active_skills`, `active_skill_instructions` |
| **Closing** | `closing_stage` (→ technical → candidate_question_asked → candidate_question_answered → final_summary → closed), `counter_question` |
| **Routing** | `turn_action`, `turn_reason`, `question_intent` |

---

## SSE 事件类型

前端通过 `POST /api/chat/conversations/{id}/messages` 接收以下事件：

| 事件 | 用途 |
|------|------|
| `step` | 流程阶段标记 |
| `tool_step` | 工具调用详情 |
| `chunk` | 流式文本片段 |
| `thinking_start/done` | 思考过程标记 |
| `thinking` | 思考内容 |
| `retrieved` | 检索结果 |
| `insight` | 面试洞察 |
| `candidates` | 候选题目列表 |
| `selected_question` | 选中的题目 |
| `question_plan` | 出题计划 |
| `basis` | 决策依据元数据 |
| `done` | 结束（携带完整 trace） |
| `error` | 错误 |

---

## 关键源文件索引

| 文件 | 职责 |
|------|------|
| `agents/chat/pipeline.py` | 主流程编排，`run_chat()` 入口 |
| `agents/chat/react_loop.py` | ReAct 循环核心，`_react_loop()` |
| `agents/chat/tools.py` | 4 个工具定义 + 执行逻辑 |
| `agents/chat/tool_strategy.py` | 动态工具策略（prompt 注入） |
| `agents/chat/nodes.py` | system prompt 组装 + 各步骤实现 |
| `agents/chat/state.py` | ChatState TypedDict 定义 |
| `agents/chat/stop_policy.py` | 面试结束判定策略 |
| `agents/chat/routing.py` | 意图路由纯函数 |
| `agents/chat/graph.py` | 兼容 shim，re-export `run_chat` |
| `routers/chat.py` | HTTP API 层，SSE 推送 |
