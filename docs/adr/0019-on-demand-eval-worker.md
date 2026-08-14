# ADR-0019: 小服务器采用按需启动的 Eval Worker

**Status:** accepted

1.0 阶段评测频率不高且服务器资源有限，因此不长期常驻 Eval Worker。Eval Queue 和 Redis 持久存在，待处理 Eval Run 进入队列后，由独立 launcher 启动短生命周期 Worker；Worker 以低并发执行，队列清空且没有需要恢复的租约后自动退出。

运行策略：

- 同一时间最多启动一个 Eval Worker；
- Worker 不与用户服务 Worker 共享进程、并发池或队列；
- 一个 Worker 执行一组父子 Eval 任务，不为每个 Case 单独创建操作系统进程；
- `eval_runs`、子任务状态和 `eval_run_events` 在 Worker 退出后继续保留；
- Worker 崩溃后由数据库租约和 launcher 重新发现未完成任务；
- 前端将等待 Worker 启动显示为 `queued`/`waiting_for_capacity`，不误报为失败；
- Worker 启动和退出不依赖 SSE 连接，SSE 断开不影响评测执行。

launcher 可以由部署环境提供的 systemd timer、容器调度器或其他轻量外部调度机制触发。它只负责发现待处理任务、获取启动锁和拉起 Eval Worker，不承载评测业务逻辑。未来评测频率增加时，可以在不改变 Eval Run 和队列协议的情况下切换为常驻独立 Worker Pool。
