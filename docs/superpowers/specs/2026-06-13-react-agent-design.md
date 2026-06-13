# InterviewBoss 面试 Chatbot Agent 架构设计

## 背景

当前 InterviewBoss 的面试 chatbot 使用纯 async pipeline（pipeline.py），虽然已经从 LangGraph 迁移，但路由逻辑仍然是预定义的 if/elif，缺乏灵活性。用户希望 LLM 能自己决定下一步做什么，实现更智能的面试流程控制、检索策略选择和技能调用。

## 设计目标

1. **智能路由**：LLM 自己决定下一步做什么，而不是预定义的 if/elif
2. **Skill 驱动**：复用现有 skills 系统，让 LLM 动态选择和激活技能
3. **渐进式披露**：三阶段上下文管理，减少 token 开销
4. **向后兼容**：保持现有 API 接口不变，渐进式迁移

## 架构设计

### 整体架构

```
用户消息 → ReAct 循环 → Skill 系统 → 工具执行 → 观察 → 继续推理
```

### 核心组件

#### 1. ReAct Agent（主循环）

负责管理推理→行动→观察的循环，让 LLM 自己决定下一步做什么。

```python
class ReActAgent:
    async def run(self, user_message: str, context: dict) -> AsyncGenerator[dict, None]:
        state = self._initial_state(user_message, context)
        
        while True:
            # 1. LLM 推理
            thought = await self._think(state)
            
            # 2. 决定行动
            action = await self._decide_action(thought)
            
            # 3. 执行行动
            if action.type == "activate_skill":
                result = await self._activate_skill(action.skill_name)
                state.observations.append(result)
            elif action.type == "call_tool":
                result = await self._call_tool(action.tool, action.params)
                state.observations.append(result)
            elif action.type == "final_answer":
                yield {"type": "chunk", "content": action.answer}
                break
            
            # 4. 检查终止条件
            if self._should_stop(state):
                break
```

#### 2. SOUL.md + AGENTS.md + SKILL.md 架构（2026最佳实践）

采用2026年主流的三层架构，实现高度可配置和可复用的agent设计：

**目录结构**

```
agents/
├── shared/                    # 可重复的基建（代码）
│   ├── state.py              # 状态定义
│   ├── events.py             # 事件格式化
│   ├── tools.py              # 工具注册表基类
│   ├── skill_loader.py       # Skill加载器
│   ├── react_agent.py        # ReAct循环基类
│   └── soul_loader.py        # SOUL.md/AGENTS.md加载器
│
├── interview/                 # 面试官agent
│   ├── SOUL.md               # 面试官人格、价值观、边界
│   ├── AGENTS.md             # 面试官操作规则、工作流程
│   ├── skills/               # 面试官专用技能
│   │   ├── star-method/
│   │   │   └── SKILL.md
│   │   ├── behavioral-interview/
│   │   │   └── SKILL.md
│   │   └── technical-assessment/
│   │       └── SKILL.md
│   └── __init__.py
│
├── evaluator/                 # 评估agent（未来扩展）
│   ├── SOUL.md
│   ├── AGENTS.md
│   ├── skills/
│   └── __init__.py
│
└── coach/                     # 辅导agent（未来扩展）
    ├── SOUL.md
    ├── AGENTS.md
    ├── skills/
    └── __init__.py
```

**各层职责**

| 文件 | 职责 | 稳定性 | 类比 |
|------|------|--------|------|
| **SOUL.md** | 人格、价值观、语气、边界（"who the agent IS"） | 很少修改 | 人的性格 |
| **AGENTS.md** | 操作规则、工作流程、工具使用（"what the agent DOES"） | 按项目修改 | 人的职业规范 |
| **SKILL.md** | 任务特定知识、工作流程（可复用） | 按任务类型修改 | 人的技能 |

**示例：面试官 SOUL.md**

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
你是一位专业的技术面试官，擅长考察候选人的技术能力和思维过程。

