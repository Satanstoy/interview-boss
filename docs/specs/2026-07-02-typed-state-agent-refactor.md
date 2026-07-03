# Spec: Typed State Agent Refactor — 让面试官状态机自然流转

> **位置**: `backend/app/agents/chat/` + `backend/app/mcp_server/` + `backend/app/agents/chat/skills/`
> **类型**: 架构级重构 spec
> **日期**: 2026-07-02
> **状态**: 实施中

## 背景

当前 interview-boss 的 chat agent 在关键流转节点上依赖硬编码接管：

- `react_loop.py` 用 `OFF_TOPIC_SIGNALS` 字符串匹配判断"LLM 是否已经自然处理答非所问"。
- `nodes.py` 的 `_build_tool_strategy()` 是 140+ 行的 `if/elif` 树，根据消息数、技能、覆盖状态现场决定工具策略。
- `classify_intent()` 只返回扁平 `intent` 字符串，导致下游所有节点必须从 `message_history` 或回答文本中二次推断。
- `stop_policy.py` 和 `answer.py` 的重复检测、话题切换、过渡文案大量依赖字符串匹配与硬编码模板。
- `prompts.py` 和 `SKILL.md` 里写满了"第 1 次...第 2 次...第 3 次..."的硬编码流程规则。

这些硬编码让面试官行为显得"不自然、不智能"：同样一句话有时触发 guard，有时不触发；话题切换机械；答非所问只能重复追问。

## 核心思路

> **分类阶段写状态，后续节点读状态。**

把 LLM 在分类/推理阶段已经知道的信息（意图、回答质量、是否需要检索、升级层级、过渡风格等）直接写成结构化的 `ChatState` 字段。ReAct loop、工具策略、停止策略、过渡文案、skill prompt 全部变成对状态的声明式查询，而不是在代码里重新推导。

本项目**不是 LangGraph**，只是借鉴其"节点 + 条件边"的形式；所有路由都是普通 Python 函数，直接调用，不引入任何 LangGraph 依赖。

## 设计目标

1. `classify_intent` 输出结构化 `ClassifyResult`，包含 `answer_quality`、`should_retrieve`、`transition_style`、`escalation_level` 等字段。
2. 删除 `OFF_TOPIC_SIGNALS` 等中文信号词硬编码；检索建议缺口只读 `state["answer_quality"]` 和 `state["should_retrieve"]` 做观测记录，不做后置强制接管。
3. `_build_tool_strategy()` 的 `if/elif` 树替换为 `compute_tool_strategy(state)` 查询。
4. 话题切换、重复追问、答非所问升级由 LLM 在分类阶段写入状态，后端只读状态路由。
5. MCP 工具层只执行工具、返回统一 envelope，不做流程决策；`tools.py` 只负责转发。
6. 保留并复用 `DecisionConfig` 和 `coverage_events`，但读取方式改为"状态字段 + 配置阈值"。

## 新状态字段 Schema

### `ClassifyResult`（Pydantic 模型）

新增文件 `backend/app/agents/chat/classify_result.py`：

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional

class ClassifyResult(BaseModel):
    intent: Literal[
        "interview_question",
        "practice_request",
        "chat",
        "follow_up",
        "end_interview",
    ]
    answer_quality: Literal[
        "complete",      # 回答完整，可进入下一题/检索
        "incomplete",    # 回答不完整，需要追问
        "off_topic",     # 答非所问
        "repeated",      # 与之前回答实质重复
        "vague",         # 笼统/背书式，需要澄清
    ] = "complete"
    question_type: Optional[Literal[
        "project_followup",
        "knowledge_probe",
        "algorithm_coding",
        "system_design",
        "behavioral",
    ]] = None
    should_retrieve: bool = Field(
        default=False,
        description="本轮是否需要先调用 search_questions / draw_questions",
    )
    transition_style: Optional[Literal[
        "natural",              # 正常承接
        "from_candidate_keyword",  # 用候选人关键词承接
        "pivot",                # 明确切换方向
        "closing",              # 进入收尾
    ]] = "natural"
    escalation_level: int = Field(
        default=0, ge=0, le=3,
        description="同一问题/话题的追问升级层级",
    )
    off_topic_streak: int = Field(
        default=0, ge=0,
        description="连续答非所问次数",
    )
    repetition_streak: int = Field(
        default=0, ge=0,
        description="连续重复回答次数（pair count）",
    )
    requires_bank_question: bool = Field(
        default=False,
        description="本轮是否必须绑定题库题目",
    )

    def to_state(self) -> dict:
        return self.model_dump(exclude_none=True)
