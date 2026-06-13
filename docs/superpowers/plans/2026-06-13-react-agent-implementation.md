# InterviewBoss ReAct Agent 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将InterviewBoss面试chatbot从现有pipeline迁移到SOUL.md + AGENTS.md + SKILL.md + ReAct循环架构

**Architecture:** 采用2026年主流的三层架构（SOUL.md/AGENTS.md/SKILL.md）+ ReAct循环，实现高度可配置和可复用的agent设计

**Tech Stack:** Python 3.10+, FastAPI, AsyncOpenAI, Pydantic, YAML

---

## 文件结构

### 阶段1：基础设施（shared模块）

```
backend/app/agents/shared/
├── __init__.py
├── state.py              # 状态定义
├── events.py             # 事件格式化（已有，需扩展）
├── tools.py              # 工具注册表基类
├── skill_loader.py       # Skill加载器
├── react_agent.py        # ReAct循环基类
└── soul_loader.py        # SOUL.md/AGENTS.md加载器
```

### 阶段2：Agent配置化（面试官agent）

```
backend/app/agents/interview/
├── __init__.py
├── SOUL.md               # 面试官人格、价值观、边界
├── AGENTS.md             # 面试官操作规则、工作流程
├── skills/               # 面试官专用技能（复用现有）
│   ├── adaptive-difficulty/
│   ├── algorithm-coding/
│   ├── hr-soft-skills/
│   ├── interview-rhythm/
│   ├── project-deep-dive/
│   └── theory-qa/
└── react_interviewer.py  # 面试官ReAct Agent实现
```

### 阶段3：工具集成

```
backend/app/agents/shared/
├── tools/
│   ├── __init__.py
│   ├── base.py           # 工具基类
│   ├── skill_tools.py    # 技能工具
│   ├── search_tools.py   # 检索工具
│   ├── flow_tools.py     # 流程控制工具
│   └── memory_tools.py   # 记忆工具
```

---

## 并行任务分析

### 可以并行的任务组

**Wave 1（基础设施 - 完全并行）：**
- Task 1: 状态定义（state.py）
- Task 2: 工具注册表基类（tools.py）
- Task 3: Soul Loader（soul_loader.py）
- Task 4: Skill Loader（skill_loader.py）

**Wave 2（依赖Wave 1 - 部分并行）：**
- Task 5: ReAct Agent基类（react_agent.py）- 依赖Task 1,2
- Task 6: 面试官SOUL.md - 无依赖
- Task 7: 面试官AGENTS.md - 无依赖

**Wave 3（依赖Wave 2 - 完全并行）：**
- Task 8: 技能工具（skill_tools.py）- 依赖Task 2,4
- Task 9: 检索工具（search_tools.py）- 依赖Task 2
- Task 10: 流程控制工具（flow_tools.py）- 依赖Task 2
- Task 11: 记忆工具（memory_tools.py）- 依赖Task 2

**Wave 4（依赖Wave 3 - 部分并行）：**
- Task 12: 面试官ReAct Agent实现 - 依赖Task 5,6,7,8,9,10,11
- Task 13: 单元测试 - 依赖所有实现任务

**Wave 5（依赖Wave 4）：**
- Task 14: 集成测试 - 依赖Task 12,13
- Task 15: 性能优化 - 依赖Task 14

---

## 详细任务

### Task 1: 状态定义（state.py）

**Files:**
- Create: `backend/app/agents/shared/state.py`
- Test: `backend/tests/agents/shared/test_state.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agents/shared/test_state.py
import pytest
from app.agents.shared.state import ReActState, Thought, Action

def test_react_state_initialization():
    """测试ReActState初始化"""
    state = ReActState(
        user_message="你好",
        conversation_id="test-123",
        user_id=1
    )
    assert state.user_message == "你好"
    assert state.conversation_id == "test-123"
    assert state.user_id == 1
    assert state.observations == []
    assert state.active_skills == []

def test_thought_parse():
    """测试Thought解析"""
    thought = Thought(
        should_activate_skill=True,
        skill_name="star-method",
        should_call_tool=False,
        tool=None,
        params=None,
        answer=None
    )
    assert thought.should_activate_skill is True
    assert thought.skill_name == "star-method"

def test_action_types():
    """测试Action类型"""
    action1 = Action(type="activate_skill", skill_name="star-method")
    assert action1.type == "activate_skill"
    
    action2 = Action(type="call_tool", tool="search_questions", params={"query": "算法"})
    assert action2.type == "call_tool"
    
    action3 = Action(type="final_answer", answer="这是回答")
    assert action3.type == "final_answer"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/test_state.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'app.agents.shared.state'"

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/agents/shared/state.py
from __future__ import annotations
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

class ReActState(BaseModel):
    """ReAct Agent状态"""
    user_message: str
    conversation_id: str
    user_id: int
    mode: str = "free_practice"
    jd_id: Optional[int] = None
    resume_text: Optional[str] = None
    jd_text: Optional[str] = None
    model: Optional[str] = None
    bank_mode: str = "public"
    
    # 上下文
    memories: List[Dict[str, Any]] = Field(default_factory=list)
    memory_summaries: List[Dict[str, Any]] = Field(default_factory=list)
    message_history: List[Dict[str, Any]] = Field(default_factory=list)
    recent_messages: List[Dict[str, Any]] = Field(default_factory=list)
    interview_context: str = ""
    job_position: Optional[str] = None
    session_notes: str = ""
    
    # ReAct状态
    observations: List[Dict[str, Any]] = Field(default_factory=list)
    active_skills: List[str] = Field(default_factory=list)
    current_thought: Optional[str] = None
    loop_count: int = 0
    max_loops: int = 10
    
    # 检索状态
    retrieved_questions: List[Dict[str, Any]] = Field(default_factory=list)
    selected_basis_questions: List[Dict[str, Any]] = Field(default_factory=list)
    
    # 响应状态
    response: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

class Thought(BaseModel):
    """LLM推理结果"""
    should_activate_skill: bool = False
    skill_name: Optional[str] = None
    should_call_tool: bool = False
    tool: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    answer: Optional[str] = None
    reasoning: str = ""

class Action(BaseModel):
    """Agent行动"""
    type: str  # "activate_skill", "call_tool", "final_answer"
    skill_name: Optional[str] = None
    tool: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    answer: Optional[str] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/test_state.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/shared/state.py backend/tests/agents/shared/test_state.py
git commit -m "feat(agents): add ReAct state definitions"
```

