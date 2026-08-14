# ADR-0029: 现有 12 个模拟面试场景组成 Benchmark Suite 1.0

**Status:** accepted

不等待“完美覆盖”才启动评测系统。当前评测框架已有的 12 个场景先冻结为 `benchmark-suite@1.0` 的初始范围，并在基准案例层补齐可执行的预期行为和评分定义。

初始场景键为：

```text
long_session_mid
long_session_senior
long_session_jd
error_correction
early_close_guard
proper_end
insufficient_evidence
counter_question
greeting_role_adherence
tool_timing
natural_closing
counter_question_flow
```

每个场景必须登记为独立 Benchmark Case，至少包含输入快照、Expected Behavior、Hard Assertions、Quality Rubric 和 Replication Policy。现有脚本生成的历史 JSON/Markdown 报告可以作为迁移参考，但不能自动等同于已版本化的 Benchmark Case。

后续新增场景、修改预期行为、修改硬断言或修改评分量规都必须产生新的 Benchmark Suite Release 或显式扩展版本；生产采样和临时探索案例不得静默混入 `benchmark-suite@1.0`。
