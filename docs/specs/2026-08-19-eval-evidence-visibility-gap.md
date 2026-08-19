# Spec: 评测 Case 证据可见性差距分析与改进方案

> 位置: `frontend/src/components/business/EvalEvidencePanel.vue` + `frontend/src/views/admin/EvaluationRunView.vue`
> 类型: 前端数据展示补全
> 日期: 2026-08-19
> 状态: 待实施
> 依据: 后端数据模型分析（`admin_evaluation.py` + `evaluation_executor.py` + 各 adapter）vs 前端 EvalEvidencePanel 渲染逻辑

## 背景

后端为每个评测 Case 返回了极其丰富的数据：完整对话轨迹（含每轮工具调用链、意图分类结果）、确定性指标明细（逐项比对）、Judge 多维度评分及推理、关键问题与亮点、冻结的输入快照和评测契约。但前端 `EvalEvidencePanel` 目前只展示了其中约 20% 的信息。

用户点击一个 Case 后，只能看到：
- 对话文字（仅 user/assistant 文本，元数据全部丢弃）
- 两个聚合数字（如 "3 次调用 · 0 次失败"）
- 一个最终分数（如 0.837）

**看不到**：这个 Case 要测什么、Agent 每一轮做了什么决策、Judge 为什么给这个分、出了什么具体问题。

---

## 差距矩阵：后端提供 vs 前端展示

### 1. 对话记录（turns）

**后端提供**（`observation.payload.turns[]`）：
```
{
  "turn": 1,
  "user": "候选人消息",
  "assistant": "面试官回复",
  "events": [ ... pipeline 事件 ... ],
  "metadata": {
    "tool_calls_trace": [
      { "tool_name": "search_questions", "ok": true, "result_count": 5, "elapsed_ms": 320, "fallback_used": false }
    ],
    "classify_result": {
      "intent": "knowledge_question",
      "candidate_act": "answer",
      "should_retrieve": true,
      "requires_question_bank": true
    },
    "turn_intent": { "strategy": "deep_dive", "tool_intent": { "requires_question_bank": true } },
    "selected_question": { "id": "q_123" },
    "question_source": "search",
    "has_summary": false
  }
}
```

**前端展示**：
```html
<div>候选人 · 第 1 轮</div>
<div>{{ turn.user }}</div>
<div>面试官 / Agent</div>
<div>{{ turn.assistant }}</div>
```

**缺失**：
- ❌ 工具调用轨迹（`tool_calls_trace`）— 每轮调了什么工具、成功/失败、耗时、返回几条结果
- ❌ 意图分类结果（`classify_result`）— 每轮判了什么意图、候选人行为类型、是否需要检索
- ❌ 决策策略（`turn_intent`）— Agent 本轮的策略选择
- ❌ 题目来源（`question_source`）— 题目是从搜索/抽取/内部/检索来的
- ❌ Pipeline 事件（`events`）— Agent 内部执行步骤

---

### 2. 工具调用效果（tool_metrics）

**后端提供**：
```
{
  "call_count": 3,
  "tool_names": ["search_questions", "search_bank"],
  "failed_call_count": 0,
  "required_tools": ["search_questions"],
  "required_tools_missing": [],
  "forbidden_tools_used": [],
  "result_used": true
}
```

**前端展示**：
```
工具调用: 3 次调用 · 0 次失败
```

**缺失**：
- ❌ 调用了哪些工具（`tool_names`）
- ❌ 必需工具是否缺失（`required_tools_missing`）
- ❌ 是否使用了禁止工具（`forbidden_tools_used`）
- ❌ 结果是否被使用（`result_used`）
- ❌ 逐轮调用详情（`tool_calls` 数组）

---

### 3. 意图识别效果（intent_metrics）

**后端提供**：
```
{
  "evaluated_count": 3,
  "failed_count": 0,
  "observed_turn_count": 3,
  "missing_intent_count": 0,
  "intent_coverage": 1.0,
  "strategy_coverage": 0.67,
  "accuracy": 1.0,
  "results": [
    {
      "turn": 1,
      "passed": true,
      "expected": { "intent": "knowledge_question", "candidate_act": "answer" },
      "actual": { "intent": "knowledge_question", "candidate_act": "answer" },
      "failures": []
    }
  ]
}
```

**前端展示**：
```
意图识别: 覆盖率 100% · 准确率 100%
```

**缺失**：
- ❌ 逐轮 expected vs actual 比对（`results[]`）
- ❌ 每轮失败原因（`failures[]`）
- ❌ 策略覆盖率（`strategy_coverage`）
- ❌ 缺失意图数量（`missing_intent_count`）

