# ADR-0030: Benchmark Suite 按评测目标拆分

**Status:** accepted

Benchmark Suite 不作为覆盖所有产品能力的单一案例集合，而是按评测目标或同类目标拆分维护。每个 Suite 拥有独立的案例、Expected Behavior、Hard Assertions、Quality Rubric、Replication Policy 和版本生命周期。

1.0 的初始 Suite 规划为：

```text
interview-e2e-suite@1.0
interview-extraction-suite@1.0
resume-analysis-suite@1.0
```

其中当前已有的 12 个模拟面试场景属于 `interview-e2e-suite@1.0`，不自动代表面经提取或简历分析已经具备完整 Benchmark。每个 Eval Run 只能选择与其 `target_type` 兼容的 Suite；跨目标的系统总览只能在各 Suite 结果分别聚合后展示，不能直接混合计算一个质量分数。
