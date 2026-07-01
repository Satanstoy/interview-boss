# Spec: 模拟面试状态、节奏学习与前端观测性

> 位置: `backend/app/agents/chat/`
> 类型: 功能增强 spec
> 日期: 2026-07-01
> 状态: 待实施

## 背景

当前 chat agent 已经不是空白状态机。实际架构是纯 async pipeline:

```text
run_chat() -> _step_load_context -> _step_classify -> _react_loop
  -> _persist_active_skills -> save_mcp_session -> _step_extract_memory
```

现有能力包括:

- `InterviewLedger`: 从历史 assistant metadata、session notes、selected question、retrieved questions 中汇总已问问题、类别计数、题型计数和近期主题，用于防重复和覆盖度判断。
- full-loop harness: 基于 `InterviewLedger` 推导下一优先评估维度，覆盖项目深挖、八股基础、算法、系统设计、行为面和反问。
- question plan: 出题时本地绑定 `selected_question`，生成 `next_question_plan`，偏离时 repair 或 deterministic fallback。
- message metadata: assistant 消息会持久化 `selected_question`、`question_plan`、`retrieved_questions`、`thinking`、`thinking_duration`、`steps`、`insights` 等信息。

因此本 spec 不再假设“没有面试状态管理”。真正缺口是:

1. 状态是分散推导出来的，不够显式，难以给产品、调试和报告稳定使用。
2. 面经节奏学习还没有成为可复用配置，当前更多依赖规则和题库检索。
3. thinking/steps 已写入消息 metadata，但前端对“历史回放”的展示能力还不完整。
4. skill 加载能作为 step 展示，但“加载了哪个 skill、刷新后是否清晰可见”还没有稳定产品契约。
5. tool call 目前只有后端日志和前端 step 摘要，没有完整、可恢复的 per-turn tool trace。

## 目标

1. 在现有 `ChatState + InterviewLedger + metadata` 基础上增加显式 `interview_state`，不另起一套平行状态机。
2. 支持从指定面经或岗位默认样本中学习节奏，影响覆盖阈值和下一阶段优先级。
3. 将面试过程中的关键状态持久化到可恢复位置，页面刷新后仍能看到本轮的思考耗时、skill 加载、检索/抽题摘要和采用题目。
4. 为完整 tool call 审计留出后端持久化结构，但默认不把原始 tool payload 暴露给前端。

## 非目标

- 不重写 `_react_loop` 为 LangGraph StateGraph。
- 不废弃 `InterviewLedger`、question plan、full-loop harness。
- 不把 LLM 的完整内部 reasoning 作为产品能力承诺；只记录 provider 返回的 thinking 片段和耗时，且限制大小。
- 不把敏感 tool 参数、skill 全文、检索原始返回完整暴露给前端。

## 现状持久化矩阵

| 数据 | 当前是否写库 | 当前写入位置 | 前端刷新后是否天然可恢复 | 问题 |
|---|---:|---|---:|---|
| assistant 正文 | 是 | `chat_messages.content` | 是 | 已稳定 |
| thinking duration | 是 | `chat_messages.metadata.thinking_duration` | 取决于前端是否渲染历史 metadata | 后端已有，前端展示需确认/补齐 |
| thinking chunks | 部分 | `chat_messages.metadata.thinking` | 取决于前端是否渲染历史 metadata | 当前事件字段存在 `content`/`data.text` 形状不一致风险 |
| step 摘要 | 是 | `chat_messages.metadata.steps` | 取决于前端是否渲染历史 metadata | 能看到“加载技能/检索题库”等摘要，不是原始 tool call |
| insight | 是 | `chat_messages.metadata.insights` | 取决于前端是否渲染历史 metadata | 已进 metadata |
| active skills | 是 | `chat_messages.metadata.active_skills` 与 `chat_conversations.metadata.persistent_skill_names` | 消息历史可恢复 skill 名称 | 只保存 skill 名称，不保存 skill 全文 |
| selected question / question plan | 是 | `chat_messages.metadata.selected_question` / `question_plan` | 是，如果前端读取 metadata | 已稳定 |
| raw tool_calls | 否 | 后端日志 `ReAct trace` | 否 | 只有日志，且参数会脱敏 |
| tool 执行结果摘要 | 部分 | `steps` + retrieved/candidate metadata | 部分 | 没有统一 per-turn tool trace |
| MCP session state | 临时 | Redis 或 SQLite `mcp_sessions` | 否 | TTL 状态，不是用户可见历史 |

