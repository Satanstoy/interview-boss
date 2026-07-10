# Interview Agent Harness 设计

日期：2026-07-10
状态：设计完成，待用户 review

## 背景

`backend/scripts/eval_interview_agent.py` 近期报告暴露了模拟面试 agent 的几个真实问题：

1. 工具调用和候选题检索发生了，但最终没有稳定形成 `selected_question` / `asked_questions`。
2. 已绑定的计划题可能没有被自然问出来，失败时不能用 `{question_text}` 或固定前缀话术伪装完成。
3. 收尾阶段出现重复 goodbye、无结构化总结，或把自然收尾语和总结 renderer 混在一起。
4. 当前 ReAct loop 同时承担工具调用、流程选择和最终用户可见话术，导致后端只能在末尾做事后修补。

本设计把模拟面试 agent 从 ReAct-only 调整为 Interview Agent Harness：ReAct loop 保留为工具和证据采集阶段，最终用户输出由本轮 `TurnContract`、专门 writer 和 validator 接管。

## 设计目标

- 不回到 LangGraph 状态图，不用大量边和场景分支枚举用户说法。
- 不用正则/关键词作为主流程判断器。正则只允许用于格式、安全、legacy fallback。
- 不让 ReAct loop 拥有最终用户可见输出。
- 不使用机械题干 fallback。不能自然完成 contract 时，返回可观测的生成失败。
- 收尾一律采用两阶段：LLM 自然收尾语 + LLM 结构化面试总结。
- 保留现有 skill 和 MCP 工具能力，但把它们限定在工具使用和证据采集层。
- 让 eval 可以同时检查 final output、trajectory、contract、validator 结果。

## 非目标

- 不重写整个 chat pipeline。
- 不引入 LangGraph 或其他图框架。
- 不把 TurnPlanner 做成纯 LLM planner。
- 不让每一轮都强制做 LLM validator，避免延迟和成本失控。
- 不把所有自然追问都强行绑定题库题。
- 不改动当前拆分中的 `backend/scripts/eval_interview_agent.py`。

## 主流实践对齐

本设计采用生产 agent 常见的 harness 模式：

- Anthropic 的 agent workflow 建议把复杂任务拆成 prompt chaining、routing、evaluator gate，而不是一个 prompt 负责所有决策和输出。
- OpenAI Agents SDK 将 agent 表达为 LLM、tools、structured outputs、guardrails 和 runtime hooks 的组合。
- LangChain / LangGraph 文档区分 workflow 与 agent：workflow 适合有产品流程和退出条件的确定路径，agent 适合动态工具使用。

InterviewBoss 的模拟面试不是开放聊天。它有题库覆盖、面试节奏、收尾总结和反问处理这些产品契约，因此应采用 agent inside workflow：外层 harness 管契约，ReAct 管工具，LLM writer 管自然表达。

## 总体架构

```text
run_chat
  -> load context / ledger / interview state
  -> Semantic Classifier
  -> Tool Strategy
  -> ReAct Tool Loop
      -> load_skill
      -> search_questions / draw_questions / select_question
      -> write retrieved_questions / candidate_questions / selected_question
  -> TurnPlanner
      -> emits TurnContract
  -> Contract Writer
      -> natural user-facing text or structured JSON
  -> Validators
      -> deterministic checks
      -> selected LLM semantic validators
  -> stream final response
  -> done metadata / coverage_events / eval traces
```

Ownership after the change:

| Layer | Owns | Does not own |
|-------|------|--------------|
| Semantic Classifier | 语义信号 | 最终 contract |
| ReAct Tool Loop | 工具调用和证据采集 | 最终用户话术 |
| TurnPlanner | 本轮输出契约 | 原始文本语义理解 |
| Writer | 自然表达 / JSON summary | 流程决策 |
| Validator | pass / fail / retry feedback | 新流程选择 |

## 节点设计与避免正则的方式

### Semantic Classifier

LLM 级别。它读取用户当前消息、上一道问题、短历史、interview state，输出结构化语义信号，而不是输出下一状态。

