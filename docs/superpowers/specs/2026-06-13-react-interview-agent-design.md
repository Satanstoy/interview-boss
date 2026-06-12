# ReAct 面试 Agent 设计文档

**日期**: 2026-06-13
**状态**: Draft
**范围**: 改造 chat pipeline Step 3-5 为 ReAct 循环

---

## 1. 背景与目标

### 现状

当前 chat pipeline 是固定 5 步流程：

```
Step 1: load_context → Step 2: classify → Step 3: resolve_skills → Step 4: route_and_generate → Step 5: extract_memory
```

问题：
- Step 3 的 skill 匹配基于关键词，效果差
- Step 4 的路由逻辑硬编码（if/elif on intent），LLM 无法自主决策
- 工具调用（search_questions、draw_questions）由 pipeline 代码控制，LLM 无法选择

### 目标

将 Step 3-5 替换为 ReAct 循环，让 LLM 通过 tool calling 自主决定：
- 加载哪些面试技能
- 搜索还是抽题
- 何时直接回答

### 设计原则

- **Progressive Disclosure**: system prompt 只放 skill 目录摘要，完整指令按需加载
- **LLM 自主决策**: 工具选择由 LLM 决定，不硬编码路由
- **流式输出**: 最终回答保持打字机效果
- **渐进迁移**: Step 1-2 不动，最小化改动风险

---

## 2. 架构设计

### 改造前

```
run_chat()
  Step 1: _step_load_context()        ← 加载上下文
  Step 2: _step_classify()            ← 意图分类
  Step 3: _step_resolve_skills()      ← 关键词匹配 skill
  Step 4: _route_and_generate()       ← 硬编码路由 + 生成
  Step 5: _step_extract_memory()      ← 后台记忆提取
```

### 改造后

```
run_chat()
  Step 1: _step_load_context()        ← 不变
  Step 2: _step_classify()            ← 不变
  Step 3: _react_loop(state)          ← 新：ReAct 循环
       │
       ├─ 构建 system prompt（含轻量级 skill 目录）
       ├─ 构建 messages
       ├─ 注册 tools = [load_skill, search_questions, draw_questions]
       │
       ├─ while step < MAX_REACT_STEPS:
       │    result = llm_with_tools(messages, tools)
       │    if tool_calls:
       │      执行工具 → emit 进度 → 追加结果到 messages
       │    else:
       │      break
       │
       ├─ stream_llm_messages(messages)  ← 流式生成最终回答
       │
       └─ asyncio.create_task(_step_extract_memory(state))  ← 不变
```

### 关键决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 改造范围 | Step 3-5 | Step 1-2 是确定性逻辑，不需要 LLM 决策 |
| 框架 | 纯 Python（不用 LangGraph） | Chat agent 已迁移，ReAct 循环只需 while + llm_with_tools |
| 最终回答 | 流式生成 | 复用现有 stream_llm_messages，保持打字机效果 |
| 工具数量 | 3 个 | 够用即可，避免工具过多导致选择错误 |

---

## 3. Tool 定义

### 3.1 load_skill

```json
{
  "name": "load_skill",
  "description": "加载面试技能指令。根据面试话题或用户问题的领域，选择最合适的技能来指导你的面试行为。在开始面试或切换话题时调用。",
  "parameters": {
    "type": "object",
    "properties": {
      "skill_name": {
        "type": "string",
        "enum": [
          "interview-rhythm",
          "adaptive-difficulty",
          "project-deep-dive",
          "algorithm-coding",
          "theory-qa",
          "hr-soft-skills"
        ],
        "description": "技能名称"
      }
    },
    "required": ["skill_name"]
  }
}
```

执行逻辑：从 `SkillRegistry` 读取 skill 的完整 `instruction_template`，返回文本。

### 3.2 search_questions

```json
{
  "name": "search_questions",
  "description": "从题库中搜索面试题。当需要找到与用户问题相关的面试题时调用。返回匹配的题目列表。",
  "parameters": {
    "type": "object",
    "properties": {
      "keywords": {
        "type": "array",
        "items": {"type": "string"},
        "description": "搜索关键词，如 ['Redis', '缓存穿透']"
      },
      "question_type": {
        "type": "string",
        "enum": ["project_followup", "knowledge_probe", "new_question"],
        "description": "题目类型偏好"
      }
    },
    "required": ["keywords"]
  }
}
```

执行逻辑：调用 `hybrid_search()` + `llm_rerank_questions()`，返回 top 3 题目 JSON。

