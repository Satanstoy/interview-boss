# ADR-0024: Eval Item 的重试使用独立不可变 Attempt

**Status:** accepted

`Eval Run Item` 是统计意义上的一个 Case/Replication 样本，`Eval Item Attempt` 是该样本的一次实际执行。基础设施失败、Worker 崩溃、网络错误或超时只能创建新的 Attempt，不能创建新的 Replication，也不能覆盖原 Attempt。

每个 Attempt 至少记录：

- `item_id`、`attempt_number`、Attempt 原因和生命周期状态；
- 实际执行时间、Worker/容器标识和错误摘要；
- 继承的 Batch fingerprint、planned seed 和运行配置摘要；
- 原始轨迹、工具调用、日志和输出 Artifact 引用；
- 是否被选为 Item 的最终有效 Attempt。

操作性重试默认复用同一个 Replication 的 planned seed 和执行上下文；如果需要改变 seed、Candidate Simulator、Harness 或其他评测参数，必须创建新的 Eval Item 或扩展 Batch，而不能伪装成重试。每个 Attempt 使用独立的 execution identity 和隔离的测试会话，避免重试污染前一次部分执行产生的状态。

Item 的聚合只消费被标记为有效的 Attempt。失败 Attempt 仍可在管理员详情页查看，并用于诊断 Harness、服务依赖和成本问题。
