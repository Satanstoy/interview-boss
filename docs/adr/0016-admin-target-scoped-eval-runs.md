# ADR-0016: 管理员通过目标级 Eval Run 发起完整评测

**Status:** accepted

AI Evaluation System 的前端定位为管理员评测控制台。管理员从 Agent、Workflow 或 Pipeline 中选择一个具体的不可变 `target_release`，发起独立的 `Eval Run`；评测结果不依赖可变的“当前版本”指针。

创建 Eval Run 时必须解析并锁定完整依赖集合：

```text
target_release
benchmark_suite_release
eval_protocol_release
judge_release
simulator_harness_release
candidate_simulator_release
```

运行开始后，即使目标的当前版本发生变化，已有 Eval Run 仍然使用创建时锁定的 Release，并保存原始轨迹、单 Case 结果、聚合指标和错误信息。Agent、Workflow 和 Pipeline 分别拥有自己的 Eval Run 生命周期；未来可以提供批量评测入口，但批量评测只是多个目标级 Eval Run 的编排，不合并其证据和结果。

控制台至少需要支持：目标和 Release 选择、Benchmark/Judge/Harness/Simulator 配置、运行创建与进度监控、单 Case 详情、回归与稳定性结果，以及人工 Pairwise A/B 评测入口。
