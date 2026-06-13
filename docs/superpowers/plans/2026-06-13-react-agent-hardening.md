# ReAct Agent 生产级加固 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 ReAct 面试 agent 从"能跑"升级到"行为稳定、可解释、可持续优化"——通过强化 tool schema、升级 skill 注入机制、增加 tool 选择策略。

**Architecture:** 三阶段渐进式改动：Phase 1 纯 prompt/schema 文本改动（零逻辑变更）；Phase 2 改 load_skill 执行逻辑 + system prompt 注入；Phase 3 增加基于 intent 的 tool 策略注入 + intent 分类微调。

**Tech Stack:** Python / FastAPI / OpenAI function calling / pytest

**Spec:** `docs/superpowers/specs/2026-06-13-react-agent-hardening-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/app/agents/chat/tools.py` | Modify | Tool schemas (Phase 1) + load_skill 执行逻辑 (Phase 2) |
| `backend/app/agents/shared/skills/builder.py` | Modify | Tool guidance 文本 (Phase 1) + active skill 注入函数 (Phase 2) |
| `backend/app/agents/chat/state.py` | Modify | 新增 `active_skill_instructions` 字段 (Phase 2) |
| `backend/app/agents/chat/nodes.py` | Modify | `build_react_system_prompt` 注入 active skills (Phase 2) + tool strategy (Phase 3) |
| `backend/app/agents/chat/prompts.py` | Modify | `INTENT_CLASSIFY_PROMPT` 微调 (Phase 3) |
| `backend/tests/chat/test_tools.py` | Modify | Phase 1/2 测试 |
| `backend/tests/chat/test_skill_catalog.py` | Modify | Phase 1 测试 |
| `backend/tests/chat/test_react_loop.py` | Modify | Phase 2 集成测试 |

---

## Phase 1: Tool Schema 强化

### Task 1: 更新 search_questions schema

**Files:**
- Modify: `backend/app/agents/chat/tools.py:73-95`
- Test: `backend/tests/chat/test_tools.py`

- [ ] **Step 1: 写失败测试 — search_questions schema 包含 WHEN TO USE/NOT USE**

```python
# tests/chat/test_tools.py — 在 TestExecuteToolSearchQuestions 类之前新增
class TestToolSchemas:
    def test_search_questions_schema_has_when_to_use(self):
        """search_questions description should contain usage guidance."""
        from app.agents.chat.tools import SEARCH_QUESTIONS_SCHEMA

        desc = SEARCH_QUESTIONS_SCHEMA["function"]["description"]
        assert "何时使用" in desc or "WHEN TO USE" in desc
        assert "何时不用" in desc or "WHEN NOT TO USE" in desc

    def test_search_questions_keywords_description_is_specific(self):
        """keywords parameter description should guide against generic terms."""
        from app.agents.chat.tools import SEARCH_QUESTIONS_SCHEMA

        kw_desc = SEARCH_QUESTIONS_SCHEMA["function"]["parameters"]["properties"]["keywords"]["description"]
        assert "2-5" in kw_desc or "具体" in kw_desc

    def test_search_questions_question_type_has_enum_descriptions(self):
        """question_type description should explain each enum value."""
        from app.agents.chat.tools import SEARCH_QUESTIONS_SCHEMA

        qt_desc = SEARCH_QUESTIONS_SCHEMA["function"]["parameters"]["properties"]["question_type"]["description"]
        assert "project_followup" in qt_desc
        assert "knowledge_probe" in qt_desc
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose exec backend pytest backend/tests/chat/test_tools.py::TestToolSchemas -v`
Expected: FAIL（当前 description 只有一句话，不含"何时使用"）

- [ ] **Step 3: 更新 search_questions schema**

替换 `tools.py:73-95` 的 `SEARCH_QUESTIONS_SCHEMA`：

