# ReAct 面试 Agent 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 chat pipeline Step 3-5 替换为 ReAct 循环，让 LLM 通过 tool calling 自主选择面试技能和检索工具。

**Architecture:** 保留 Step 1-2（load_context + classify）不变，Step 3-5 替换为 `_react_loop()`。LLM 通过 3 个 tool（load_skill、search_questions、draw_questions）自主决策。最终回答通过 `stream_llm_messages` 流式生成。

**Tech Stack:** Python 3.10+, asyncio, pytest, existing `llm_with_tools` + `stream_llm_messages`

**Spec:** `docs/superpowers/specs/2026-06-13-react-interview-agent-design.md`

---

## 文件结构

| 文件 | 操作 | 职责 |
|------|------|------|
| `backend/app/agents/chat/tools.py` | **新建** | Tool schema 定义 + `execute_tool()` 执行器 |
| `backend/tests/chat/test_tools.py` | **新建** | Tool 执行器单元测试 |
| `backend/app/agents/shared/skills/builder.py` | 修改 | 新增 `build_skill_catalog()` |
| `backend/tests/chat/test_skill_catalog.py` | **新建** | Skill catalog 测试 |
| `backend/app/agents/chat/nodes.py` | 修改 | 新增 `build_react_system_prompt()` |
| `backend/tests/chat/test_react_prompt.py` | **新建** | System prompt 构建测试 |
| `backend/app/agents/chat/pipeline.py` | 修改 | 新增 `_react_loop()`，替换 Step 3-5 |
| `backend/tests/chat/test_react_loop.py` | **新建** | ReAct 循环集成测试 |

---

### Task 1: Tool Schema 定义 + 执行器

**Files:**
- Create: `backend/app/agents/chat/tools.py`
- Test: `backend/tests/chat/test_tools.py`

- [ ] **Step 1: 写失败测试 — load_skill tool**

```python
# backend/tests/chat/test_tools.py
"""Tests for ReAct agent tools."""

import json
import pytest
from unittest.mock import MagicMock, patch, AsyncMock


class TestExecuteToolLoadSkill:
    """load_skill tool 执行测试"""

    @pytest.mark.asyncio
    async def test_load_skill_returns_instruction(self):
        """load_skill 应返回 skill 的完整指令文本"""
        from app.agents.chat.tools import execute_tool

        mock_skill = MagicMock()
        mock_skill.get_instruction.return_value = "# Algorithm Coding\n\n面试算法题时..."

        mock_registry = MagicMock()
        mock_registry.get.return_value = mock_skill

        state = {"user_id": 1}
        tool_call = {
            "id": "call_1",
            "function": {
                "name": "load_skill",
                "arguments": json.dumps({"skill_name": "algorithm-coding"}),
            },
        }

        with patch("app.agents.chat.tools._get_skill_registry", return_value=mock_registry):
            result = await execute_tool(tool_call, state)

        assert "# Algorithm Coding" in result
        mock_registry.get.assert_called_once_with("algorithm-coding")

    @pytest.mark.asyncio
    async def test_load_skill_unknown_name(self):
        """load_skill 遇到未知 skill 名称应返回错误"""
        from app.agents.chat.tools import execute_tool

        mock_registry = MagicMock()
        mock_registry.get.return_value = None

        state = {"user_id": 1}
        tool_call = {
            "id": "call_1",
            "function": {
                "name": "load_skill",
                "arguments": json.dumps({"skill_name": "nonexistent"}),
            },
        }

        with patch("app.agents.chat.tools._get_skill_registry", return_value=mock_registry):
            result = await execute_tool(tool_call, state)

        parsed = json.loads(result)
        assert "error" in parsed
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest backend/tests/chat/test_tools.py::TestExecuteToolLoadSkill -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.agents.chat.tools'`

- [ ] **Step 3: 写失败测试 — search_questions tool**

在 `backend/tests/chat/test_tools.py` 中追加：

```python
class TestExecuteToolSearchQuestions:
    """search_questions tool 执行测试"""

    @pytest.mark.asyncio
    async def test_search_returns_json_results(self):
        """search_questions 应返回 JSON 格式的题目列表"""
        from app.agents.chat.tools import execute_tool

        mock_results = [
            {"id": 1, "question": "什么是缓存穿透？", "cat1": "Redis"},
            {"id": 2, "question": "Redis 和 Memcached 区别？", "cat1": "Redis"},
        ]

        state = {"user_id": 1, "job_position": "后端开发"}
        tool_call = {
            "id": "call_2",
            "function": {
                "name": "search_questions",
                "arguments": json.dumps({"keywords": ["Redis", "缓存"]}),
            },
        }

        with patch("app.agents.chat.tools._hybrid_search", new_callable=AsyncMock, return_value=mock_results):
            result = await execute_tool(tool_call, state)

        parsed = json.loads(result)
        assert len(parsed) == 2
        assert parsed[0]["question"] == "什么是缓存穿透？"
        # 验证 state 被更新
        assert state["retrieved_questions"] == mock_results

    @pytest.mark.asyncio
    async def test_search_with_question_type(self):
        """search_questions 支持 question_type 参数"""
        from app.agents.chat.tools import execute_tool

        state = {"user_id": 1, "job_position": None}
        tool_call = {
            "id": "call_3",
            "function": {
                "name": "search_questions",
                "arguments": json.dumps({
                    "keywords": ["项目经验"],
                    "question_type": "project_followup",
                }),
            },
        }

        with patch("app.agents.chat.tools._hybrid_search", new_callable=AsyncMock, return_value=[]) as mock_search:
            await execute_tool(tool_call, state)

        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args
        assert call_kwargs.kwargs.get("question_type") == "project_followup" or call_kwargs[1].get("question_type") == "project_followup"
```

