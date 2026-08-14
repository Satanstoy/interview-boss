# ADR-0014: 当前评测系统登记为 1.0 初始基线

**Status:** accepted

当前正在建设的 AI Evaluation System 以 `1.0` 作为初始冻结基线。这个基线登记当前系统行为以及评测所需的初始组件版本，包括评测目标、Simulator Harness、Candidate Simulator、Judge、Benchmark Suite 和评测协议。

各组件使用独立版本标识，例如：

- `evaluation-system@1.0`
- `evaluation-target/<target>@1.0`
- `simulator-harness@1.0`
- `candidate-simulator@1.0`
- `judge@1.0`
- `benchmark-suite@1.0`
- `eval-protocol@1.0`

`1.0` 只代表可追溯的版本起点，不代表当前系统质量已经通过所有门禁。后续修改只递增发生变化的组件版本，并保留与 `1.0` 或 parent release 的比较关系；不得通过覆盖配置或修改历史记录的方式重写 `1.0` 的含义。