---

### Task 2: 工具注册表基类（tools.py）

**Files:**
- Create: `backend/app/agents/shared/tools.py`
- Test: `backend/tests/agents/shared/test_tools.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agents/shared/test_tools.py
import pytest
from app.agents.shared.tools import Tool, ToolRegistry

class MockTool(Tool):
    """模拟工具"""
    name = "mock_tool"
    description = "这是一个模拟工具"
    
    async def execute(self, params: dict) -> dict:
        return {"result": "mock_result", "params": params}

def test_tool_registry_register():
    """测试工具注册"""
    registry = ToolRegistry()
    tool = MockTool()
    registry.register_tool(tool)
    assert "mock_tool" in registry.tools

def test_tool_registry_call():
    """测试工具调用"""
    import asyncio
    registry = ToolRegistry()
    tool = MockTool()
    registry.register_tool(tool)
    
    result = asyncio.run(registry.call_tool("mock_tool", {"test": "value"}))
    assert result["result"] == "mock_result"
    assert result["params"]["test"] == "value"

def test_tool_registry_not_found():
    """测试工具不存在"""
    registry = ToolRegistry()
    with pytest.raises(ValueError, match="Tool not found"):
        import asyncio
        asyncio.run(registry.call_tool("nonexistent_tool", {}))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/test_tools.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'app.agents.shared.tools'"

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/agents/shared/tools.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger("interview-boss")

class Tool(ABC):
    """工具基类"""
    name: str
    description: str
    
    @abstractmethod
    async def execute(self, params: dict) -> dict:
        """执行工具"""
        pass

class ToolRegistry:
    """工具注册表"""
    
    def __init__(self):
        self.tools: Dict[str, Tool] = {}
    
    def register_tool(self, tool: Tool):
        """注册工具"""
        self.tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")
    
    def list_tools(self) -> list[dict]:
        """列出所有工具"""
        return [
            {"name": tool.name, "description": tool.description}
            for tool in self.tools.values()
        ]
    
    async def call_tool(self, tool_name: str, params: dict) -> dict:
        """调用工具"""
        tool = self.tools.get(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")
        
        logger.info(f"Calling tool: {tool_name} with params: {params}")
        result = await tool.execute(params)
        logger.info(f"Tool {tool_name} returned: {result}")
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/test_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/shared/tools.py backend/tests/agents/shared/test_tools.py
git commit -m "feat(agents): add tool registry base class"
```

---

### Task 3: Soul Loader（soul_loader.py）

**Files:**
- Create: `backend/app/agents/shared/soul_loader.py`
- Test: `backend/tests/agents/shared/test_soul_loader.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agents/shared/test_soul_loader.py
import pytest
import os
import tempfile
from app.agents.shared.soul_loader import SoulLoader

def test_soul_loader_load_soul():
    """测试加载SOUL.md"""
    with tempfile.TemporaryDirectory() as tmpdir:
        soul_content = """---
name: "test-agent"
version: "1.0.0"
description: "测试agent"
personality: "友好"
---

# 测试Agent

## 人格
这是一个测试agent。
"""
        soul_path = os.path.join(tmpdir, "SOUL.md")
        with open(soul_path, "w", encoding="utf-8") as f:
            f.write(soul_content)
        
        loader = SoulLoader()
        result = loader.load_soul(tmpdir)
        
        assert result["name"] == "test-agent"
        assert result["version"] == "1.0.0"
        assert "测试Agent" in result["body"]

def test_soul_loader_load_agents():
    """测试加载AGENTS.md"""
    with tempfile.TemporaryDirectory() as tmpdir:
        agents_content = """# 测试Agent

## 可用技能
- `test-skill`：测试技能

## 可用工具
- `test-tool`：测试工具
"""
        agents_path = os.path.join(tmpdir, "AGENTS.md")
        with open(agents_path, "w", encoding="utf-8") as f:
            f.write(agents_content)
        
        loader = SoulLoader()
        result = loader.load_agents(tmpdir)
        
        assert "测试Agent" in result["body"]
        assert "test-skill" in result["body"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/test_soul_loader.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'app.agents.shared.soul_loader'"

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/agents/shared/soul_loader.py
from __future__ import annotations
import os
import yaml
from typing import Dict, Any, Optional
import logging

logger = logging.getLogger("interview-boss")

class SoulLoader:
    """加载SOUL.md和AGENTS.md"""
    
    def load_soul(self, agent_dir: str) -> Dict[str, Any]:
        """加载SOUL.md"""
        soul_path = os.path.join(agent_dir, "SOUL.md")
        if not os.path.exists(soul_path):
            logger.warning(f"SOUL.md not found at {soul_path}")
            return {"body": ""}
        
        return self._parse_md(soul_path)
    
    def load_agents(self, agent_dir: str) -> Dict[str, Any]:
        """加载AGENTS.md"""
        agents_path = os.path.join(agent_dir, "AGENTS.md")
        if not os.path.exists(agents_path):
            logger.warning(f"AGENTS.md not found at {agents_path}")
            return {"body": ""}
        
        return self._parse_md(agents_path)
    
    def _parse_md(self, file_path: str) -> Dict[str, Any]:
        """解析Markdown文件，提取YAML frontmatter和正文"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 分离YAML frontmatter和正文
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1])
                    body = parts[2].strip()
                    return {**frontmatter, 'body': body}
                except yaml.YAMLError as e:
                    logger.error(f"Failed to parse YAML frontmatter: {e}")
                    return {'body': content}
        
        return {'body': content}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/test_soul_loader.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/shared/soul_loader.py backend/tests/agents/shared/test_soul_loader.py
git commit -m "feat(agents): add SOUL.md/AGENTS.md loader"
```

---

### Task 4: Skill Loader（skill_loader.py）