```python
SEARCH_QUESTIONS_SCHEMA = {
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
            "- 已有未使用的检索结果（retrieved_questions 非空）\n"
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
                    "description": "2-5 个具体技术术语或主题短语。从用户回答或对话上下文中提取。避免泛词如「技术」「问题」「项目」。",
                },
                "question_type": {
                    "type": "string",
                    "enum": ["project_followup", "knowledge_probe", "new_question"],
                    "description": "project_followup: 深挖用户项目回答。knowledge_probe: 探测理论理解。new_question: 切换新话题。",
                },
            },
            "required": ["keywords"],
        },
    },
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose exec backend pytest backend/tests/chat/test_tools.py::TestToolSchemas -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/chat/tools.py backend/tests/chat/test_tools.py
git commit -m "feat(chat): strengthen search_questions tool schema with usage guidance"
```

---

### Task 2: 更新 draw_questions schema

**Files:**
- Modify: `backend/app/agents/chat/tools.py:97-117`
- Test: `backend/tests/chat/test_tools.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/chat/test_tools.py — TestToolSchemas 类中追加
    def test_draw_questions_schema_has_when_to_use(self):
        """draw_questions description should contain usage guidance."""
        from app.agents.chat.tools import DRAW_QUESTIONS_SCHEMA

        desc = DRAW_QUESTIONS_SCHEMA["function"]["description"]
        assert "何时使用" in desc or "WHEN TO USE" in desc
        assert "何时不用" in desc or "WHEN NOT TO USE" in desc

    def test_draw_questions_count_has_default_description(self):
        """count parameter should mention default value."""
        from app.agents.chat.tools import DRAW_QUESTIONS_SCHEMA

        count_desc = DRAW_QUESTIONS_SCHEMA["function"]["parameters"]["properties"]["count"]["description"]
        assert "默认" in count_desc or "default" in count_desc.lower()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose exec backend pytest backend/tests/chat/test_tools.py::TestToolSchemas::test_draw_questions_schema_has_when_to_use -v`
Expected: FAIL

- [ ] **Step 3: 更新 draw_questions schema**

替换 `tools.py:97-117` 的 `DRAW_QUESTIONS_SCHEMA`：

```python
DRAW_QUESTIONS_SCHEMA = {
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
                    "default": 3,
                },
                "difficulty": {
                    "type": "string",
                    "enum": ["easy", "medium", "hard"],
                    "description": "难度筛选。不指定则根据用户水平自动加权。",
                },
            },
        },
    },
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose exec backend pytest backend/tests/chat/test_tools.py::TestToolSchemas -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/chat/tools.py backend/tests/chat/test_tools.py
git commit -m "feat(chat): strengthen draw_questions tool schema with usage guidance"
```

---

### Task 3: 更新 load_skill schema

**Files:**
- Modify: `backend/app/agents/chat/tools.py:54-71`
- Test: `backend/tests/chat/test_tools.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/chat/test_tools.py — TestToolSchemas 类中追加
    def test_load_skill_schema_has_usage_guidance(self):
        """load_skill description should explain when to use and when not to."""
        from app.agents.chat.tools import LOAD_SKILL_SCHEMA

        desc = LOAD_SKILL_SCHEMA["function"]["description"]
        assert "何时使用" in desc or "WHEN TO USE" in desc
        assert "何时不用" in desc or "WHEN NOT TO USE" in desc

    def test_load_skill_enum_descriptions(self):
        """skill_name description should list all skills with their purposes."""
        from app.agents.chat.tools import LOAD_SKILL_SCHEMA

        skill_desc = LOAD_SKILL_SCHEMA["function"]["parameters"]["properties"]["skill_name"]["description"]
        assert "project-deep-dive" in skill_desc
        assert "algorithm-coding" in skill_desc
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose exec backend pytest backend/tests/chat/test_tools.py::TestToolSchemas::test_load_skill_schema_has_usage_guidance -v`
Expected: FAIL

- [ ] **Step 3: 更新 load_skill schema**

替换 `tools.py:54-71` 的 `LOAD_SKILL_SCHEMA`：