## 风格
- 提问清晰、有层次感
- 给候选人思考空间，不急于打断
- 适时追问，深入了解候选人理解深度

## 禁忌
- 不问与岗位无关的问题
- 不给候选人压力或刁难
- 不透露面试评分标准
```

**示例：面试官 AGENTS.md**

```markdown
# 面试官 Agent

## 可用技能
- `star-method`：STAR法则评估
- `behavioral-interview`：行为面试技巧
- `technical-assessment`：技术能力评估

## 可用工具
- `search_questions`：搜索面试题
- `draw_questions`：抽取高频题
- `evaluate_answer`：评估回答

## 工作流程
1. 开场：自我介绍，了解候选人背景
2. 提问：一次一题，根据回答调整难度
3. 追问：深入了解候选人理解深度
4. 评估：实时评估候选人表现
5. 收尾：总结面试，允许候选人提问
```

**示例：SKILL.md**

```markdown
---
name: "star-method"
description: "STAR法则评估候选人的行为面试回答"
version: "1.0.0"
---

# STAR法则评估

## 何时使用
当候选人回答行为面试问题时，使用STAR法则评估其回答的完整性。

## 评估标准
- **Situation**：候选人是否清晰描述了情境
- **Task**：候选人是否明确了任务和目标
- **Action**：候选人是否详细说明了采取的行动
- **Result**：候选人是否量化了结果

## 评估流程
1. 识别候选人的回答是否包含STAR要素
2. 如果缺少某个要素，追问该要素
3. 评估每个要素的质量
4. 给出整体评估
```

**优势**

1. **开发新agent快**：只要修改md，配置skills就行
2. **非技术人员可参与**：人格、行为用markdown定义
3. **复用性高**：skills可以跨agent复用
4. **易于维护**：代码和配置分离
5. **符合2026标准**：SOUL.md/AGENTS.md/SKILL.md是主流

#### 3. Skill System（技能系统）

复用现有的 skills 系统，支持三阶段渐进式披露：

**Level 1 — 元数据（始终在上下文中）**
- 每个 skill 的 name 和 description（~100 tokens/skill）
- 在 system prompt 中作为 skill 目录

**Level 2 — 激活（按需加载）**
- LLM 调用 `activate_skill(skill_name)` 时加载完整 SKILL.md
- 懒加载：只在需要时加载

**Level 3 — 资源（条件触发）**
- SKILL.md 中引用的脚本和资源
- 按需加载，进一步减少上下文

#### 4. Tool Registry（工具注册表）

管理所有可用工具，包括：

**技能工具**
- `list_skills()`：发现可用技能
- `activate_skill(skill_name)`：激活技能
- `run_skill_script(script_name)`：执行技能脚本

**检索工具**
- `search_questions(query, filters)`：搜索面试题
- `draw_questions(count, filters)`：从题库抽取

**流程控制工具**
- `ask_followup(question)`：追问
- `change_topic(new_topic)`：换题
- `end_interview(summary)`：结束面试
- `evaluate_answer(answer, criteria)`：评估回答

**记忆工具**
- `recall_memories(query)`：召回相关记忆
- `extract_memory(content)`：提取新记忆

### 数据流

```
1. 用户发送消息
2. ReAct Agent 初始化状态
3. 进入循环：
   a. LLM 推理当前状态
   b. 决定下一步行动
   c. 执行行动（激活技能/调用工具/生成回复）
   d. 观察结果，更新状态
   e. 检查终止条件