## 本次必须解决的三个前端观测性问题

这三个问题必须和状态/节奏学习一起进入实施范围，不能只停留在口头说明。

### 1. 模型思考时间与 thinking 内容

现状:

- 流式过程中，前端能看到 thinking 状态和思考耗时。
- 后端 `done.metadata` 会包含 `thinking_duration`，并随 assistant message 写入 `chat_messages.metadata`。
- 前端历史消息会读取 `message.metadata.thinking_duration` 并显示“思考了 x 秒”。

问题:

- 后端累积 thinking chunks 时存在事件字段形状不一致风险: 真实流式事件常用 `content`，测试 mock 使用 `data.text`。
- 前端历史渲染目前更偏向把 `metadata.thinking` 当字符串展示；如果后端保存 list 结构，刷新后 thinking 内容可能展示不完整或格式不一致。

要求:

- 后端收集 thinking 时同时兼容 `event["content"]` 和 `event["data"]["text"]`。
- assistant message metadata 中统一保存:

```json
{
  "thinking": [
    {
      "chunks": ["..."],
      "duration_ms": 1234
    }
  ],
  "thinking_duration": 1.2
}
```

- 前端历史展示兼容旧格式字符串和新格式 list。至少保证刷新后能稳定看到“思考了 x 秒”。

### 2. Skill 加载与可见性

现状:

- `load_skill` 会作为 step 事件进入前端 ReasoningTimeline。
- assistant message metadata 中会保存 `steps`，刷新后可以看到类似“正在加载面试策略...”的步骤。
- `active_skills` 会进入 assistant metadata；跨轮持久 skill 名称会保存在 `chat_conversations.metadata.persistent_skill_names`。

问题:

- 前端 step 文案现在不一定明确展示具体 skill 名称。
- 用户刷新页面后，能看到“加载面试策略”这类摘要，但不一定能一眼知道加载的是 `project-deep-dive`、`theory-qa` 还是 `algorithm-coding`。

要求:

- `load_skill` step metadata 必须包含脱敏后的 `skill_name`，例如:

```json
{
  "step": "load_skill",
  "message": "已加载项目深挖策略",
  "skill_name": "project-deep-dive"
}
```

- 前端 ReasoningTimeline 对 `load_skill` 显示具体 skill 名称或对应中文名称。
- 历史消息从 `GET /messages` 恢复后仍能看到本轮加载过的 skill。
- 不保存、不展示 skill 全文，只展示 skill 名称和简短说明。

### 3. Tool call 摘要与 raw tool call 边界

现状:

- 前端能看到 `search_questions`、`draw_questions`、`select_question`、`load_skill` 这类 step 摘要。
- assistant message metadata 会保存 `steps`、`selected_question`、`candidate_questions`、`retrieved_questions` 等结果摘要。
- raw `tool_calls` 和完整 tool result 不进入前端；后端只写 ReAct trace 日志，并且参数会脱敏。

问题:

- 用户从前端只能看到“做了什么大动作”，看不到统一的工具调用摘要，例如工具名、耗时、结果数量、是否 fallback。
- 如果后续要 debug 某轮为什么抽了这道题，只有日志不够稳定，日志也不是用户历史消息的一部分。

要求:

- 前端默认仍不展示 raw tool call。
- assistant message metadata 中新增可恢复的 `tool_steps` 或增强 `steps`，至少包含:

```json
{
  "step": "search_questions",
  "tool_name": "search_questions",
  "message": "检索了相关面试题",
  "elapsed_ms": 320,
  "result_count": 3,
  "fallback_used": false
}
```

- 如果需要更完整审计，写入后端 `chat_tool_traces` 表，只保存脱敏 args 和 result summary。
- 前端最多展示工具摘要，不展示 raw arguments、完整返回 payload、skill 全文或用户隐私原文。

## 设计原则

1. **单一事实来源**: 继续让 `InterviewLedger` 负责从历史消息重建已问问题和覆盖度，新的 `interview_state` 是其产品化快照，不替代 ledger。
2. **每轮增量持久化**: 每个 assistant message 的 metadata 保存本轮快照；conversation metadata 只保存跨轮配置和轻量累计状态。
3. **前端展示用摘要，后端审计用 trace**: 前端展示 skill 名称、step 摘要、耗时、采用题目；后端可选保存脱敏 tool trace。
4. **权限先行**: `experience_id` 必须按 `owner_id/status/job_position` 过滤，不允许裸 ID 读取别人的面经。
5. **兼容旧会话**: 旧消息没有 `interview_state` 时，通过 `InterviewLedger` 和历史 metadata 尽量重建。