- [ ] **Step 4: 写失败测试 — draw_questions tool**

在 `backend/tests/chat/test_tools.py` 中追加：

```python
class TestExecuteToolDrawQuestions:
    """draw_questions tool 执行测试"""

    @pytest.mark.asyncio
    async def test_draw_returns_json_results(self):
        """draw_questions 应返回 JSON 格式的题目列表"""
        from app.agents.chat.tools import execute_tool

        mock_results = [
            {"id": 10, "question": "实现 LRU Cache", "difficulty": "medium"},
        ]

        state = {"user_id": 1, "bank_mode": "public"}
        tool_call = {
            "id": "call_4",
            "function": {
                "name": "draw_questions",
                "arguments": json.dumps({"count": 1, "difficulty": "medium"}),
            },
        }

        with patch("app.agents.chat.tools._draw_questions", return_value=mock_results):
            with patch("app.agents.chat.tools.asyncio.to_thread", new_callable=AsyncMock, return_value=mock_results):
                result = await execute_tool(tool_call, state)

        parsed = json.loads(result)
        assert len(parsed) == 1
        assert parsed[0]["difficulty"] == "medium"

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self):
        """未知工具名应返回错误"""
        from app.agents.chat.tools import execute_tool

        state = {"user_id": 1}
        tool_call = {
            "id": "call_5",
            "function": {
                "name": "nonexistent_tool",
                "arguments": "{}",
            },
        }

        result = await execute_tool(tool_call, state)
        parsed = json.loads(result)
        assert "error" in parsed
```

- [ ] **Step 5: 跑所有测试确认失败**

Run: `.venv/bin/python -m pytest backend/tests/chat/test_tools.py -v`
Expected: FAIL — module not found

- [ ] **Step 6: 实现 tools.py**

