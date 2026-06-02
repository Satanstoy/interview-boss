# 修复计划

**Bug ID:** BUG-001
**日期:** 2026-06-02
**优先级:** P0

## 修复步骤

### 步骤 1: 添加 cron 导入
**文件:** `backend/app/worker.py`
**行号:** 14
**修改类型:** 新增

**修改前:**
```python
from arq.connections import RedisSettings
```

**修改后:**
```python
from arq.connections import RedisSettings
from arq.cron import cron
```

### 步骤 2: 替换 cron_jobs 配置
**文件:** `backend/app/worker.py`
**行号:** 358-365
**修改类型:** 修正

**修改前:**
```python
    cron_jobs = [
        {
            "function": scheduled_compaction_task,
            "hour": 3,
            "minute": 0,
            "next_run": None  # ARQ 会自动计算
        }
    ]
```

**修改后:**
```python
    cron_jobs = [
        cron(scheduled_compaction_task, hour={3}, minute={0})
    ]
```

说明：使用 `cron()` 辅助函数（arq 0.28 推荐方式），`hour={3}` 表示凌晨 3 点执行。

## 验证方法
1. `docker compose build backend worker`
2. `docker compose up -d backend worker`
3. `docker compose ps` — worker 状态应为 `Up` 而非 `Restarting`
4. `docker compose logs worker` — 应看到 `ARQ Worker 已启动`

## 回滚方案
`git revert HEAD` 回退本次修改，重新部署。
