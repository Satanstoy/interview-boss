# ADR-0020: 1.0 使用 Docker Compose 按需部署 Eval Worker

**Status:** accepted

1.0 以 Docker Compose 作为部署基线。用户任务继续使用现有的常驻 `worker` 服务；评测新增独立的 `eval-worker` Compose service，使用 `eval` profile、专用 ARQ queue 配置和独立资源限制。

`eval-worker` 不使用常驻 `restart: unless-stopped` 策略。宿主机 launcher 在检测到待处理 Eval Run 后通过 `docker compose --profile eval run --rm eval-worker` 启动一次短生命周期 Worker；Worker 以 burst 模式消费 Eval Queue，完成队列中的可执行任务后退出。Redis、数据库和 Eval Run 记录不随 Worker 退出而删除。

部署边界：

- `worker` 和 `eval-worker` 使用不同的 WorkerSettings/queue 配置；
- 两类 Worker 可以复用同一个 Redis 服务，但不得消费同一个 ARQ queue；
- `eval-worker` 不加入默认 `docker compose up -d` 启动集合；
- launcher 负责启动锁、健康检查和防止重复容器，不负责执行评测业务逻辑；
- Eval Worker 的容器日志、数据库状态和 `eval_run_events` 共同支持失败诊断与恢复；
- 评测任务需要的代码、Prompt、工具夹具和输出 Artifact 必须通过 Release Manifest 与受控卷/存储提供，不读取用户服务的临时进程状态。