**Files:**
- Create: `backend/app/agents/shared/skill_loader.py`
- Test: `backend/tests/agents/shared/test_skill_loader.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agents/shared/test_skill_loader.py
import pytest
import os
import tempfile
from app.agents.shared.skill_loader import SkillLoader

def test_skill_loader_list_skills():
    """测试列出所有技能"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建测试技能
        skill_dir = os.path.join(tmpdir, "test-skill")
        os.makedirs(skill_dir)
        skill_content = """---
name: "test-skill"
description: "测试技能"
version: "1.0.0"
---

# 测试技能

## 何时使用
这是一个测试技能。
"""
        skill_path = os.path.join(skill_dir, "SKILL.md")
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(skill_content)
        
        loader = SkillLoader(tmpdir)
        skills = loader.list_skills()
        
        assert len(skills) == 1
        assert skills[0]["name"] == "test-skill"
        assert skills[0]["description"] == "测试技能"

def test_skill_loader_activate_skill():
    """测试激活技能"""
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建测试技能
        skill_dir = os.path.join(tmpdir, "test-skill")
        os.makedirs(skill_dir)
        skill_content = """---
name: "test-skill"
description: "测试技能"
version: "1.0.0"
---

# 测试技能

## 何时使用
这是一个测试技能。

## 评估标准
- 标准1
- 标准2
"""
        skill_path = os.path.join(skill_dir, "SKILL.md")
        with open(skill_path, "w", encoding="utf-8") as f:
            f.write(skill_content)
        
        loader = SkillLoader(tmpdir)
        skill = loader.activate_skill("test-skill")
        
        assert skill.name == "test-skill"
        assert "测试技能" in skill.content
        assert "评估标准" in skill.content
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/test_skill_loader.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'app.agents.shared.skill_loader'"

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/agents/shared/skill_loader.py
from __future__ import annotations
import os
import yaml
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger("interview-boss")

@dataclass
class Skill:
    """技能数据类"""
    name: str
    description: str
    content: str
    version: str = "1.0.0"
    metadata: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}

class SkillLoader:
    """Skill加载器，支持三阶段渐进式披露"""
    
    def __init__(self, skills_dir: str):
        self.skills_dir = skills_dir
        self.loaded_skills: Dict[str, Skill] = {}
        self._skill_metadata: List[Dict[str, Any]] = []
        self._discover_skills()
    
    def _discover_skills(self):
        """发现所有技能（Level 1：元数据）"""
        if not os.path.exists(self.skills_dir):
            logger.warning(f"Skills directory not found: {self.skills_dir}")
            return
        
        for item in os.listdir(self.skills_dir):
            skill_dir = os.path.join(self.skills_dir, item)
            if os.path.isdir(skill_dir):
                skill_md = os.path.join(skill_dir, "SKILL.md")
                if os.path.exists(skill_md):
                    metadata = self._load_metadata(skill_md)
                    if metadata:
                        self._skill_metadata.append(metadata)
        
        logger.info(f"Discovered {len(self._skill_metadata)} skills")
    
    def _load_metadata(self, skill_md: str) -> Optional[Dict[str, Any]]:
        """加载技能元数据（Level 1）"""
        try:
            with open(skill_md, 'r', encoding='utf-8') as f:
                content = f.read()
            
            if content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    metadata = yaml.safe_load(parts[1])
                    return metadata
        except Exception as e:
            logger.error(f"Failed to load metadata from {skill_md}: {e}")
        
        return None
    
    def list_skills(self) -> List[Dict[str, Any]]:
        """Level 1：返回所有 skill 的元数据"""
        return self._skill_metadata
    
    def activate_skill(self, skill_name: str) -> Skill:
        """Level 2：加载完整 SKILL.md"""
        if skill_name in self.loaded_skills:
            return self.loaded_skills[skill_name]
        
        # 查找技能目录
        skill_dir = os.path.join(self.skills_dir, skill_name)
        if not os.path.exists(skill_dir):
            raise ValueError(f"Skill not found: {skill_name}")
        
        skill_md = os.path.join(skill_dir, "SKILL.md")
        if not os.path.exists(skill_md):
            raise ValueError(f"SKILL.md not found for skill: {skill_name}")
        
        # 加载完整内容
        with open(skill_md, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 解析frontmatter和正文
        metadata = {}
        body = content
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                try:
                    metadata = yaml.safe_load(parts[1])
                    body = parts[2].strip()
                except yaml.YAMLError as e:
                    logger.error(f"Failed to parse YAML: {e}")
        
        skill = Skill(
            name=metadata.get('name', skill_name),
            description=metadata.get('description', ''),
            content=body,
            version=metadata.get('version', '1.0.0'),
            metadata=metadata
        )
        
        self.loaded_skills[skill_name] = skill
        logger.info(f"Activated skill: {skill_name}")
        return skill
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/test_skill_loader.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/shared/skill_loader.py backend/tests/agents/shared/test_skill_loader.py
git commit -m "feat(agents): add skill loader with progressive disclosure"
```

---

### Task 5: ReAct Agent基类（react_agent.py）

**Files:**
- Create: `backend/app/agents/shared/react_agent.py`
- Test: `backend/tests/agents/shared/test_react_agent.py`

**Dependencies:** Task 1 (state.py), Task 2 (tools.py)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agents/shared/test_react_agent.py
import pytest
from app.agents.shared.react_agent import ReActAgent
from app.agents.shared.state import ReActState, Thought, Action

class MockReActAgent(ReActAgent):
    """模拟ReAct Agent"""
    
    async def _think(self, state: ReActState) -> Thought:
        """模拟思考"""
        if state.loop_count == 0:
            return Thought(
                should_call_tool=True,
                tool="mock_tool",
                params={"test": "value"},
                reasoning="需要调用工具"
            )
        else:
            return Thought(
                answer="这是最终回答",
                reasoning="已经完成任务"
            )
    
    async def _execute_action(self, state: ReActState, action: Action) -> dict:
        """模拟执行行动"""
        return {"result": "mock_result"}

def test_react_agent_initialization():
    """测试ReAct Agent初始化"""
    agent = MockReActAgent()
    assert agent.max_loops == 10

def test_react_agent_should_stop():
    """测试停止条件"""
    agent = MockReActAgent()
    
    state1 = ReActState(
        user_message="测试",
        conversation_id="test-123",
        user_id=1,
        loop_count=5
    )
    assert agent._should_stop(state1) is False
    
    state2 = ReActState(
        user_message="测试",
        conversation_id="test-123",
        user_id=1,
        loop_count=15
    )
    assert agent._should_stop(state2) is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/test_react_agent.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'app.agents.shared.react_agent'"

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/agents/shared/react_agent.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import AsyncGenerator, Dict, Any, Optional
import logging
import time

from app.agents.shared.state import ReActState, Thought, Action
from app.agents.shared.tools import ToolRegistry

logger = logging.getLogger("interview-boss")