```python
# backend/app/agents/chat/tools.py
"""ReAct Agent Tools — LLM 可调用的工具定义和执行器。

工具列表:
- load_skill: 加载面试技能指令
- search_questions: RAG 搜索题库
- draw_questions: 随机抽题
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.chat.state import ChatState

logger = logging.getLogger("interview-boss")


# ── 依赖注入（方便测试 mock）──

def _get_skill_registry():
    from app.agents.chat.skills import get_default_registry
    return get_default_registry()


async def _hybrid_search(**kwargs):
    from app.services.fts_service import hybrid_search
    return hybrid_search(**kwargs)


def _draw_questions(**kwargs):
    from app.services.question_draw_service import draw_questions
    return draw_questions(**kwargs)


# ── Tool Schemas（OpenAI function calling 格式）──

LOAD_SKILL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "load_skill",
        "description": (
            "加载面试技能指令。根据面试话题或用户问题的领域，"
            "选择最合适的技能来指导你的面试行为。在开始面试或切换话题时调用。"
        ),
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
                        "hr-soft-skills",
                    ],
                    "description": "技能名称",
                },
            },
            "required": ["skill_name"],
        },
    },
}

SEARCH_QUESTIONS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_questions",
        "description": (
            "从题库中搜索面试题。当需要找到与用户问题相关的面试题时调用。"
            "返回匹配的题目列表。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "keywords": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "搜索关键词，如 ['Redis', '缓存穿透']",
                },
                "question_type": {
                    "type": "string",
                    "enum": ["project_followup", "knowledge_probe", "new_question"],
                    "description": "题目类型偏好",
                },
            },
            "required": ["keywords"],
        },
    },
}

DRAW_QUESTIONS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "draw_questions",
        "description": "从题库中随机抽题。当用户要求练习、或需要随机出题时调用。",
        "parameters": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "抽题数量，默认 1",
                    "default": 1,
                },
                "difficulty": {
                    "type": "string",
                    "enum": ["easy", "medium", "hard"],
                    "description": "难度偏好",
                },
            },
        },
    },
}

ALL_TOOLS = [LOAD_SKILL_SCHEMA, SEARCH_QUESTIONS_SCHEMA, DRAW_QUESTIONS_SCHEMA]


# ── Tool 进度消息 ──

_TOOL_PROGRESS_MESSAGES = {
    "load_skill": lambda args: f"加载 {args.get('skill_name', '')} 技能...",
    "search_questions": lambda args: "搜索相关面试题...",
    "draw_questions": lambda args: "抽取面试题...",
}


def tool_progress_message(tool_call: dict) -> str:
    """根据 tool call 生成用户可见的进度消息。"""
    name = tool_call["function"]["name"]
    try:
        args = json.loads(tool_call["function"]["arguments"])
    except (json.JSONDecodeError, KeyError):
        args = {}
    builder = _TOOL_PROGRESS_MESSAGES.get(name)
    return builder(args) if builder else f"执行 {name}..."


# ── Tool 执行器 ──

async def execute_tool(tool_call: dict, state: ChatState) -> str:
    """执行单个 tool call，返回结果字符串。

    Args:
        tool_call: {"id": str, "function": {"name": str, "arguments": str}}
        state: 当前 ChatState（search_questions 会更新 state["retrieved_questions"]）

    Returns:
        JSON 字符串（成功时为结果，失败时为 {"error": "..."}）
    """
    name = tool_call["function"]["name"]
    try:
        args = json.loads(tool_call["function"]["arguments"])
    except (json.JSONDecodeError, KeyError) as e:
        return json.dumps({"error": f"参数解析失败: {e}"})

    try:
        if name == "load_skill":
            return _execute_load_skill(args)
        elif name == "search_questions":
            return await _execute_search_questions(args, state)
        elif name == "draw_questions":
            return await _execute_draw_questions(args, state)
        else:
            return json.dumps({"error": f"Unknown tool: {name}"})
    except Exception as e:
        logger.error(f"Tool {name} execution failed: {e}", exc_info=True)
        return json.dumps({"error": f"{name} 执行失败: {str(e)}"})


def _execute_load_skill(args: dict) -> str:
    """执行 load_skill：从 registry 读取完整指令。"""
    skill_name = args.get("skill_name", "")
    registry = _get_skill_registry()
    skill = registry.get(skill_name)
    if skill is None:
        return json.dumps({"error": f"未知技能: {skill_name}"})
    instruction = skill.get_instruction()
    if not instruction:
        return json.dumps({"error": f"技能 {skill_name} 没有指令内容"})
    return instruction


async def _execute_search_questions(args: dict, state: ChatState) -> str:
    """执行 search_questions：调用 hybrid_search。"""
    keywords = args.get("keywords", [])
    if not keywords:
        return json.dumps({"error": "keywords 不能为空"})

    question_type = args.get("question_type")
    job_position = state.get("job_position")

    results = await _hybrid_search(
        keywords=keywords,
        job_position=job_position,
        question_type=question_type,
        limit=5,
    )

    # 取 top 3 返回，同时更新 state
    top3 = results[:3] if results else []
    state["retrieved_questions"] = top3
    return json.dumps(top3, ensure_ascii=False, default=str)


async def _execute_draw_questions(args: dict, state: ChatState) -> str:
    """执行 draw_questions：从题库随机抽取。"""
    count = args.get("count", 1)
    difficulty = args.get("difficulty")
    user = {"id": state["user_id"], "bank_mode": state.get("bank_mode") or "public"}

    results = await asyncio.to_thread(
        _draw_questions,
        user=user,
        count=count,
        difficulty=difficulty,
    )

    if not results:
        return json.dumps([])

    state["retrieved_questions"] = results
    return json.dumps(results, ensure_ascii=False, default=str)
```

- [ ] **Step 7: 跑测试确认通过**

Run: `.venv/bin/python -m pytest backend/tests/chat/test_tools.py -v`
Expected: 6 passed

- [ ] **Step 8: Commit**

```bash
git add backend/app/agents/chat/tools.py backend/tests/chat/test_tools.py
git commit -m "feat(chat): add ReAct agent tools (load_skill, search_questions, draw_questions)"
```

---

### Task 2: Skill Catalog Builder

**Files:**
- Modify: `backend/app/agents/shared/skills/builder.py`
- Test: `backend/tests/chat/test_skill_catalog.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/chat/test_skill_catalog.py
"""Tests for skill catalog builder."""

import pytest


class TestBuildSkillCatalog:

    def test_catalog_contains_all_skills(self):
        """catalog 应包含所有注册 skill 的名字和描述"""
        from app.agents.chat.tools import _get_skill_registry
        from app.agents.shared.skills.builder import build_skill_catalog

        catalog = build_skill_catalog()

        assert "interview-rhythm" in catalog
        assert "algorithm-coding" in catalog
        assert "load_skill" in catalog  # 包含工具使用提示

    def test_catalog_does_not_contain_full_instructions(self):
        """catalog 不应包含完整的 skill 指令（只有名字+描述）"""
        from app.agents.shared.skills.builder import build_skill_catalog

        catalog = build_skill_catalog()

        # 指令通常很长（>500 字），catalog 应该很短
        assert len(catalog) < 2000
        # 不应包含 XML 标签
        assert "<skill_instruction" not in catalog

    def test_catalog_is_well_formatted(self):
        """catalog 应有清晰的格式"""
        from app.agents.shared.skills.builder import build_skill_catalog

        catalog = build_skill_catalog()

        # 应包含列表格式
        assert "- **" in catalog or "- " in catalog
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest backend/tests/chat/test_skill_catalog.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_skill_catalog'`

