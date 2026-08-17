# ADR-0030: Benchmark Suite 按评测目标拆分

**Status:** accepted; version packaging superseded by ADR-0043 and ADR-0044

Benchmark 内容不作为覆盖所有产品能力的单一案例集合，而是按评测目标或同类目标放入对应的 Evaluation Release。每个目标类型拥有独立的案例、Expected Behavior、Hard Assertions、Quality Rubric、Replication Policy 和配置作用域，但这些内容不再单独产生公开 Suite 版本；它们随 Evaluation Release 整体冻结。

1.0 的初始 Suite 规划为：

```text
interview-eval@1.0
experience-extraction-eval@1.0
resume-analysis-eval@1.0
```

其中当前已有的 12 个模拟面试场景属于 `interview-eval@1.0` 的 Benchmark 配置，不自动代表面经提取或简历分析已经具备完整 Benchmark。每个 Eval Run 只能选择与其 `target_type` 兼容的 Evaluation Release；跨目标的系统总览只能在各目标结果分别聚合后展示，不能直接混合计算一个质量分数。
