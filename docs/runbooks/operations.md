# InterviewBoss 故障运行手册

适用范围：Docker Compose 生产部署。执行任何可能改写或删除数据的动作前，
先确认责任人、工单和备份；优先使用 `sudo ./deploy/docker-deploy.sh` 提供的
受保护入口，不直接对生产 SQLite 执行删除命令。所有时间均记录为 UTC。

## 通用诊断顺序

1. 记录发生时间、部署版本、操作者、用户影响和最近一次变更。
2. 执行 `sudo docker compose ps`、`sudo docker compose logs --tail=200 backend worker nginx oauth-gateway`。
3. 执行 `df -h`、`docker system df`、`sudo docker stats --no-stream`，保存输出但不要提交其中的 secret。
4. 检查 `curl -fsS http://127.0.0.1:8081/api/health` 与 `sudo docker compose exec -T backend sh -lc 'df -h /app/backend/data'`。
5. 若影响范围不明确，先停止发布与自动重试，升级给 deployment owner。

每个故障条目都要补充：症状、止损、验证、恢复、数据影响、回滚条件、事后记录。

## 数据库不可用或锁

症状：API 返回 5xx，日志包含 `database is locked`、迁移失败或 healthcheck 失败。

止损：暂停 worker，保留 API 容器现场；不要删除 `*.db-wal` / `*.db-shm`，不要重复运行破坏性迁移。

验证：查看 `sudo docker compose logs --tail=200 backend worker`；在只读副本上执行
`sqlite3 <copy> 'PRAGMA integrity_check; PRAGMA foreign_key_check;'`。

恢复：确认没有写入者后执行 `sudo ./deploy/docker-deploy.sh restart`；若仍失败，使用
`sudo ./deploy/docker-deploy.sh restore <verified-backup>`，再执行 `status` 和 healthcheck。

数据影响：锁等待通常不丢数据；从备份恢复会丢失备份时间点后的写入，必须明确记录。

回滚条件：`integrity_check` 非 `ok`、FK 非 0、或恢复后 schema version 不匹配时停止服务并升级。

事后记录：锁持有进程、等待时长、迁移版本、备份校验结果和丢失窗口。

## Redis 不可用

症状：backend health 失败、worker offline、任务停在 pending，日志包含连接/认证/timeout。

止损：不要清空 Redis queue；暂停会创建大量任务的入口，保留 Redis 容器日志和 AOF。

验证：执行 `sudo docker compose ps redis redis-cache`；用
`sudo docker compose exec -T redis sh -lc 'REDISCLI_AUTH="$(cat /run/secrets/redis_password)" redis-cli ping'`，期望 `PONG`。

恢复：先检查 secret 文件权限和磁盘，再执行 `sudo docker compose restart redis redis-cache`；
恢复后重启 worker 并观察一轮任务从 pending 到 completed。

数据影响：queue Redis 的持久化恢复决定任务是否可重放；cache Redis 丢失只影响读缓存。

回滚条件：认证失败或 AOF 重放失败时不要重建卷，升级给数据 owner 进行备份恢复。

事后记录：不可用区间、丢失/重放任务数、AOF/备份版本和是否触发重复执行。

## Worker offline / 队列积压

症状：任务进度长期不变，`worker` health 为 unhealthy，或 pending 数持续增长。

止损：暂停新的批量导入；不要手工修改 jobs 状态或删除队列消息。

验证：执行 `sudo docker compose ps worker`、`sudo docker compose logs --tail=300 worker`，
并在数据库只读查询中检查 `jobs.status, available_at, locked_until, last_error`。

恢复：修复依赖/凭据后执行 `sudo ./deploy/docker-deploy.sh worker-restart`；观察 lease
超时、重试次数和完成率。失败任务依照 `last_error` 单独处理。

数据影响：重启可能触发 lease 到期后的安全重试；记录是否存在非幂等外部副作用。

回滚条件：重试次数异常增长、同一 idempotency key 多次产生副作用或数据库锁升高时停止 worker。

事后记录：积压峰值、处理速率、失败根因、重试/放弃数量和用户可见影响。

## LLM 5xx、超时与 rate limit

症状：答案生成失败、任务进入 retry，日志出现 HTTP 5xx、timeout、429/rate limit。

止损：降低批量并发，暂停自动重试风暴；不要把 API key 写入日志、工单或截图。

验证：检查 backend/worker 日志中的 provider、HTTP 状态、耗时和脱敏 request id；
确认 `OPENAI_BASE_URL`/用户 endpoint 的 DNS 与 `docs/compliance/deployment-matrix.template.md` 一致。

恢复：按 provider SLA 退避；必要时在设置中切换到已审核的 endpoint，先用一条合成输入验证，
再恢复 worker。不要绕过出站 URL 校验或打开自动跟随 redirect。

数据影响：provider 未收到请求时通常无外部数据影响；已收到的 JD/简历字段按实例合规矩阵和 provider retention 处理。

回滚条件：连续 5xx、认证失败、endpoint 归属不明或数据地区不明时禁止切换到未经审核的 provider。

事后记录：provider 状态、失败/重试数、退避时间、endpoint 变更和合规审查结果。

## 磁盘耗尽与容器 OOM

症状：Docker build 或 SQLite 写入失败，healthcheck 反复重启，kernel/Compose 日志出现 OOM。

止损：停止发布和批量任务；先保存 `df -h`、`docker system df`、`docker stats --no-stream`，
不要执行无范围的 `docker system prune -a`。

验证：执行 `sudo ./deploy/docker-deploy.sh storage-check`，检查 `backend/data`、日志轮转、
备份目录和 BuildKit cache 的归属。

恢复：按部署脚本的项目级 cache 清理策略释放空间；确认备份可读后再恢复服务，降低 worker 并发。

数据影响：删除 cache/日志通常不影响业务；删除未验证备份或数据库文件可能造成不可逆丢失。

回滚条件：可用空间低于部署硬阈值、备份校验失败或容器持续 OOM 时不继续升级。

事后记录：峰值占用、清理对象、备份校验、OOM 容器和资源阈值调整建议。

## 备份、恢复与回滚

1. 备份前置：执行 `sudo ./deploy/docker-deploy.sh backup`，记录生成文件、大小、时间和校验摘要。
2. 验证：对副本执行 `sqlite3 <copy> 'PRAGMA integrity_check; PRAGMA foreign_key_check;'`，并确认 schema version 与当前迁移 registry 一致。
3. 确认：恢复或 `POST /api/clear-db` 必须由管理员确认，clear-db 会生成确认事件和清空前备份；不得把 confirm token 写入工单。
4. 恢复：停止写入者，使用 `sudo ./deploy/docker-deploy.sh restore <verified-backup>`，再启动 backend、nginx、OAuth 和 worker。
5. 回滚条件：恢复后健康检查、FK 检查、关键读取和一条合成 worker 任务任一失败，就保持隔离并升级。
6. 事后记录：恢复点、RPO/RTO、丢失窗口、验证命令输出摘要、操作者与后续修复项。

破坏性动作（清空、恢复、删除卷）必须有明确确认、可读备份和回滚负责人；
操作失败也要保留 admin audit event，不以“接口返回成功”代替数据库验证。
