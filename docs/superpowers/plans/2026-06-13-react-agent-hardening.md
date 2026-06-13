# ReAct Agent 生产级加固 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 ReAct 面试 agent 从"能跑"升级到"行为稳定、可解释、可持续优化"——通过强化 tool schema、升级 skill 注入机制、增加 tool 选择策略。

**Architecture:** 四阶段渐进式改动：Phase 1 纯 prompt/schema 文本改动（零逻辑变更）；Phase 2 改 load_skill 执行逻辑 + 当前 ReAct loop 内 system prompt 注入（不跨会话）；Phase 2.5 持久化 active skill names 到 conversation metadata，并在下一轮从 registry 重新加载指令；Phase 3 增加 answer_complete heuristic + 基于 intent 的 tool 策略注入。

**Tech Stack:** Python / FastAPI / OpenAI function calling / pytest

**Spec:** `docs/superpowers/specs/2026-06-13-react-agent-hardening-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/app/agents/chat/tools.py` | Modify | Tool schemas (Phase 1) + load_skill 执行逻辑 (Phase 2) |
| `backend/app/agents/shared/skills/builder.py` | Modify | Tool guidance 文本 (Phase 1) |
| `backend/app/agents/chat/state.py` | Modify | 新增 `active_skill_instructions` 字段（当前 ReAct loop 待注入指令，不做跨轮持久化） |
| `backend/app/agents/chat/nodes.py` | Modify | `build_react_system_prompt` 注入 active skills (Phase 2) + tool strategy (Phase 3) |
| `backend/app/agents/chat/pipeline.py` | Modify | ReAct loop 重建 system prompt (Phase 2) + 持久化 (Phase 2.5) |
| `backend/app/agents/chat/prompts.py` | Modify | `INTENT_CLASSIFY_PROMPT` 微调 (Phase 3) |
| `backend/app/services/memory_recall_service.py` | Modify | `answer_complete` heuristic (Phase 3) |
| `backend/app/services/chat_service.py` | Modify | conversation metadata 读写 (Phase 2.5) |
| `backend/tests/chat/test_tools.py` | Modify | Phase 1/2 测试 |
| `backend/tests/chat/test_skill_catalog.py` | Modify | Phase 1 测试 |
| `backend/tests/chat/test_react_loop.py` | Modify | Phase 2/3 集成测试 |
| `backend/tests/chat/test_react_e2e.py` | Modify | 真实链路端到端测试 (Phase 验证) |

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

    def test_search_questions_schema_explains_result_usage(self):
        """search_questions description should tell the model how to use returned questions."""
        from app.agents.chat.tools import SEARCH_QUESTIONS_SCHEMA

        desc = SEARCH_QUESTIONS_SCHEMA["function"]["description"]
        assert "如何使用返回结果" in desc
        assert "top 3" in desc
        assert "不要机械复述" in desc
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
            "- 新话题：keywords=['算法', '动态规划'], question_type='new_question'\n\n"
            "【如何使用返回结果】\n"
            "- 工具返回 top 3 候选题。选择最贴近当前对话的一题，改写成自然的面试官追问。\n"
            "- 不要机械复述题库原文；要结合候选人刚才的回答承接发问。\n"
            "- 如果结果和当前回答不匹配，可以忽略检索结果并直接追问。"
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
            "加载面试技能的完整指导。技能指令将注入到当前对话的系统提示中。\n\n"
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

## Phase 2: Skill 注入升级（当前 ReAct loop 内）

