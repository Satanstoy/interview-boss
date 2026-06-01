# TDD 开发计划

**功能名称:** Redis + ARQ 消息队列引入
**日期:** 2026-05-16
**TDD 状态:** 🔴 红灯阶段准备

## 需求描述

将当前基于 SQLite 的同步任务队列替换为 Redis + ARQ 异步任务队列，提升系统响应速度，同时在 2c4g 服务器上合理控制资源消耗。

## 2c4g 资源约束

| 资源 | 限制 | 策略 |
|------|------|------|
| 内存 | 4GB 总计 | Redis maxmemory=128MB，ARQ max_concurrent_jobs=1 |
| CPU | 2 核 | Worker 单并发，避免与 FastAPI 抢占 CPU |
| 进程 | 最少 | FastAPI + ARQ Worker 各 1 个进程 |

## 验收标准

- [ ] Redis 连接配置正确，支持环境变量覆盖
- [ ] ARQ Worker 能独立运行，处理聚类任务
- [ ] FastAPI 能将任务异步推送到 ARQ 队列
- [ ] 2c4g 资源限制配置合理（Redis 128MB、Worker 单并发）
- [ ] 现有 pipeline.py 的队列操作保持兼容（SQLite 队列表保留）
- [ ] Worker 崩溃后能自动重启（systemd）
- [ ] 部署脚本能同时启动 FastAPI 和 Worker

## 测试清单（按优先级排序）

| ID | 测试场景 | 输入 | 预期输出 | 状态 |
|----|---------|------|----------|------|
| T-001 | Redis 连接配置 | REDIS_URL 环境变量 | RedisSettings 对象正确创建 | ⏳ 待写 |
| T-002 | Redis 连接池创建 | RedisSettings | 连接池对象成功创建 | ⏳ 待写 |
| T-003 | ARQ Worker 配置 | WorkerSettings 类 | functions/on_startup/on_shutdown 正确注册 | ⏳ 待写 |
| T-004 | 任务入队 | interview_id, user_id | 任务成功入队，返回 job_id | ⏳ 待写 |
| T-005 | 任务执行（聚类） | 队列中有 pending 任务 | Worker 取出并执行聚类，状态变为 done | ⏳ 待写 |
| T-006 | 任务执行（空队列） | 队列为空 | 返回 empty 状态，无异常 | ⏳ 待写 |
| T-007 | 任务失败重试 | 聚类过程中抛异常 | 任务标记为 pending，最多重试 3 次 | ⏳ 待写 |
| T-008 | 任务超时 | 聚类耗时超过 job_timeout | 任务自动终止并重试 | ⏳ 待写 |
| T-009 | 全量重建任务 | force_cluster_all_task | 所有 pending 队列被处理 | ⏳ 待写 |
| T-010 | 资源限制验证 | WorkerSettings 配置 | job_timeout=600, max_tries=3 | ⏳ 待写 |
| T-011 | FastAPI 集成 | 面经提交后 | 任务通过 ARQ 异步调度，不阻塞响应 | ⏳ 待写 |
| T-012 | 部署脚本集成 | deploy.sh | 同时重启 FastAPI 和 Worker | ⏳ 待写 |

## 测试用例详细设计

### T-001: Redis 连接配置
```python
def test_redis_settings_from_env():
    """验证 REDIS_URL 环境变量正确解析为 RedisSettings"""
    import os
    os.environ["REDIS_URL"] = "redis://localhost:6379/0"
    from arq.connections import RedisSettings
    settings = RedisSettings.from_dsn("redis://localhost:6379/0")
    assert settings.host == "localhost"
    assert settings.port == 6379
    assert settings.database == 0
```

### T-002: Redis 连接池创建
```python
async def test_redis_pool_creation():
    """验证 Redis 连接池能成功创建"""
    from arq.connections import create_pool, RedisSettings
    pool = await create_pool(RedisSettings.from_dsn("redis://localhost:6379/0"))
    assert pool is not None
    await pool.close()
```

### T-003: ARQ Worker 配置
```python
def test_worker_settings_class():
    """验证 WorkerSettings 类配置正确"""
    from app.worker import WorkerSettings
    assert hasattr(WorkerSettings, 'functions')
    assert hasattr(WorkerSettings, 'on_startup')
    assert hasattr(WorkerSettings, 'on_shutdown')
    assert len(WorkerSettings.functions) == 2  # cluster + force_cluster
```

### T-004: 任务入队
```python
async def test_enqueue_cluster_task():
    """验证任务能成功入队"""
    from app.worker import enqueue_cluster_task
    job_id = await enqueue_cluster_task(interview_id=1, user_id=1)
    assert job_id is not None
```

### T-005: 任务执行（聚类）
```python
async def test_cluster_task_execution():
    """验证 Worker 能执行聚类任务"""
    # 需要 mock pipeline 函数
    # 验证 dequeue_batch -> cluster_batch -> mark_batch_done 流程
```

### T-010: 资源限制验证
```python
def test_resource_limits_for_2c4g():
    """验证 2c4g 服务器的资源限制配置"""
    from app.worker import WorkerSettings
    assert WorkerSettings.job_timeout == 600
    assert WorkerSettings.max_tries == 3
    assert WorkerSettings.keep_result == 3600
```

## 红-绿-重构循环计划

- [ ] 循环 1: T-001 + T-002 - Redis 连接配置和连接池
- [ ] 循环 2: T-003 + T-010 - Worker 配置和资源限制
- [ ] 循环 3: T-004 - 任务入队函数
- [ ] 循环 4: T-005 + T-006 - 任务执行（正常和空队列）
- [ ] 循环 5: T-007 + T-008 - 失败重试和超时
- [ ] 循环 6: T-009 - 全量重建任务
- [ ] 循环 7: T-011 - FastAPI 集成
- [ ] 循环 8: T-012 - 部署脚本集成
