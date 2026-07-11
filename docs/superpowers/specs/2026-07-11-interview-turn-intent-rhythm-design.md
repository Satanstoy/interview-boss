# 模拟面试 TurnIntent 与节奏控制设计

日期：2026-07-11
状态：设计已讨论确认，等待实现计划 review

## 问题

当前 chat harness 已经把 ReAct 的工具执行和最终面向候选人的话术分开，但节奏控制仍分散在三处：

- `interview-rhythm` 与领域 skill 影响 ReAct prompt；
- `rhythm_profile`、覆盖率与 stop policy 影响题型阈值和收尾；
- contract writer 只拿到很薄的 `next_focus`，重新猜下一问。

因此 skill 即使已加载、ReAct 即使已按它调用工具，最终 writer 仍可能提出泛化或节奏不合适的问题。系统缺少一个唯一且可观测的决策，说明本轮为什么是深挖、澄清、切题、回答反问或收尾。

## 目标

- 保持纯 async harness，不重新引入 LangGraph 的状态边。
- 保持 ReAct 只负责证据与工具执行。
- 让 `rhythm_profile`、`interview-rhythm` 与 `project-deep-dive` 等聚焦 skill 一起影响最终用户可见回合。
- 不枚举候选人的说法，也不维护关键词式对话状态；使用 LLM 语义理解与结构化面试事实。
- 保留现有五种 `TurnContract` action。
- 将实际执行的节奏决策写入 done metadata，并可在 API E2E 中验证。

## 非目标

- 不在会话开始时生成固定的 10-15 题脚本。
- 不让一个 LLM prompt 同时决定工具、策略和最终问题。
- 不把 skill 内的示例变成字面题目。
- 不让每轮都需要阻断式 LLM validator。

## 总体架构

```text
LLM 语义解释器
  -> 面试策略引擎
  -> TurnIntent
  -> TurnContract
  -> ReAct 证据采集（需要工具时）
  -> Contract writer
  -> validator / metadata
```

### LLM 语义解释器

沿用现有结构化 classifier，负责理解当前候选人回合：回答质量、候选人行为、是否反问、是否要求结束、是否需要澄清，以及语义置信度。它不决定最终问题，也不决定节奏策略。

### 面试策略引擎

这是唯一的节奏决策权威，综合以下输入：

- 语义解释器的结构化事实；
- `InterviewLedger` 中的题目覆盖、最近话题和重复事实；
- `rhythm_profile` 提供的宏观覆盖偏好；
- `interview-rhythm` 提供的连续深挖和维度切换规则；
- 当前聚焦 skill 的局部追问策略，例如项目深挖的下一层。

策略采用混合裁决：

- LLM 语义理解可判断当前项目是否仍有值得继续深挖的未解决材料；
- ledger 与覆盖规则负责硬边界，防止同类追问过多、重复题、遗漏关键维度和过早收尾。

### TurnIntent

`TurnIntent` 是单轮短生命周期决策记录，不是会话状态机，也不负责分类候选人措辞。

建议结构：

```python
class TurnIntent(BaseModel):
    strategy: Literal[
        "deep_dive", "clarification", "topic_shift",
        "counter_response", "close",
    ]
    assessment_goal: str
    target_dimension: str | None
    drill_layer: str | None
    tool_intent: ToolIntent
    writer_brief: WriterBrief
    source_facts: dict
    reason: str
```

示例：

- `deep_dive + drill_layer=decision_rationale`：围绕候选人已经提到的架构选择追问取舍；
- `topic_shift + target_dimension=algorithm_coding`：必须从对应题库类别选择算法题；
- `clarification`：保持同一个评估信号，不检索新题。

`writer_brief` 只包含证据锚点、本轮要收集的信号和语义边界，不包含固定题目模板。

### 两类节奏来源的职责

`rhythm_profile` 是宏观 policy：题型比例、缺失维度和是否具备收尾条件。

`interview-rhythm` 是策略规则：根据宏观事实选择本轮继续深挖、澄清或切换维度。

聚焦 skill 只在策略已经确定后提供局部追问策略：

- `project-deep-dive`：架构、取舍、故障恢复、压力测试、个人贡献或量化影响；
- `theory-qa`：基础知识允许的追问深度和预期证据；
- `algorithm-coding`：算法题的预期证据与题库使用方式。

skill 不再依赖最终 writer 从非结构化 ReAct prompt 中重新理解长篇说明。

### TurnContract、ReAct 与 writer 的边界

现有五种 `TurnContract` action 保持不变。`TurnIntent` 在最终输出前生成，说明这个 action 应如何执行。

ReAct 只接收 intent 指定的工具需要，可检索候选题、抽题、显式选题和加载 skill；它不能改掉已经确定的策略或最终 contract。

writer 同时接收 `TurnContract` 与 `TurnIntent`：

- follow-up writer 按确定的深挖层或切题方向表达问题；
- question writer 在保持 intent 评估目标的前提下表达已选题；
- counter 与 close writer 在 metadata 保留当前 intent，供后续总结与覆盖记录区分正常反问和未收集到的回答信号。

## 评估证据的后续衔接

同一份 intent 会记录面试官期望收集的信号。下一轮语义解释器记录该信号是已观察、部分观察还是未观察。技术问题尚未回答时出现候选人反问，应记录为 `not_assessed`，不能记录为薄弱或回避。

该证据是后续练习反馈 summary 的输入，与节奏策略分层，但共享题目和回合标识。

## 可观测性

done metadata 新增：

```json
{
  "turn_intent": {
    "strategy": "deep_dive",
    "assessment_goal": "decision_rationale",
    "target_dimension": "project_followup"
  },
  "turn_contract": {"action": "continue_natural_followup"},
  "writer_trace": {"writer": "followup_writer"},
  "tool_contract_trace": {}
}
```

metadata 必须记录实际执行的 intent，不能在输出后另做一个旁路决策。

## TDD 验收场景

1. 项目已完成两层充分回答且理论覆盖不足：策略引擎必须生成 `topic_shift -> theory`，writer 不能继续项目深挖。
2. 项目仍缺技术取舍信号：策略引擎必须生成 `deep_dive -> decision_rationale`，不能检索或提出算法题。
3. 候选人提出反问：contract 为 `answer_counter_question`；尚未收集到的技术信号保持 `not_assessed`，不是负面证据。
4. 候选人要求结束：contract 为 `close_with_summary`；summary 输入将未观察信号标为 `not_assessed`，不能写成薄弱或回避。
5. API E2E：每个相关回合的 done 事件必须暴露实际执行的 `turn_intent`、contract、工具 trace 和 writer trace。

## 迁移步骤

1. 引入 `TurnIntent` 与策略引擎，先以旁路观测方式运行，并补纯函数测试。
2. 将 intent 注入 contract executor 与 writer，使其成为最终 writer brief 的唯一来源。
3. 在 metadata 中持久化实际 intent 与评估证据。
4. 把刚才 `sj` 的真实会话转成 mock API E2E fixture，并保留真实模型手工验收以判断自然度。