class ReActAgent(ABC):
    """ReAct Agent基类"""
    
    def __init__(self, max_loops: int = 10):
        self.max_loops = max_loops
        self.tool_registry = ToolRegistry()
    
    async def run(self, state: ReActState) -> AsyncGenerator[Dict[str, Any], None]:
        """运行ReAct循环"""
        state.max_loops = self.max_loops
        
        while not self._should_stop(state):
            state.loop_count += 1
            logger.info(f"ReAct loop {state.loop_count}/{self.max_loops}")
            
            # 1. LLM推理
            thought = await self._think(state)
            state.current_thought = thought.reasoning
            
            # 2. 决定行动
            action = self._decide_action(thought)
            
            # 3. 执行行动
            if action.type == "final_answer":
                yield {"type": "chunk", "content": action.answer}
                break
            
            result = await self._execute_action(state, action)
            state.observations.append(result)
            
            # 4. 生成中间事件
            yield {
                "type": "observation",
                "loop": state.loop_count,
                "action": action.dict(),
                "result": result
            }
        
        # 生成最终事件
        yield {
            "type": "done",
            "loops": state.loop_count,
            "observations": len(state.observations)
        }
    
    def _should_stop(self, state: ReActState) -> bool:
        """检查停止条件"""
        return state.loop_count >= state.max_loops
    
    def _decide_action(self, thought: Thought) -> Action:
        """根据推理决定行动"""
        if thought.should_activate_skill:
            return Action(type="activate_skill", skill_name=thought.skill_name)
        elif thought.should_call_tool:
            return Action(type="call_tool", tool=thought.tool, params=thought.params)
        else:
            return Action(type="final_answer", answer=thought.answer)
    
    @abstractmethod
    async def _think(self, state: ReActState) -> Thought:
        """LLM推理"""
        pass
    
    @abstractmethod
    async def _execute_action(self, state: ReActState, action: Action) -> dict:
        """执行行动"""
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/test_react_agent.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/shared/react_agent.py backend/tests/agents/shared/test_react_agent.py
git commit -m "feat(agents): add ReAct agent base class"
```

---

### Task 6: 面试官SOUL.md

**Files:**
- Create: `backend/app/agents/interview/SOUL.md`

**Dependencies:** 无

- [ ] **Step 1: 创建面试官SOUL.md**

```markdown
---
name: "interview-interviewer"
version: "1.0.0"
description: "专业的技术面试官，擅长考察候选人的技术能力和思维过程"
personality: "专业、友善、有耐心"
tone: "清晰、有层次感"
values: ["公平", "专业", "尊重"]
constraints: ["不问与岗位无关的问题", "不给候选人压力"]
---

# 面试官 SOUL

## 人格
你是一位专业的技术面试官，擅长考察候选人的技术能力和思维过程。你的目标是全面评估候选人的技术水平、解决问题的能力和沟通表达能力。

## 风格
- 提问清晰、有层次感，从基础到深入
- 给候选人思考空间，不急于打断
- 适时追问，深入了解候选人理解深度
- 保持专业友善的态度，营造良好的面试氛围

## 价值观
- **公平**：对所有候选人一视同仁，不偏不倚
- **专业**：专注于技术能力评估，不问无关问题
- **尊重**：尊重候选人的回答，不嘲笑或贬低

## 禁忌
- 不问与岗位无关的问题（如年龄、婚姻状况、政治观点等）
- 不给候选人压力或刁难
- 不透露面试评分标准
- 不在面试过程中表现出不耐烦

## 面试原则
1. **STAR法则**：对于行为面试问题，引导候选人按STAR法则回答
2. **一次一题**：每次只问一个问题，等候选人回答完再问下一个
3. **适时追问**：根据候选人回答的深度，决定是否追问
4. **客观评估**：基于候选人的实际表现评估，不凭印象打分
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/agents/interview/SOUL.md
git commit -m "feat(agents): add interviewer SOUL.md"
```

---

### Task 7: 面试官AGENTS.md

**Files:**
- Create: `backend/app/agents/interview/AGENTS.md`

**Dependencies:** 无

- [ ] **Step 1: 创建面试官AGENTS.md**

```markdown
# 面试官 Agent

## 可用技能
- `adaptive-difficulty`：自适应难度调整，根据候选人表现调整问题难度
- `algorithm-coding`：算法编程评估，考察候选人的算法能力
- `hr-soft-skills`：HR软技能评估，考察候选人的沟通、团队合作等软技能
- `interview-rhythm`：面试节奏控制，管理面试流程和时间
- `project-deep-dive`：项目深挖，深入了解候选人的项目经验
- `theory-qa`：理论问答，考察候选人的理论知识

## 可用工具
- `search_questions`：搜索面试题，根据关键词和条件搜索
- `draw_questions`：抽取高频题，从题库中抽取常见问题
- `evaluate_answer`：评估候选人的回答
- `ask_followup`：追问，深入了解候选人的理解
- `change_topic`：换题，转换面试话题
- `end_interview`：结束面试，生成面试总结

## 工作流程

### 1. 开场（前2分钟）
- 自我介绍
- 了解候选人背景（技术栈、工作经验）
- 说明面试流程

### 2. 提问阶段（主要时间）
- 一次一题，根据候选人回答调整难度
- 使用STAR法则评估行为面试问题
- 适时追问，深入了解候选人理解深度
- 记录候选人的关键回答

### 3. 评估阶段（实时）
- 评估候选人的技术能力
- 评估候选人的问题解决能力
- 评估候选人的沟通表达能力
- 记录评估结果

### 4. 收尾阶段（最后2分钟）
- 总结面试表现
- 允许候选人提问
- 感谢候选人参与

## 决策规则

### 何时追问
- 候选人回答过于简短
- 候选人回答有明显漏洞
- 候选人回答有亮点值得深入

### 何时换题
- 候选人完全不会回答
- 已经充分了解候选人在该领域的能力
- 时间安排需要

### 何时结束
- 所有计划问题已问完
- 候选人明确表示不想继续
- 时间已到

## 技能使用指南

### adaptive-difficulty
- 当候选人连续答对时，增加难度
- 当候选人连续答错时，降低难度
- 保持适度的挑战性

### star-method
- 对于行为面试问题，引导候选人按STAR法则回答
- 评估回答的完整性（情境、任务、行动、结果）

