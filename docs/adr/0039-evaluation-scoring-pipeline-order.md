# ADR-0039: 评测先做 Harness 校验，再做硬断言和 Judge

**Status:** accepted

有效 Observation 的标准评分顺序为：

```text
Target 执行
  ↓
Harness 合约校验
  ↓
Hard Assertions
  ↓
LLM Judge
  ↓
聚合结果
```

如果 Harness/Simulator 契约无效，例如输入泄漏、轨迹损坏、状态不可恢复或终态缺失，该 Item 标记为执行无效并跳过质量 Judge；如果 Harness 有效但 Agent 行为违反 Hard Assertion，仍然运行 Judge，以便保留深度、完整性、自然度等质量诊断。Hard Assertion 失败始终可以阻断案例通过，LLM Judge 不能覆盖硬门禁。
