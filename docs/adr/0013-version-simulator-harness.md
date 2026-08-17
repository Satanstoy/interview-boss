# ADR-0013: Simulator Harness 与 Candidate Simulator 独立版本化

**Status:** superseded by ADR-0043 and ADR-0044

模拟面试的 E2E 结果必须同时固定 Simulator Harness 配置和 Candidate Simulator 配置。两者继续保持清晰的内部配置边界，但共同属于同一个按目标类型组织的 Evaluation Release，不再作为管理员分别维护的公开版本。

Simulator Harness 配置至少覆盖运行器、对话状态推进、工具与环境夹具、超时与重试策略、随机性配置、轨迹采集和评测输入组装规则。Candidate Simulator 配置至少覆盖模拟器模型、System Prompt、候选人画像、回复策略、工具配置和采样参数。

这样可以区分两类变化：

- 被测 Agent 变化导致的质量变化；
- Simulator 或 Harness 变化导致的输入分布、轨迹或观测方式变化。

稳定 E2E Benchmark 必须固定同一个 Evaluation Release 中的两类配置；随机 E2E Stability Evaluation 可以在固定 Evaluation Release 下重复运行，并将 `seed`、运行环境和实际配置一并记录。任一内部配置变化都应产生新的 Evaluation Release，不得直接与旧结果混合计算趋势。