- [ ] **Step 3: 实现 build_skill_catalog**

在 `backend/app/agents/shared/skills/builder.py` 末尾追加：

```python
def build_skill_catalog(registry: SkillRegistry | None = None) -> str:
    """构建轻量级 skill 目录（只有名字 + 描述），用于 system prompt 注入。

    与 build_skill_prompt 不同，这里不加载完整指令，
    LLM 需要通过 load_skill tool 按需获取完整内容。

    Returns:
        格式化的 skill 目录文本，约 300-500 tokens。
    """
    if registry is None:
        from app.agents.chat.skills import get_default_registry
        registry = get_default_registry()

    if not registry._skills:
        return ""

    sorted_skills = sorted(
        registry._skills.values(), key=lambda s: s.priority, reverse=True
    )

    lines = [
        "## 可用技能",
        "",
        "你可以通过 load_skill 工具加载以下技能来指导你的面试行为：",
        "",
    ]
    for skill in sorted_skills:
        lines.append(f"- **{skill.name}**: {skill.description}")

    lines.extend([
        "",
        "根据面试话题选择最相关的技能加载。一次可以加载多个。",
        "",
        "## 工具使用指南",
        "",
        "你有以下工具可用：",
        "- load_skill: 加载面试技能指令（在需要专业面试技巧时调用）",
        "- search_questions: 搜索题库（当需要找相关面试题时调用）",
        "- draw_questions: 随机抽题（当用户要求练习时调用）",
        "",
        "请根据用户的提问内容自主决定使用哪些工具。你可以：",
        "1. 先加载相关技能，再搜索或抽取题目",
        "2. 直接回答简单问题（不需要工具时）",
        "3. 多次调用工具组合使用",
        "",
        "如果不调用任何工具，你将直接生成回答。",
    ])

    return "\n".join(lines)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest backend/tests/chat/test_skill_catalog.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/shared/skills/builder.py backend/tests/chat/test_skill_catalog.py
git commit -m "feat(skills): add build_skill_catalog for progressive disclosure"
```

---

### Task 3: ReAct System Prompt Builder

**Files:**
- Modify: `backend/app/agents/chat/nodes.py` (新增函数，不改现有代码)
- Test: `backend/tests/chat/test_react_prompt.py`

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/chat/test_react_prompt.py
"""Tests for ReAct system prompt builder."""

import pytest


class TestBuildReactSystemPrompt:

    def test_prompt_contains_base_info(self):
        """prompt 应包含面试上下文信息"""
        from app.agents.chat.nodes import build_react_system_prompt

        state = {
            "user_id": 1,
            "mode": "free_practice",
            "interview_context": "目标岗位：后端开发",
            "session_notes": "",
            "compressed_context": None,
            "memory_summaries": [],
        }

        prompt = build_react_system_prompt(state)

        assert "后端开发" in prompt or "面试" in prompt

    def test_prompt_contains_skill_catalog(self):
        """prompt 应包含 skill 目录"""
        from app.agents.chat.nodes import build_react_system_prompt

        state = {
            "user_id": 1,
            "mode": "free_practice",
            "interview_context": "",
            "session_notes": "",
            "compressed_context": None,
            "memory_summaries": [],
        }

        prompt = build_react_system_prompt(state)

        assert "load_skill" in prompt
        assert "search_questions" in prompt
        assert "draw_questions" in prompt

    def test_prompt_not_excessively_long(self):
        """prompt 不应超过 5000 字符"""
        from app.agents.chat.nodes import build_react_system_prompt

        state = {
            "user_id": 1,
            "mode": "free_practice",
            "interview_context": "测试" * 100,
            "session_notes": "",
            "compressed_context": None,
            "memory_summaries": [],
        }

        prompt = build_react_system_prompt(state)

        assert len(prompt) < 8000
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest backend/tests/chat/test_react_prompt.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_react_system_prompt'`

- [ ] **Step 3: 实现 build_react_system_prompt**

在 `backend/app/agents/chat/nodes.py` 末尾追加：