```python
LOAD_SKILL_SCHEMA = {
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
                    "enum": SKILL_NAMES,
                    "description": (
                        "要加载的技能名称。各技能用途：\n"
                        "- adaptive-difficulty: 动态调整面试难度\n"
                        "- algorithm-coding: 手撕代码/算法题面试\n"
                        "- hr-soft-skills: HR 行为面试/软技能\n"
                        "- interview-rhythm: 面试节奏控制（始终激活）\n"
                        "- project-deep-dive: 项目经历深度追问\n"
                        "- theory-qa: 技术理论问答"
                    ),
                },
            },
            "required": ["skill_name"],
        },
    },
}
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose exec backend pytest backend/tests/chat/test_tools.py::TestToolSchemas -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/chat/tools.py backend/tests/chat/test_tools.py
git commit -m "feat(chat): strengthen load_skill tool schema with usage guidance"
```

---

### Task 4: 更新 build_skill_catalog tool guidance

**Files:**
- Modify: `backend/app/agents/shared/skills/builder.py:71-92`
- Test: `backend/tests/chat/test_skill_catalog.py`

- [ ] **Step 1: 写失败测试 — catalog 包含场景化 tool 建议**

```python
# tests/chat/test_skill_catalog.py — 追加
    def test_catalog_has_scene_based_tool_guidance(self):
        """catalog should provide scene-based tool usage suggestions."""
        from app.agents.shared.skills.builder import build_skill_catalog

        catalog = build_skill_catalog()
        # 应该包含基于场景的建议，而不是泛泛的"请自主判断"
        assert "面试追问" in catalog or "追问题" in catalog
        assert "新话题" in catalog or "练习请求" in catalog
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose exec backend pytest backend/tests/chat/test_skill_catalog.py::TestBuildSkillCatalog::test_catalog_has_scene_based_tool_guidance -v`
Expected: FAIL（当前 guidance 只有"请根据用户的提问内容自主决定"）

- [ ] **Step 3: 更新 build_skill_catalog tool guidance**

替换 `builder.py:71-92` 的 `lines.extend(...)` 块：

```python
    lines.extend([
        "",
        "根据面试话题选择最相关的技能加载。一次可以加载多个。",
        "",
        "## 工具使用策略",
        "",
        "根据当前对话状态选择合适的工具：",
        "",
        "### 面试追问场景（用户刚回答完一个问题）",
        "1. 从用户回答中提取技术关键词",
        "2. 调用 search_questions(keywords=[...], question_type='project_followup' 或 'knowledge_probe')",
        "3. 如果需要切换面试类型，先调用 load_skill",
        "",
        "### 新话题/练习请求",
        "1. 调用 search_questions 获取相关题目",
        "2. 结果不足时用 draw_questions 补充",
        "",
        "### 普通对话/用户还没回答完",
        "不调用任何工具，直接回复",
        "",
        "重要边界：技能名和工具名是内部控制信号，只能用于 tool calling；不得把 "
        "project-deep-dive、load_skill 等名称作为最终回复正文输出。",
        "最终回复必须是面试官直接对候选人说的话。",
        "",
        "如果不调用任何工具，你将直接生成回答。",
    ])
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose exec backend pytest backend/tests/chat/test_skill_catalog.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/shared/skills/builder.py backend/tests/chat/test_skill_catalog.py
git commit -m "feat(chat): update skill catalog with scene-based tool usage guidance"
```

---

## Phase 2: Skill 注入升级

### Task 5: State 新增 active_skill_instructions 字段

**Files:**
- Modify: `backend/app/agents/chat/state.py:77-78`

- [ ] **Step 1: 写失败测试**

