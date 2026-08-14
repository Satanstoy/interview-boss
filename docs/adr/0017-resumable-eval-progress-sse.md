# ADR-0017: Eval Run 使用可恢复的持久化 SSE 进度流

**Status:** accepted

评测控制台需要让管理员实时知道 Eval Run 当前处于哪个阶段、完成了多少 Case/Replication，以及是否发生错误。实现采用“持久化事件日志 + SSE 传输”：`eval_run_events` 是事实来源，SSE 只是实时投递和重放通道。

评测进度事件与用户面试的 `interview_events` 分开存储，至少包含：

- `run_id`、单调递增的 `sequence` 和事件时间；
- `event_type`、`stage`、运行状态；
- 当前 Case、当前 Replication、已完成数量和总数量；
- `overall_progress`、阶段进度和可展示的摘要消息；
- 错误摘要、Schema 版本和可选的关联对象 ID。

典型阶段为：`validating`、`preparing`、`executing`、`scoring`、`aggregating` 和 `completed`。前端不能只显示一个百分比，应同时显示阶段、Case/Replication 计数和当前项；总量未知时显示阶段进度或不确定状态，不伪造精确百分比。

进度 SSE 必须支持：

- 通过 `Last-Event-ID` 从指定序号继续重放；
- 心跳事件，避免长时间无输出被代理关闭；
- 终态事件后正常结束；
- SSE 断开后自动重连，且不取消后台 Eval Run；
- 取消通过独立的管理员 API 执行，并由后台任务写入 `cancelled` 终态。

进度流只传输管理员需要的状态和摘要；完整的对话轨迹、工具调用和裁判证据通过受保护的 Eval Run 详情接口按需加载。项目现有的前端 `fetch + ReadableStream` SSE 客户端和后台 durable job 模式作为实现基础，不直接使用浏览器 `EventSource` 替代现有认证与重试机制。
