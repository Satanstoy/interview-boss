# ReAct Agent 生产级加固设计

**日期**：2026-06-13
**状态**：已批准
**范围**：backend/app/agents/chat/

## 背景

当前 ReAct 面试 agent 能跑通基本流程，但存在三个生产级缺陷：

1. **Tool schema 太薄**：每个 tool 只有一句话描述，LLM 缺乏足够信息做准确的 tool 选择
2. **Skill 注入走 tool result**：`load_skill` 返回的全文指令被当普通 observation，容易被后续对话冲淡
3. **无 tool 选择策略**：完全靠 LLM 自主判断，没有基于 intent 的引导

## 设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 落地方式 | 渐进式（3 Phase） | 每阶段独立可测可回滚 |
| Skill 注入 | LLM 选择 + 后端注入 system prompt | 保持 LLM 自主性，同时解决指令被冲淡的问题 |
| Tool 路由 | 软路由（system prompt 建议） | tool 调用决策权留给 LLM |
| Intent 调整 | 微调现有分类，不新增 intent | 现有 4 个 intent 粒度足够 |

---

## Phase 1：Tool Schema 强化

**改动范围**：`tools.py` + `builder.py`（纯文本改动，零逻辑变更）

### 1.1 search_questions schema

```python
{
    "type": "function",
    "function": {
        "name": "search_questions",
        "description": (
            "从面试题库中搜索相关题目。返回匹配的题目及元数据（分类、难度等）。\n\n"
            "【何时使用】\n"
            "- 用户提交了回答，需要追问题（intent=interview_question, answer_complete=true）\n"
            "- 需要特定技术主题的题目（如「Redis 持久化」「微服务拆分」）\n"
            "- 用户请求练习某类题目（intent=practice_request）\n\n"
            "【何时不用】\n"
            "- 用户在闲聊或还没回答完（intent=chat 或 answer_complete=false）\n"
            "- 已有未使用的检索结果（state.retrieved_questions 非空）\n"
            "- 用户明确要求跳过或换话题\n\n"
            "【参数示例】\n"
            "- 追问项目：keywords=['微服务', '服务拆分', 'DDD'], question_type='project_followup'\n"
            "- 知识探测：keywords=['Redis', '持久化', 'RDB'], question_type='knowledge_probe'\n"
            "- 新话题：keywords=['算法', '动态规划'], question_type='new_question'"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "2-5 个具体技术术语或主题短语。从用户回答或对话上下文中提取。避免泛词如「技术」「问题」「项目」。"
                },
                "question_type": {
                    "type": "string",
                    "enum": ["project_followup", "knowledge_probe", "new_question"],
                    "description": "project_followup: 深挖用户项目回答。knowledge_probe: 探测理论理解。new_question: 切换新话题。"
                }
            },
            "required": ["keywords"]
        }
    }
}
```

### 1.2 draw_questions schema

```python
{
    "type": "function",
    "function": {
        "name": "draw_questions",
        "description": (
            "从题库中加权随机抽取题目。用于需要新鲜题目的场景。\n\n"
            "【何时使用】\n"
            "- search_questions 结果不足或为空时补充\n"
            "- 用户请求「随机出题」「来几道题」\n"
            "- 需要跨话题混合出题\n\n"
            "【何时不用】\n"
            "- 已有未使用的检索结果\n"
            "- 需要特定技术主题的题目（应优先用 search_questions）\n"
            "- 用户在闲聊或还没回答完"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "抽取题目数量，默认 3，最大 5",
                    "default": 3
                },
                "difficulty": {
                    "type": "string",
                    "enum": ["easy", "medium", "hard"],
                    "description": "难度筛选。不指定则根据用户水平自动加权。"
                }
            }
        }
    }
}
```

### 1.3 load_skill schema