```python
# tests/chat/test_tools.py — 新增测试类
class TestLoadSkillStateInjection:
    async def test_load_skill_stores_instruction_in_state(self, sample_state):
        """load_skill should store instruction in state for system prompt injection."""
        from app.agents.chat.tools import execute_tool

        sample_skill = MagicMock()
        sample_skill.name = "theory-qa"
        sample_skill.description = "理论问答策略"
        sample_skill.get_instruction.return_value = "## Theory QA full instruction"

        tool_call = {
            "function": {
                "name": "load_skill",
                "arguments": json.dumps({"skill_name": "theory-qa"}),
            }
        }

        mock_registry = MagicMock()
        mock_registry.get.return_value = sample_skill

        with patch("app.agents.chat.tools._get_skill_registry", return_value=mock_registry):
            result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        # 新行为：返回确认信息，不返回全文
        assert parsed["status"] == "loaded"
        assert parsed["skill"] == "theory-qa"
        assert "instruction" not in parsed

        # 指令存入 state
        assert "active_skill_instructions" in sample_state
        assert len(sample_state["active_skill_instructions"]) == 1
        assert sample_state["active_skill_instructions"][0]["skill_name"] == "theory-qa"
        assert sample_state["active_skill_instructions"][0]["instruction"] == "## Theory QA full instruction"

    async def test_load_skill_already_active_returns_already_active(self, sample_state):
        """load_skill should return already_active if skill is already loaded."""
        from app.agents.chat.tools import execute_tool

        sample_state["active_skills"] = ["theory-qa"]

        tool_call = {
            "function": {
                "name": "load_skill",
                "arguments": json.dumps({"skill_name": "theory-qa"}),
            }
        }

        mock_registry = MagicMock()
        sample_skill = MagicMock()
        sample_skill.get_instruction.return_value = "instruction"
        mock_registry.get.return_value = sample_skill

        with patch("app.agents.chat.tools._get_skill_registry", return_value=mock_registry):
            result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert parsed["status"] == "already_active"
        assert "active_skill_instructions" not in sample_state or sample_state.get("active_skill_instructions") == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose exec backend pytest backend/tests/chat/test_tools.py::TestLoadSkillStateInjection -v`
Expected: FAIL（当前 load_skill 返回 `{"instruction": ...}`，不存 state）

- [ ] **Step 3: 在 state.py 新增字段**

在 `state.py:78`（`active_skills` 之后）新增：

```python
    active_skill_instructions: list[dict]  # [{"skill_name": str, "instruction": str}] 待注入 system prompt
```

- [ ] **Step 4: Commit state 变更**

```bash
git add backend/app/agents/chat/state.py
git commit -m "feat(chat): add active_skill_instructions field to ChatState"
```

---

### Task 6: 修改 load_skill 执行逻辑

**Files:**
- Modify: `backend/app/agents/chat/tools.py:180-193`

- [ ] **Step 1: 运行 Task 5 的测试确认仍然失败**

Run: `docker compose exec backend pytest backend/tests/chat/test_tools.py::TestLoadSkillStateInjection -v`
Expected: FAIL（state 字段有了但执行逻辑没改）

- [ ] **Step 2: 修改 _execute_load_skill**

替换 `tools.py:180-193`：

```python
def _execute_load_skill(args: dict, state: ChatState) -> str:
    """Load a skill's instruction, store in state for system prompt injection."""
    skill_name = args.get("skill_name", "")
    registry = _get_skill_registry()
    skill = registry.get(skill_name)

    if skill is None:
        return json.dumps({"error": f"Unknown skill: {skill_name}"})

    # Already active — skip
    active_skills = state.setdefault("active_skills", [])
    if skill_name in active_skills:
        return json.dumps({"status": "already_active", "skill": skill_name})

    # Mark active
    active_skills.append(skill_name)

    # Store instruction for system prompt injection (not as tool result)
    instruction = skill.get_instruction()
    if instruction:
        state.setdefault("active_skill_instructions", []).append({
            "skill_name": skill_name,
            "instruction": instruction,
        })

    return json.dumps({
        "status": "loaded",
        "skill": skill_name,
        "summary": f"技能「{skill.description}」已激活，将在后续对话中生效。",
    })
```

- [ ] **Step 3: 运行测试确认通过**

Run: `docker compose exec backend pytest backend/tests/chat/test_tools.py::TestLoadSkillStateInjection -v`
Expected: PASS

- [ ] **Step 4: 运行所有 tools 测试确认无回归**

Run: `docker compose exec backend pytest backend/tests/chat/test_tools.py -v`
Expected: PASS（注意：旧测试 `test_load_skill_returns_instruction` 需要更新断言）

- [ ] **Step 5: 更新旧测试断言**

`test_tools.py` 中 `TestExecuteToolLoadSkill.test_load_skill_returns_instruction` 需要改为验证新行为：