```

### `ChatState` 扩展

在 `backend/app/agents/chat/state.py` 的 `# === 意图分类 ===` 区域新增字段：

```python
class ChatState(TypedDict, total=False):
    # ... 已有字段 ...
    intent: str
    answer_complete: bool
    answer_quality: str                     # NEW
    should_retrieve: bool                   # NEW
    transition_style: Optional[str]         # NEW
    escalation_level: int                   # NEW
    off_topic_streak: int                   # NEW
    repetition_streak: int                  # NEW
    requires_bank_question: bool            # NEW
    classify_result: dict                   # NEW: 保留原始 ClassifyResult 快照
    # ...
```

### `ToolStrategy`（数据类）

新增文件 `backend/app/agents/chat/tool_strategy.py`：

```python
from dataclasses import dataclass, field

@dataclass(frozen=True)
class ToolStrategy:
    requires_retrieval: bool = False
    allow_search: bool = True
    allow_draw: bool = True
    allow_load_skill: bool = True
    allowed_skills: list[str] = field(default_factory=list)
    instruction: str = ""
    next_phase_hint: str = ""

    def to_prompt_text(self) -> str:
        ...
```

`compute_tool_strategy(state: ChatState) -> ToolStrategy` 根据以下状态字段推导策略：
- `intent`
- `answer_quality`
- `should_retrieve`
- `requires_bank_question`
- `retrieved_questions` / `candidate_questions`
- `active_skills`
- `interview_state` / `harness_focus`
- `message_history` 长度（用于阶段判断，非字符串匹配）
- `escalation_level` / `off_topic_streak` / `repetition_streak`

### 路由函数

新增文件 `backend/app/agents/chat/routing.py`，提供纯函数条件边：

```python
def route_after_classify(state: ChatState) -> str:
    """根据分类结果返回下一节点名称。"""
    intent = state.get("intent", "interview_question")
    if intent == "end_interview":
        return "closing"
    if intent == "chat":
        return "direct_response"
    if intent == "practice_request":
        return "tool_loop"
    return "tool_loop"

def should_record_retrieval_gap(state: ChatState) -> bool:
    """是否记录“建议检索但模型自然追问”的缺口。"""
    return (
        state.get("intent") == "interview_question"
        and state.get("answer_quality") in ("complete", "vague")
        and state.get("should_retrieve") is True
        and not state.get("retrieved_questions")
        and not state.get("candidate_questions")
    )

def should_topic_shift(state: ChatState) -> bool:
    return state.get("off_topic_streak", 0) >= 3 or state.get("repetition_streak", 0) >= 2

def should_close(state: ChatState, config: DecisionConfig | None = None) -> bool:
    ...
```

## 分类节点改造

### `classify_intent` 输出 `ClassifyResult`

`backend/app/agents/chat/nodes.py`：

1. 保留轻量 keyword 预判断作为快速路径，但把 keyword 映射抽成配置数据，而不是硬编码在函数里。
2. LLM 分类 prompt 改为要求输出 JSON，格式与 `ClassifyResult` 一致。
3. 解析失败时返回安全的默认 `ClassifyResult`（`intent=interview_question`, `answer_quality=complete`, `should_retrieve=false`）。
4. `classify_intent` 返回 `{"classify_result": result.to_state()}`；下游 `pipeline.py` 把 `classify_result` 展开写入 `ChatState`。

### 新的分类 Prompt