### 3.3 draw_questions

```json
{
  "name": "draw_questions",
  "description": "从题库中随机抽题。当用户要求练习、或需要随机出题时调用。",
  "parameters": {
    "type": "object",
    "properties": {
      "count": {
        "type": "integer",
        "description": "抽题数量，默认 1",
        "default": 1
      },
      "difficulty": {
        "type": "string",
        "enum": ["easy", "medium", "hard"],
        "description": "难度偏好"
      }
    }
  }
}
```

执行逻辑：调用 `draw_questions()`，返回题目 JSON。

### 3.4 Tool 执行器

```python
async def execute_tool(tool_call: dict, state: ChatState) -> str:
    """执行单个 tool call，返回结果字符串。"""
    name = tool_call["function"]["name"]
    args = json.loads(tool_call["function"]["arguments"])

    if name == "load_skill":
        skill = skill_registry.get(args["skill_name"])
        return skill.get_instruction()

    elif name == "search_questions":
        results = await hybrid_search(
            keywords=args["keywords"],
            question_type=args.get("question_type"),
            job_position=state.get("job_position"),
        )
        # 更新 state 供后续 basis 追踪
        state["retrieved_questions"] = results[:3]
        return json.dumps(results[:3], ensure_ascii=False, default=str)

    elif name == "draw_questions":
        results = await asyncio.to_thread(
            draw_questions,
            user={"id": state["user_id"]},
            count=args.get("count", 1),
            difficulty=args.get("difficulty"),
        )
        state["retrieved_questions"] = results
        return json.dumps(results, ensure_ascii=False, default=str)

    else:
        return json.dumps({"error": f"Unknown tool: {name}"})
```

---

## 4. ReAct 循环实现

```python
MAX_REACT_STEPS = 5

async def _react_loop(state: ChatState) -> AsyncGenerator:
    """ReAct 循环：LLM 自主选择工具，最终流式生成回答。"""

    # 1. 构建 system prompt
    system_prompt = _build_base_system_prompt(state)
    skill_catalog = _build_skill_catalog()  # 名字 + 描述，~500 tokens
    system_prompt += f"\n\n{skill_catalog}"
    system_prompt += "\n\n你可以调用 load_skill 工具来加载完整技能指令。"

    # 2. 构建 messages
    messages = _build_messages(system_prompt, state)

    # 3. 注册 tools
    tools = [LOAD_SKILL_SCHEMA, SEARCH_QUESTIONS_SCHEMA, DRAW_QUESTIONS_SCHEMA]

    # 4. ReAct 循环
    for step in range(MAX_REACT_STEPS):
        result = await llm_with_tools(messages, tools, user_id=state["user_id"])

        if not result["tool_calls"]:
            break  # LLM 决定直接回答

        # 追加 assistant message（含 tool_calls）
        messages.append({
            "role": "assistant",
            "content": result["content"],
            "tool_calls": result["tool_calls"],
        })

        # 执行每个 tool call
        for tc in result["tool_calls"]:
            tool_name = tc["function"]["name"]
            _emit({"type": "step", "step": tool_name,
                   "message": _tool_progress_message(tc)})

            output = await execute_tool(tc, state)

            # search_questions 结果需要 emit retrieved 事件
            if tool_name == "search_questions" and state.get("retrieved_questions"):
                _emit({"type": "retrieved", "questions": state["retrieved_questions"]})

            messages.append(make_tool_result_message(tc["id"], output))

    # 5. 流式生成最终回答
    _emit({"type": "step", "step": "generating", "message": "正在生成回答..."})
    async for event in stream_llm_messages(messages, user_id=state["user_id"]):
        if isinstance(event, dict):
            yield event
        else:
            yield {"type": "chunk", "content": event}

    # 6. 发送完成事件
    yield {"type": "done", "metadata": state.get("metadata", {})}
```

---

## 5. System Prompt 设计

### Layer 1: Base Prompt（保留现有）

包含 JD/简历信息、面试阶段、答题依据等。从现有的 `_build_base_system_prompt()` 复用。

### Layer 2: Skill 目录（新增，轻量级）

```
## 可用技能

你可以通过 load_skill 工具加载以下技能来指导你的面试行为：

- **interview-rhythm**: 面试节奏控制——何时追问、何时切换话题、何时结束
- **adaptive-difficulty**: 根据候选人表现动态调整问题难度
- **project-deep-dive**: 深入追问项目经验，验证真实性
- **algorithm-coding**: 算法题面试——出题、引导、评估
- **theory-qa**: 理论知识问答——概念理解、原理分析
- **hr-soft-skills**: 软技能评估——团队协作、沟通能力

根据面试话题选择最相关的技能加载。一次可以加载多个。
```

