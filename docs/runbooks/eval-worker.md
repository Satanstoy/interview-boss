# Eval Worker 运维 Runbook

## 安装与查看

在项目根目录执行：

```bash
./deploy/docker-deploy.sh eval-worker-install
./deploy/docker-deploy.sh eval-worker-status
```

`eval-worker-install` 安装并启用 `interview-boss-eval-worker.timer`。Timer 每分钟检查一次待执行评测；没有 `created`、`queued` 或 `running` Run 时不会启动容器。

`eval-worker-status` 同时显示 systemd timer、一次性容器、SQLite Run 状态和 `eval-worker` heartbeat。状态含义：

- `queue_empty`：没有待执行 Run。
- `worker_online`：有待执行 Run 且最近 heartbeat 正常。
- `worker_offline`：有待执行 Run，但没有在线 heartbeat。
- `queued_stuck`：有超过 10 分钟仍为 `created/queued` 的 Run，需要检查 Redis、Docker 和 timer 日志。

## 手工验证

```bash
systemctl status interview-boss-eval-worker.timer
journalctl -u interview-boss-eval-worker.service -n 100 --no-pager
./deploy/eval-worker-launcher.sh
```

启动器在真正拉起 Eval Worker 前会检查 Docker、Redis 服务、Redis `PING` 和 SQLite `PRAGMA quick_check`。任一前置检查失败都会以非零状态退出，避免把“未执行”误报成“队列为空”。

## 故障处理

1. `worker_offline`：确认 Docker daemon、Redis 容器和 timer active，再查看 service journal。
2. `queued_stuck`：先确认数据库 `quick_check` 为 `ok`，再重启 Redis 或手动执行 launcher；不要直接修改 `eval_runs` 状态。
3. worker 进程异常退出时，ARQ 最多重试 3 次；Run 的事件、Item、Attempt 和 heartbeat 保留在 SQLite 中。
4. 涉及数据库修复前先执行 `./deploy/docker-deploy.sh backup`，恢复使用 `restore`，保留恢复前保险备份。