---

### 4. Judge 评分

**后端提供**：
```
{
  "judge_model": "gpt-4o",
  "judge_reported_score": 4.2,
  "weighted_avg": 0.84,
  "dimensions": {
    "relevance": { "score": 4, "reasoning": "回答与问题高度相关...", "weight": 0.3 },
    "depth": { "score": 5, "reasoning": "回答展示了深入理解...", "weight": 0.3 },
    "clarity": { "score": 4, "reasoning": "表达清晰...", "weight": 0.2 },
    "completeness": { "score": 3, "reasoning": "缺少具体例子...", "weight": 0.2 }
  },
  "critical_issues": ["未提供具体代码示例"],
  "highlights": ["对设计模式的理解很深入"]
}
```

**前端展示**：
```
Judge 分: 0.837
```

**缺失**：
- ❌ 各维度分数（`dimensions.*.score`）
- ❌ 各维度推理理由（`dimensions.*.reasoning`）
- ❌ 维度权重（`dimensions.*.weight`）
- ❌ 关键问题（`critical_issues`）
- ❌ 亮点（`highlights`）
- ❌ Judge 原始分数（`judge_reported_score`）
- ❌ Judge 模型（`judge_model`）

---

### 5. 分数分解

**后端提供**：
```
{
  "score": 0.837,
  "deterministic_score": 0.75,
  "deterministic_dimensions": ["tool_scoring", "intent_scoring"],
  "deterministic_weight": 0.6,
  "judge_weight": 0.4,
  "score_source": "hybrid",
  "weighted_avg": 0.84
}
```

**前端展示**：
```
混合 · 规则 0.750 · Judge 0.840
```
（在 RunView 的 `scoreSummary` 函数中，但该函数已被删除为死代码）

**缺失**：
- ❌ 确定性分数使用了哪些维度（`deterministic_dimensions`）
- ❌ 权重配置（`deterministic_weight` / `judge_weight`）
- ❌ 分数来源类型（`score_source`）的解释

---

### 6. 输入快照（input_snapshot）

**后端提供**（Interview 类型）：
```
{
  "candidate_view": {
    "profile": "候选人简历全文...",
    "difficulty": "medium",
    "mode": "standard",
    "opening": "请简单介绍一下你自己",
    "max_turns": 5
  },
  "harness_context": {
    "max_turns": 5,
    "behavior_injections": { "3": "如果候选人回答太短，追问一个具体例子" },
    "candidate_prompt_overrides": { ... }
  }
}
```

**前端展示**：
```html
<pre>{{ JSON.stringify(evidence.case?.input_snapshot || {}, null, 2) }}</pre>
```

**缺失**：
- ❌ 关键字段结构化展示（候选人画像、难度、模式、开场白）
- ❌ 行为注入说明（`behavior_injections`）
- ❌ 面试配置（`max_turns`, `mode`）

---

### 7. 评测契约（contract）

**后端提供**（Interview 类型）：
```
{
  "hard_assertions": [
    { "id": "selected_question" },
    { "id": "tool_result_used" },
    { "id": "raw_tool_leak" },
    { "id": "closing" }
  ],
  "rubric": {
    "relevance": { "weight": 0.3 },
    "depth": { "weight": 0.3 },
    "clarity": { "weight": 0.2 },
    "completeness": { "weight": 0.2 }
  },
  "tool_expectations": {
    "required_tools": ["search_questions"],
    "forbidden_tools": [],
    "min_calls": 1,
    "max_calls": 5,
    "max_failed_calls": 0,
    "require_result_used": true
  },
  "intent_expectations": [
    { "turn": 1, "expected_intent": "knowledge_question", "expected_candidate_act": "answer", "expected_strategy": "deep_dive", "requires_question_bank": true }
  ]
}
```

**前端展示**：
```html
<pre>{{ JSON.stringify(evidence.case?.contract || {}, null, 2) }}</pre>
```

**缺失**：
- ❌ 硬门禁项列表（哪些断言要检查）
- ❌ 评分维度及权重（`rubric`）
- ❌ 工具调用期望（`tool_expectations`）
- ❌ 逐轮意图期望（`intent_expectations`）— 这是判断 Agent 做得对不对的基准

---

### 8. 确定性指标明细（逐项比对）

**后端提供**（`intent_metrics.results[]`）：
```
{
  "turn": 1,
  "passed": true,
  "expected": { "intent": "knowledge_question", "candidate_act": "answer" },
  "actual": { "intent": "knowledge_question", "candidate_act": "answer" },
  "failures": []
}
```

