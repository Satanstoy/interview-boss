"""
ARQ Worker 配置

独立于 FastAPI 进程运行，处理异步聚类任务。
2c4g 资源优化：单并发、10 分钟超时、最多重试 3 次。
"""
import os
import logging
from arq.connections import RedisSettings

logger = logging.getLogger("interview-boss")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")


async def _get_redis_pool():
    """获取 Redis 连接池（惰性创建，避免模块加载时连接）"""
    from arq.connections import create_pool
    return await create_pool(RedisSettings.from_dsn(REDIS_URL))


async def enqueue_cluster_task(interview_id: int, user_id: int = None):
    """将聚类任务入队"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("cluster_questions_task", interview_id, user_id)
    finally:
        await pool.close()


async def enqueue_force_cluster_task(user_id: int = None):
    """将全量重建任务入队"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("force_cluster_all_task", user_id)
    finally:
        await pool.close()


async def startup(ctx):
    """Worker 启动时初始化"""
    from app.db.connection import init_db
    from app.core.config import _reload_from_db
    init_db()
    _reload_from_db()
    logger.info("ARQ Worker 已启动")


async def shutdown(ctx):
    """Worker 关闭时清理"""
    logger.info("ARQ Worker 已关闭")


async def cluster_questions_task(ctx, interview_id: int, user_id: int = None):
    """聚类任务：从队列取出一批问题，执行增量聚类"""
    from app.services.pipeline import (
        dequeue_batch, cluster_batch, mark_batch_done, mark_batch_failed, BATCH_SIZE
    )
    batch = dequeue_batch(BATCH_SIZE)
    if not batch:
        return {"status": "empty", "new_count": 0}

    try:
        new_count = await cluster_batch(batch, user_id=user_id)
        queue_ids = [item['queue_id'] for item in batch]
        mark_batch_done(queue_ids)
        return {"status": "done", "new_count": new_count}
    except Exception as e:
        queue_ids = [item['queue_id'] for item in batch]
        mark_batch_failed(queue_ids)
        raise


async def force_cluster_all_task(ctx, user_id: int = None):
    """全量重建任务"""
    from app.services.pipeline import force_cluster_all_pending
    return await force_cluster_all_pending(user_id=user_id)


class WorkerSettings:
    functions = [cluster_questions_task, force_cluster_all_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    job_timeout = 600          # 单任务最长 10 分钟
    max_tries = 3              # 最多重试 3 次
    keep_result = 3600         # 结果保留 1 小时
    queue_read_limit = 10      # 每次最多读取 10 个任务