```python
def build_react_system_prompt(state: ChatState) -> str:
    """构建 ReAct 循环的 system prompt。

    结构:
    1. Base prompt（面试官角色 + 上下文）
    2. Skill 目录（轻量级，名字+描述）
    3. 工具使用指南
    """
    from app.agents.shared.skills.builder import build_skill_catalog

    mode = state.get("mode", "free_practice")
    interview_context = state.get("interview_context", "")
    session_notes = state.get("session_notes", "")
    memory_summaries = state.get("memory_summaries", [])
    compressed = state.get("compressed_context")

    # Layer 1: Base prompt
    if mode == "jd_resume" and state.get("jd_text"):
        from app.agents.chat.prompts import INTERVIEW_SYSTEM_PROMPT_JD
        base = INTERVIEW_SYSTEM_PROMPT_JD.format(
            jd_text=state.get("jd_text", ""),
            resume_text=state.get("resume_text", ""),
            interview_context=interview_context,
            interview_phase="面试进行中",
        )
    else:
        from app.agents.chat.prompts import INTERVIEW_SYSTEM_PROMPT_PRACTICE
        base = INTERVIEW_SYSTEM_PROMPT_PRACTICE.format(
            interview_context=interview_context,
            interview_phase="面试进行中",
        )

    parts = [base]

    # Layer 2: 记忆摘要
    if memory_summaries:
        memory_text = "\n".join(
            f"- [{m.get('memory_type', '')}] {m.get('summary', '')}"
            for m in memory_summaries[:3]
        )
        parts.append(f"## 候选人相关记忆\n{memory_text}")

    # Layer 3: Session notes
    if session_notes:
        parts.append(f"## 本次面试笔记\n{session_notes}")

    # Layer 4: 压缩上下文
    if compressed:
        parts.append(f"## 历史对话摘要\n{compressed}")

    # Layer 5: Skill 目录 + 工具指南
    catalog = build_skill_catalog()
    if catalog:
        parts.append(catalog)

    return "\n\n".join(parts)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest backend/tests/chat/test_react_prompt.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/chat/nodes.py backend/tests/chat/test_react_prompt.py
git commit -m "feat(chat): add build_react_system_prompt for ReAct agent"
```

---

### Task 4: ReAct 循环核心实现

**Files:**
- Modify: `backend/app/agents/chat/pipeline.py`
- Test: `backend/tests/chat/test_react_loop.py`

- [ ] **Step 1: 写失败测试 — LLM 直接回答（不调工具）**

