"""
ARQ Worker 配置

独立于 FastAPI 进程运行，处理异步聚类任务。
2c4g 资源优化：单并发、10 分钟超时、最多重试 3 次。
"""
import os
import time
import shutil
import asyncio
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


async def enqueue_build_job(job_id: int):
    """将 master bank 重建任务入队"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("build_master_bank_task", job_id)
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


async def build_master_bank_task(ctx, job_id: int):
    """后台任务：重建 master bank 题库"""
    from app.services.pipeline import dequeue_batch, cluster_batch, mark_batch_done, mark_batch_failed, BATCH_SIZE
    from app.db.connection import get_db_connection
    from app.core.config import DB_PATH

    def _update_progress(current, total, message=''):
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'running', progress_current = ?, progress_total = ?, progress_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (current, total, message, job_id)
            )
            conn.commit()

    def _mark_complete(status, result=None, error=None):
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE jobs SET status = ?, result = ?, error = ?, completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (status, result, error, job_id)
            )
            conn.commit()

    try:
        # Step 1: 备份
        _update_progress(0, 0, '正在备份数据库...')
        backup_dir = os.path.join(os.path.dirname(DB_PATH), 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        backup_path = os.path.join(backup_dir, f'interview-boss-build-{int(time.time())}.db')
        shutil.copy2(DB_PATH, backup_path)
        # 清理旧备份（保留最近 3 个）
        try:
            import glob
            backups = sorted(glob.glob(os.path.join(backup_dir, 'interview-boss-build-*.db')), key=os.path.getmtime, reverse=True)
            for old in backups[3:]:
                os.remove(old)
        except Exception:
            pass

        # Step 2: 加载数据
        _update_progress(0, 0, '加载题目数据...')
        from app.db.connection import get_current_job_position
        current_pos = get_current_job_position()

        def _load():
            with get_db_connection() as conn:
                raw = conn.execute(
                    "SELECT qd.id, qd.question, qd.cat1, qd.cat2, qd.tags, qd.diff_tag, qd.url, qd.company, qd.round "
                    "FROM questions_detail qd WHERE qd.question IS NOT NULL AND qd.question != '' AND qd.deleted_at IS NULL AND qd.job_position = ?",
                    (current_pos,)
                ).fetchall()
                existing = conn.execute(
                    "SELECT question, ai_answer FROM question_bank WHERE ai_answer IS NOT NULL AND ai_answer != '' AND job_position = ?",
                    (current_pos,)
                ).fetchall()
                return raw, {r['question']: r['ai_answer'] for r in existing}

        raw_questions, existing_answers_map = await asyncio.to_thread(_load)
        if not raw_questions:
            _mark_complete('completed', result='没有数据')
            return {"status": "empty"}

        total = len(raw_questions)
        _update_progress(0, total, f'共 {total} 道题目，准备聚类...')

        # Step 3: 清空公共题库
        _update_progress(0, total, '清空旧题库...')
        def _clear_bank():
            with get_db_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("BEGIN")
                try:
                    cursor.execute(
                        "DELETE FROM user_question_view WHERE question_bank_id IN "
                        "(SELECT id FROM question_bank WHERE job_position = ? AND owner_id IS NULL)",
                        (current_pos,)
                    )
                    cursor.execute(
                        "DELETE FROM user_practice_history WHERE question_bank_id IN "
                        "(SELECT id FROM question_bank WHERE job_position = ? AND owner_id IS NULL)",
                        (current_pos,)
                    )
                    cursor.execute(
                        "DELETE FROM question_position WHERE question_id IN "
                        "(SELECT id FROM question_bank WHERE job_position = ? AND owner_id IS NULL)",
                        (current_pos,)
                    )
                    cursor.execute("DELETE FROM question_bank WHERE job_position = ? AND owner_id IS NULL", (current_pos,))
                    conn.commit()
                except Exception:
                    conn.rollback()
                    raise

        await asyncio.to_thread(_clear_bank)

        # Step 4: 入队所有问题
        def _enqueue_all():
            with get_db_connection() as conn:
                conn.execute("DELETE FROM analysis_queue")
                qd_rows = conn.execute(
                    "SELECT qd.id, i.id as interview_id FROM questions_detail qd "
                    "JOIN interview i ON qd.url = i.url "
                    "WHERE qd.deleted_at IS NULL AND i.deleted_at IS NULL AND qd.job_position = ?",
                    (current_pos,)
                ).fetchall()
                for row in qd_rows:
                    conn.execute(
                        "INSERT OR IGNORE INTO analysis_queue (interview_id, question_detail_id, status) VALUES (?, ?, 'pending')",
                        (row['interview_id'], row['id'])
                    )
                conn.commit()
                return len(qd_rows)

        enqueued = await asyncio.to_thread(_enqueue_all)
        _update_progress(0, enqueued, f'已入队 {enqueued} 道题目，开始批量聚类...')
        logger.info(f"重建题库(ARQ): 已入队 {enqueued} 道题目")

        # Step 5: 分批聚类
        # 从任务上下文获取 user_id（提交者）
        def _get_job_creator():
            with get_db_connection() as conn:
                row = conn.execute("SELECT created_by FROM jobs WHERE id = ?", (job_id,)).fetchone()
                return row['created_by'] if row else None

        creator_id = await asyncio.to_thread(_get_job_creator)

        total_new = 0
        batch_num = 0
        while True:
            batch = dequeue_batch(BATCH_SIZE)
            if not batch:
                break
            batch_num += 1
            try:
                new_count = await cluster_batch(batch, user_id=creator_id, skip_clean=True)
                queue_ids = [item['queue_id'] for item in batch]
                mark_batch_done(queue_ids)
                total_new += new_count
                _update_progress(batch_num * BATCH_SIZE, enqueued, f'批次 {batch_num}: 新增 {new_count} 个聚类（累计 {total_new}）')
            except Exception as e:
                logger.error(f"重建聚类批次 {batch_num} 失败: {e}")
                queue_ids = [item['queue_id'] for item in batch]
                mark_batch_failed(queue_ids)
                raise

        # Step 6: 恢复 AI 答案
        _update_progress(enqueued, enqueued, '恢复 AI 答案...')
        def _restore_answers():
            with get_db_connection() as conn:
                restored = 0
                rows = conn.execute(
                    "SELECT id, question, original_questions FROM question_bank "
                    "WHERE job_position = ? AND owner_id IS NULL AND (ai_answer IS NULL OR ai_answer = '')",
                    (current_pos,)
                ).fetchall()
                for r in rows:
                    ai_answer = existing_answers_map.get(r['question'])
                    if not ai_answer:
                        try:
                            import json
                            oqs = json.loads(r['original_questions'] or '[]')
                            for oq in oqs:
                                ai_answer = existing_answers_map.get(oq)
                                if ai_answer:
                                    break
                        except Exception:
                            pass
                    if ai_answer:
                        conn.execute("UPDATE question_bank SET ai_answer = ? WHERE id = ?", (ai_answer, r['id']))
                        restored += 1
                conn.commit()
                return restored

        restored = await asyncio.to_thread(_restore_answers)
        logger.info(f"全量重建完成(ARQ): {total_new} 个聚类，恢复 {restored} 个 AI 答案")
        _mark_complete('completed', result=f'重建完成，新增 {total_new} 个聚类，恢复 {restored} 个 AI 答案')
        return {"status": "completed", "total_new": total_new, "restored": restored}

    except Exception as e:
        logger.exception(f"全量重建任务(ARQ)失败: job_id={job_id}")
        _mark_complete('failed', error=str(e)[:500])
        raise


class WorkerSettings:
    functions = [cluster_questions_task, force_cluster_all_task, build_master_bank_task]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    job_timeout = 900          # 单任务最长 15 分钟（重建可能较慢）
    max_tries = 2              # 最多重试 2 次（重建任务重试成本高）
    keep_result = 3600         # 结果保留 1 小时
    queue_read_limit = 10      # 每次最多读取 10 个任务
