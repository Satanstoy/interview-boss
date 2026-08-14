# ADR-0027: Eval Artifact 按来源和用途分层保留

**Status:** accepted

评测 Artifact 不采用统一的永久保留或统一的短期清理策略。每个 Artifact 在创建时记录来源、用途、保留级别、到期时间和是否被 Benchmark/人工证据引用；Retention Worker 只能清理到期且未被长期证据链引用的 Artifact。

1.0 的默认策略：

- 官方 Fixed Benchmark 的输入、结果和回归报告：长期保留；
- accepted Attempt、Judge 证据、聚合结果和人工 Pairwise A/B 记录：长期保留；
- Worker 崩溃、网络失败等无效 Attempt 的原始日志：默认保留 90 天；
- 未晋升为 Benchmark 的 Production Sample：默认保留 30 天；
- 被提升为 Benchmark Case 的 Production Sample：继承官方 Benchmark 的长期保留级别。

清理操作必须是可审计的，并先检查 Artifact 引用关系。不能因为删除临时日志而删除 Eval Run 的状态、Batch fingerprint、有效 Attempt、最终 Judge 结果或人工 A/B 结论；若核心 Artifact 缺失，详情页必须显示证据不完整，而不能伪造完整结果。