```python
    async def test_load_skill_returns_confirmation(self, sample_state, sample_skill):
        """load_skill should return confirmation with status, not full instruction."""
        from app.agents.chat.tools import execute_tool

        tool_call = {
            "function": {
                "name": "load_skill",
                "arguments": json.dumps({"skill_name": "theory-qa"}),
            }
        }

        mock_registry = MagicMock()
        mock_registry.get.return_value = sample_skill

        with patch("app.agents.chat.tools._get_skill_registry", return_value=mock_registry):
            result = await execute_tool(tool_call, sample_state)

        parsed = json.loads(result)
        assert parsed["status"] == "loaded"
        assert parsed["skill"] == "theory-qa"
        assert "summary" in parsed
        assert "instruction" not in parsed  # 全文不再通过 tool result 返回
```

同时更新 `sample_skill` fixture 加上 `description` 属性：

```python
@pytest.fixture
def sample_skill():
    """A mock Skill object."""
    skill = MagicMock()
    skill.name = "theory-qa"
    skill.description = "理论问答策略"
    skill.get_instruction.return_value = "## Theory QA Instruction\n\nAsk theory questions."
    return skill
```

- [ ] **Step 6: 运行全部 tools 测试**

Run: `docker compose exec backend pytest backend/tests/chat/test_tools.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/agents/chat/tools.py backend/tests/chat/test_tools.py
git commit -m "feat(chat): load_skill stores instruction in state, returns confirmation"
```

---

### Task 7: build_react_system_prompt 注入 active skill 指令

**Files:**
- Modify: `backend/app/agents/chat/nodes.py:1560-1624`
- Test: `backend/tests/chat/test_react_loop.py`

- [ ] **Step 1: 写失败测试 — system prompt 包含 active skill 指令**

```python
# tests/chat/test_react_loop.py — 追加
class TestBuildReactSystemPrompt:
    def test_injects_active_skill_instructions(self):
        """build_react_system_prompt should inject active skill instructions."""
        from app.agents.chat.nodes import build_react_system_prompt

        state = {
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": ["theory-qa"],
            "active_skill_instructions": [
                {"skill_name": "theory-qa", "instruction": "## Theory QA\nAsk deep theory questions."},
            ],
        }

        prompt = build_react_system_prompt(state)
        assert "<active_skill_instructions>" in prompt
        assert "Theory QA" in prompt
        assert "Ask deep theory questions." in prompt

    def test_no_active_skills_no_injection(self):
        """build_react_system_prompt should not inject when no active skills."""
        from app.agents.chat.nodes import build_react_system_prompt

        state = {
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": [],
        }

        prompt = build_react_system_prompt(state)
        assert "<active_skill_instructions>" not in prompt
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose exec backend pytest backend/tests/chat/test_react_loop.py::TestBuildReactSystemPrompt -v`
Expected: FAIL（当前 build_react_system_prompt 不注入 active skill 指令）

- [ ] **Step 3: 修改 build_react_system_prompt**

在 `nodes.py:1620`（Layer 6 basis guidance 之前）插入新 Layer：

```python
    # Layer 5.5: Active skill instructions (injected from load_skill tool results)
    active_skill_instructions = state.get("active_skill_instructions", [])
    if active_skill_instructions:
        skill_parts = []
        for item in active_skill_instructions:
            name = item.get("skill_name", "")
            instruction = item.get("instruction", "")
            if instruction:
                skill_parts.append(f'<skill name="{name}">\n{instruction}\n</skill>')
        if skill_parts:
            parts.append(
                "<active_skill_instructions>\n"
                + "\n\n".join(skill_parts)
                + "\n</active_skill_instructions>"
            )
```

同时需要在 `_react_loop` 中，每轮 ReAct 迭代开始时清空 `active_skill_instructions`（因为已注入 system prompt）。在 `pipeline.py` 的 `_react_loop` 函数中，在 `for step in range(MAX_REACT_STEPS):` 循环体内、`llm_with_tools` 调用之前，重建 system prompt：

