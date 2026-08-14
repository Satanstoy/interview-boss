# ADR-0040: AI Evaluation System 1.0 实施决策汇总

**Status:** accepted

在完成架构对齐后，1.0 按以下默认方案进入实施：

1. **数据模型**：新增独立的 `eval_runs`、`eval_batches`、`eval_items`、`eval_attempts`、`eval_events` 和 `eval_artifacts` 领域对象；通用 `jobs` 只作为 ARQ 投递和 Worker 生命周期的连接，不承载完整评测状态。
2. **Release 生命周期**：`draft → published → archived`。只有 `published` Release 可以进入正式 Fixed Benchmark；历史 Release 不覆盖、不删除。
3. **Replication 协议**：每个 Case 默认执行 5 次；接近门槛或波动过大时创建独立扩展 Batch，增加到 10 次；原 Batch 的 Item 总量和 fingerprint 不变。
4. **Admin API/SSE**：通过创建、查询、取消 API 管理 Eval Run，通过带 `Last-Event-ID` 的 SSE 订阅可恢复进度；SSE 断开不取消后台任务。
5. **评分与聚合**：Harness 合约校验 → Hard Assertions → LLM Judge → 聚合；Hard Gate 不能被 LLM 分数覆盖，输出均值、中位数、P95、关键失败率和维度分数。人工 A/B 作为独立证据，不自动覆盖硬门禁。
6. **前端控制台**：1.0 提供评测总览、目标与版本、Benchmark 管理、Eval Run 详情/进度、结果对比与人工 A/B 五个主页面；发起评测使用弹窗或抽屉。

这组决策作为 1.0 的实施边界。后续优化可以增加能力，但不得在未创建新 Protocol/Release 的情况下改变历史 Run 的含义。