**前端展示**：无。只有聚合数字。

**缺失**：
- ❌ 逐轮 expected vs actual 表格
- ❌ 每轮 pass/fail 状态
- ❌ 失败原因

---

## 改进方案

### Phase 1: Case 概览卡（新增）

在对话记录之前，加一个 Case 概览区，展示：
- **Case 标识**：case_key + scenario_key + replication_index + seed
- **输入摘要**：从 input_snapshot 提取关键字段（如：候选人画像前 100 字、难度、模式、开场白、最大轮数）
- **契约摘要**：硬门禁项数量、评分维度列表、必需工具、禁止工具
- **最终得分**：混合分 + 规则分 + Judge 分 + 分数来源

### Phase 2: 对话记录增强

每轮对话下方增加元数据折叠区：
- **工具调用**：本轮调了哪些工具、成功/失败、耗时、返回结果数
- **意图分类**：本轮判的意图、候选人行为、策略、是否需要题库
- **题目来源**：search / draw / retrieval / agent_internal

### Phase 3: 指标面板重构

将当前的"确定性指标"卡片改为分组展示：
- **工具调用详情**：调用列表（工具名/成功/失败/耗时）+ 必需工具检查 + 禁止工具检查 + 结果使用检查
- **意图识别详情**：逐轮 expected vs actual 表格 + 失败原因 + 策略覆盖率
- **结构化抽取详情**（extraction 类型）：逐字段 expected vs actual + field_results

### Phase 4: Judge 评分面板

将当前的单行 "Judge 分: 0.837" 改为：
- **维度分数表**：每个维度的分数、权重、推理理由
- **关键问题**：`critical_issues` 列表（红色标记）
- **亮点**：`highlights` 列表（绿色标记）
- **原始分数**：judge_reported_score + weighted_avg

### Phase 5: 分数分解面板

在评分区域增加分数分解可视化：
- **混合分数条**：规则分（蓝色段）+ Judge 分（绿色段）+ 最终分（标记线）
- **权重说明**：规则 60% + Judge 40%
- **确定性维度**：使用了哪些维度计分

### Phase 6: 契约详情面板

将当前的 JSON dump 替换为结构化展示：
- **硬门禁项**：每项的 ID + 当前状态（通过/失败）
- **评分维度**：维度名 + 权重
- **工具期望**：必需工具 / 禁止工具 / 调用次数范围 / 结果使用要求
- **意图期望**：逐轮 expected 意图/行为/策略/题库需求（与 actual 并排对比）

---

## 数据流改造

### 现状

```
fetchEvaluationItem(runId, itemId) → { item, case, attempts, artifacts }
  item.result = { observation, score }  ← 后端已解码 result_json
```

前端 `EvalEvidencePanel` 接收 `item`（来自 run.items[]，含 result）和 `evidence`（来自 fetchEvaluationItem，含 case/attempts/artifacts）。

### 改造点

1. **EvalEvidencePanel 需要完整 item.result**：当前模板只读 `turns(item)` 和 `hardAssertions(item)`，需要扩展读取 `item.result.score.dimensions`、`item.result.score.critical_issues`、`item.result.score.highlights` 等
2. **对话元数据提取**：从 `turn.metadata` 提取 tool_calls_trace 和 classify_result
3. **契约与实际对比**：将 `evidence.case.contract.intent_expectations` 与 `item.result.observation.payload.intent_metrics.results` 并排展示

---

## 文件影响

| 文件 | 改动 |
|------|------|
| `EvalEvidencePanel.vue` | 主要改造：新增 6 个面板组件 |
| `evaluationShared.js` | 新增：提取输入快照摘要、契约摘要的工具函数 |
| `EvalScoreBar.vue` | 可能扩展：支持显示维度分数 |

## 优先级

| Phase | 内容 | 用户价值 | 工作量 |
|-------|------|---------|--------|
| P1 | Case 概览卡 | ⭐⭐⭐ 立即知道这个 Case 在测什么 | 30m |
| P2 | 对话元数据 | ⭐⭐⭐ 知道 Agent 每轮做了什么 | 1h |
| P4 | Judge 维度详情 | ⭐⭐⭐ 知道分数为什么高/低 | 45m |
| P3 | 指标面板重构 | ⭐⭐ 逐项比对 | 1h |
| P5 | 分数分解 | ⭐⭐ 理解混合计分 | 30m |
| P6 | 契约详情 | ⭐⭐ 理解评测标准 | 45m |

**建议实施顺序**：P1 → P4 → P2 → P3 → P5 → P6（先解决"不知道在测什么"和"不知道为什么得这个分"两个核心问题）