```python
    for step in range(MAX_REACT_STEPS):
        react_step = step + 1

        # Rebuild system prompt if skills were loaded in previous step
        if step > 0 and state.get("active_skill_instructions"):
            system_prompt = build_react_system_prompt(state)
            messages[0] = {"role": "system", "content": system_prompt}
            state["active_skill_instructions"] = []  # consumed

        llm_started = time.monotonic()
        ...（后续代码不变）
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose exec backend pytest backend/tests/chat/test_react_loop.py::TestBuildReactSystemPrompt -v`
Expected: PASS

- [ ] **Step 5: 运行所有 react_loop 测试确认无回归**

Run: `docker compose exec backend pytest backend/tests/chat/test_react_loop.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/chat/nodes.py backend/app/agents/chat/pipeline.py backend/tests/chat/test_react_loop.py
git commit -m "feat(chat): inject active skill instructions into system prompt"
```

---

## Phase 3: Tool 选择策略 + Intent 微调

### Task 8: 新增 _build_tool_strategy 函数

**Files:**
- Modify: `backend/app/agents/chat/nodes.py`
- Test: `backend/tests/chat/test_react_loop.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/chat/test_react_loop.py — 追加
class TestBuildToolStrategy:
    def test_interview_question_answer_complete_suggests_search(self):
        """Should suggest search_questions when user completed their answer."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "interview_question", "answer_complete": True, "retrieved_questions": []}
        strategy = _build_tool_strategy(state)
        assert "search_questions" in strategy
        assert "追问题" in strategy or "检索" in strategy

    def test_interview_question_answer_incomplete_suggests_wait(self):
        """Should suggest waiting when user hasn't finished answering."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "interview_question", "answer_complete": False}
        strategy = _build_tool_strategy(state)
        assert "不调用工具" in strategy or "等待" in strategy

    def test_practice_request_suggests_search_and_draw(self):
        """Should suggest search + draw for practice requests."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "practice_request", "answer_complete": False}
        strategy = _build_tool_strategy(state)
        assert "search_questions" in strategy

    def test_chat_suggests_no_tools(self):
        """Should suggest no tools for casual chat."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "chat", "answer_complete": False}
        strategy = _build_tool_strategy(state)
        assert "不调用工具" in strategy

    def test_follow_up_suggests_contextual_answer(self):
        """Should suggest contextual answer for follow-ups."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "follow_up", "answer_complete": False}
        strategy = _build_tool_strategy(state)
        assert "上下文" in strategy or "直接回答" in strategy

    def test_already_retrieved_suggests_no_search(self):
        """Should not suggest search when retrieved_questions is non-empty."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "interview_question", "answer_complete": True, "retrieved_questions": [{"id": 1}]}
        strategy = _build_tool_strategy(state)
        assert "search_questions" not in strategy
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose exec backend pytest backend/tests/chat/test_react_loop.py::TestBuildToolStrategy -v`
Expected: FAIL（`_build_tool_strategy` 不存在）

- [ ] **Step 3: 实现 _build_tool_strategy**

在 `nodes.py` 的 `build_react_system_prompt` 函数之前新增：

```python
def _build_tool_strategy(state: ChatState) -> str:
    """Build tool usage strategy guidance based on current intent and state."""
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
    elif intent == "interview_question" and answer_complete and has_retrieved:
        return (
            "<tool_strategy>\n"
            "当前状态：用户回答完毕，已有检索结果。\n"
            "建议：直接使用已检索的题目进行追问，无需再次检索。\n"
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

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose exec backend pytest backend/tests/chat/test_react_loop.py::TestBuildToolStrategy -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/chat/nodes.py backend/tests/chat/test_react_loop.py
git commit -m "feat(chat): add _build_tool_strategy for intent-based tool guidance"
```

---

### Task 9: 将 tool strategy 注入 build_react_system_prompt

**Files:**
- Modify: `backend/app/agents/chat/nodes.py:1560-1624`

- [ ] **Step 1: 写失败测试**

