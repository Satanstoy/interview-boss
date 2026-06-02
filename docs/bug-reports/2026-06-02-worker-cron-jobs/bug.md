# Bug 详细分析报告

**Bug ID:** BUG-001
**发现日期:** 2026-06-02
**状态:** 已确认

## 问题概述
Worker 容器启动时，arq 的 `Worker.__init__` 方法在处理 `cron_jobs` 列表时，校验每个元素必须是 `arq.cron.CronJob` 的实例。当前代码传入了 plain dict，导致 `RuntimeError` 异常，Worker 无法启动。

## 根本原因分析

### BUG-001: cron_jobs 使用 dict 而非 CronJob 实例
- **位置:** `backend/app/worker.py:358-365`
- **症状:** Worker 容器反复 Restarting，日志报 `RuntimeError: cron_jobs, must be instances of CronJob`
- **根因:** arq 0.28 的 `Worker.__init__` (arq/worker.py:232) 执行如下检查：
  ```python
  for cron_job in cron_jobs:
      if not isinstance(cron_job, CronJob):
          raise RuntimeError('cron_jobs, must be instances of CronJob')
  ```
  传入 dict 无法通过 `isinstance` 检查。
- **影响:** Worker 完全无法启动，后台任务（聚类、重建、定时 compaction）全部阻塞
- **严重程度:** P0

## 复现步骤
1. `./deploy/docker-deploy.sh update`
2. `docker compose ps` — 观察 worker 状态为 `Restarting`
3. `docker compose logs worker` — 可见 `RuntimeError: cron_jobs, must be instances of CronJob`

## 修复建议
使用 arq 0.28 提供的 `arq.cron.cron()` 辅助函数创建 `CronJob` 实例，替换 plain dict：
```python
from arq.cron import cron

cron_jobs = [
    cron(scheduled_compaction_task, hour=3, minute=0)
]
```
