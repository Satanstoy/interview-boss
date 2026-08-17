# ADR-0043: 被测对象与完整评测版本采用双版本轴

**Status:** accepted

评测系统对管理员只暴露两个顶层版本：被测对象版本（Target Release）和按评测目标组织的完整评测版本（Evaluation Release）。完整评测版本将 Benchmark、评测协议、Judge、Simulator Harness、Candidate Simulator、Embedding/Retrieval 及相关模型参数作为一个不可变整体保存；这些内容在前端以中文配置分组展示，但不再作为六类互相独立的公开 Release 维护。一次 Eval Run 一对一绑定一个 Target Release 和一个 Evaluation Release；目标版本可以独立更新，评测内容发生任何影响结果的变化则生成新的 Evaluation Release。A/B 对比复用同一个 Evaluation Release，只改变 Target Release。

该决策取代此前将 Judge、Simulator Harness 和 Candidate Simulator 作为管理员独立公开版本的包装方式；其内部配置边界和信息隔离约束保留在 Evaluation Release Manifest 中。这样既保持历史结果的不可变性，又避免管理员维护一组互相漂移的组件版本号。