```python
{
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": (
            "加载面试技能的完整指导。技能指令将在后续对话中持续生效。\n\n"
            "【何时使用】\n"
            "- 需要切换面试模式（如从普通问答切到项目深挖）\n"
            "- 用户的回答涉及需要特殊追问策略的领域（算法、HR、项目经历）\n"
            "- 当前面试节奏需要调整（如难度过高/过低）\n\n"
            "【何时不用】\n"
            "- 技能已在 active_skills 中（不要重复加载）\n"
            "- 普通知识问答不需要特殊技能\n"
            "- 用户在闲聊"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "skill_name": {
                    "type": "string",
                    "enum": [
                        "adaptive-difficulty",
                        "algorithm-coding",
                        "hr-soft-skills",
                        "interview-rhythm",
                        "project-deep-dive",
                        "theory-qa"
                    ],
                    "description": "要加载的技能名称。各技能用途：\n"
                        "- adaptive-difficulty: 动态调整面试难度\n"
                        "- algorithm-coding: 手撕代码/算法题面试\n"
                        "- hr-soft-skills: HR 行为面试/软技能\n"
                        "- interview-rhythm: 面试节奏控制（始终激活）\n"
                        "- project-deep-dive: 项目经历深度追问\n"
                        "- theory-qa: 技术理论问答"
                }
            },
            "required": ["skill_name"]
        }
    }
}
```

### 1.4 build_skill_catalog() tool guidance 更新

在 `builder.py` 的 `build_skill_catalog()` 中，把当前的通用 guidance 替换为基于场景的具体建议：

```
【工具使用策略】
根据当前对话状态选择合适的工具：

面试追问场景（用户刚回答完一个问题）：
1. 从用户回答中提取技术关键词
2. 调用 search_questions(keywords=[...], question_type='project_followup' 或 'knowledge_probe')
3. 如果需要切换面试类型，先调用 load_skill

新话题/练习请求：
1. 调用 search_questions 获取相关题目
2. 结果不足时用 draw_questions 补充

普通对话/用户还没回答完：
不调用任何工具，直接回复
```

---

## Phase 2：Skill 注入升级

**改动范围**：`tools.py` + `nodes.py` + `state.py`

### 2.1 State 新增字段

```python
# state.py
pending_skill_instructions: list[dict]  # [{"skill_name": str, "instruction": str}]
```

### 2.2 load_skill 执行逻辑变更

```python
# tools.py - execute_tool("load_skill")
async def _execute_load_skill(args, state):
    skill_name = args["skill_name"]

    # 检查是否已激活
    if skill_name in state.get("active_skills", []):
        return json.dumps({"status": "already_active", "skill": skill_name})

    # 加载 skill
    registry = get_agent_skill_registry("chat")
    skill = registry.get(skill_name)
    if not skill:
        return json.dumps({"error": f"Skill not found: {skill_name}"})

    # 标记激活
    state.setdefault("active_skills", []).append(skill_name)

    # 存入 pending，下一轮注入 system prompt
    state.setdefault("pending_skill_instructions", []).append({
        "skill_name": skill_name,
        "instruction": skill.instruction_template,
    })

    # 返回确认信息（不再返回全文）
    return json.dumps({
        "status": "loaded",
        "skill": skill_name,
        "summary": f"技能「{skill.description}」已激活，将在后续对话中生效。",
    })
```

### 2.3 build_react_system_prompt 注入 active skills

在 `nodes.py` 的 `build_react_system_prompt()` 末尾增加：

```python
# 注入已激活的 skill 指令
active_skills = state.get("active_skills", [])
if active_skills:
    registry = get_agent_skill_registry("chat")
    parts.append("\n<active_skill_instructions>")
    for skill_name in active_skills:
        skill = registry.get(skill_name)
        if skill and skill.instruction_template:
            parts.append(f'<skill name="{skill_name}">\n{skill.instruction_template}\n</skill>')
    parts.append("</active_skill_instructions>")
```

### 2.4 清空 pending