```python
INTENT_CLASSIFY_PROMPT = """分析用户的最新消息，输出 JSON 格式的分类结果。

## 输出字段
- intent: interview_question | practice_request | chat | follow_up | end_interview
- answer_quality: complete | incomplete | off_topic | repeated | vague
- question_type: project_followup | knowledge_probe | algorithm_coding | system_design | behavioral | null
- should_retrieve: boolean（本轮是否需要先检索/抽题）
- transition_style: natural | from_candidate_keyword | pivot | closing | null
- escalation_level: 0-3（同一问题追问升级层级）
- off_topic_streak: 0+（连续答非所问次数，需结合历史判断）
- repetition_streak: 0+（连续重复回答次数）
- requires_bank_question: boolean（本轮是否必须绑定题库题目）

## 判断规则
- answer_quality:
  - complete: 用户明确回答完毕、方案完整
  - incomplete: 只给片段、反问确认、过渡词
  - off_topic: 回答与问题明显不相关
  - repeated: 与之前回答实质重复
  - vague: 笼统、背书式、缺乏细节
- should_retrieve:
  - true 当 intent=interview_question 且 answer_quality=complete/vague，且当前没有未使用的候选题
  - true 当 intent=practice_request
  - false 当 intent=chat/follow_up/end_interview 或 answer_quality=incomplete/off_topic/repeated
- requires_bank_question:
  - true 当 intent=practice_request 或 question_type=algorithm_coding
  - false 当开场前 N 轮（由后端根据 message_count 覆盖）
  - 其他情况由 LLM 根据对话节奏判断

## 用户消息
{user_message}

## 最近对话
{recent_context}

请只输出合法 JSON，不要其他内容。"""
```

## ReAct Loop 改造

### `backend/app/agents/chat/react_loop.py`

1. **删除 `OFF_TOPIC_SIGNALS` 字符串匹配**。不再从 `final_answer_text` 中搜中文信号词。
2. **检索建议缺口改为读取状态并仅记录事实**：
   ```python
   should_record_gap = (
       not stop_reason
       and final_answer_text
       and should_record_retrieval_gap(state)
       and not search_or_draw_called
   )
   ```
3. 如果 `should_record_retrieval_gap(state)` 为 true，只写入 `state["retrieval_gap"]`、`question_source=conversation` 和 `question_source_reason=retrieval_recommended_but_skipped`。不要注入额外系统消息，不要二次调用 LLM，不要由代码替模型执行题库工具。
4. 移除 `chat_constants.py` 中的 `OFF_TOPIC_SIGNALS`。

## 工具策略改造

### `backend/app/agents/chat/nodes.py`

1. 删除 `_build_tool_strategy()` 的巨型 `if/elif` 树。
2. 改为调用 `compute_tool_strategy(state)`。
3. `build_react_system_prompt()` 中把 `ToolStrategy.to_prompt_text()` 注入 prompt。

### `compute_tool_strategy` 行为

| 状态组合 | ToolStrategy |
|---|---|
| `intent == end_interview` | `requires_retrieval=False`, `allow_search=False`, `allow_draw=False`, instruction=直接收尾 |
| `answer_quality in (incomplete, off_topic, repeated)` | `requires_retrieval=False`, instruction=追问/指出问题/换方向 |
| `escalation_level >= 3` 或 `off_topic_streak >= 3` | `requires_retrieval=True`, `allow_search=False`, `allow_draw=True`, instruction=用 draw_questions 切换完全不同方向 |
| `repetition_streak >= 2` | `requires_retrieval=True`, `allow_draw=True`, instruction=切换方向或进入反问 |
| `should_retrieve=True` 且无候选题 | `requires_retrieval=True`, 根据 `active_skills`/`question_type` 决定 search 或 draw |
| `harness_focus.phase == wrap_up` | `requires_retrieval=False`, `allow_search=False`, `allow_draw=False`, instruction=收尾 |
| `message_count >= strong_close` | `requires_retrieval=False`, instruction=只补最后缺口 |
| 默认 | `requires_retrieval=False`, instruction=基于已有候选题自然追问 |

## 停止策略与回答过渡改造

### `backend/app/agents/chat/stop_policy.py`

1. `evaluate_interview_stop(state)` 读取 `repetition_streak`、`off_topic_streak`、`escalation_level` 等状态字段。
2. 重复检测不再现场数文本，而是读取 `state["repetition_streak"]`。
3. 保留 `DecisionConfig` 阈值，但判断逻辑改为：
   ```python
   if state.get("repetition_streak", 0) >= config.candidate_repeat_close:
       return close(...)
   if state.get("repetition_streak", 0) >= config.candidate_repeat_degraded:
       return ask_candidate_question(...)
   ```

