# ADR-0023: 普通 Eval Batch 单目标，A/B 使用 Comparison Group

**Status:** accepted

普通 Eval Batch 只允许绑定一个评测目标和一个 `target_release`。Agent、Workflow 和 Pipeline 不在同一个普通 Batch 中混合执行；每个 Eval Run 的进度、失败、重试和聚合结果都归属于自己的目标。

A/B 评测通过 `comparison_group` 建立关联。Comparison Group 下的 sibling Eval Run 各自独立执行和存储结果，但必须共享同一个 Batch 执行上下文，唯一允许的实验变量是 `target_release`。如果需要比较多个候选版本，应建立多个成对的 Comparison Group，或明确使用多臂比较协议，不把多个目标隐式塞入一个 Batch。

这样可以同时满足目标级独立评测和公平对比：普通回归结果保持清晰，A/B 结果可以按同一 Case、同一 Replication、同一 Judge 和同一 Harness 进行配对分析。
