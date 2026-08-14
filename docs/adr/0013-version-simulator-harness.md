# ADR-0013: Simulator Harness 与 Candidate Simulator 独立版本化

**Status:** accepted

模拟面试的 E2E 结果必须同时绑定 `Simulator Harness Release` 和 `Candidate Simulator Release`。前者描述评测基础设施如何运行和观测模拟器，后者描述候选人行为如何生成；两者不能合并成一个模糊的 simulator 版本。

`Simulator Harness Release` 至少覆盖运行器、对话状态推进、工具与环境夹具、超时与重试策略、随机性配置、轨迹采集和评测输入组装规则。`Candidate Simulator Release` 至少覆盖模拟器模型、System Prompt、候选人画像、回复策略、工具配置和采样参数。

这样可以区分两类变化：

- 被测 Agent 变化导致的质量变化；
- Simulator 或 Harness 变化导致的输入分布、轨迹或观测方式变化。

稳定 E2E Benchmark 必须固定两类 Release；随机 E2E Stability Evaluation 可以在固定两类 Release 下重复运行，并将 `seed`、运行环境和实际配置一并记录。任何一类 Release 变化都应产生新的评测协议版本或新的可比性分组，不得直接与旧结果混合计算趋势。
