# 模拟面试 Harness P2：CandidateSet、EvidenceBundle 与结构化 Turn 设计

**日期：** 2026-07-14  
**状态：** 核心 domain/ledger 已实现（migration 046、CandidateSet、EvidenceBundle、TurnContractV2、event/generation replay）；完整 writer adapter 和 H0/H1/H2 profile 仍可继续扩展
**前置：** P0 边界和 revision、P1 durable side effects

## 背景

当前候选题仍保存在 ReAct state/MCP session JSON，ReAct 工具输出和最终话术
之间通过 ad-hoc 字段连接，TurnContract 的 payload/source facts 没有统一
版本。`closing_stage`、distribution、coverage 和 assistant generations 也
没有一个完整的结构化 turn ledger。

## 目标

1. 候选集成为有 owner、source、expiry、消费状态的服务端对象。
2. ReAct 只产生可审计的 `EvidenceBundle`，不决定最终话术或状态转移。
3. TurnContract 变成版本化、类型化、可验证的内部 domain contract。
4. interview lifecycle、coverage、assistant generation 和 revision 可从同一
   turn 事实重建。

## 非目标

- 不改变 P0 已建立的 HTTP/SSE 兼容入口。
- 不允许 LLM 直接写 conversation status、coverage 或 candidate set。
- 不把所有历史消息物化为完整 event sourcing；只记录影响面试决策的 domain
  events。
- 不用 prompt 文本替代结构化状态机。

## 数据模型

### CandidateSet

```sql
CREATE TABLE chat_candidate_sets (
    id TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    conversation_id TEXT NOT NULL,
    source TEXT NOT NULL,
    source_turn_id TEXT,
    items_json TEXT NOT NULL,
    schema_version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'available',
    expires_at TIMESTAMP NOT NULL,
    selected_item_id INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    consumed_at TIMESTAMP
);
```

候选项只存 question ID、来源和排序证据。选择时永远从题库重新读取权威
内容；过期、跨用户、已消费候选不可绑定。

### EvidenceBundle

内部模型至少包含：

```python
class EvidenceBundle(BaseModel):
    schema_version: int
    tool_facts: list[ToolFact]
    selected_question_ref: QuestionRef | None
    candidate_set_ref: str | None
    coverage_facts: list[CoverageFact]
    source_refs: list[SourceRef]
    confidence: Literal["none", "low", "medium", "high"]
```

Bundle 不包含面试官最终自然语言。工具结果先经过 normalizer 和 authority
reload，再进入 bundle。

### TurnContract v2

```python
class TurnContractV2(BaseModel):
    schema_version: int
    action: TurnAction
    priority: int
    question_ref: QuestionRef | None
    evidence_refs: list[str]
    state_transition: StateTransition
    writer_brief: WriterBrief
    contract_hash: str
```

不同 action 使用不同 payload model，不再使用任意 `dict`。writer 只能消费
contract 和 bundle，validator 验证输出是否满足 contract。

### Assistant generations

assistant message 与 generation/revision 独立建模，保存 parent generation、
source turn、contract hash、evidence refs 和 visible status。前端可以选择当前
visible generation，历史 revision 仍可审计。

## 服务端状态机

将 interview lifecycle 明确为：

```text
technical -> candidate_question -> final_summary -> closed
```

每次转移必须由服务端 deterministic transition function 产生，并写入
`interview_events`。LLM classifier 只能提供候选事实和 confidence，不能直接
写状态。非法转移拒绝生成并记录 reason。

coverage/distribution 从 append-only events 折叠成 read model；下一轮读取
read model，不依赖前端展示 metadata 或上一轮模型复述。

## ReAct 边界

ReAct 的输出只包括：

- tool call trace；
- normalized tool facts；
- selected candidate/question reference；
- evidence confidence；
- stop/budget reason。

达到最大步骤时不得用 raw LLM text 作为最终 answer；必须交给
`TurnPlanner -> TurnContractV2 -> Writer -> Validator`。

## 测试

- candidate set owner/expiry/consumption/authority reload；
- tool facts 能构建稳定 EvidenceBundle；
- contract schema version、hash、evidence refs 和 state transition 校验；
- writer 无法越过 contract 改变 action；
- classifier 不能直接结束或重置 interview state；
- revision generation 可回放，coverage 不重复计数；
- 任意单 turn event replay 后 read model 与线上状态一致；
- evaluator 支持 H0/H1/H2 能力隔离实验，而不只是改 prompt label。

## 交付顺序

1. domain model 与 schema version；
2. CandidateSet repository/authority reload；
3. EvidenceBundle normalizer；
4. TurnContract v2 与 writer adapter；
5. lifecycle event/read model；
6. assistant generation/revision UI；
7. evaluator harness profiles 和 replay/fault matrix。

## 当前实现映射

- `chat_candidate_sets` 只持有 question reference，消费时通过 `resolve_candidate_question()` 从权威题库重新加载。
- `structured_turn.py` 提供 typed `EvidenceBundle`、`TurnContractV2`、稳定 contract hash 和 writer output validator。
- `interview_events` 折叠为 deterministic lifecycle/coverage read model；`assistant_generations` 独立保存 visible generation、parent 和 evidence refs。
- legacy `TurnContract`、HTTP/SSE 和既有 distribution metadata 保持兼容，P2 通过 adapter 逐步接入。
