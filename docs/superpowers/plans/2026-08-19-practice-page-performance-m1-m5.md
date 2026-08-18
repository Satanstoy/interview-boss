# 实施计划 — 刷题页面性能优化 M1 + M5

> 日期:2026-08-19 · 上游:docs/superpowers/specs/2026-08-19-practice-page-performance-design.md + ADR 0046
> 方法:每个 Task 都是 2–5 分钟原子操作,严格 TDD 红-绿-重构,逐 Task 提交。

## Task 0 · 测试容器就绪(只做一次)

**Files:**
- (无源码改动)

- [ ] Step 1: 确认 test-runtime 可用:`docker compose --profile test run --rm test uv run pytest backend/tests/infra/test_arq_integration.py -q` 通过
- [ ] Step 2: 确认 mock_redis fixture 可用(conftest.py 已提供)

---

## M1 · 观测性记账挪出 SQLite + cron 降频

### Task 1: core/cache.py 增加 worker 记账 Redis helper

**Files:**
- Edit: `backend/app/core/cache.py`
- Test: `backend/tests/infra/test_worker_observability_redis.py`(新建)

- [ ] Step 1(红): 写测试——`worker_status_set(name,status)` 写 Redis key `interview-boss:worker:status:<name>`(SETEX,ttl 300s);`worker_status_get(name)` 读回;Redis 不可用/未配置时返回 None 不抛错(mock_redis 分别覆盖命中/未命中/异常)
- [ ] Step 2: 跑测试确认失败
- [ ] Step 3(绿): 在 cache.py 实现,复用 `get_cache_client()`,fail-open
- [ ] Step 4: 跑测试通过
- [ ] Step 5: 提交 `feat(backend): worker 状态记帐走 Redis(cache helper)`

### Task 2: record_worker_heartbeat 主写 Redis、SQLite 兜底

**Files:**
- Edit: `backend/app/worker.py`(`record_worker_heartbeat` at :68;eval_worker.py 复用)
- Test: `backend/tests/infra/test_worker_observability_redis.py`(追加)

- [ ] Step 1(红): 测试——心跳正常时写 Redis 且不写 `worker_heartbeats` 表;Redis 不可用时回退写 SQLite(fail-open);`get_cron_status`/健康语义不变
- [ ] Step 2: 跑测试确认失败
- [ ] Step 3(绿): 改 `record_worker_heartbeat`:优先 Redis(`worker_status_set`),Redis 异常回退 SQLite
- [ ] Step 4: 跑全部 infra 测试通过
- [ ] Step 5: 提交

### Task 3: observed_cron_task 运行时标记走 Redis,仅失败/状态变化写 SQLite

**Files:**
- Edit: `backend/app/worker.py`(`observed_cron_task` at :167-182;`record_cron_execution` at :107)
- Test: 同 `test_worker_observability_redis.py`

- [ ] Step 1(红): 测试——同一 cron 连续成功运行时,`worker_cron_runs.run_count` 不增长(SQLite 少写);失败路径仍写 SQLite 且 `last_error` 记录;Redis 不可用回退 SQLite
- [ ] Step 2: 确认失败
- [ ] Step 3(绿): 改 observed_cron_task:开始时 Redis 写 running;结束时若(成功且状态结果未变化)只刷 Redis,否则(失败/结果变化)写 SQLite
- [ ] Step 4: 通过
- [ ] Step 5: 提交

### Task 4: cron 降频

**Files:**
- Edit: `backend/app/worker.py`(`WorkerSettings.cron_jobs` at :1615-1624)
- Test: `backend/tests/infra/test_arq_integration.py`(cron 注册断言)

- [ ] Step 1(红): 测试断言新频率——heartbeat 每 5 分钟;submit dispatch 每 5 分钟;cluster review dispatch 每 30 分钟;chat side effects 每 30 分钟
- [ ] Step 2: 确认失败
- [ ] Step 3(绿): minute 集合改为每 5 分钟与每 30 分钟组合
- [ ] Step 4: 通过;随后跑 `./deploy/docker-deploy.sh test -q` 全量不回归
- [ ] Step 5: 提交

---

## M5 · 写端健康(WAL checkpoint + 备份修正 + 限流)

### Task 5: scheduled_wal_checkpoint_task(每日 4:10,PASSIVE→TRUNCATE)

**Files:**
- Edit: `backend/app/worker_scheduled.py`(新增任务)
- Edit: `backend/app/worker.py`(cron_jobs 注册 + functions 列表)
- Test: `backend/tests/infra/test_wal_checkpoint.py`(新建,用临时 sqlite 文件)

- [ ] Step 1(红): 测试——真实 sqlite 临时文件:写入大量帧后,`scheduled_wal_checkpoint_task` 执行后 `-wal` 归零(PASSIVE→TRUNCATE);busy 非 0 时只 PASSIVE 不 TRUNCATE(用只读快照模拟读者);幂等:空 WAL 执行不报错;返回 `{busy, log_frames, checkpointed}`
- [ ] Step 2: 确认失败
- [ ] Step 3(绿): 实现 `scheduled_wal_checkpoint_task`(循环 PASSIVE 至 busy=0 或 ≤N 轮,再 TRUNCATE,记日志),注册 4:10 cron + functions
- [ ] Step 4: 通过
- [ ] Step 5: 提交

### Task 6: build_master_bank_task 备份 copy2 → sqlite backup

**Files:**
- Edit: `backend/app/worker.py`(`build_master_bank_task` 的 Step 1 备份段)
- Test: `backend/tests/infra/test_bank_backup_wal.py`(新建)

- [ ] Step 1(红): 测试——构造有未 checkpoint 帧的临时库,用新备份逻辑生成的快照可打开且包含最近写入(旧 copy2 会漏 WAL 帧→断言旧方式缺行)
- [ ] Step 2: 确认失败
- [ ] Step 3(绿): 用 `sqlite3.Connection.backup()`(对照 migrations/__init__.py:32)替换 `shutil.copy2`
- [ ] Step 4: 通过;`backend/tests/bank/ -q` 不回归
- [ ] Step 5: 提交

### Task 7: 重活接入 AdaptiveSemaphore 限流

**Files:**
- Edit: `backend/app/worker.py`(`build_master_bank_task`、批量答案生成路径)
- Test: `backend/tests/infra/test_backpressure_wiring.py`(新建)

- [ ] Step 1(红): 测试——并发调用重活入口时,同一时刻进入临界区的数量 ≤ semaphore 上限(mock);任务完成后恢复
- [ ] Step 2: 确认失败
- [ ] Step 3(绿): 重活任务用 `async with AdaptiveSemaphore(...)` 包裹核心写段(先查 `services/backpressure.py` 构造函数参数再接入)
- [ ] Step 4: 通过
- [ ] Step 5: 提交

---

## 收尾

- [ ] 跑 `./deploy/docker-deploy.sh check backend` + `./deploy/docker-deploy.sh test -q`
- [ ] 更新对应目录 CLAUDE.md(worker/worker_scheduled 职责表补新条目)
- [ ] 部署 `./deploy/docker-deploy.sh update`;观察 48h:`database is locked` 计数、`-wal` 文件大小
