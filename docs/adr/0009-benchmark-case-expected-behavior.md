# ADR-009: Benchmark Case 以预期行为而非唯一答案为中心

**Status:** accepted

每个 Benchmark Case 以 Expected Behavior 作为通过标准，并组合 Hard Assertions、Quality Rubric 和可选 Reference Answer。固定答案只用于事实核对或辅助 Judge，不作为所有开放式 Agent 和 Workflow 输出的唯一正确形式，以避免版本为了匹配文本而产生机械行为。