### interview-rhythm
- 控制面试节奏，避免过快或过慢
- 合理分配时间，确保覆盖所有重要领域
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/agents/interview/AGENTS.md
git commit -m "feat(agents): add interviewer AGENTS.md"
```

---

### Task 8: 技能工具（skill_tools.py）

**Files:**
- Create: `backend/app/agents/shared/tools/skill_tools.py`
- Test: `backend/tests/agents/shared/tools/test_skill_tools.py`

**Dependencies:** Task 2 (tools.py), Task 4 (skill_loader.py)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agents/shared/tools/test_skill_tools.py
import pytest
import asyncio
from app.agents.shared.tools.skill_tools import ListSkillsTool, ActivateSkillTool
from app.agents.shared.skill_loader import SkillLoader

def test_list_skills_tool():
    """测试列出技能工具"""
    # 创建模拟的SkillLoader
    class MockSkillLoader:
        def list_skills(self):
            return [
                {"name": "test-skill", "description": "测试技能"}
            ]
    
    tool = ListSkillsTool(skill_loader=MockSkillLoader())
    result = asyncio.run(tool.execute({}))
    
    assert "skills" in result
    assert len(result["skills"]) == 1
    assert result["skills"][0]["name"] == "test-skill"

def test_activate_skill_tool():
    """测试激活技能工具"""
    # 创建模拟的SkillLoader
    class MockSkill:
        name = "test-skill"
        content = "测试技能内容"
    
    class MockSkillLoader:
        def activate_skill(self, skill_name):
            return MockSkill()
    
    tool = ActivateSkillTool(skill_loader=MockSkillLoader())
    result = asyncio.run(tool.execute({"skill_name": "test-skill"}))
    
    assert result["skill_name"] == "test-skill"
    assert "测试技能内容" in result["content"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/tools/test_skill_tools.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/agents/shared/tools/skill_tools.py
from __future__ import annotations
from typing import Dict, Any
from app.agents.shared.tools import Tool
from app.agents.shared.skill_loader import SkillLoader

class ListSkillsTool(Tool):
    """列出所有可用技能"""
    name = "list_skills"
    description = "发现所有可用技能，返回技能名称和描述"
    
    def __init__(self, skill_loader: SkillLoader):
        self.skill_loader = skill_loader
    
    async def execute(self, params: dict) -> dict:
        """执行列出技能"""
        skills = self.skill_loader.list_skills()
        return {"skills": skills}

class ActivateSkillTool(Tool):
    """激活指定技能"""
    name = "activate_skill"
    description = "激活指定技能，加载完整的技能指令"
    
    def __init__(self, skill_loader: SkillLoader):
        self.skill_loader = skill_loader
    
    async def execute(self, params: dict) -> dict:
        """执行激活技能"""
        skill_name = params.get("skill_name")
        if not skill_name:
            raise ValueError("skill_name is required")
        
        skill = self.skill_loader.activate_skill(skill_name)
        return {
            "skill_name": skill.name,
            "content": skill.content,
            "description": skill.description
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/tools/test_skill_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/shared/tools/skill_tools.py backend/tests/agents/shared/tools/test_skill_tools.py
git commit -m "feat(agents): add skill tools"
```

---

### Task 9: 检索工具（search_tools.py）

**Files:**
- Create: `backend/app/agents/shared/tools/search_tools.py`
- Test: `backend/tests/agents/shared/tools/test_search_tools.py`

**Dependencies:** Task 2 (tools.py)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agents/shared/tools/test_search_tools.py
import pytest
import asyncio
from app.agents.shared.tools.search_tools import SearchQuestionsTool, DrawQuestionsTool

def test_search_questions_tool():
    """测试搜索面试题工具"""
    # 创建模拟的搜索函数
    async def mock_search(query, filters=None):
        return [
            {"id": 1, "question": "测试问题1", "cat1": "技术"},
            {"id": 2, "question": "测试问题2", "cat1": "技术"}
        ]
    
    tool = SearchQuestionsTool(search_func=mock_search)
    result = asyncio.run(tool.execute({"query": "技术问题"}))
    
    assert "questions" in result
    assert len(result["questions"]) == 2

def test_draw_questions_tool():
    """测试抽取高频题工具"""
    # 创建模拟的抽取函数
    async def mock_draw(count=5, cat1=None, question_type=None):
        return [
            {"id": 1, "question": "高频问题1"},
            {"id": 2, "question": "高频问题2"}
        ]
    
    tool = DrawQuestionsTool(draw_func=mock_draw)
    result = asyncio.run(tool.execute({"count": 2}))
    
    assert "questions" in result
    assert len(result["questions"]) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/tools/test_search_tools.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/agents/shared/tools/search_tools.py
from __future__ import annotations
from typing import Dict, Any, List, Callable, Awaitable
from app.agents.shared.tools import Tool

class SearchQuestionsTool(Tool):
    """搜索面试题"""
    name = "search_questions"
    description = "根据关键词和条件搜索面试题"
    
    def __init__(self, search_func: Callable[..., Awaitable[List[dict]]]):
        self.search_func = search_func
    
    async def execute(self, params: dict) -> dict:
        """执行搜索"""
        query = params.get("query", "")
        filters = params.get("filters", {})
        
        questions = await self.search_func(query, filters)
        return {"questions": questions}

class DrawQuestionsTool(Tool):
    """抽取高频题"""
    name = "draw_questions"
    description = "从题库中抽取高频面试题"
    
    def __init__(self, draw_func: Callable[..., Awaitable[List[dict]]]):
        self.draw_func = draw_func
    
    async def execute(self, params: dict) -> dict:
        """执行抽取"""
        count = params.get("count", 5)
        cat1 = params.get("cat1")
        question_type = params.get("question_type")
        
        questions = await self.draw_func(count, cat1, question_type)
        return {"questions": questions}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/tools/test_search_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/shared/tools/search_tools.py backend/tests/agents/shared/tools/test_search_tools.py