### `backend/app/agents/chat/answer.py`

1. `_format_bank_question_fallback()` 读取 `state["transition_style"]`：
   - `from_candidate_keyword`: 尝试用 LLM rewrite 从候选人回答中提取关键词承接。
   - `pivot`: 简洁切换到新方向，不硬编码"换个具体点的问题"。
   - `closing`: 进入收尾文案。
   - `natural`: 默认自然过渡。
2. 保留 `_rewrite_transition_with_llm()` 作为 fallback，但不再依赖 `TRANSITION_REJECTED_PATTERNS` 做硬编码拒绝列表；而是直接让 LLM 生成自然过渡。
3. 删除或弱化 `TRANSITION_REJECTED_PATTERNS`。

## Question Plan 改造

### `backend/app/agents/chat/question_plan.py`

1. `_should_require_bank_question(state)` 改为读取 `state["requires_bank_question"]`，同时保留基于 `message_count` 的开场豁免逻辑作为状态覆盖。
2. `_count_consecutive_similar_user_answers()` 和 `_count_consecutive_similar_questions()` 保留作为底层计数函数，但结果写入 `state["repetition_streak"]`，而不是被下游现场调用。
3. `_build_repetition_protection_note()` 读取 `state["repetition_streak"]` 和 `state["escalation_level"]`，而不是重新计算。

## Prompt 与 Skill 改造

### `backend/app/agents/chat/prompts.py`

1. 删除"答非所问：指出后要求重答，最多追问3次再换方向"这类硬编码规则。
2. 改为在 system prompt 中注入当前状态字段：
   ```
   【当前回合状态】
   - 回答质量: {answer_quality}
   - 追问升级层级: {escalation_level}
   - 连续答非所问: {off_topic_streak}
   - 连续重复回答: {repetition_streak}
   - 过渡风格: {transition_style}
   ```
3. 告诉 LLM：根据这些状态字段决定是追问、提示、换方向还是收尾，而不是背规则。

### `backend/app/agents/chat/skills/interview-rhythm/SKILL.md`

1. 删除"第 1 次...第 2 次...第 3 次..."的硬编码升级规则。
2. 改为：
   - 当后端提供 `answer_quality=off_topic` 或 `escalation_level>0` 时，指出不相关并决定下一步。
   - 当后端提供 `repetition_streak>=2` 时，指出重复并切换方向。
   - 当后端提供 `transition_style=pivot` 时，用候选人关键词自然承接后切换。
3. 保留节奏比例、题型覆盖、自然过渡等高层指导。

### `backend/app/agents/chat/skills/adaptive-difficulty/SKILL.md`

1. 删除"Bad answer → de-escalate"中的硬编码步骤。
2. 改为根据 `answer_quality` 和 `escalation_level` 动态调整。

## MCP 工具边界清理

### `backend/app/mcp_server/interview_tools.py`

1. `load_skill_tool` 已使用 `build_success_envelope` / `build_error_envelope`，基本符合契约。保留并确保 `metadata.metrics.total_ms` 和 `debug_reason` 存在。
2. `select_question_tool` 已下沉越界检查到 `interview_tools.py`，保留。
3. 工具函数只执行动作、更新状态、返回 envelope，不做任何"该不该调用"的决策。

### `backend/app/agents/chat/tools.py`

1. `_execute_select_question()` 保持纯转发（已满足）。
2. `_execute_load_skill()` / `_execute_search_questions()` / `_execute_draw_questions()` 保持纯转发。
3. 工具 schema 描述中减少硬编码流程规则，改为描述工具本身能力；流程决策由 agent 状态机负责。

### `backend/app/mcp_server/app.py`

1. `select_question` MCP 工具保持 `candidate_index` 参数，与内部路径一致。
2. 错误码统一为 `NO_CANDIDATES` / `INDEX_OUT_OF_RANGE`。

## 实施顺序