示例：

```json
{
  "candidate_act": "answered_question",
  "answer_quality": "complete",
  "asked_counter_question": false,
  "asked_for_summary": false,
  "requested_end": false,
  "needs_clarification": false,
  "needs_new_dimension": true,
  "suggested_question_type": "system_design",
  "should_retrieve": true,
  "confidence": 0.86,
  "evidence": "候选人完整回答了 Agent 工具调用落地，可以切到系统可靠性评估"
}
```

避免正则的方法：

- 不通过“谢谢”“总结”“吗”等关键词判断用户意图。
- 让 LLM 基于上下文输出语义字段和证据说明。
- 后端只消费结构化字段，不让 classifier 直接选择 contract。

### Ledger / Coverage

确定性事实账本。主路径读取 metadata，而不是从自然文本猜。

事实包括：

- 已问过的 `question_id` 和题面。
- 各 phase / question_type / cat1 / cat2 的覆盖情况。
- 本轮和历史的 `coverage_events`。
- 是否已问过候选人反问。
- 最近评估焦点和重复追问信号。

避免正则的方法：

- 优先读取 `coverage_events`、`selected_question`、`asked_question_id` 等结构化 metadata。
- 历史文本解析只作为旧数据兼容，不参与新路径主判断。

### Tool Strategy

根据 semantic signals 和 coverage gap 生成工具意图。

示例：

```text
answer_quality=complete
needs_new_dimension=true
coverage 缺 algorithm_coding
suggested_question_type=algorithm_coding
-> recommend draw_questions(question_type="algorithm_coding")
```

避免正则的方法：

- 不因用户说了“代码”“系统”就直接抽题。
- 由 LLM 语义结果和 coverage 事实共同决定是否需要工具。

### ReAct Tool Loop

保留现有 ReAct 工具能力，但职责收窄为 evidence collector。

职责：

- 根据 tool strategy 和 skill 指令调用 `load_skill`、`search_questions`、`draw_questions`、`select_question`。
- 读取统一 tool envelope。
- 写入 `retrieved_questions`、`candidate_questions`、`selected_question`、`tool_calls_trace`、`active_skills`。

不再负责：

- 直接生成最终用户可见问题。
- 决定是否进入最终总结。
- 在已有 `selected_question` 时自由改写成另一道题。

避免正则的方法：

- 动态工具调用仍由 ReAct + skill 完成，不写死关键词到工具映射。
- 工具返回结构化 envelope，后续节点消费结构化事实。

### Question Selector

将候选题升级为 `selected_question` 的选择器。它可以位于工具执行后或 `select_question` 路径中。

判断依据：

- `question_id` 存在且未问过。
- `question_type` 与 requested / suggested 类型匹配。
- 与当前 coverage gap 匹配。
- 题目不命中 negative terms。
- 相关性分数、rerank 结果或 LLM rerank 说明达到阈值。

避免正则的方法：

- 不用题面字符串包含某个词作为主绑定条件。
- token overlap 只能做弱信号；强绑定依赖结构化字段和语义 rerank。

### Stop Policy

确定性策略函数。它结合语义信号和面试事实决定是否允许或要求结束。

输入：

- coverage 是否足够。
- message_count 是否超过 soft / strong / hard close 阈值。
- 是否已问过候选人反问。
- semantic classifier 是否判断用户要求结束或要求总结。
- 候选人是否真的在反问。

避免正则的方法：

- “用户是不是想结束”来自 LLM semantic classifier。
- StopPolicy 不读取原始文本关键词作为主判断。
- 关键词检测只允许保留为 legacy session 的低优先级兜底。

### TurnPlanner

确定性 policy，但不是正则。它不读原始用户文本，只读结构化输入。

输入：

- semantic classifier result。
- ledger / coverage facts。
- stop policy result。
- tool facts，包括 `selected_question`。

输出本轮 `TurnContract`。

优先级：