git commit -m "feat(agents): add search tools"
```

---

### Task 10: 流程控制工具（flow_tools.py）

**Files:**
- Create: `backend/app/agents/shared/tools/flow_tools.py`
- Test: `backend/tests/agents/shared/tools/test_flow_tools.py`

**Dependencies:** Task 2 (tools.py)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agents/shared/tools/test_flow_tools.py
import pytest
import asyncio
from app.agents.shared.tools.flow_tools import (
    AskFollowupTool, 
    ChangeTopicTool, 
    EndInterviewTool,
    EvaluateAnswerTool
)

def test_ask_followup_tool():
    """测试追问工具"""
    tool = AskFollowupTool()
    result = asyncio.run(tool.execute({"question": "能详细说说吗？"}))
    
    assert result["action"] == "ask_followup"
    assert result["question"] == "能详细说说吗？"

def test_change_topic_tool():
    """测试换题工具"""
    tool = ChangeTopicTool()
    result = asyncio.run(tool.execute({"new_topic": "算法"}))
    
    assert result["action"] == "change_topic"
    assert result["new_topic"] == "算法"

def test_end_interview_tool():
    """测试结束面试工具"""
    tool = EndInterviewTool()
    result = asyncio.run(tool.execute({"summary": "面试表现良好"}))
    
    assert result["action"] == "end_interview"
    assert result["summary"] == "面试表现良好"

def test_evaluate_answer_tool():
    """测试评估回答工具"""
    tool = EvaluateAnswerTool()
    result = asyncio.run(tool.execute({
        "answer": "候选人回答内容",
        "criteria": ["技术深度", "表达清晰"]
    }))
    
    assert result["action"] == "evaluate_answer"
    assert "evaluation" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/tools/test_flow_tools.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/agents/shared/tools/flow_tools.py
from __future__ import annotations
from typing import Dict, Any, List
from app.agents.shared.tools import Tool

class AskFollowupTool(Tool):
    """追问工具"""
    name = "ask_followup"
    description = "向候选人追问，深入了解其理解"
    
    async def execute(self, params: dict) -> dict:
        """执行追问"""
        question = params.get("question", "")
        return {
            "action": "ask_followup",
            "question": question
        }

class ChangeTopicTool(Tool):
    """换题工具"""
    name = "change_topic"
    description = "转换面试话题"
    
    async def execute(self, params: dict) -> dict:
        """执行换题"""
        new_topic = params.get("new_topic", "")
        return {
            "action": "change_topic",
            "new_topic": new_topic
        }

class EndInterviewTool(Tool):
    """结束面试工具"""
    name = "end_interview"
    description = "结束面试并生成总结"
    
    async def execute(self, params: dict) -> dict:
        """执行结束面试"""
        summary = params.get("summary", "")
        return {
            "action": "end_interview",
            "summary": summary
        }

class EvaluateAnswerTool(Tool):
    """评估回答工具"""
    name = "evaluate_answer"
    description = "评估候选人的回答"
    
    async def execute(self, params: dict) -> dict:
        """执行评估"""
        answer = params.get("answer", "")
        criteria = params.get("criteria", [])
        
        # 这里可以集成LLM进行评估
        evaluation = {
            "answer_length": len(answer),
            "criteria_count": len(criteria),
            "has_content": bool(answer.strip())
        }
        
        return {
            "action": "evaluate_answer",
            "evaluation": evaluation
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/tools/test_flow_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/shared/tools/flow_tools.py backend/tests/agents/shared/tools/test_flow_tools.py
git commit -m "feat(agents): add flow control tools"
```

---

### Task 11: 记忆工具（memory_tools.py）

**Files:**
- Create: `backend/app/agents/shared/tools/memory_tools.py`
- Test: `backend/tests/agents/shared/tools/test_memory_tools.py`

**Dependencies:** Task 2 (tools.py)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agents/shared/tools/test_memory_tools.py
import pytest
import asyncio
from app.agents.shared.tools.memory_tools import RecallMemoriesTool, ExtractMemoryTool

def test_recall_memories_tool():
    """测试召回记忆工具"""
    async def mock_recall(query, user_id):
        return [
            {"id": 1, "content": "记忆1"},
            {"id": 2, "content": "记忆2"}
        ]
    
    tool = RecallMemoriesTool(recall_func=mock_recall)
    result = asyncio.run(tool.execute({"query": "技术面试", "user_id": 1}))
    
    assert "memories" in result
    assert len(result["memories"]) == 2

def test_extract_memory_tool():
    """测试提取记忆工具"""
    async def mock_extract(content, user_id):
        return {"id": 3, "content": content, "extracted": True}
    
    tool = ExtractMemoryTool(extract_func=mock_extract)
    result = asyncio.run(tool.execute({
        "content": "候选人擅长Python",
        "user_id": 1
    }))
    
    assert result["extracted"] is True
    assert result["content"] == "候选人擅长Python"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/tools/test_memory_tools.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/agents/shared/tools/memory_tools.py
from __future__ import annotations
from typing import Dict, Any, List, Callable, Awaitable
from app.agents.shared.tools import Tool

class RecallMemoriesTool(Tool):
    """召回相关记忆"""
    name = "recall_memories"
    description = "根据查询召回相关的长期记忆"
    
    def __init__(self, recall_func: Callable[..., Awaitable[List[dict]]]):
        self.recall_func = recall_func
    
    async def execute(self, params: dict) -> dict:
        """执行召回记忆"""
        query = params.get("query", "")
        user_id = params.get("user_id")
        
        memories = await self.recall_func(query, user_id)
        return {"memories": memories}

class ExtractMemoryTool(Tool):
    """提取新记忆"""
    name = "extract_memory"
    description = "从对话中提取新的长期记忆"
    
    def __init__(self, extract_func: Callable[..., Awaitable[dict]]):
        self.extract_func = extract_func
    
    async def execute(self, params: dict) -> dict:
        """执行提取记忆"""
        content = params.get("content", "")
        user_id = params.get("user_id")
        
        result = await self.extract_func(content, user_id)
        return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend uv run pytest backend/tests/agents/shared/tools/test_memory_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/shared/tools/memory_tools.py backend/tests/agents/shared/tools/test_memory_tools.py
git commit -m "feat(agents): add memory tools"
```

---

### Task 12: 面试官ReAct Agent实现

**Files:**
- Create: `backend/app/agents/interview/react_interviewer.py`
- Test: `backend/tests/agents/interview/test_react_interviewer.py`

**Dependencies:** Task 5 (react_agent.py), Task 6 (SOUL.md), Task 7 (AGENTS.md), Task 8-11 (tools)

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/agents/interview/test_react_interviewer.py
import pytest
from app.agents.interview.react_interviewer import InterviewReActAgent
from app.agents.shared.state import ReActState

def test_interview_react_agent_initialization():
    """测试面试官ReAct Agent初始化"""
    agent = InterviewReActAgent(agent_dir="backend/app/agents/interview")
    
    assert agent.soul is not None
    assert agent.agents_config is not None
    assert "面试官" in agent.soul.get("body", "")

def test_interview_react_agent_build_prompt():
    """测试构建提示词"""
    agent = InterviewReActAgent(agent_dir="backend/app/agents/interview")
    
    state = ReActState(
        user_message="你好，我是候选人",
        conversation_id="test-123",
        user_id=1
    )
    
    prompt = agent._build_think_prompt(state)
    
    assert "面试官" in prompt
    assert "候选人" in prompt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend uv run pytest backend/tests/agents/interview/test_react_interviewer.py -v`