| 步骤 | 任务 | 文件 | 依赖 |
|---|---|---|---|
| 1 | 创建 `ClassifyResult` 模型 + `ToolStrategy` + `routing.py` | 新增 | 无 |
| 2 | 扩展 `ChatState` | `state.py` | 步骤 1 |
| 3 | 改造 `classify_intent` 输出结构化结果 + 新 prompt | `nodes.py`, `prompts.py` | 步骤 2 |
| 4 | 用 `compute_tool_strategy` 替换 `_build_tool_strategy` | `nodes.py`, `tool_strategy.py` | 步骤 2 |
| 5 | 移除 `react_loop` 后置检索接管逻辑，改为 retrieval gap 记录，并删除 `OFF_TOPIC_SIGNALS` | `react_loop.py`, `chat_constants.py` | 步骤 3, 4 |
| 6 | `stop_policy` 读状态字段 | `stop_policy.py`, `question_plan.py` | 步骤 2 |
| 7 | `answer.py` 过渡读 `transition_style` | `answer.py` | 步骤 2 |
| 8 | 重构 SKILL.md / prompts 状态字段驱动 | `skills/*`, `prompts.py` | 步骤 3 |
| 9 | MCP 边界最终对齐 | `mcp_server/*`, `tools.py` | 步骤 4 |
| 10 | 测试更新与新增 | `tests/chat/*` | 步骤 5-9 |

## 验收标准

- [ ] `classify_intent` 返回 `classify_result` 字典，包含所有 `ClassifyResult` 字段。
- [ ] `ChatState` 包含 `answer_quality`、`should_retrieve`、`transition_style`、`escalation_level`、`off_topic_streak`、`repetition_streak`、`requires_bank_question`。
- [ ] `OFF_TOPIC_SIGNALS` 从 `chat_constants.py` 删除，`react_loop.py` 不再做字符串匹配。
- [ ] `should_record_retrieval_gap(state)` 纯函数测试通过。
- [ ] `_build_tool_strategy()` 不存在或变为 `compute_tool_strategy(state)` 的薄包装。
- [ ] `stop_policy.py` 不直接调用 `_count_consecutive_similar_user_answers`，而是读 `state["repetition_streak"]`。
- [ ] `answer.py` 的 fallback 文案不硬编码"换个具体点的问题"，而是根据 `transition_style` 选择。
- [ ] `prompts.py` 和 `SKILL.md` 不再包含"第 1 次...第 2 次...第 3 次..."硬编码规则。
- [ ] `interview_tools.py` 所有返回走统一 envelope；`tools.py` 所有工具纯转发。
- [ ] 现有 `backend/tests/chat/` 全部通过。
- [ ] 新增 `test_classify_result.py`、`test_tool_strategy.py`、`test_routing.py`。

## 风险与回滚

- **分类 Prompt 变复杂**：可能导致 LLM 输出不稳定。需增加 JSON parse 失败兜底，并保留 keyword 快速路径。
- **状态字段漂移**：新增字段较多，需确保每个写入点都有单测覆盖。
- **MCP 双入口行为变化**：外部 MCP client 可能依赖旧错误码。需确认前端/error handling。
- **回滚方案**：本次重构按文件逐步修改，每个文件 commit 独立；如出问题可回滚单个文件。

## 参考文件

- `backend/app/agents/chat/nodes.py`
- `backend/app/agents/chat/react_loop.py`
- `backend/app/agents/chat/stop_policy.py`
- `backend/app/agents/chat/answer.py`
- `backend/app/agents/chat/question_plan.py`
- `backend/app/agents/chat/prompts.py`
- `backend/app/agents/chat/state.py`
- `backend/app/agents/chat/chat_constants.py`
- `backend/app/agents/chat/decision_config.py`
- `backend/app/agents/chat/coverage_events.py`
- `backend/app/agents/chat/tools.py`
- `backend/app/agents/chat/tool_gateway.py`
- `backend/app/mcp_server/interview_tools.py`
- `backend/app/mcp_server/app.py`
- `backend/app/agents/chat/skills/interview-rhythm/SKILL.md`
- `backend/app/agents/chat/skills/adaptive-difficulty/SKILL.md`