```text
1. close_with_summary
2. answer_counter_question
3. clarify_candidate_answer
4. ask_selected_question
5. continue_natural_followup
```

设计理由：

- `close_with_summary` 优先，因为收尾是产品级 exit condition。
- `answer_counter_question` 优先于继续技术面，避免候选人反问被硬切题库题。
- `clarify_candidate_answer` 优先于 `ask_selected_question`，避免回答含糊时为了覆盖率强切新题。
- `ask_selected_question` 只有在 coverage gap 明确、题库选题高置信、无更高优先级 contract 时才出现。
- `continue_natural_followup` 是默认低风险路径。

避免正则的方法：

- Planner 不判断“这句话是什么意思”，只裁决已经结构化的事实。
- 不枚举用户话术，不维护“感谢状态”“结束状态”等长期状态。

## TurnContract 设计

`TurnContract` 是短生命周期对象，只对本轮有效。下一轮重新计算，历史事实写入 ledger。

建议 schema：

```python
class TurnContract(BaseModel):
    action: Literal[
        "close_with_summary",
        "answer_counter_question",
        "clarify_candidate_answer",
        "ask_selected_question",
        "continue_natural_followup",
    ]
    priority: str
    payload: dict
    validation: list[str]
    reason: str
    source_facts: dict
```

示例：

```json
{
  "action": "ask_selected_question",
  "priority": "coverage_gap",
  "payload": {
    "question_id": 6370,
    "question_text": "Agent范式在项目中有没有用过？",
    "source": "draw_questions",
    "expected_focus": ["agent范式", "项目落地经验"]
  },
  "validation": [
    "non_empty",
    "no_internal_marker",
    "semantic_question_adherence"
  ],
  "reason": "knowledge_probe gap with high-confidence selected question",
  "source_facts": {
    "answer_quality": "complete",
    "needs_new_dimension": true,
    "selected_question_id": 6370
  }
}
```

## Contract Writers

每个 writer 只负责把 contract 表达出来，不拥有流程决策。

| Writer | 输入 | 输出 | 禁止 |
|--------|------|------|------|
| `question_writer` | selected question + 上一答 + 面试上下文 | 自然提问 | 换题、机械 fallback |
| `clarify_writer` | 上一题 + 候选人含糊回答 | 澄清问题 | 引入新题 |
| `counter_writer` | 候选人反问 + 面试上下文 | 回答反问 | 继续技术追问 |
| `closing_writer` | 收尾原因 + transcript summary | 自然收尾语 | 输出结构化总结 |
| `summary_writer` | 全量 transcript + metadata | structured JSON summary | 输出普通聊天文本 |
| `followup_writer` | 上一答 + 当前 focus | 自然追问 | 过早总结 |

`close_with_summary` 固定两阶段：

```text
closing_writer -> natural closing utterance
summary_writer -> structured JSON summary
renderer -> combine
```

`_render_interview_summary_markdown()` 不应再内置固定收尾句。收尾语属于 `closing_writer`。

## Validator 设计

Validator 分两层。

### Deterministic Validators

用于格式、安全和结构，不做语义理解。

- `non_empty`
- `no_internal_marker`
- `no_unrequested_summary`
- `summary_json_schema_valid`
- `contract_payload_complete`
- `selected_question_payload_present`
- `no_mechanical_question_fallback`

### LLM Semantic Validators

只用于语义契约。

线上阻断：

- `semantic_question_adherence`：`ask_selected_question` 必须通过。失败后带 feedback 重试一次；仍失败则返回 `GenerationError`。

先观测、后续可升级：

- `counter_answer_grounding`：反问回答是否基于上下文，是否胡编岗位信息。
- `closing_utterance_check`：收尾语是否自然结束，是否继续提新技术题。
- `summary_evidence_check`：总结强弱项是否能从 transcript 找到证据。
- `clarification_adherence`：澄清问题是否真的围绕上一答补证据。

`semantic_question_adherence` 输出示例：