## 数据模型

### InterviewPhase

阶段名称要与现有题型和 harness 术语对齐:

```python
class InterviewPhase(str, Enum):
    WARMUP = "warmup"
    PROJECT_FOLLOWUP = "project_followup"
    KNOWLEDGE_PROBE = "knowledge_probe"
    ALGORITHM_CODING = "algorithm_coding"
    SYSTEM_DESIGN = "system_design"
    BEHAVIORAL = "behavioral"
    WRAP_UP = "wrap_up"
```

### InterviewStateSnapshot

该对象是可序列化快照，保存进 assistant message metadata 的 `interview_state` 字段。

```python
@dataclass
class InterviewStateSnapshot:
    conversation_id: str
    job_position: str
    difficulty: str
    current_phase: str
    next_focus: str | None
    turn_count: int
    coverage: dict[str, dict[str, int | bool]]
    last_answer_evaluation: dict | None
    recent_decisions: list[dict]
    rhythm_profile: dict
    generated_at: float
```

示例 JSON:

```json
{
  "current_phase": "project_followup",
  "next_focus": "knowledge_probe",
  "coverage": {
    "project_followup": {"current_count": 3, "threshold": 5, "is_covered": false},
    "knowledge_probe": {"current_count": 1, "threshold": 3, "is_covered": false},
    "algorithm_coding": {"current_count": 0, "threshold": 1, "is_covered": false}
  },
  "recent_decisions": [
    {
      "from": "project_followup",
      "to": "knowledge_probe",
      "mode": "natural",
      "reason": "project depth is sufficient for this turn; move to core knowledge",
      "trigger": "coverage_priority"
    }
  ]
}
```

### Conversation Metadata

`chat_conversations.metadata` 保存跨轮配置:

```json
{
  "interview_config": {
    "difficulty": "mid",
    "experience_id": 123,
    "rhythm_profile_id": "experience:123",
    "coverage_thresholds": {
      "project_followup": 5,
      "knowledge_probe": 3,
      "algorithm_coding": 1,
      "system_design": 1,
      "behavioral": 1
    }
  },
  "persistent_skill_names": ["interview-rhythm"]
}
```

不把大体量评分历史长期堆在 conversation metadata 中；每轮快照进入 assistant message metadata。

## 覆盖度阈值

默认阈值保留岗位 + 难度维度。第一版只实现 `agent_llm` 和 `backend`，其他岗位回退到 `agent_llm/mid`。

```python
DEFAULT_COVERAGE_THRESHOLDS = {
    ("agent_llm", "junior"): {
        "project_followup": 3,
        "knowledge_probe": 3,
        "algorithm_coding": 1,
        "system_design": 0,
        "behavioral": 1,
    },
    ("agent_llm", "mid"): {
        "project_followup": 5,
        "knowledge_probe": 3,
        "algorithm_coding": 1,
        "system_design": 1,
        "behavioral": 1,
    },
    ("agent_llm", "senior"): {
        "project_followup": 6,
        "knowledge_probe": 3,
        "algorithm_coding": 1,
        "system_design": 1,
        "behavioral": 1,
    },
    ("agent_llm", "staff_plus"): {
        "project_followup": 6,
        "knowledge_probe": 2,
        "algorithm_coding": 1,
        "system_design": 2,
        "behavioral": 1,
    },
    ("backend", "mid"): {
        "project_followup": 3,
        "knowledge_probe": 5,
        "algorithm_coding": 2,
        "system_design": 1,
        "behavioral": 1,
    },
}
```

阈值是目标覆盖，不是硬性轮次数。实际下一题仍要参考:

- `InterviewLedger` 中已问问题和类别计数。
- 候选人上一轮回答是否完整。
- 当前是否存在 `must_ask` question plan。
- forced search guard 是否已经触发。

## 面经节奏学习

### 数据来源

从 `interview` 表读取:

```sql
SELECT id, questions_list, difficulty, job_position, owner_id, status
FROM interview
WHERE id = ?
  AND deleted_at IS NULL
  AND status = 'approved'
  AND (owner_id = ? OR owner_id IS NULL)
  AND (job_position = ? OR job_position = '')
```

如果当前数据库迁移中没有 `deleted_at`，查询实现必须通过 schema 检查兼容旧库。

### 分类方式

不要在多个文件重复维护关键词。第一版可以创建 `rhythm_profile.py`，提供:

