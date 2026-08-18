# WAL checkpoint 纪律(每日低峰显式 checkpoint + 统一 sqlite 备份 API)

## Status: accepted (2026-08-19)

## 背景

SQLite 以 WAL 模式运行(`backend/app/db/connection.py`:`PRAGMA journal_mode=WAL`),自动 checkpoint 使用默认 `wal_autocheckpoint=1000` 页(≈4MB)且为 PASSIVE 语义:只要任一读者持有旧快照就会提前停止。web 与 worker 两进程的长期连接(ContextVar 线程本地)构成常驻读者,导致 `interview-boss.db-wal` 长期超阈值堆积到 ~11MB;当写者真正触发 checkpoint 时需一次回写 2700+ 页,是读端 500ms 抖动档的来源之一。`busy_timeout=10000` 把这种撞车表现为"慢"而非报错,掩盖了问题。

## 决定

1. **每日低峰显式 checkpoint**:worker 新增定时任务 `scheduled_wal_checkpoint_task`,每天 4:10(紧贴 retention 4:00 之后)执行 `PRAGMA wal_checkpoint(PASSIVE)` 循环至 busy=0(固定轮数上限兜底)再 `TRUNCATE`。失败仅记日志、幂等、次日重跑,不重试。任务每次上报 busy、回写页数、耗时作为观测。
2. **备份统一使用 `sqlite3.Connection.backup()`**:`build_master_bank_task` 的 `shutil.copy2(DB_PATH,...)` 备份在 WAL 下会漏掉 `-wal` 未合并帧,是不一致快照,替换为 backup API(`migrations/__init__.py` 的 `_backup_before_destructive` 已是正确做法,作为对照实现)。
3. **`busy_timeout=10000` 保持不动**:fail-open——让请求等待而非报错;撞车来源由写噪声治理(worker 记账挪 Redis)+ 批量写限流(`services/backpressure.py` 的 `AdaptiveSemaphore`,重活任务接入)消除。
4. **不做**:重排批量写任务的调度时段、把 `wal_autocheckpoint`/`page_size` 抽成常量(YAGNI)。

## 备选

- 调小 `wal_autocheckpoint`(如 500 页)让自动 checkpoint 更勤 —— 会更频繁地撞读者,拒绝。
- 不修 `copy2` 备份 —— 保留不一致快照风险,拒绝。
- 把 checkpoint 并入 retention 任务 —— 耦合两个职责,拒绝。

## 后果

凌晨多了个秒级维护任务;WAL 文件大小与 48h `database is locked` 计数作为 M5 验收指标。未来不要把该任务当作"多余"删除——它是 WAL 堆积的对症手段。
