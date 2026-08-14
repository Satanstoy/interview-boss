# ADR-0037: Agent、Workflow 和 Pipeline 通过 Target Adapter 接入

**Status:** accepted

AI Evaluation System 不直接依赖每个 Agent、Workflow 或 Pipeline 的内部实现，而是要求每个评测目标提供统一的 Target Adapter。Eval Worker 只编排 Adapter、持久化执行状态和 Artifact、执行重试策略，并把标准 Observation 交给通用评测链路。

Target Adapter 的最小职责为：

```text
prepare(case_snapshot, target_release)
run(prepared_case, target_release)
observe(raw_result)
```

Adapter 必须能够输出标准化的 Observation，但不在 Adapter 内决定最终质量分数，不读取 Judge Rubric，也不把目标内部实现暴露给管理员。Benchmark Hard Assertions、LLM Judge、人工 A/B 和聚合指标由通用评测系统处理。

这样可以让面经提取 Agent、简历分析 Workflow 和模拟面试 Pipeline 共享同一套 Eval Run、Attempt、Artifact、SSE 进度和结果模型，同时保留各自的运行协议和目标特有字段。