- `classify_question_phase(question: str) -> str`
- `analyze_topic_distribution(questions: list[str]) -> dict[str, int]`
- `analyze_topic_transition(questions: list[str]) -> dict[str, dict[str, int]]`
- `build_rhythm_profile(...) -> dict`

分类优先级:

1. 如果题目来自 `questions_detail` 或 `question_bank`，优先用已有 `question_type/cat1/cat2`。
2. 否则使用关键词兜底。
3. 分类失败时归入 `project_followup`，但在 profile metadata 中记录 `unknown_count`。

### RhythmProfile

```json
{
  "source": "experience",
  "experience_id": 123,
  "distribution": {
    "project_followup": 4,
    "knowledge_probe": 3,
    "algorithm_coding": 1,
    "system_design": 1,
    "behavioral": 0
  },
  "transition": {
    "project_followup": {"knowledge_probe": 2, "system_design": 1},
    "knowledge_probe": {"algorithm_coding": 1}
  },
  "recommended_order": [
    "project_followup",
    "knowledge_probe",
    "system_design",
    "algorithm_coding"
  ],
  "confidence": 0.74,
  "unknown_count": 1
}
```

使用方式:

- `distribution` 可调整覆盖阈值，但要设置上下限，避免单个面经把某阶段阈值拉到极端。
- `transition` 只影响 tie-breaker，不覆盖 `must_ask` 题目计划。
- `confidence < 0.5` 时只使用默认岗位阈值。

## Pipeline 集成

### 创建会话

`CreateConversationRequest` 增加:

```python
class CreateConversationRequest(BaseModel):
    mode: str = Field(..., pattern="^(jd_resume|free_practice)$")
    title: str | None = None
    jd_id: int | None = None
    resume_text: str | None = None
    difficulty: str | None = Field(None, pattern="^(junior|mid|senior|staff_plus)$")
    experience_id: int | None = None
```

`job_position` 继续来自用户 profile，不从请求体传，避免前端随意覆盖岗位隔离。

创建流程:

1. 解析 `difficulty`，默认 `mid`。
2. 用当前用户 profile 得到 `job_position`。
3. 如果有 `experience_id`，按权限过滤并构建 `rhythm_profile`。
4. 合成 `coverage_thresholds`。
5. 写入 `chat_conversations.metadata.interview_config`。

### 每轮开始

`run_chat()` 不新建空状态，而是:

1. `_step_load_context` 加载历史消息和 conversation metadata。
2. 用 `InterviewLedger` 从历史消息重建已问问题、类别计数和近期主题。
3. 用 `interview_config + ledger` 构建本轮 `interview_state_snapshot`。
4. 将快照注入 `ChatState["interview_state"]`。
5. `build_react_system_prompt(state)` 渲染一段简短、稳定的 `<interview_state>` 上下文。

### 每轮结束

在 `done` metadata 中追加:

```python
metadata["interview_state"] = build_interview_state_snapshot(state, response)
metadata["observability"] = {
    "thinking_duration": metadata.get("thinking_duration", 0),
    "step_count": len(metadata.get("steps", [])),
    "active_skills": metadata.get("active_skills", []),
    "tool_trace_persisted": False,
}
```

如果本轮启用后端 tool trace 持久化，则 `tool_trace_persisted = True` 并带 `tool_trace_id`，但前端默认只显示摘要。

## Tool Call 审计设计

当前已有后端日志:

```text
ReAct trace: event=llm_step ...
ReAct trace: event=tool_call ...
```

第一版不改变默认产品展示，只新增可选后端审计表，并把轻量摘要合并进 assistant message metadata:

```sql
CREATE TABLE chat_tool_traces (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    message_id INTEGER,
    react_step INTEGER NOT NULL,
    tool_name TEXT NOT NULL,
    sanitized_args_json TEXT NOT NULL,
    result_summary_json TEXT NOT NULL,
    elapsed_ms INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

规则:

- 只保存 `_sanitize_tool_args()` 之后的参数。
- 只保存 `_summarize_tool_output()` 之后的结果摘要。
- 不保存 skill 全文、完整 retrieved items、用户隐私原文或 provider raw payload。
- 前端如需展示，只展示“调用了什么工具、耗时、结果数量、是否 fallback”，不展示原始参数。

## 前端展示要求

历史消息加载 `GET /api/chat/conversations/{id}/messages` 后，assistant 消息应从 metadata 恢复:

1. 思考耗时: `metadata.thinking_duration`，显示为“思考 x.x 秒”。
2. thinking 内容: 兼容旧格式字符串和新格式 `metadata.thinking[].chunks`；默认可折叠。
3. skill 加载: `metadata.active_skills`、`metadata.steps[step=load_skill]`，以及 step 中的 `skill_name`。
4. tool call 摘要: `metadata.steps` 或 `metadata.tool_steps` 中的 `search_questions/draw_questions/select_question/load_skill` step。
5. 采用题目: `metadata.selected_question` 和 `metadata.question_plan`。
6. 面试状态: `metadata.interview_state.coverage` 和 `next_focus`，可用于报告或调试面板。

前端不要假设 metadata 一定存在。旧消息应降级为空状态。

## 测试计划

### 后端单元测试

- `coverage_config`:
  - 已知岗位 + 难度返回指定阈值。
  - 未知岗位/难度回退 `agent_llm/mid`。
- `rhythm_profile`:
  - 面经题目可分类并生成 distribution/transition。
  - 低质量面经返回低 confidence。
  - 读取面经时必须校验 owner/status/job_position。
- `interview_state`:
  - 能从 `InterviewLedger` 构建覆盖度快照。
  - Enum/string 可 JSON 序列化。
  - 旧消息缺 metadata 时不崩。

### Pipeline 测试

- `run_chat()` 的 done metadata 包含 `interview_state`。
- thinking 事件用真实 `content` 字段时，metadata.thinking chunks 不为空。
- `active_skills` 能进入 assistant message metadata，`load_skill` step 能携带 skill 名称。
- tool call 通过 step/tool_steps 摘要进入前端 metadata，不泄露 raw payload。
- 可选 tool trace 审计只保存脱敏 args 和 result summary。

### Router/Service 测试

- 创建会话保存 `interview_config`。
- `experience_id` 越权返回 404 或 403。
- `get_messages()` 返回 metadata，可用于前端恢复。

### 前端测试

- 新消息流式过程中显示 thinking/step。
- 刷新后从历史 metadata 恢复 thinking duration、thinking 内容、skill 名称、tool step 摘要和 selected question。
- 旧消息 metadata 为空时 UI 不报错。

## 实施顺序

1. 修正 thinking metadata 收集字段: 同时兼容 `content` 和 `data.text`。
2. 统一前端历史 thinking 渲染: 兼容旧字符串和新 list chunks。
3. 增强 `load_skill` step: 持久化 skill 名称，前端刷新后可见。
4. 增强 tool step 摘要: 保存工具名、耗时、结果数量、fallback 状态。
5. 添加 `coverage_config.py` 和 `rhythm_profile.py`，包含权限安全读取。
6. 添加 `interview_state.py`，只负责快照构建和序列化。
7. 修改 create conversation，保存 `interview_config`。
8. 修改 `_step_load_context` / prompt 构建，注入 `interview_state`。
9. 修改 done metadata，持久化 `interview_state` 和 observability 摘要。
10. 可选: 增加 `chat_tool_traces` 后端审计表和写入逻辑。

## 验收标准

- 新会话能配置 difficulty，可选指定面经节奏来源。
- 同一会话多轮后，`GET /messages` 中 assistant metadata 包含可恢复的 `interview_state`。
- 页面刷新后能看到每轮 assistant 的思考耗时、thinking 内容、已加载 skill 名称、工具步骤摘要和采用题目。
- 完整 raw tool call 不暴露给前端。
- 越权 `experience_id` 不能读取。
- `docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q` 通过。

## 风险

- metadata 体积膨胀: thinking chunks、steps、interview_state 都要限制长度。
- 阶段分类不准: 第一版必须保留 confidence 和 unknown_count，不把低置信面经强行变成节奏。
- 状态双写分裂: `InterviewLedger` 是重建来源，`interview_state` 是快照，不允许两边各自独立推进。
- 隐私泄露: tool trace 只能保存脱敏 args 和摘要。

## 参考文件

- `backend/app/agents/chat/CLAUDE.md`
- `backend/app/agents/chat/pipeline.py`
- `backend/app/agents/chat/react_loop.py`
- `backend/app/agents/chat/question_plan.py`
- `backend/app/agents/chat/metadata.py`
- `backend/app/agents/chat/answer.py`
- `backend/app/routers/chat.py`
- `backend/app/services/chat_service.py`
- `backend/app/mcp_server/session.py`
- `backend/app/db/migrations/chat.py`
- `backend/app/db/migrations/question_bank.py`
