# ADR-0032: Benchmark Case 使用结构化评测契约

**Status:** accepted

Benchmark Case 不以一段不可解析的期望描述作为唯一评测依据，而是使用结构化 Case Contract。Contract 允许同一份 Case 定义同时驱动确定性 Hard Assertion、LLM Judge 和人工 Pairwise Review。

1.0 的 Case Contract 至少包含：

```json
{
  "facts": [],
  "actions": [],
  "boundaries": [],
  "quality_requirements": [],
  "hard_assertions": [],
  "rubric": [],
  "reference_answer": null
}
```

`facts`、`actions` 和 `boundaries` 描述必须满足的行为约束；`quality_requirements` 和 `rubric` 描述开放式表现；`hard_assertions` 必须可由轨迹、结构化输出、工具调用或状态直接判定；`reference_answer` 只作为可选辅助证据，不代表唯一正确文本。

Contract 本身纳入 Evaluation Release 的 Benchmark Manifest 和 `content_digest`。修改任何字段都必须创建新的 Evaluation Release，历史 Eval Run 继续引用旧 Contract。