在 `_react_loop()` 的每轮迭代开始时，清空 `pending_skill_instructions`（已注入 system prompt）。

---

## Phase 3：Tool 选择策略 + Intent 微调

**改动范围**：`prompts.py` + `nodes.py`

### 3.1 Intent 微调

调整 `INTENT_CLASSIFY_PROMPT` 中 `answer_complete` 的判断标准：

```
answer_complete 判断规则：
- true: 用户明确表示回答完毕（"就这些"、"答完了"、"大概就是这样"）
- true: 用户给出了完整的项目描述或技术方案（有开头有结尾）
- false: 用户只说了几个关键词或片段（"用了 Redis"、"微服务"）
- false: 用户在反问或确认（"你是说...？"、"这样对吗？"）
- false: 用户说"嗯"、"好的"等过渡词（可能是思考中）
```

### 3.2 Tool 策略注入

在 `build_react_system_prompt()` 中，根据 intent + answer_complete 动态生成策略段：

```python
def _build_tool_strategy(state: ChatState) -> str:
    intent = state.get("intent", "chat")
    answer_complete = state.get("answer_complete", False)
    has_retrieved = bool(state.get("retrieved_questions"))

    if intent == "interview_question" and answer_complete and not has_retrieved:
        return (
            "<tool_strategy>\n"
            "当前状态：用户刚回答完面试问题。\n"
            "建议：从用户回答中提取 2-5 个技术关键词，调用 search_questions 检索追问题。\n"
            "如果需要切换面试类型（如从项目深挖转理论），先调用 load_skill。\n"
            "</tool_strategy>"
        )
    elif intent == "interview_question" and not answer_complete:
        return (
            "<tool_strategy>\n"
            "当前状态：用户尚未回答完毕。\n"
            "建议：不调用工具，等待用户完成回答或给出追问引导。\n"
            "</tool_strategy>"
        )
    elif intent == "practice_request":
        return (
            "<tool_strategy>\n"
            "当前状态：用户请求练习。\n"
            "建议：调用 search_questions 检索相关题目，结果不足时用 draw_questions 补充。\n"
            "</tool_strategy>"
        )
    elif intent == "follow_up":
        return (
            "<tool_strategy>\n"
            "当前状态：用户在追问或确认。\n"
            "建议：基于上下文直接回答，如需补充题目再调用 search_questions。\n"
            "</tool_strategy>"
        )
    else:  # chat
        return (
            "<tool_strategy>\n"
            "当前状态：用户在闲聊或过渡。\n"
            "建议：不调用工具，自然回复后引导回面试。\n"
            "</tool_strategy>"
        )
```

### 3.3 策略注入位置

在 `build_react_system_prompt()` 中，tool strategy 放在 skill catalog 之后、basis guidance 之前：

```
...base prompt...
...memory summaries...
...session notes...
...compressed context...
...skill catalog...
{tool_strategy}        ← 新增
...basis guidance...
...active skill instructions...  ← Phase 2
```

---

## 影响分析

| Phase | 改动文件 | 风险 | 回滚方式 |
|-------|---------|------|---------|
| 1 | tools.py, builder.py | 极低（纯文本） | git revert |
| 2 | tools.py, nodes.py, state.py | 低（流程变更但有 fallback） | git revert |
| 3 | prompts.py, nodes.py | 低（prompt 注入） | git revert |

## 测试策略

每个 Phase 独立测试：

- **Phase 1**：单元测试验证 schema 结构完整性，E2E 测试验证 LLM tool 选择准确率
- **Phase 2**：单元测试验证 load_skill 执行逻辑，集成测试验证 system prompt 注入
- **Phase 3**：单元测试验证策略矩阵覆盖，集成测试验证 intent 分类准确率

## 不在范围内

- 新增 tool（如 `end_interview`、`skip_question`）
- 新增 intent 类型
- Tool 调用结果的 rerank 逻辑（已有）
- 前端 UI 变更
