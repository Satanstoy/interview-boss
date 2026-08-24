# 备份与恢复 Runbook（backup / restore）

> audit 2026-08-24 P3 落地项：恢复路径此前从未被验证。本文档记录 RPO/RTO、
> 恢复流程与演练方法。最近一次成功演练：**2026-08-24**
> （`interview-boss_20260824_161230.db`，integrity ok，FK 0 违规，
> users=53 / question_bank=284 / interview=37）。

## 备份机制

| 时机 | 触发 | 产物位置 |
|---|---|---|
| 破坏性迁移前 | `run_migrations()` 自动 | `backend/data/backups/pre_migration_v*.db` |
| 手动/按需 | `./deploy/docker-deploy.sh backup` | `backups/interview-boss_<ts>.db` + `redis_<ts>.rdb` |
| 存储维护（每日 03:30 systemd timer） | storage-maintenance | 仅做备份目录修剪（prune），不新建备份 |

技术要点：SQLite 处于 WAL 模式，裸 cp 会漏掉 `-wal` 中未 checkpoint 的已提交事务，
必须走 sqlite 在线备份 API（`do_backup` 内的 `backup_sqlite_wal`）。

## RPO / RTO

- **RPO（可容忍数据丢失窗口）= 自上次备份起**。
  当前没有每日自动全量备份 cron——迁移前自动备份 + 手动 backup 是仅有的快照来源。
  **建议：每周至少手动执行一次 `./deploy/docker-deploy.sh backup`**（或后续把该命令挂 systemd timer）。
- **RTO（恢复耗时）≈ 2 分钟**：`do_restore` 停 backend → 覆盖库文件 → 清 `-wal/-shm`
  → 启动并等待健康检查（60s 超时）。

## 恢复流程（生产切换）

```bash
./deploy/docker-deploy.sh restore                # 用最新备份
./deploy/docker-deploy.sh restore backups/interview-boss_20260824_161230.db   # 指定文件
```

内置保护：
1. 校验文件头确为 SQLite；
2. **恢复前自动再备份当前库**到 `backups/interview-boss_pre-restore_<ts>.db`；
3. 停止 backend 容器后再覆盖，避免运行中写入撕裂；
4. 启动后健康检查失败时给出回滚提示（用 pre-restore 备份原路返回）。

## 恢复演练（不触碰生产库）

```bash
./deploy/docker-deploy.sh backup          # 先有新备份
./deploy/docker-deploy.sh restore --verify # 演练：临时副本上校验后清理
```

--verify 在 `/tmp` 生成临时副本执行三步校验：`integrity_check`、
`foreign_key_check`、关键表行数抽样（users/question_bank/interview），
全程不停止任何容器、不写生产库。

## 已知边界

- Redis 队列仅 BGSAVE 快照（cache 实例无持久化不备份）；队列丢失可由 jobs 表
  durable outbox 接管，详见 `app/services/job_lifecycle.py`。
- `oauth-gateway-data` 卷未纳入备份；其内容为 OAuth 会话态，丢失即用户重新登录，可接受。
