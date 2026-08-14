# ADR-0034: Candidate Simulator 不得接收评测标准

**Status:** accepted

Candidate Simulator 必须模拟一个只知道候选人可见信息的外部参与者。Harness 通过显式的 `candidate_view` 白名单输入向 Simulator 提供简历、JD、当前问题、历史对话和其他真实候选人可见上下文；Expected Behavior、Hard Assertions、Quality Rubric、Judge Release、评分结果和内部诊断信息始终留在 Harness/Judge 上下文中。

该边界不是 Prompt 约定，而是输入契约：

- Simulator API 只接受 `candidate_view` Schema；
- 禁止字段不得通过 system prompt、tool args、metadata、错误消息或日志回传；
- Harness 在执行前校验输入不包含评测标准字段；
- 违规时标记为 Harness/Simulator contract failure，不把该运行当作有效质量样本；
- Simulator 输出只作为候选人行为输入，不能直接修改 Expected Behavior、Rubric 或 Judge 配置。

这样可以避免 Candidate Simulator 通过“知道标准答案”迎合评测，也避免评测逻辑污染被测 Agent 实际面对的对话环境。