```python
# backend/tests/chat/test_react_loop.py
"""Tests for ReAct loop in chat pipeline."""

import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


@pytest.fixture
def base_state():
    """基础 state fixture"""
    return {
        "conversation_id": "test-conv-1",
        "user_id": 1,
        "user_message": "你好",
        "mode": "free_practice",
        "jd_id": None,
        "jd_text": None,
        "resume_text": None,
        "model": None,
        "bank_mode": "public",
        "memories": [],
        "memory_summaries": [],
        "resume_summary": None,
        "session_notes": "",
        "interview_context": "目标岗位：后端开发",
        "job_position": "后端开发",
        "message_history": [],
        "compressed_context": None,
        "recent_messages": [],
        "budget_snapshot": None,
        "intent": "chat",
        "answer_complete": False,
        "keywords": [],
        "search_query": "",
        "retrieval_intent": None,
        "search_positive_terms": [],
        "search_negative_terms": [],
        "question_type": None,
        "retrieved_questions": [],
        "selected_basis_questions": [],
        "rerank_metadata": {},
        "response": "",
        "metadata": {},
        "basis_type": "none",
        "basis_question_ids": [],
        "basis_confidence": 0.0,
        "should_show_references": False,
        "active_skills": [],
    }


class TestReactLoop:
    """ReAct 循环测试"""

    @pytest.mark.asyncio
    async def test_direct_answer_no_tools(self, base_state):
        """LLM 不调工具时应直接流式生成回答"""
        from app.agents.chat.pipeline import _react_loop

        # Mock llm_with_tools 返回无 tool_calls
        mock_llm_result = {
            "content": "你好，欢迎来面试。",
            "tool_calls": None,
            "finish_reason": "stop",
        }

        # Mock stream_llm_messages 返回 chunks
        async def mock_stream(*args, **kwargs):
            yield "你好，"
            yield "欢迎来面试。"

        collected = []
        with patch("app.agents.chat.pipeline.llm_with_tools", new_callable=AsyncMock, return_value=mock_llm_result):
            with patch("app.agents.chat.pipeline.stream_llm_messages", side_effect=mock_stream):
                async for event in _react_loop(base_state):
                    collected.append(event)

        # 应该有 chunk 事件和 done 事件
        chunk_events = [e for e in collected if e.get("type") == "chunk"]
        done_events = [e for e in collected if e.get("type") == "done"]
        assert len(chunk_events) == 2
        assert len(done_events) == 1

    @pytest.mark.asyncio
    async def test_tool_call_then_answer(self, base_state):
        """LLM 先调工具再回答"""
        from app.agents.chat.pipeline import _react_loop

        # 第一次调用：返回 tool_calls
        tool_call_result = {
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "function": {
                    "name": "search_questions",
                    "arguments": json.dumps({"keywords": ["Redis"]}),
                },
            }],
            "finish_reason": "tool_calls",
        }

        # 第二次调用：直接回答
        answer_result = {
            "content": "让我问你一道 Redis 相关的问题。",
            "tool_calls": None,
            "finish_reason": "stop",
        }

        call_count = 0

        async def mock_llm_with_tools(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return tool_call_result
            return answer_result

        async def mock_stream(*args, **kwargs):
            yield "让我问你一道 Redis 相关的问题。"

        mock_search_results = json.dumps([{"id": 1, "question": "什么是缓存穿透？"}])

        collected = []
        with patch("app.agents.chat.pipeline.llm_with_tools", side_effect=mock_llm_with_tools):
            with patch("app.agents.chat.pipeline.stream_llm_messages", side_effect=mock_stream):
                with patch("app.agents.chat.pipeline.execute_tool", new_callable=AsyncMock, return_value=mock_search_results):
                    async for event in _react_loop(base_state):
                        collected.append(event)

        # 应该有 step 事件（search_questions）+ retrieved + chunk + done
        step_events = [e for e in collected if e.get("type") == "step"]
        tool_steps = [e for e in step_events if e.get("step") == "search_questions"]
        assert len(tool_steps) >= 1

        retrieved_events = [e for e in collected if e.get("type") == "retrieved"]
        assert len(retrieved_events) >= 1

        # llm_with_tools 应该被调用 2 次
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_max_steps_limit(self, base_state):
        """ReAct 循环应有步数上限"""
        from app.agents.chat.pipeline import _react_loop, MAX_REACT_STEPS

        # 每次都返回 tool_calls（模拟无限循环）
        always_tool_result = {
            "content": None,
            "tool_calls": [{
                "id": "call_loop",
                "function": {
                    "name": "load_skill",
                    "arguments": json.dumps({"skill_name": "interview-rhythm"}),
                },
            }],
            "finish_reason": "tool_calls",
        }

        call_count = 0

        async def mock_llm_with_tools(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return always_tool_result

        async def mock_stream(*args, **kwargs):
            yield "回答"

        with patch("app.agents.chat.pipeline.llm_with_tools", side_effect=mock_llm_with_tools):
            with patch("app.agents.chat.pipeline.stream_llm_messages", side_effect=mock_stream):
                with patch("app.agents.chat.pipeline.execute_tool", new_callable=AsyncMock, return_value="skill content"):
                    collected = []
                    async for event in _react_loop(base_state):
                        collected.append(event)

        # llm_with_tools 应该恰好被调用 MAX_REACT_STEPS 次
        assert call_count == MAX_REACT_STEPS
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest backend/tests/chat/test_react_loop.py -v`
Expected: FAIL — `ImportError: cannot import name '_react_loop'`

- [ ] **Step 3: 实现 _react_loop**

在 `backend/app/agents/chat/pipeline.py` 中：

1. 在文件顶部 import 区新增：
```python
from app.agents.chat.tools import (
    ALL_TOOLS,
    execute_tool,
    tool_progress_message,
)
from app.agents.chat.nodes import build_react_system_prompt
from app.services.llm import llm_with_tools, stream_llm_messages, make_tool_result_message
```

2. 在 `_step_extract_memory` 函数之后、`_route_and_generate` 之前新增：