4. 生成最终回复
5. 后台提取记忆
```

### 与现有系统的集成

#### 复用现有组件

- **Skills 系统**：复用 `SkillRegistry` 和 `build_skill_prompt()`
- **记忆系统**：复用 `recall_memories` 和 `extract_memory`
- **检索系统**：复用 `fts_retrieve` 和 `draw_questions`
- **流式输出**：复用现有的 SSE 机制
- **上下文构建**：复用 `build_interview_context()`

#### 现有Skills复用

项目已有6个成熟的skills，可以直接复用：

| Skill | 功能 | 复用方式 |
|-------|------|----------|
| `adaptive-difficulty` | 自适应难度调整 | 作为ReAct工具，LLM决定何时调用 |
| `algorithm-coding` | 算法编程评估 | 作为ReAct工具，LLM决定何时调用 |
| `hr-soft-skills` | HR软技能评估 | 作为ReAct工具，LLM决定何时调用 |
| `interview-rhythm` | 面试节奏控制 | 作为ReAct工具，LLM决定何时调用 |
| `project-deep-dive` | 项目深挖 | 作为ReAct工具，LLM决定何时调用 |
| `theory-qa` | 理论问答 | 作为ReAct工具，LLM决定何时调用 |

**复用方式**：
1. 将现有skills目录移动到新架构的`agents/interview/skills/`目录
2. 在AGENTS.md中声明可用skills
3. 在ReAct循环中，LLM可以动态激活这些skills
4. 无需修改skill内容，只需调整目录结构

#### 新增组件

- **ReAct Agent**：新的主循环，替代现有 pipeline
- **Tool Registry**：统一管理所有工具
- **Skill Loader**：支持三阶段渐进式披露
- **Soul Loader**：加载SOUL.md/AGENTS.md

### 迁移策略

#### 阶段 1：基础设施（1 周）

1. 实现 ReAct Agent 核心循环
2. 实现 Tool Registry
3. 实现 Skill Loader（三阶段加载）
4. 实现 Soul Loader（加载SOUL.md/AGENTS.md）

#### 阶段 2：Agent配置化（1 周）

1. 创建面试官agent目录结构
2. 编写面试官SOUL.md（人格、价值观、边界）
3. 编写面试官AGENTS.md（操作规则、工作流程）
4. 迁移现有skills到面试官agent目录

#### 阶段 3：工具集成（1 周）

1. 将现有工具封装为 ReAct 工具
2. 实现技能工具（list_skills, activate_skill）
3. 实现检索工具（search_questions, draw_questions）
4. 实现流程控制工具（ask_followup, change_topic, end_interview）

#### 阶段 4：测试与优化（1 周）

1. 单元测试：测试每个工具和组件
2. 集成测试：测试完整 ReAct 循环
3. 性能优化：优化 token 使用和响应速度
4. 向后兼容：确保现有 API 接口不变

### 技术细节

#### ReAct 循环实现

```python
async def _think(self, state: ReActState) -> Thought:
    """LLM 推理当前状态"""
    prompt = self._build_think_prompt(state)
    response = await self.llm.generate(prompt)
    return Thought.parse(response)

async def _decide_action(self, thought: Thought) -> Action:
    """根据推理决定行动"""
    if thought.should_activate_skill:
        return Action(type="activate_skill", skill_name=thought.skill_name)
    elif thought.should_call_tool:
        return Action(type="call_tool", tool=thought.tool, params=thought.params)
    else:
        return Action(type="final_answer", answer=thought.answer)
```

#### Soul Loader 实现

```python
class SoulLoader:
    """加载SOUL.md和AGENTS.md"""
    
    def load_soul(self, agent_dir: str) -> dict:
        """加载SOUL.md"""
        soul_path = os.path.join(agent_dir, "SOUL.md")
        return self._parse_md(soul_path)
    
    def load_agents(self, agent_dir: str) -> dict:
        """加载AGENTS.md"""
        agents_path = os.path.join(agent_dir, "AGENTS.md")
        return self._parse_md(agents_path)
    
    def _parse_md(self, file_path: str) -> dict:
        """解析Markdown文件，提取YAML frontmatter和正文"""
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 分离YAML frontmatter和正文
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1])
                body = parts[2].strip()
                return {**frontmatter, 'body': body}
        
        return {'body': content}