> 注意：Phase 2 只保证当前 ReAct loop 内的 system prompt 注入。跨轮持久化见 Phase 2.5。

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
    active_skill_instructions: list[dict]  # [{"skill_name": str, "instruction": str}] 当前 ReAct loop 待注入 system prompt；跨轮只持久化 skill_name
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
    """Load a skill's instruction, store as current-loop pending system prompt injection."""
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

    # Store instruction for current-loop system prompt injection (not as tool result)
    instruction = skill.get_instruction()
    if instruction:
        state.setdefault("active_skill_instructions", []).append({
            "skill_name": skill_name,
            "instruction": instruction,
        })

    return json.dumps({
        "status": "loaded",
        "skill": skill_name,
        "summary": f"技能「{skill.description}」已激活，将注入到当前 ReAct loop 的系统提示中。",
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
    # Layer 5.5: Active skill instructions (current-loop pending instructions)
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

## Phase 2.5: 持久化 active skill names 到 conversation metadata

> Phase 2 只在当前 ReAct loop 内注入 skill。Phase 2.5 让 active skill names 跨轮持久化——用户下一次发消息时，根据 skill name 从 registry 重新加载最新指令并注入 system prompt。不要把完整 skill instruction 长期写入 conversation metadata。

### Task 7.5: 持久化 active skill names + 跨轮恢复

**Files:**
- Modify: `backend/app/agents/chat/pipeline.py`（`run_chat` 结束时持久化 active skill names）
- Modify: `backend/app/agents/chat/nodes.py`（`_step_load_context` 恢复 active skill names 并从 registry 加载指令）
- Modify: `backend/app/services/chat_service.py`（conversation metadata 读写）
- Test: `backend/tests/chat/test_react_loop.py`

**背景**：当前 `active_skills` 只存在于内存中的 `ChatState`。一轮对话结束后，下一轮重新初始化 state，active_skills 丢失。需要：
1. 在 `run_chat` 结束时，只把 `active_skill_names` 写入 conversation metadata
2. 在 `_step_load_context` 时，从 conversation metadata 恢复 skill names，并从 skill registry 重新加载最新 skill 指令

- [ ] **Step 1: 写失败测试 — 从 metadata 中的 skill names 跨轮恢复 active_skills**

```python
# tests/chat/test_react_loop.py — 新增
class TestActiveSkillsPersistence:
    def test_restore_active_skills_loads_latest_instruction_from_registry(self):
        """Restoring from metadata should load latest skill instructions by name."""
        from app.agents.chat.nodes import _restore_active_skills_from_metadata

        state = {}
        metadata = {"active_skill_names": ["project-deep-dive"]}

        mock_skill = MagicMock()
        mock_skill.get_instruction.return_value = "## Project Deep Dive\nLatest instruction."
        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_skill

        _restore_active_skills_from_metadata(state, metadata, registry=mock_registry)

        assert state["active_skills"] == ["project-deep-dive"]
        assert state["active_skill_instructions"] == [
            {"skill_name": "project-deep-dive", "instruction": "## Project Deep Dive\nLatest instruction."}
        ]
        mock_registry.get.assert_called_once_with("project-deep-dive")
```

- [ ] **Step 2: 运行测试确认失败或通过**

Run: `docker compose exec backend pytest backend/tests/chat/test_react_loop.py::TestActiveSkillsPersistence -v`
Expected: FAIL（`_restore_active_skills_from_metadata` 不存在）

- [ ] **Step 3: 在 run_chat 结束时持久化 active skill names**

在 `pipeline.py` 的 `_run_pipeline()` 中，response 保存之后、记忆提取之前，加入持久化逻辑：

```python
            state["response"] = response
            state["metadata"] = metadata

            # 持久化 active skill names 到 conversation metadata
            if state.get("active_skills"):
                await _persist_active_skills(state)

            # 后台记忆提取
            asyncio.create_task(_step_extract_memory(dict(state)))
```

新增 `_persist_active_skills` 函数：

```python
async def _persist_active_skills(state: ChatState) -> None:
    """Persist active skill names to conversation metadata for cross-round recovery."""
    try:
        conversation_id = state.get("conversation_id")
        if not conversation_id:
            return
        active_skills = state.get("active_skills", [])
        if not active_skills:
            return
        # 只保存 skill names；下一轮从 registry 重新加载最新 instruction
        await asyncio.to_thread(
            chat_service.update_conversation_metadata,
            conversation_id,
            {"active_skill_names": active_skills},
        )
    except Exception:
        logger.exception("Failed to persist active_skills")
```

- [ ] **Step 4: 在 nodes.py 新增恢复 helper，并在 _step_load_context 调用**

在 `nodes.py` 新增 helper，读取 conversation metadata 并恢复：

```python
def _restore_active_skills_from_metadata(
    state: ChatState,
    metadata: dict,
    registry=None,
) -> None:
    """Restore active skills from persisted names and load latest instructions."""
    persisted_skill_names = metadata.get("active_skill_names", [])
    if not persisted_skill_names:
        return
    if registry is None:
        from app.agents.chat.skills import get_default_registry

        registry = get_default_registry()
    restored_instructions = []
    valid_skill_names = []
    for name in persisted_skill_names:
        skill = registry.get(name)
        if not skill:
            continue
        valid_skill_names.append(name)
        instruction = skill.get_instruction()
        if instruction:
            restored_instructions.append({"skill_name": name, "instruction": instruction})
    state["active_skills"] = valid_skill_names
    state["active_skill_instructions"] = restored_instructions
```

然后在 `_step_load_context` 或相关上下文加载函数中，读取 conversation metadata 后调用：

```python
_restore_active_skills_from_metadata(state, conversation.get("metadata", {}) or {})
```

- [ ] **Step 5: 检查 chat_service 是否有 metadata 读写接口**

如果 `chat_service.update_conversation_metadata` 不存在，需要在 `chat_service.py` 中新增。检查现有 conversation 的 metadata 字段是否已支持。

- [ ] **Step 6: 运行测试**

Run: `docker compose exec backend pytest backend/tests/chat/ -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/agents/chat/pipeline.py backend/app/agents/chat/nodes.py backend/app/services/chat_service.py backend/tests/chat/test_react_loop.py
git commit -m "feat(chat): persist active skill names for cross-round recovery"
```

---

## Phase 3: Tool 选择策略 + answer_complete Heuristic

### Task 8: 新增 _build_tool_strategy 函数

**Files:**
- Modify: `backend/app/agents/chat/nodes.py`
- Test: `backend/tests/chat/test_react_loop.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/chat/test_react_loop.py — 追加
class TestBuildToolStrategy:
    def test_interview_question_answer_complete_default_search(self):
        """Should require search_questions when user completed their answer (default)."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "interview_question", "answer_complete": True, "retrieved_questions": [], "active_skills": []}
        strategy = _build_tool_strategy(state)
        assert "search_questions" in strategy
        assert "必须" in strategy

    def test_interview_question_deep_dive_allows_direct_followup(self):
        """Project deep-dive mode: can directly follow up without search."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "interview_question", "answer_complete": True, "retrieved_questions": [], "active_skills": ["project-deep-dive"]}
        strategy = _build_tool_strategy(state)
        assert "search_questions" in strategy  # still mentions search
        assert "直接追问" in strategy or "不检索" in strategy  # but allows skipping

    def test_interview_question_answer_incomplete_suggests_wait(self):
        """Should suggest waiting when user hasn't finished answering."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "interview_question", "answer_complete": False, "active_skills": []}
        strategy = _build_tool_strategy(state)
        assert "不调用工具" in strategy or "等待" in strategy

    def test_practice_request_requires_search(self):
        """Practice requests must search (required, not suggested)."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "practice_request", "answer_complete": False, "active_skills": []}
        strategy = _build_tool_strategy(state)
        assert "search_questions" in strategy
        assert "必须" in strategy

    def test_chat_suggests_no_tools(self):
        """Should suggest no tools for casual chat."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "chat", "answer_complete": False, "active_skills": []}
        strategy = _build_tool_strategy(state)
        assert "不调用工具" in strategy

    def test_follow_up_suggests_contextual_answer(self):
        """Should suggest contextual answer for follow-ups."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "follow_up", "answer_complete": False, "active_skills": []}
        strategy = _build_tool_strategy(state)
        assert "上下文" in strategy or "直接回答" in strategy

    def test_already_retrieved_suggests_no_search(self):
        """Should not suggest search when retrieved_questions is non-empty."""
        from app.agents.chat.nodes import _build_tool_strategy

        state = {"intent": "interview_question", "answer_complete": True, "retrieved_questions": [{"id": 1}], "active_skills": []}
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
    """Build tool usage strategy guidance based on current intent and state.

    核心原则：默认检索，但项目连续深挖时可直接追问（不检索）。
    """
    intent = state.get("intent", "chat")
    answer_complete = state.get("answer_complete", False)
    has_retrieved = bool(state.get("retrieved_questions"))
    active_skills = state.get("active_skills", [])
    is_deep_dive = "project-deep-dive" in active_skills

    if intent == "interview_question" and answer_complete and not has_retrieved:
        if is_deep_dive:
            return (
                "<tool_strategy>\n"
                "当前状态：用户回答完毕，项目深挖模式。\n"
                "建议：默认调用 search_questions 检索追问题。"
                "但如果用户回答中包含明确的技术细节可以直接追问，也可以不检索直接追问。\n"
                "</tool_strategy>"
            )
        return (
            "<tool_strategy>\n"
            "当前状态：用户刚回答完面试问题。\n"
            "必须：从用户回答中提取 2-5 个技术关键词，调用 search_questions 检索追问题。\n"
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
            "必须：调用 search_questions 检索相关题目，结果不足时用 draw_questions 补充。\n"
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

### Task 10: answer_complete Heuristic + 分类 Prompt 微调

**Files:**
- Modify: `backend/app/agents/chat/prompts.py:141-155`
- Modify: `backend/app/services/memory_recall_service.py`（`INTENT_AND_MEMORY_PROMPT` + `classify_and_recall_fast` 的 answer_complete heuristic）
- Test: `backend/tests/chat/test_react_loop.py`

**背景**：主分类路径使用 `classify_and_recall`（LLM 返回 JSON 含 `answer_complete`）。但 fallback 路径 `classify_and_recall_fast` 硬编码 `answer_complete=True`，这对短消息（"嗯"、"用了 Redis"）判断不准。需要加 code-level heuristic。

- [ ] **Step 1: 写失败测试 — answer_complete heuristic**

```python
# tests/chat/test_react_loop.py — 新增
class TestAnswerCompleteHeuristic:
    def test_short_message_not_complete(self):
        """Short messages (< 15 chars) should be answer_complete=False."""
        from app.services.memory_recall_service import _heuristic_answer_complete

        assert _heuristic_answer_complete("嗯") is False
        assert _heuristic_answer_complete("用了 Redis") is False
        assert _heuristic_answer_complete("这样对吗？") is False

    def test_long_message_likely_complete(self):
        """Long messages (> 30 chars with substance) should be answer_complete=True."""
        from app.services.memory_recall_service import _heuristic_answer_complete

        msg = "我在项目中使用了 Redis 做缓存层，通过布隆过滤器解决缓存穿透，用分布式锁解决缓存击穿"
        assert _heuristic_answer_complete(msg) is True

    def test_explicit_completion_markers(self):
        """Messages with explicit completion markers should be True."""
        from app.services.memory_recall_service import _heuristic_answer_complete

        assert _heuristic_answer_complete("就这些") is True
        assert _heuristic_answer_complete("答完了") is True
        assert _heuristic_answer_complete("大概就是这样吧") is True

    def test_question_marks_not_complete(self):
        """Questions/confirmations should be False."""
        from app.services.memory_recall_service import _heuristic_answer_complete

        assert _heuristic_answer_complete("你是说用 Redis 吗？") is False
        assert _heuristic_answer_complete("能不能再解释一下") is False

    def test_substantive_answer_with_how_why_words_is_complete(self):
        """Substantive answers containing 怎么/为什么 should not be misclassified."""
        from app.services.memory_recall_service import _heuristic_answer_complete

        msg = "我是这么解决的：先分析为什么慢，再看怎么优化缓存和接口调用链路，最后做压测验证"
        assert _heuristic_answer_complete(msg) is True
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose exec backend pytest backend/tests/chat/test_react_loop.py::TestAnswerCompleteHeuristic -v`
Expected: FAIL（`_heuristic_answer_complete` 不存在）

- [ ] **Step 3: 实现 _heuristic_answer_complete**

在 `memory_recall_service.py` 中新增：

```python
# answer_complete 启发式判断
_EXPLICIT_COMPLETE_MARKERS = {"就这些", "答完了", "大概就是这样", "大概就是这样吧", "说完了", "完了", "没有了"}
_EXPLICIT_INCOMPLETE_MARKERS = {"嗯", "好的", "对", "是的", "没错", "ok", "OK"}
_QUESTION_PREFIXES = ("你是说", "能不能", "可以再", "再解释", "怎么", "为什么")

def _heuristic_answer_complete(message: str) -> bool:
    """Heuristic for answer_complete when LLM classification is unavailable.

    Rules:
    - Explicit completion markers → True
    - Very short messages / filler words → False
    - Questions → False
    - Long substantive messages (> 30 chars) → True
    """
    text = message.strip()

    # Explicit completion
    for marker in _EXPLICIT_COMPLETE_MARKERS:
        if marker in text:
            return True

    # Filler / short
    if text in _EXPLICIT_INCOMPLETE_MARKERS:
        return False
    if len(text) < 15:
        return False

    # Questions / confirmations. Be conservative: full answers often contain
    # words like "怎么" or "为什么", so only treat them as questions at the
    # beginning or when the message ends with a question mark.
    if text.endswith(("?", "？")):
        return False
    if text.startswith(_QUESTION_PREFIXES):
        return False

    # Long substantive
    if len(text) >= 30:
        return True

    # Default: not complete
    return False
```

- [ ] **Step 4: 替换 classify_and_recall_fast 中的硬编码**

在 `classify_and_recall_fast` 中，把 `answer_complete = True` 改为：

```python
answer_complete = _heuristic_answer_complete(user_message)
```

- [ ] **Step 5: 替换 classify_and_recall 的 fallback 路径**

在 `classify_and_recall` 中，把 fallback 路径的 `answer_complete = len(user_message.strip()) >= 20` 改为：

```python
answer_complete = _heuristic_answer_complete(user_message)
```

- [ ] **Step 6: 更新 INTENT_CLASSIFY_PROMPT（fallback 路径）**

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

- [ ] **Step 7: 更新 INTENT_AND_MEMORY_PROMPT 中的 answer_complete 判断标准**

读取 `memory_recall_service.py` 中 `INTENT_AND_MEMORY_PROMPT`，在 `answer_complete` 说明处加入更明确的判断标准：

```
answer_complete 判断标准：
- true: 用户明确表示回答完毕（"就这些"、"答完了"、"大概就是这样"）
- true: 用户给出了完整的项目描述或技术方案（有开头有结尾，超过 30 字）
- false: 用户只说了几个关键词或片段（"用了 Redis"、"微服务"）
- false: 用户在反问或确认（"你是说...？"、"这样对吗？"）
- false: 用户说"嗯"、"好的"等过渡词（可能是思考中）
```

- [ ] **Step 8: 运行测试**

Run: `docker compose exec backend pytest backend/tests/chat/ -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add backend/app/agents/chat/prompts.py backend/app/services/memory_recall_service.py backend/tests/chat/test_react_loop.py
git commit -m "feat(chat): add answer_complete heuristic + improve classification prompts"
```

---

### Task 11: 真实链路端到端验证

**Files:**
- Test: `backend/tests/chat/test_react_e2e.py`（新文件）

**原则**：不 mock 被测对象。只 mock 外部依赖（LLM API、数据库）。验证 `tools.py → nodes.py → pipeline.py` 的真实调用链。

- [ ] **Step 1: 写真实链路测试 — load_skill → system prompt 注入**

```python
"""真实链路测试 — 不 mock 被测对象，只 mock 外部依赖（LLM API）。"""
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agents.shared.events import _event_queue_var


class TestRealLinkSkillInjection:
    """验证 load_skill → state 更新 → system prompt 注入 的真实链路。"""

    async def test_load_skill_then_system_prompt_contains_instruction(self):
        """真实调用 load_skill → build_react_system_prompt，验证指令注入。"""
        from app.agents.chat.tools import execute_tool
        from app.agents.chat.nodes import build_react_system_prompt

        state = {
            "user_id": 1,
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": [],
            "retrieved_questions": [],
        }

        # 真实调用 load_skill（只 mock skill registry 返回的 Skill 对象）
        tool_call = {
            "function": {
                "name": "load_skill",
                "arguments": json.dumps({"skill_name": "theory-qa"}),
            }
        }

        mock_skill = MagicMock()
        mock_skill.name = "theory-qa"
        mock_skill.description = "理论问答策略"
        mock_skill.get_instruction.return_value = "## Theory QA\nAsk deep theory questions about CS fundamentals."

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_skill

        with patch("app.agents.chat.tools._get_skill_registry", return_value=mock_registry):
            result = await execute_tool(tool_call, state)

        # 验证 tool 返回确认
        parsed = json.loads(result)
        assert parsed["status"] == "loaded"

        # 验证 state 更新（真实链路）
        assert "theory-qa" in state["active_skills"]
        assert len(state["active_skill_instructions"]) == 1

        # 真实调用 build_react_system_prompt
        prompt = build_react_system_prompt(state)
        assert "<active_skill_instructions>" in prompt
        assert "Theory QA" in prompt
        assert "Ask deep theory questions" in prompt

    async def test_full_react_loop_with_real_tools(self):
        """完整 ReAct loop：LLM 调 load_skill → 真实 execute_tool → 真实 build_react_system_prompt → LLM 回答。"""
        from app.agents.chat.pipeline import _react_loop

        state = {
            "user_id": 1,
            "user_message": "介绍一下你自己",
            "model": None,
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "memory_summaries": [],
            "compressed_context": None,
            "active_skills": [],
            "retrieved_questions": [],
            "intent": "interview_question",
            "answer_complete": True,
        }

        # LLM 第一步调 load_skill，第二步回答
        step1 = {
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "function": {
                    "name": "load_skill",
                    "arguments": json.dumps({"skill_name": "theory-qa"}),
                },
            }],
            "finish_reason": "tool_calls",
        }
        step2 = {
            "content": "请解释一下 JVM 内存模型。",
            "tool_calls": None,
            "finish_reason": "stop",
        }

        call_count = 0
        captured_system_prompts = []

        async def mock_llm(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            # 捕获第二次调用的 system prompt
            if call_count == 2:
                messages = args[0] if args else kwargs.get("messages", [])
                if messages and messages[0].get("role") == "system":
                    captured_system_prompts.append(messages[0]["content"])
            return [step1, step2][call_count - 1]

        mock_skill = MagicMock()
        mock_skill.name = "theory-qa"
        mock_skill.description = "理论问答策略"
        mock_skill.get_instruction.return_value = "## Theory QA\nAsk deep theory questions."

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_skill

        emitted: list[dict] = []
        mock_queue = MagicMock()
        mock_queue.put_nowait = lambda e: emitted.append(e)

        token = _event_queue_var.set(mock_queue)
        try:
            with (
                patch("app.agents.chat.pipeline.llm_with_tools", side_effect=mock_llm),
                patch("app.agents.chat.pipeline.stream_llm_messages", side_effect=lambda *a, **kw: _mock_stream("请解释一下 JVM 内存模型。")),
                patch("app.agents.chat.tools._get_skill_registry", return_value=mock_registry),
            ):
                collected = []
                async for event in _react_loop(state):
                    collected.append(event)
        finally:
            _event_queue_var.reset(token)

        # 验证：第二次 LLM 调用时 system prompt 包含 skill 指令
        assert len(captured_system_prompts) == 1
        assert "Theory QA" in captured_system_prompts[0]
        assert "Ask deep theory questions" in captured_system_prompts[0]

        # 验证事件流
        all_events = emitted + collected
        assert any(e.get("type") == "done" for e in all_events)


async def _mock_stream(*chunks: str):
    for c in chunks:
        yield c
```

- [ ] **Step 2: 运行测试**

Run: `docker compose exec backend pytest backend/tests/chat/test_react_e2e.py -v`
Expected: PASS

- [ ] **Step 3: 运行全部 chat 测试确认无回归**

Run: `docker compose exec backend pytest backend/tests/chat/ -v`
Expected: PASS

- [ ] **Step 4: 运行完整后端测试套件**

Run: `docker compose exec backend pytest backend/tests/ -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/tests/chat/test_react_e2e.py
git commit -m "test(chat): add real-link e2e tests for skill injection pipeline"
```

- [ ] **Step 6: 最终 Commit（如有遗漏）**

```bash
git add -A
git commit -m "feat(chat): ReAct agent production hardening — schema + skill injection + tool strategy + answer_complete heuristic"
```