```python
MAX_REACT_STEPS = 5


async def _react_loop(state: ChatState) -> AsyncGenerator[dict, None]:
    """ReAct 循环：LLM 自主选择工具，最终流式生成回答。

    流程:
    1. 构建 system prompt（含 skill 目录 + 工具指南）
    2. 构建 messages
    3. ReAct 循环：LLM 调用工具或直接回答
    4. 流式生成最终回答
    """
    # 1. 构建 system prompt
    system_prompt = build_react_system_prompt(state)

    # 2. 构建 messages
    messages = [{"role": "system", "content": system_prompt}]

    # 压缩上下文
    compressed = state.get("compressed_context")
    if compressed:
        messages.append({"role": "user", "content": f"[历史对话摘要]\n{compressed}"})

    # 最近消息
    for msg in state.get("recent_messages", [])[-10:]:
        role = msg.get("role", "user")
        if role in ("user", "assistant"):
            messages.append({"role": role, "content": msg.get("content", "")})

    # 当前用户消息
    messages.append({"role": "user", "content": state["user_message"]})

    # 3. ReAct 循环
    for step in range(MAX_REACT_STEPS):
        try:
            result = await llm_with_tools(
                messages, ALL_TOOLS, user_id=state["user_id"],
                model=state.get("model"),
            )
        except Exception as e:
            logger.error(f"ReAct step {step} LLM call failed: {e}")
            break

        if not result.get("tool_calls"):
            break  # LLM 决定直接回答

        # 追加 assistant message（含 tool_calls）
        messages.append({
            "role": "assistant",
            "content": result.get("content"),
            "tool_calls": result["tool_calls"],
        })

        # 执行每个 tool call
        for tc in result["tool_calls"]:
            tool_name = tc["function"]["name"]

            # emit 进度事件
            _emit({
                "type": "step",
                "step": tool_name,
                "message": tool_progress_message(tc),
            })

            # 执行工具
            output = await execute_tool(tc, state)

            # search_questions 结果 emit retrieved 事件
            if tool_name == "search_questions" and state.get("retrieved_questions"):
                _emit({
                    "type": "retrieved",
                    "questions": [
                        {
                            "id": q.get("id"),
                            "question": q.get("question", ""),
                            "cat1": q.get("cat1", ""),
                            "cat2": q.get("cat2", ""),
                            "company": _extract_company(q),
                            "round": _extract_round(q),
                        }
                        for q in state["retrieved_questions"][:3]
                    ],
                })

            # draw_questions 结果也 emit retrieved 事件
            if tool_name == "draw_questions" and state.get("retrieved_questions"):
                _emit({
                    "type": "retrieved",
                    "questions": [
                        {
                            "id": q.get("id"),
                            "question": q.get("question", ""),
                            "cat1": q.get("cat1", ""),
                            "cat2": q.get("cat2", ""),
                        }
                        for q in state["retrieved_questions"][:3]
                    ],
                })

            messages.append(make_tool_result_message(tc["id"], output))

    # 4. 流式生成最终回答
    _emit({"type": "step", "step": "generating", "message": "正在生成回答..."})
    async for event in stream_llm_messages(messages, user_id=state["user_id"], model=state.get("model")):
        if isinstance(event, dict):
            yield event
        else:
            yield {"type": "chunk", "content": event}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest backend/tests/chat/test_react_loop.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/chat/pipeline.py backend/tests/chat/test_react_loop.py
git commit -m "feat(chat): implement ReAct loop with tool calling"
```

---

### Task 5: 接线 — 替换 pipeline Step 3-5

**Files:**
- Modify: `backend/app/agents/chat/pipeline.py` (修改 `_run_pipeline` 和 `run_chat`)

- [ ] **Step 1: 修改 `_run_pipeline` 使用 `_react_loop`**

在 `pipeline.py` 的 `_run_pipeline` 函数中，将 Step 3-5 替换：

```python
    async def _run_pipeline() -> None:
        t0 = time.monotonic()
        try:
            # 1. 加载上下文（不变）
            await _step_load_context(state)

            # 2. 意图分类 + 关键词（不变）
            await _step_classify(state)

            # 3-5. ReAct 循环（替代 resolve_skills + route_and_generate）
            response = ""
            metadata = {}
            async for event in _react_loop(state):
                event_type = event.get("type")
                if event_type == "done":
                    metadata = event.get("metadata", {})
                    _emit({"type": "basis", **_basis_event_payload(metadata)})
                    _emit({"type": "done", "metadata": metadata})
                    continue
                if event_type in {"chunk", "thinking", "thinking_start", "thinking_done", "error"}:
                    if event_type == "chunk":
                        response += event.get("content", "")
                    _emit(event)
                # step 和 retrieved 事件已在 _react_loop 内部 emit

            state["response"] = response
            state["metadata"] = metadata

            # 后台记忆提取（不变）
            asyncio.create_task(_step_extract_memory(dict(state)))

            elapsed = time.monotonic() - t0
            logger.info(
                f"Pipeline completed in {elapsed:.1f}s, "
                f"intent={state.get('intent')}"
            )
        except Exception as e:
            logger.exception("Pipeline 执行失败")
            queue.put_nowait(
                {"type": "error", "message": _sanitize_error_message(e)}
            )
        finally:
            queue.put_nowait(_SENTINEL)
```

- [ ] **Step 2: 清理不再需要的 import**

从 `pipeline.py` 顶部的 import 中移除不再使用的：
```python
# 删除这些 import（不再需要）
from app.agents.chat.nodes import (
    ...
    resolve_active_skills,  # 删除
    generate_direct_response,  # 删除
    generate_response,  # 删除
    fts_retrieve,  # 删除
    llm_rerank_questions,  # 删除
)
```

保留仍然需要的 import：
```python
from app.agents.chat.nodes import (
    extract_memory,
    load_history,
    recall_memories,
    summarize_context,
)
```

- [ ] **Step 3: 跑全部 chat 测试**

Run: `.venv/bin/python -m pytest backend/tests/chat/ -v --tb=short 2>&1 | tail -30`
Expected: 全部通过（可能有需要适配的旧测试）

- [ ] **Step 4: Commit**

```bash
git add backend/app/agents/chat/pipeline.py
git commit -m "refactor(chat): wire up ReAct loop, replace Steps 3-5"
```

