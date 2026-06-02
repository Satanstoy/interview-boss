# Bug 预览报告

**日期:** 2026-06-02
**问题:** Worker 启动崩溃 — cron_jobs 使用 dict 而非 CronJob 实例
**严重程度:** Critical (P0 — Worker 完全无法启动)

## 初步诊断

### 问题现象
Worker 容器启动后立即崩溃并反复重启，日志报错：
```
RuntimeError: cron_jobs, must be instances of CronJob
```

### 根本原因
`backend/app/worker.py:358-365` 中 `WorkerSettings.cron_jobs` 使用了 plain dict 格式：
```python
cron_jobs = [
    {
        "function": scheduled_compaction_task,
        "hour": 3,
        "minute": 0,
        "next_run": None
    }
]
```
但 arq 0.28 的 `Worker.__init__` 会校验 `isinstance(cron_job, CronJob)`，dict 无法通过检查。

### 影响范围
- **功能:** Worker 完全不可用，所有后台任务（聚类、重建、定时 compaction）无法执行
- **用户:** 所有用户 — 提交面经后聚类任务无法处理
- **数据:** 不影响数据完整性，但会阻塞数据处理流水线

## 风险评估

| 风险类型 | 等级 | 说明 |
|---------|------|------|
| 功能中断 | Critical | Worker 完全不可用 |
| 数据完整性 | Low | 不破坏已有数据 |
| 安全风险 | None | 无安全影响 |