```json
{
  "passes": true,
  "score": 0.91,
  "reason": "最终问题询问候选人是否在项目中使用过 Agent 范式，与计划题语义一致。",
  "detected_question": "你在那个项目里有实际用过 Agent 范式吗？",
  "issues": []
}
```

失败示例：

```json
{
  "passes": false,
  "score": 0.38,
  "reason": "最终问题转向工具调用稳定性，没有询问是否实际使用过 Agent 范式。",
  "detected_question": "你们怎么保证工具调用稳定？",
  "issues": ["topic_drift"]
}
```

## 失败策略

通用规则：

```text
writer output
  -> deterministic validators
  -> required LLM semantic validators
  -> pass: stream output
  -> fail: retry once with validator feedback
  -> still fail: GenerationError
```

明确禁止：

- 不输出 `{question_text}`。
- 不输出“好，那我们聊聊 XXX？”这类固定机械 fallback。
- 不把失败隐藏成 conversation-only followup。

失败时 metadata 必须记录：

- `turn_contract`
- `writer_name`
- `validator_results`
- `retry_count`
- `generation_error_code`
- `selected_question_id`（如果有）

## Skill 和 MCP 工具的位置

Skill 和 MCP 工具保留在 ReAct Tool Loop 层。

Skill 负责：

- 指导何时 `search_questions` / `draw_questions` / `select_question`。
- 说明如何读取 tool envelope。
- 防止弱相关题强绑定。
- 指导 algorithm/coding/system_design 等题型的工具使用。
- 避免泄露内部工具信息。

MCP tools 负责：

- `load_skill`：加载工具使用策略。
- `search_questions`：提供语义检索候选。
- `draw_questions`：提供题型/难度/分类抽题候选。
- `select_question`：显式绑定候选题。

它们不负责：

- 最终用户可见话术。
- 是否结束面试。
- 是否生成总结。
- contract pass/fail。

工具事实进入 state 后，由 TurnPlanner 判断是否足够形成 `ask_selected_question` contract。

## 与现有模块的映射

| 当前模块 | 调整后职责 |
|----------|------------|
| `pipeline.py` | orchestrate harness steps，保持 run_chat 入口 |
| `classify_result.py` | 扩展或收敛 semantic signal schema |
| `tool_strategy.py` | 从 semantic + coverage 推导工具意图 |
| `react_loop.py` | evidence collector，不再拥有最终输出 |
| `tools.py` / `tool_gateway.py` | 保持 tool envelope 和 state 更新 |
| `question_plan.py` | 提供 question selection / ledger / coverage helper |
| `stop_policy.py` | 继续做产品级结束裁决，但输入 semantic signal |
| `turn_controller.py` | 可替换或收敛为 `turn_planner.py` |
| `answer.py` | 拆出 contract writers 和 validators；保留通用输出清洗 |
| `summary.py` | 拆分 closing_writer、summary_writer、renderer |
| `output_guardrails.py` | 纳入 deterministic / semantic validator 体系 |

## 数据流细节

### 正常新题路径

```text
用户完整回答上一题
  -> classifier: answer_quality=complete, needs_new_dimension=true
  -> coverage: 缺 system_design
  -> tool_strategy: draw_questions(system_design)
  -> react_loop: draw/select 得到 selected_question
  -> planner: ask_selected_question
  -> question_writer: 自然过渡到该题
  -> semantic_question_adherence: pass
  -> stream
  -> metadata: coverage_events + turn_contract + validator result
```

### 回答含糊路径

```text
用户回答很短或缺关键证据
  -> classifier: answer_quality=vague, needs_clarification=true
  -> planner: clarify_candidate_answer
  -> clarify_writer: 追问上一答的具体证据
  -> deterministic validators
  -> stream
```

### 反问路径

```text
候选人问面试官问题
  -> classifier: candidate_act=asked_counter_question
  -> stop_policy: not force close
  -> planner: answer_counter_question
  -> counter_writer
  -> grounding validator 先观测
  -> stream
```

### 收尾路径

