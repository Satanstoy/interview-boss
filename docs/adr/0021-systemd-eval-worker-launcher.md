# ADR-0021: 使用 systemd timer 按需拉起 Eval Worker

**Status:** accepted

1.0 使用宿主机 systemd timer 作为 Eval Worker Launcher。timer 周期性检查是否存在 `queued`、`running` 租约过期或需要恢复的 Eval Run；launcher 获取单实例锁后，按需执行 Compose 的 `eval-worker` burst 容器。

launcher 的职责仅限于：

- 检查数据库或受保护的内部状态接口中的待处理评测；
- 获取和释放启动锁，防止 timer 重叠启动多个 Eval Worker；
- 检查 Redis、数据库和 Docker Compose 依赖是否可用；
- 启动 `docker compose --profile eval run --rm eval-worker`；
- 记录启动失败、退出码和诊断日志。

launcher 不执行 Case、Judge 或聚合逻辑，FastAPI 也不直接调用 Docker 或 systemd。Eval Run 的实际恢复仍由数据库任务状态、租约和 ARQ 队列负责；timer 只是让没有常驻 Worker 的系统重新获得执行机会。未来如果评测频率上升，可以保留相同的队列和任务协议，替换为常驻独立 Worker Pool。