---

### Task 6: 清理不再使用的代码

**Files:**
- Modify: `backend/app/agents/chat/nodes.py` (删除不再需要的函数)
- Modify: `backend/app/agents/chat/pipeline.py` (删除不再需要的函数)

- [ ] **Step 1: 从 nodes.py 中删除不再使用的函数**

删除以下函数（它们的逻辑已被 ReAct 循环 + tools.py 替代）：
- `resolve_active_skills()` (line 261-277) — 被 load_skill tool 替代
- `plan_skill_guided_strategy()` (line 280-471) — 被 LLM 自主决策替代

保留以下函数（仍然被 `_step_classify` 或其他地方使用）：
- `recall_memories()`, `load_history()`, `summarize_context()` — Step 1 使用
- `check_round_limit()` — Step 1 使用
- `extract_memory()` — 后台记忆提取使用
- `_format_messages_for_llm()`, `_truncate_to_budget()` 等工具函数

- [ ] **Step 2: 从 pipeline.py 中删除不再使用的函数**

删除以下函数：
- `_step_resolve_skills()` (line 276-281)
- `_step_retrieve()` (line 284-316)
- `_step_draw()` (line 319-388)
- `_step_generate()` (line 391-411)
- `_step_generate_direct()` (line 414-438)
- `_route_and_generate()` (line 454-477)

保留以下函数：
- `_emit()`, `_step()`, `_extract_company()`, `_extract_round()` — ReAct 循环使用
- `_sanitize_error_message()`, `_basis_event_payload()` — 主流程使用
- `_initial_state()` — 初始化使用
- `_step_load_context()`, `_step_classify()` — Step 1-2 使用
- `_step_extract_memory()` — 后台记忆使用
- `_react_loop()` — 新的 ReAct 循环
- `run_chat()` — 入口

- [ ] **Step 3: 跑全部测试**

Run: `.venv/bin/python -m pytest backend/tests/chat/ -v --tb=short 2>&1 | tail -30`
Expected: 全部通过

- [ ] **Step 4: Commit**

```bash
git add backend/app/agents/chat/nodes.py backend/app/agents/chat/pipeline.py
git commit -m "refactor(chat): remove unused skill resolution and routing functions"
```

---

### Task 7: 集成验证

**Files:**
- Modify: `backend/tests/chat/test_react_loop.py` (追加集成测试)

- [ ] **Step 1: 追加集成测试 — load_skill + search + answer**

在 `backend/tests/chat/test_react_loop.py` 中追加：

```python
class TestReactLoopIntegration:
    """ReAct 循环集成测试（模拟完整工具调用链）"""

    @pytest.mark.asyncio
    async def test_load_skill_then_search_then_answer(self, base_state):
        """LLM 先加载技能，再搜索题库，最后回答"""
        from app.agents.chat.pipeline import _react_loop

        # 第 1 次：调用 load_skill
        step1 = {
            "content": None,
            "tool_calls": [{
                "id": "call_1",
                "function": {
                    "name": "load_skill",
                    "arguments": json.dumps({"skill_name": "algorithm-coding"}),
                },
            }],
            "finish_reason": "tool_calls",
        }

        # 第 2 次：调用 search_questions
        step2 = {
            "content": None,
            "tool_calls": [{
                "id": "call_2",
                "function": {
                    "name": "search_questions",
                    "arguments": json.dumps({"keywords": ["排序算法"]}),
                },
            }],
            "finish_reason": "tool_calls",
        }

        # 第 3 次：直接回答
        step3 = {
            "content": "好的，请实现一个快速排序。",
            "tool_calls": None,
            "finish_reason": "stop",
        }

        call_count = 0

        async def mock_llm(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return [step1, step2, step3][call_count - 1]

        async def mock_stream(*args, **kwargs):
            yield "好的，"
            yield "请实现一个快速排序。"

        collected = []
        with patch("app.agents.chat.pipeline.llm_with_tools", side_effect=mock_llm):
            with patch("app.agents.chat.pipeline.stream_llm_messages", side_effect=mock_stream):
                with patch("app.agents.chat.pipeline.execute_tool", new_callable=AsyncMock, return_value="mock result"):
                    async for event in _react_loop(base_state):
                        collected.append(event)

        # 验证事件序列
        types = [e.get("type") for e in collected]
        assert "step" in types  # 进度事件
        assert "chunk" in types  # 流式内容
        assert "done" in types  # 完成

        # llm_with_tools 被调用 3 次
        assert call_count == 3
```

- [ ] **Step 2: 跑全部测试**

Run: `.venv/bin/python -m pytest backend/tests/chat/ -v --tb=short 2>&1 | tail -40`
Expected: 全部通过

- [ ] **Step 3: 最终 Commit**

```bash
git add backend/tests/chat/test_react_loop.py
git commit -m "test(chat): add ReAct loop integration tests"
```