Expected: FAIL with "ModuleNotFoundError"

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/agents/interview/react_interviewer.py
from __future__ import annotations
import os
from typing import Dict, Any, Optional
import logging

from app.agents.shared.react_agent import ReActAgent
from app.agents.shared.state import ReActState, Thought, Action
from app.agents.shared.soul_loader import SoulLoader
from app.agents.shared.skill_loader import SkillLoader
from app.agents.shared.tools import ToolRegistry
from app.agents.shared.tools.skill_tools import ListSkillsTool, ActivateSkillTool
from app.agents.shared.tools.flow_tools import (
    AskFollowupTool, ChangeTopicTool, EndInterviewTool, EvaluateAnswerTool
)
from app.services import llm

logger = logging.getLogger("interview-boss")

class InterviewReActAgent(ReActAgent):
    """面试官ReAct Agent"""
    
    def __init__(self, agent_dir: str, max_loops: int = 10):
        super().__init__(max_loops=max_loops)
        self.agent_dir = agent_dir
        
        # 加载SOUL.md和AGENTS.md
        soul_loader = SoulLoader()
        self.soul = soul_loader.load_soul(agent_dir)
        self.agents_config = soul_loader.load_agents(agent_dir)
        
        # 加载技能
        skills_dir = os.path.join(agent_dir, "skills")
        self.skill_loader = SkillLoader(skills_dir)
        
        # 注册工具
        self._register_tools()
        
        logger.info(f"Initialized InterviewReActAgent with {len(self.tool_registry.tools)} tools")
    
    def _register_tools(self):
        """注册所有工具"""
        # 技能工具
        self.tool_registry.register_tool(ListSkillsTool(self.skill_loader))
        self.tool_registry.register_tool(ActivateSkillTool(self.skill_loader))
        
        # 流程控制工具
        self.tool_registry.register_tool(AskFollowupTool())
        self.tool_registry.register_tool(ChangeTopicTool())
        self.tool_registry.register_tool(EndInterviewTool())
        self.tool_registry.register_tool(EvaluateAnswerTool())
    
    async def _think(self, state: ReActState) -> Thought:
        """LLM推理"""
        prompt = self._build_think_prompt(state)
        
        # 调用LLM进行推理
        response = await llm.generate(
            prompt=prompt,
            model=state.model
        )
        
        # 解析LLM响应
        thought = self._parse_thought(response)
        return thought
    
    def _build_think_prompt(self, state: ReActState) -> str:
        """构建推理提示词"""
        # 基础提示词
        prompt = f"""你是一位专业的技术面试官。

## 你的身份
{self.soul.get('body', '')}

## 可用技能
{self._format_skills()}

## 可用工具
{self._format_tools()}

## 当前对话
用户消息：{state.user_message}

## 历史消息
{self._format_history(state.message_history[-5:])}

## 你的任务
根据用户的回答，决定下一步行动：
1. 如果需要使用技能，返回 activate_skill
2. 如果需要使用工具，返回 call_tool
3. 如果可以生成回复，返回 final_answer

请以JSON格式返回你的决策：
{{
    "reasoning": "你的推理过程",
    "should_activate_skill": true/false,
    "skill_name": "技能名称（如果需要）",
    "should_call_tool": true/false,
    "tool": "工具名称（如果需要）",
    "params": {{}},
    "answer": "最终回答（如果不需要工具）"
}}
"""
        return prompt
    
    def _format_skills(self) -> str:
        """格式化技能列表"""
        skills = self.skill_loader.list_skills()
        if not skills:
            return "无可用技能"
        
        lines = []
        for skill in skills:
            lines.append(f"- {skill['name']}: {skill['description']}")
        return "\n".join(lines)
    
    def _format_tools(self) -> str:
        """格式化工具列表"""
        tools = self.tool_registry.list_tools()
        if not tools:
            return "无可用工具"
        
        lines = []
        for tool in tools:
            lines.append(f"- {tool['name']}: {tool['description']}")
        return "\n".join(lines)
    
    def _format_history(self, history: list) -> str:
        """格式化历史消息"""
        if not history:
            return "无历史消息"
        
        lines = []
        for msg in history[-5:]:
            role = "面试官" if msg.get("role") == "assistant" else "候选人"
            content = msg.get("content", "")[:100]
            lines.append(f"{role}: {content}")
        return "\n".join(lines)
    
    def _parse_thought(self, response: str) -> Thought:
        """解析LLM响应"""
        import json
        
        try:
            # 尝试解析JSON
            data = json.loads(response)
            return Thought(
                should_activate_skill=data.get("should_activate_skill", False),
                skill_name=data.get("skill_name"),
                should_call_tool=data.get("should_call_tool", False),
                tool=data.get("tool"),
                params=data.get("params"),
                answer=data.get("answer"),
                reasoning=data.get("reasoning", "")
            )
        except json.JSONDecodeError:
            # 如果不是JSON，作为最终回答
            return Thought(
                answer=response,
                reasoning="直接生成回答"
            )
    
    async def _execute_action(self, state: ReActState, action: Action) -> dict:
        """执行行动"""
        if action.type == "activate_skill":
            # 激活技能
            skill = self.skill_loader.activate_skill(action.skill_name)
            return {
                "type": "skill_activated",
                "skill_name": skill.name,
                "content": skill.content
            }
        elif action.type == "call_tool":
            # 调用工具
            result = await self.tool_registry.call_tool(action.tool, action.params)
            return {
                "type": "tool_result",
                "tool": action.tool,
                "result": result
            }
        else:
            return {"type": "unknown_action"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend uv run pytest backend/tests/agents/interview/test_react_interviewer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/interview/react_interviewer.py backend/tests/agents/interview/test_react_interviewer.py
git commit -m "feat(agents): implement interview ReAct agent"
```

---

### Task 13: 单元测试套件

**Files:**
- Create: `backend/tests/agents/test_all.py`

**Dependencies:** 所有实现任务

- [ ] **Step 1: 创建综合测试套件**

```python
# backend/tests/agents/test_all.py
import pytest
import asyncio

class TestReActAgentSuite:
    """ReAct Agent综合测试套件"""
    
    def test_state_definitions(self):
        """测试状态定义"""
        from app.agents.shared.state import ReActState, Thought, Action
        
        state = ReActState(
            user_message="测试",
            conversation_id="test-123",
            user_id=1
        )
        assert state.user_message == "测试"
        
        thought = Thought(
            should_call_tool=True,
            tool="test_tool",
            params={"test": "value"}
        )
        assert thought.should_call_tool is True
        
        action = Action(type="call_tool", tool="test_tool")
        assert action.type == "call_tool"
    
    def test_tool_registry(self):
        """测试工具注册表"""
        from app.agents.shared.tools import Tool, ToolRegistry
        
        class TestTool(Tool):
            name = "test_tool"
            description = "测试工具"
            async def execute(self, params):
                return {"result": "test"}
        
        registry = ToolRegistry()
        tool = TestTool()
        registry.register_tool(tool)
        
        assert "test_tool" in registry.tools
        result = asyncio.run(registry.call_tool("test_tool", {}))
        assert result["result"] == "test"
    
    def test_soul_loader(self):
        """测试Soul Loader"""
        from app.agents.shared.soul_loader import SoulLoader
        import tempfile
        import os
        
        with tempfile.TemporaryDirectory() as tmpdir:
            soul_content = """---
name: "test"
---
# 测试
"""
            with open(os.path.join(tmpdir, "SOUL.md"), "w") as f:
                f.write(soul_content)
            
            loader = SoulLoader()
            result = loader.load_soul(tmpdir)
            assert result["name"] == "test"
    
    def test_skill_loader(self):
        """测试Skill Loader"""
        from app.agents.shared.skill_loader import SkillLoader
        import tempfile
        import os
        
        with tempfile.TemporaryDirectory() as tmpdir:
            skill_dir = os.path.join(tmpdir, "test-skill")
            os.makedirs(skill_dir)
            skill_content = """---
name: "test-skill"
description: "测试技能"
---
# 测试技能
"""
            with open(os.path.join(skill_dir, "SKILL.md"), "w") as f:
                f.write(skill_content)
            
            loader = SkillLoader(tmpdir)
            skills = loader.list_skills()
            assert len(skills) == 1
            assert skills[0]["name"] == "test-skill"
```

- [ ] **Step 2: Run all tests**

Run: `docker compose exec backend uv run pytest backend/tests/agents/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/agents/test_all.py
git commit -m "test(agents): add comprehensive test suite"
```

---

### Task 14: 集成测试

**Files:**
- Create: `backend/tests/agents/integration/test_react_integration.py`

**Dependencies:** Task 12, Task 13

- [ ] **Step 1: 创建集成测试**

```python
# backend/tests/agents/integration/test_react_integration.py
import pytest
import asyncio
from app.agents.interview.react_interviewer import InterviewReActAgent
from app.agents.shared.state import ReActState

@pytest.mark.asyncio
async def test_interview_react_agent_full_flow():
    """测试完整的面试流程"""
    agent = InterviewReActAgent(agent_dir="backend/app/agents/interview")
    
    state = ReActState(
        user_message="你好，我是候选人，我有3年Python开发经验",
        conversation_id="test-integration-123",
        user_id=1
    )
    
    # 运行ReAct循环
    events = []
    async for event in agent.run(state):
        events.append(event)
    
    # 验证事件
    assert len(events) > 0
    assert any(e.get("type") == "done" for e in events)

@pytest.mark.asyncio
async def test_interview_react_agent_with_skill():
    """测试使用技能的面试流程"""
    agent = InterviewReActAgent(agent_dir="backend/app/agents/interview")
    
    state = ReActState(
        user_message="请用STAR法则评估我的回答",
        conversation_id="test-skill-123",
        user_id=1,
        active_skills=["star-method"]
    )
    
    # 运行ReAct循环
    events = []
    async for event in agent.run(state):
        events.append(event)
    
    # 验证事件
    assert len(events) > 0
```

- [ ] **Step 2: Run integration tests**

Run: `docker compose exec backend uv run pytest backend/tests/agents/integration/ -v`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add backend/tests/agents/integration/test_react_integration.py
git commit -m "test(agents): add integration tests"
```

---

### Task 15: 性能优化

**Files:**
- Modify: `backend/app/agents/shared/react_agent.py`
- Modify: `backend/app/agents/interview/react_interviewer.py`

**Dependencies:** Task 14

- [ ] **Step 1: 优化ReAct循环**

```python
# 优化点：
# 1. 添加缓存机制
# 2. 优化提示词长度
# 3. 添加超时控制
# 4. 优化工具调用

# 在react_agent.py中添加：
class ReActAgent(ABC):
    def __init__(self, max_loops: int = 10, timeout: int = 30):
        self.max_loops = max_loops
        self.timeout = timeout
        self.tool_registry = ToolRegistry()
        self._cache = {}  # 添加缓存
```

- [ ] **Step 2: 运行性能测试**

Run: `docker compose exec backend uv run pytest backend/tests/agents/ -v --durations=10`
Expected: 所有测试通过，显示性能数据

- [ ] **Step 3: Commit**

```bash
git add backend/app/agents/shared/react_agent.py backend/app/agents/interview/react_interviewer.py
git commit -m "perf(agents): optimize ReAct agent performance"
```

---

## 验证清单

- [ ] 所有单元测试通过
- [ ] 所有集成测试通过
- [ ] 性能测试显示可接受的响应时间
- [ ] 现有API接口保持向后兼容
- [ ] 文档更新完成
- [ ] 代码审查通过

---

## 执行顺序

### Wave 1（并行）：
- Task 1: 状态定义
- Task 2: 工具注册表基类
- Task 3: Soul Loader
- Task 4: Skill Loader

### Wave 2（部分并行）：
- Task 5: ReAct Agent基类（依赖Task 1,2）
- Task 6: 面试官SOUL.md（无依赖）
- Task 7: 面试官AGENTS.md（无依赖）

### Wave 3（并行）：
- Task 8: 技能工具（依赖Task 2,4）
- Task 9: 检索工具（依赖Task 2）
- Task 10: 流程控制工具（依赖Task 2）
- Task 11: 记忆工具（依赖Task 2）

### Wave 4（依赖Wave 3）：
- Task 12: 面试官ReAct Agent实现
- Task 13: 单元测试套件

### Wave 5（依赖Wave 4）：
- Task 14: 集成测试
- Task 15: 性能优化