```python
# tests/chat/test_react_loop.py — TestBuildReactSystemPrompt 类中追加
    def test_injects_tool_strategy(self):
        """build_react_system_prompt should inject tool strategy based on intent."""
        from app.agents.chat.nodes import build_react_system_prompt

        state = {
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": [],
            "intent": "interview_question",
            "answer_complete": True,
            "retrieved_questions": [],
        }

        prompt = build_react_system_prompt(state)
        assert "<tool_strategy>" in prompt
        assert "search_questions" in prompt

    def test_no_tool_strategy_for_chat(self):
        """build_react_system_prompt should inject no-tools strategy for chat."""
        from app.agents.chat.nodes import build_react_system_prompt

        state = {
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": [],
            "intent": "chat",
            "answer_complete": False,
        }

        prompt = build_react_system_prompt(state)
        assert "<tool_strategy>" in prompt
        assert "不调用工具" in prompt
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose exec backend pytest backend/tests/chat/test_react_loop.py::TestBuildReactSystemPrompt::test_injects_tool_strategy -v`
Expected: FAIL

- [ ] **Step 3: 在 build_react_system_prompt 中注入 tool strategy**

在 `nodes.py` 的 `build_react_system_prompt` 中，Layer 5（skill catalog）之后、Layer 5.5（active skills）之前插入：

```python
    # Layer 5.25: Tool strategy (intent-based guidance)
    tool_strategy = _build_tool_strategy(state)
    if tool_strategy:
        parts.append(tool_strategy)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose exec backend pytest backend/tests/chat/test_react_loop.py::TestBuildReactSystemPrompt -v`
Expected: PASS

- [ ] **Step 5: 运行所有 react_loop 测试确认无回归**

Run: `docker compose exec backend pytest backend/tests/chat/test_react_loop.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/chat/nodes.py backend/tests/chat/test_react_loop.py
git commit -m "feat(chat): inject intent-based tool strategy into system prompt"
```

---

### Task 10: 微调意图分类 Prompt

**Files:**
- Modify: `backend/app/agents/chat/prompts.py:141-155`
- Modify: `backend/app/services/memory_recall_service.py`（`INTENT_AND_MEMORY_PROMPT` 中的 `answer_complete` 判断标准）

**背景**：主分类路径使用 `classify_and_recall`，它调用 `INTENT_AND_MEMORY_PROMPT`（返回 JSON 含 `intent` + `answer_complete`）。`INTENT_CLASSIFY_PROMPT` 只在 fallback 路径 `_classify_intent_only` 中使用（返回纯文本类别名）。两者都需要更新 `answer_complete` 判断标准。

- [ ] **Step 1: 更新 INTENT_CLASSIFY_PROMPT（fallback 路径）**

替换 `prompts.py:141-155` 的 `INTENT_CLASSIFY_PROMPT`：

```python
INTENT_CLASSIFY_PROMPT = """分析用户的最新消息，判断其意图类别。

## 类别定义
- interview_question: 用户在回答面试问题或给出答案
- practice_request: 用户请求开始练习或切换题目（如"给我出一道XX题"、"换个话题"）
- chat: 用户在闲聊、打招呼、或问非面试相关的问题
- follow_up: 用户在追问上一个问题的细节（如"能再解释一下吗"、"具体怎么实现"）

## answer_complete 判断参考
同时判断用户回答是否完整：
- 完整: 用户明确表示回答完毕（"就这些"、"答完了"）、给出了完整方案（有开头有结尾）
- 不完整: 只说了关键词片段（"用了 Redis"）、在反问确认（"这样对吗？"）、过渡词（"嗯"、"好的"）

## 用户消息
{user_message}

## 最近对话
{recent_context}

请只返回一个类别名称，不要返回其他内容。"""
```

- [ ] **Step 2: 更新 INTENT_AND_MEMORY_PROMPT 中的 answer_complete 判断标准**

读取 `memory_recall_service.py` 中 `INTENT_AND_MEMORY_PROMPT` 的内容（约 line 370），找到 `answer_complete` 相关的说明文字，在其中加入更明确的判断标准：

