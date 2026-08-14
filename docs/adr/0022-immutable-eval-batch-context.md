# ADR-0022: Eval Batch 使用不可变执行上下文

**Status:** accepted

同一 Eval Batch 内的运行必须共享同一个规范化执行上下文。创建 Batch 时锁定所有会影响结果或可比性的参数，并根据规范化内容计算 `batch_fingerprint`。Batch 创建后不得修改这些参数；任何变化都必须创建新的 Batch 或显式的扩展批次。

Batch 级上下文至少包括：

- `target_release` 或 A/B 对比中的目标 Release 集合；
- `benchmark_suite_release` 与 `eval_protocol_release`；
- `judge_release`；
- `simulator_harness_release` 与 `candidate_simulator_release`；
- 运行环境、工具夹具、超时、重试、并发和资源预算；
- 模型采样默认值、seed 生成策略和进度聚合规则。

允许的 Item 级差异只有基准案例输入/期望行为、Replication 序号、按固定策略生成的 seed，以及实际尝试次数。A/B 评测使用共享的 Batch 上下文建立 sibling Eval Run；两个 Run 只在 `target_release` 上不同，不能因为其他参数不同而声称是公平对比。

初始 Replication Item 在 Batch 创建时物化。接近阈值需要增加运行次数时，创建独立的 `replication_extension` Batch，记录触发原因和来源 Batch，不回写原 Batch 的总量或指纹。