```text
coverage 完整或用户要求总结且证据足够
  -> stop_policy: close
  -> planner: close_with_summary
  -> closing_writer: 自然收尾语
  -> summary_writer: JSON summary
  -> schema validator: pass
  -> renderer
  -> stream
```

## Observability 与 Eval

done metadata 应新增或稳定以下字段：

```json
{
  "turn_contract": {
    "action": "ask_selected_question",
    "reason": "...",
    "payload": {"question_id": 6370}
  },
  "writer_trace": {
    "writer": "question_writer",
    "retry_count": 1
  },
  "validator_trace": [
    {
      "name": "semantic_question_adherence",
      "blocking": true,
      "passes": true,
      "score": 0.91,
      "issues": []
    }
  ],
  "tool_contract_trace": {
    "selected_question_id": 6370,
    "source": "draw_questions"
  }
}
```

Eval 需要从只看文本升级为三层：

- Final output：用户看见的文本是否自然、是否有总结。
- Trajectory：是否调用了合理工具，是否绑定了题。
- Contract：planner 选择是否合理，writer/validator 是否执行并通过。

关键评测项：

- `ask_selected_question` 必须有 selected question、writer trace、blocking validator pass。
- `close_with_summary` 必须有 closing utterance 和 schema-valid summary。
- 非收尾 contract 不能输出总结。
- 反问路径不能继续追技术题。
- 含糊回答应进入 clarify，而不是强切新题。

## 迁移策略

建议分阶段实现，降低风险：

1. 引入 `TurnContract` 数据结构和 metadata trace，但先旁路观测，不改变输出。
2. 将 `close_with_summary` 改为自然收尾语 + 结构化总结，修复 summary renderer 混入固定收尾语。
3. 将 `ask_selected_question` 从事后 `_enforce_question_plan_on_text()` 升级为 contract writer + blocking semantic validator。
4. 收敛 `turn_controller.py` / `stop_policy.py` 冲突，形成 `turn_planner.py`。
5. 将 ReAct final output ownership 下放，只保留工具/证据职责。
6. 补充 eval 和 Docker chat tests，覆盖 contract、validator、summary schema、反问和澄清路径。

实现阶段必须遵守 TDD：

- 先写 failing tests。
- Docker 运行 `docker compose --profile test run --rm test uv run pytest backend/tests/chat/ -q`。
- 修改 chat agent 后更新 `backend/app/agents/chat/CLAUDE.md`。

## 已确认决策

- 不使用 LangGraph。
- TurnPlanner 不是纯 LLM，而是 deterministic policy over structured facts。
- `ask_selected_question` 的 LLM semantic validator 线上阻断。
- 失败不展示机械 fallback。
- `close_with_summary` 永远输出自然收尾语 + 结构化总结。
- Skill 和 MCP 工具保留在 ReAct Tool Loop / Evidence Collector 层。

## 实施细化约束

- 第一阶段优先扩展现有 `ClassifyResult`，避免新增并行 classifier schema；若字段膨胀或职责不清，再拆出 `TurnSemanticSignal`。
- `semantic_question_adherence` 初始只服务 `ask_selected_question`，采用结构化 JSON judge；通过阈值建议从 `passes=true` 且 `score >= 0.75` 起步，具体阈值由 golden eval 校准。
- `semantic_question_adherence` 失败后只允许一次 retry，retry prompt 必须带 validator feedback、原始 contract 和上一轮输出。
- `counter_answer_grounding`、`summary_evidence_check`、`clarification_adherence` 第一阶段只记录 metadata，不阻断线上输出；只有 eval 证明误放风险高于延迟成本时再升级为阻断。
- `react_loop.py` 的最终输出 ownership 应分阶段迁移：先保持现有输出并旁路记录 contract trace，再把 `ask_selected_question` 和 `close_with_summary` 两条高风险路径切到 writer/validator，最后再收敛自然追问路径。
- 旧会话缺少 `coverage_events` 时，ledger 可继续使用历史文本解析 fallback；新会话和新 metadata 必须以结构化事件为准。