### Layer 3: 行为引导（新增）

```
## 工具使用指南

你有以下工具可用：
- load_skill: 加载面试技能指令（在需要专业面试技巧时调用）
- search_questions: 搜索题库（当需要找相关面试题时调用）
- draw_questions: 随机抽题（当用户要求练习时调用）

请根据用户的提问内容自主决定使用哪些工具。你可以：
1. 先加载相关技能，再搜索或抽取题目
2. 直接回答简单问题（不需要工具时）
3. 多次调用工具组合使用

如果不调用任何工具，你将直接生成回答。
```

### Prompt Token 预算

| 部分 | 预估 tokens |
|------|------------|
| Base Prompt | ~800 |
| Skill 目录 | ~500 |
| 行为引导 | ~200 |
| Compressed context | ~500-1000 |
| Recent messages | ~1000-2000 |
| **总计** | ~3000-4500 |

---

## 6. SSE 事件流

### 事件类型（复用 + 新增）

| 事件类型 | 来源 | 说明 |
|---------|------|------|
| `step` | 现有 | 进度指示（loading, understanding, load_skill, search_questions...） |
| `retrieved` | 现有 | 检索到的题目 |
| `chunk` | 现有 | 流式文本块 |
| `thinking_*` | 现有 | 思考过程 |
| `basis` | 现有 | 答题依据 |
| `done` | 现有 | 完成 |
| `error` | 现有 | 错误 |
| `tool_result` | **新增** | 工具执行结果摘要（可选，前端可忽略） |

### 典型事件序列

```
→ {"type": "step", "step": "loading", "message": "加载上下文..."}
→ {"type": "step", "step": "understanding", "message": "理解问题..."}
→ {"type": "step", "step": "load_skill", "message": "加载 algorithm-coding 技能..."}
→ {"type": "step", "step": "search_questions", "message": "搜索相关面试题..."}
→ {"type": "retrieved", "questions": [...]}
→ {"type": "step", "step": "generating", "message": "正在生成回答..."}
→ {"type": "chunk", "content": "好的，"}
→ {"type": "chunk", "content": "让我问你一道..."}
→ {"type": "basis", "type": "question", "question_ids": [...]}
→ {"type": "done", "metadata": {...}}
```

---

## 7. 错误处理

### Tool 执行失败

- 返回错误信息给 LLM（`{"error": "..."}`），不中断循环
- LLM 自主决定重试、换工具、或直接回答
- `llm_with_tools` 已有 `@retry` 处理 LLM 调用失败（4 次 / 60s）

### ReAct 循环超限

- `MAX_REACT_STEPS = 5` 防止无限循环
- 循环结束后仍调用 `stream_llm_messages` 生成回答

### 流式中断

- 复用现有的 `_emit` + `try/finally` + `_SENTINEL` 机制
- 用户断开连接时 pipeline 自然终止

---

## 8. 测试策略

### 单元测试

- `execute_tool()`: Mock 依赖，验证参数解析和返回格式
- `_build_skill_catalog()`: 验证输出格式
- `_build_messages()`: 验证 system prompt 拼接
- `_update_state_from_tool()`: 验证 state 更新

### 集成测试（Mock LLM）

- LLM 直接回答（不调工具）
- LLM 调用 search_questions 后回答
- LLM 调用 load_skill + search_questions
- LLM 循环超限
- Tool 执行失败后 LLM 恢复

### SSE 事件测试

- 工具调用序列的事件正确性
- 流式生成的 chunk 顺序
- 错误场景的 error 事件

---

## 9. 文件变更清单

| 文件 | 变更 |
|------|------|
| `backend/app/agents/chat/pipeline.py` | 删除 Step 3-4，新增 `_react_loop()` |
| `backend/app/agents/chat/tools.py` | **新建**：tool schema 定义 + `execute_tool()` |
| `backend/app/agents/chat/nodes.py` | 删除 `resolve_active_skills()`、`plan_skill_guided_strategy()`，保留其他 node |
| `backend/app/agents/chat/state.py` | 简化：删除不再需要的 skill 相关字段 |
| `backend/app/agents/shared/skills/builder.py` | 新增 `_build_skill_catalog()` |
| `backend/tests/chat/test_react_loop.py` | **新建**：ReAct 循环测试 |
