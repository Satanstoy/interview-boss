# ADR-0014: 当前评测系统登记为 1.0 初始基线

**Status:** superseded by ADR-0043 and ADR-0044

当前正在建设的 AI Evaluation System 以 `1.0` 作为初始冻结基线。这个基线登记当前系统行为、各评测目标的初始 Target Release，以及按目标类型组织的初始 Evaluation Release。Benchmark、Simulator Harness、Candidate Simulator、Judge 和评测协议作为 Evaluation Release 的内部配置整体冻结。

面向管理员的两个顶层版本标识例如：

- `interview-agent@1.0`
- `interview-eval@1.0`

`1.0` 只代表可追溯的版本起点，不代表当前系统质量已经通过所有门禁。后续修改递增发生变化的 Target Release 或 Evaluation Release，并保留与 `1.0` 的比较关系；不得通过覆盖配置或修改历史记录的方式重写 `1.0` 的含义。
