# ADR-0033: Benchmark Case 使用不可变输入 Snapshot

**Status:** accepted

Benchmark Case 的所有输入上下文必须在 Case 创建或发布时快照化。简历、JD、候选人画像、对话初始状态、工具夹具、知识上下文和其他外部输入以带 `content_digest` 的 Snapshot 引用保存；执行时不得通过“当前用户数据”“当前数据库记录”或未锁定的外部 URL 动态获取替代内容。

Case Input Snapshot 至少记录来源类型、规范化内容、Schema 版本、创建时间和内容摘要。历史来源可以保留 source metadata 用于追溯，但重放和比较只依赖 Snapshot 内容。

如果输入需要更新，创建新的 Case Release 或新的 Snapshot 绑定，不修改旧 Case。这样相同 Case 在不同 Target Release、Judge Release、Candidate Simulator Release 和 Harness Release 下可以公平重放，输入变化也不会被误判为 Agent 质量变化。
