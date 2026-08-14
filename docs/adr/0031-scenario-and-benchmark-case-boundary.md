# ADR-0031: Scenario 作为场景族，Benchmark Case 作为具体样本

**Status:** accepted

`Scenario` 描述测试意图、行为模式或失败模式，`Benchmark Case` 描述一组可重复执行的具体输入、预期行为和评测要求。一个 Scenario 可以拥有多个 Benchmark Case；不同 Case 可以覆盖不同 JD、简历、候选人画像、工具状态或对话分支。

`interview-e2e-suite@1.0` 先为当前 12 个 Scenario 各建立至少一个初始 Benchmark Case，后续扩展 Case 时保持 Scenario 归属不变。Case 的新增、修改和废弃都必须有自己的版本或变更记录，不能因为 Scenario 名称不变而覆盖历史样本。

这样既保留现有评测框架的场景组织方式，也避免把一个场景键误当成完整的统计样本或覆盖声明。
