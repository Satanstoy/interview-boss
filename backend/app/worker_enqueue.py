"""Worker 提交侧 - 任务入队工具。

从 worker.py 机械抽取:负责把任务入队到 ARQ(Redis),供路由/服务调用。
任务执行函数仍注册在 app/worker.py 的 WorkerSettings.functions 中。
"""
import os
import logging
from arq.connections import RedisSettings
from app.core.config import build_redis_url

logger = logging.getLogger("interview-boss")

REDIS_URL = build_redis_url(
    os.environ.get("REDIS_QUEUE_URL") or os.environ.get("REDIS_URL"),
    f"redis://{os.environ.get('REDIS_HOST', 'localhost')}:6379/0",
)


async def _get_redis_pool():
    """获取 Redis 连接池（惰性创建，避免模块加载时连接）"""
    from arq.connections import create_pool
    return await create_pool(RedisSettings.from_dsn(REDIS_URL))


async def enqueue_cluster_batch_job(job_id: int):
    """将一个持久化聚类攒批任务入队。"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("cluster_batch_task", job_id)
    finally:
        await pool.close()


async def enqueue_cluster_rebuild_job(job_id: int):
    """将一个持久化全量聚类重建任务入队。"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("cluster_rebuild_task", job_id)
    finally:
        await pool.close()


async def enqueue_build_job(job_id: int):
    """将 master bank 重建任务入队"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("build_master_bank_task", job_id)
    finally:
        await pool.close()


async def enqueue_submit_import_job(job_id: int):
    """将上传导入任务入队"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("submit_import_task", job_id)
    finally:
        await pool.close()


async def enqueue_generate_answer_job(job_id: int):
    """将单道题的答案生成任务入队。"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("generate_answer_task", job_id)
    finally:
        await pool.close()


async def enqueue_generate_recitation_job(job_id: int):
    """将单道题的个人背诵稿任务入队。"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("generate_recitation_task", job_id)
    finally:
        await pool.close()


async def enqueue_interview_reprocess_job(job_id: int):
    """将面经重分析任务入队。"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("interview_reprocess_task", job_id)
    finally:
        await pool.close()


async def enqueue_interview_import_analysis_job(job_id: int):
    """将外部 GPT 面试记录分析任务入队。"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("interview_import_analysis_task", job_id)
    finally:
        await pool.close()


async def enqueue_interview_distribution_refresh(scope: str, job_position: str):
    """Queue a durable materialized-statistics refresh."""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("refresh_interview_distribution_task", scope, job_position)
    finally:
        await pool.close()


async def enqueue_recompute_embedding_job(job_id: int):
    """将全量 embedding 重算任务入队"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("recompute_embedding_task", job_id)
    finally:
        await pool.close()


async def enqueue_quality_review_scan_job(job_id: int):
    """将管理员触发的全量聚合质量审查任务入队。"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("quality_review_scan_task", job_id)
    finally:
        await pool.close()


async def enqueue_cluster_review_task(task_id: str):
    """将数据库 outbox 中的一条聚类质量评估任务投递到 ARQ。"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("cluster_review_task", task_id)
    finally:
        await pool.close()