```
answer_complete 判断标准：
- true: 用户明确表示回答完毕（"就这些"、"答完了"、"大概就是这样"）
- true: 用户给出了完整的项目描述或技术方案（有开头有结尾，超过 20 字）
- false: 用户只说了几个关键词或片段（"用了 Redis"、"微服务"）
- false: 用户在反问或确认（"你是说...？"、"这样对吗？"）
- false: 用户说"嗯"、"好的"等过渡词（可能是思考中）
```

将这段标准插入到 `INTENT_AND_MEMORY_PROMPT` 中 `answer_complete` 字段的说明处。

- [ ] **Step 3: 运行相关测试**

Run: `docker compose exec backend pytest backend/tests/chat/ -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/agents/chat/prompts.py backend/app/services/memory_recall_service.py
git commit -m "feat(chat): improve answer_complete judgment criteria in classification prompts"
```

---

### Task 11: 端到端验证 + 清理

**Files:**
- Test: `backend/tests/chat/test_react_loop.py`

- [ ] **Step 1: 写端到端集成测试 — skill 注入 + tool strategy 联动**

```python
# tests/chat/test_react_loop.py — TestReactLoopIntegration 类中追加
    async def test_load_skill_injects_into_next_system_prompt(self, base_state):
        """After load_skill, next system prompt should contain the skill instruction."""
        from app.agents.chat.pipeline import _react_loop

        base_state["intent"] = "interview_question"
        base_state["answer_complete"] = True

        # Step 1: load_skill
        step1 = {
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "function": {
                    "name": "load_skill",
                    "arguments": json.dumps({"skill_name": "project-deep-dive"}),
                },
            }],
            "finish_reason": "tool_calls",
        }

        # Step 2: answer (LLM should see skill instruction in system prompt)
        step2 = {
            "content": "请详细说说你在项目中遇到的最大技术挑战。",
            "tool_calls": None,
            "finish_reason": "stop",
        }

        call_count = 0
        captured_messages = []

        async def mock_llm(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # Capture messages sent to LLM on second call
            if call_count == 2:
                captured_messages.extend(args[0] if args else kwargs.get("messages", []))
            return [step1, step2][call_count - 1]

        mock_skill = MagicMock()
        mock_skill.name = "project-deep-dive"
        mock_skill.description = "项目深挖策略"
        mock_skill.get_instruction.return_value = "## Project Deep Dive\nDrill down 4 layers."

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_skill

        emitted: list[dict] = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)

        token = _event_queue_var.set(mock_queue)
        try:
            with (
                patch("app.agents.chat.pipeline.build_react_system_prompt") as mock_build_prompt,
                patch("app.agents.chat.pipeline.llm_with_tools", side_effect=mock_llm),
                patch("app.agents.chat.pipeline.execute_tool", new_callable=AsyncMock, return_value='{"status": "loaded", "skill": "project-deep-dive", "summary": "ok"}'),
                patch("app.agents.chat.pipeline.stream_llm_messages", side_effect=lambda *a, **kw: _mock_stream_strings("answer")),
                patch("app.agents.chat.tools._get_skill_registry", return_value=mock_registry),
            ):
                # First call returns base prompt, second call should include skill
                mock_build_prompt.side_effect = [
                    "Base prompt.",
                    "Base prompt.\n<active_skill_instructions>\n<skill name=\"project-deep-dive\">\n## Project Deep Dive\nDrill down 4 layers.\n</skill>\n</active_skill_instructions>",
                ]
                collected = []
                async for event in _react_loop(base_state):
                    collected.append(event)
        finally:
            _event_queue_var.reset(token)

        # build_react_system_prompt called twice (initial + after skill load)
        assert mock_build_prompt.call_count == 2
```

- [ ] **Step 2: 运行所有 chat 测试**

Run: `docker compose exec backend pytest backend/tests/chat/ -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/chat/test_react_loop.py
git commit -m "test(chat): add integration test for skill injection + tool strategy"
```

- [ ] **Step 4: 运行完整后端测试套件确认无回归**

Run: `docker compose exec backend pytest backend/tests/ -q`
Expected: PASS

- [ ] **Step 5: 最终 Commit（如有遗漏）**

```bash
git add -A
git commit -m "feat(chat): ReAct agent production hardening — schema + skill injection + tool strategy"
```