```

#### Skill Loader 实现

```python
class SkillLoader:
    def __init__(self, skills_dir: str):
        self.skills_dir = skills_dir
        self.registry = SkillRegistry(skills_dir)
        self.loaded_skills: dict[str, Skill] = {}
    
    def list_skills(self) -> list[dict]:
        """Level 1：返回所有 skill 的元数据"""
        return [
            {"name": skill.name, "description": skill.description}
            for skill in self.registry.skills
        ]
    
    def activate_skill(self, skill_name: str) -> Skill:
        """Level 2：加载完整 SKILL.md"""
        if skill_name not in self.loaded_skills:
            skill = self.registry.get_skill(skill_name)
            skill.load_full_content()
            self.loaded_skills[skill_name] = skill
        return self.loaded_skills[skill_name]
```

#### Tool Registry 实现

```python
class ToolRegistry:
    def __init__(self):
        self.tools: dict[str, Tool] = {}
    
    def register_tool(self, tool: Tool):
        """注册工具"""
        self.tools[tool.name] = tool
    
    async def call_tool(self, tool_name: str, params: dict) -> dict:
        """调用工具"""
        tool = self.tools.get(tool_name)
        if not tool:
            raise ValueError(f"Tool not found: {tool_name}")
        return await tool.execute(params)
```

### 风险与缓解

#### 风险 1：LLM 决策不准确

**缓解措施**：
- 提供清晰的工具描述和示例
- 实现回退机制：如果 LLM 决策失败，使用默认行为
- 添加人类在环：关键决策需要用户确认

#### 风险 2：Token 使用过高

**缓解措施**：
- 三阶段渐进式披露，减少上下文开销
- 实现上下文压缩：定期总结历史消息
- 设置 token 预算：限制每次调用的 token 使用

#### 风险 3：响应速度慢

**缓解措施**：
- 异步执行：工具调用并行执行
- 流式输出：边生成边返回
- 缓存机制：缓存常用技能和工具结果

### 监控与可观测性

#### 关键指标

- **ReAct 循环次数**：每次对话的平均循环次数
- **工具调用分布**：哪些工具被调用最多
- **技能激活率**：哪些技能最常被激活
- **Token 使用量**：每次对话的平均 token 使用
- **响应时间**：从用户消息到最终回复的时间

#### 日志记录

- 记录每次 ReAct 循环的思考、行动、观察
- 记录工具调用的输入、输出、耗时
- 记录技能激活的时机和效果

### 未来扩展

#### 多代理协作

未来可以扩展为多代理架构：
- **面试官代理**：负责提问和引导
- **评估代理**：负责评估候选人的回答
- **提示代理**：负责提供提示和引导

#### 自适应学习

根据用户反馈优化 LLM 决策：
- 记录用户对回复的满意度
- 分析哪些决策导致了好的结果
- 优化提示词和工具描述

## 总结

本设计基于 2026 年最佳实践，采用 Skill 驱动的 ReAct 架构，实现更智能的面试流程控制。通过复用现有系统，渐进式迁移，确保向后兼容。三阶段渐进式披露减少 token 开销，提高效率。

**核心优势**：
1. 智能路由：LLM 自己决定下一步做什么
2. Skill 驱动：复用现有 skills 系统，动态选择和激活技能
3. 渐进式披露：减少 token 开销，提高效率
4. 向后兼容：保持现有 API 接口不变
5. **配置化架构**：SOUL.md/AGENTS.md/SKILL.md实现agent高度可配置

**实施计划**：
- 阶段 1：基础设施（1 周）
- 阶段 2：Agent配置化（1 周）
- 阶段 3：工具集成（1 周）
- 阶段 4：测试与优化（1 周）

**总工期**：4 周

**开发新agent的方式**：
1. 创建新agent目录
2. 编写SOUL.md（人格、价值观、边界）
3. 编写AGENTS.md（操作规则、工作流程）
4. 配置skills目录下的SKILL.md
5. 无需修改代码，只需配置markdown文件
