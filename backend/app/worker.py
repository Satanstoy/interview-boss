"""
ARQ Worker 配置

独立于 FastAPI 进程运行，处理异步聚类任务。
2c4g 资源优化：单并发、10 分钟超时、最多重试 3 次。
"""
import os
import time
import json
import base64
import shutil
import asyncio
import logging
from datetime import datetime
from arq.connections import RedisSettings
from arq.cron import cron

logger = logging.getLogger("interview-boss")

REDIS_URL = os.environ.get(
    "REDIS_QUEUE_URL",
    os.environ.get("REDIS_URL", "redis://localhost:6379/0"),
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


async def recompute_embedding_task(ctx, job_id: int):
    """ARQ: 全量 embedding 重算（模型更换后自动触发）。"""
    from app.services.embedding_recompute import run_recompute

    await run_recompute(job_id)


async def cluster_review_task(ctx, task_id: str):
    """ARQ worker：执行一个带 cluster_version 校验的 AI 质量评估。"""
    from app.services.cluster_review_lifecycle import run_cluster_review_task

    return await run_cluster_review_task(task_id)


async def quality_review_scan_task(ctx, job_id: int):
    """ARQ worker：执行管理员触发的误合并 + 漏合并全量扫描。"""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        QUALITY_REVIEW_SCAN_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
        touch_job,
    )

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=QUALITY_REVIEW_SCAN_JOB_TYPE,
            )
            if not task:
                return None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            conn.commit()
            return dict(task), json.loads(payload_row["payload"]) if payload_row else {}

    claimed = await asyncio.to_thread(_claim_and_load)
    if claimed is None:
        logger.info("聚合质量扫描已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    task, payload = claimed

    def _progress(current: int, message: str):
        with get_db_connection() as conn:
            touch_job(
                conn,
                job_id,
                worker_id,
                progress_current=current,
                progress_message=message,
            )
            conn.commit()

    def _complete(result):
        with get_db_connection() as conn:
            complete_job(
                conn,
                job_id,
                worker_id,
                result=json.dumps(result, ensure_ascii=False),
            )
            conn.commit()

    def _fail(error):
        with get_db_connection() as conn:
            outcome = fail_job(conn, job_id, worker_id, error)
            conn.commit()
            return outcome

    try:
        from app.services.clustering_maintenance import generate_quality_issues
        from app.services.unmerged_quality import generate_unmerged_quality_issues

        await asyncio.to_thread(_progress, 0, "正在分析聚类内误合并")
        mismerge = await generate_quality_issues(
            user_id=payload.get("user_id"),
            limit=payload.get("mismerge_limit", 1000),
            review_task_id=str(job_id),
            trigger_reason="manual_full_scan",
        )
        await asyncio.to_thread(_progress, 1, "正在分析孤岛题漏合并")
        unmerged = await generate_unmerged_quality_issues(
            user_id=payload.get("user_id"),
            limit=payload.get("singleton_limit", 1000),
            candidate_limit=payload.get("candidate_limit", 3),
            similarity_threshold=payload.get("similarity_threshold", 0.30),
            review_task_id=str(job_id),
            trigger_reason="manual_full_scan",
        )
        from app.services.cluster_review_lifecycle import sync_review_state_after_scan

        def _sync_review_state():
            with get_db_connection() as conn:
                state = sync_review_state_after_scan(
                    conn,
                    (mismerge.get("scanned_cluster_ids") or [])
                    + (unmerged.get("scanned_singleton_ids") or []),
                    trigger_reason="manual_full_scan",
                )
                conn.commit()
                return state

        state = await asyncio.to_thread(_sync_review_state)
        result = {
            "status": "completed",
            "mismerge": mismerge,
            "unmerged": unmerged,
            "review_state": state,
        }
        _complete(result)
        return {"job_id": job_id, **result}
    except Exception as exc:
        outcome = _fail(str(exc)[:500])
        logger.exception("聚合质量扫描失败: job_id=%s", job_id)
        return {"status": outcome["status"], "job_id": job_id}


async def startup(ctx):
    """Worker 启动时初始化"""
    from app.db.connection import init_db
    from app.core.config import _reload_from_db
    from app.services.embedding_service import reload_embedding_config
    init_db()
    _reload_from_db()
    reload_embedding_config()
    try:
        from redis.asyncio import from_url
        from app.core.cache import set_cache_client
        from app.core.config import REDIS_CACHE_URL

        cache = from_url(REDIS_CACHE_URL, decode_responses=True)
        await cache.ping()
        set_cache_client(cache)
        ctx["redis_cache"] = cache
    except Exception as exc:
        logger.warning("ARQ Worker Redis cache 初始化失败: %s", exc)
    logger.info("ARQ Worker 已启动")


async def shutdown(ctx):
    """Worker 关闭时清理"""
    from app.core.cache import close_cache_client

    await close_cache_client()
    logger.info("ARQ Worker 已关闭")


async def cluster_batch_task(ctx, job_id: int):
    """ARQ task: claim and process one database-owned clustering batch."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        CLUSTER_BATCH_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
    )
    from app.services.pipeline import (
        BATCH_SIZE,
        cluster_batch,
        dequeue_batch,
        mark_batch_done,
        mark_batch_failed,
    )

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=CLUSTER_BATCH_JOB_TYPE,
            )
            if not task:
                return None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            conn.commit()
            payload = json.loads(payload_row["payload"]) if payload_row else {}
            return payload

    payload = await asyncio.to_thread(_claim_and_load)
    if payload is None:
        logger.info("聚类攒批任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    def _complete(result):
        with get_db_connection() as conn:
            complete_job(conn, job_id, worker_id, result=json.dumps(result, ensure_ascii=False))
            conn.commit()

    def _fail(error):
        with get_db_connection() as conn:
            outcome = fail_job(conn, job_id, worker_id, error)
            conn.commit()
            return outcome

    batch = []
    try:
        batch = dequeue_batch(BATCH_SIZE)
        if not batch:
            result = {"status": "empty", "new_count": 0}
            _complete(result)
            return {"job_id": job_id, **result}

        new_count = await cluster_batch(batch, user_id=payload.get("user_id"))
        queue_ids = [item["queue_id"] for item in batch]
        mark_batch_done(queue_ids)
        result = {"status": "done", "new_count": new_count, "processed": len(batch)}
        _complete(result)
        return {"job_id": job_id, **result}
    except Exception as exc:
        queue_ids = [item["queue_id"] for item in batch]
        mark_batch_failed(queue_ids)
        outcome = _fail(str(exc)[:500])
        logger.exception("聚类攒批任务失败: job_id=%s", job_id)
        return {"status": outcome["status"], "job_id": job_id}


async def cluster_rebuild_task(ctx, job_id: int):
    """ARQ task: durably process every queued question for a full rebuild."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        CLUSTER_REBUILD_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
        touch_job,
    )
    from app.services.pipeline import (
        BATCH_SIZE,
        cluster_batch,
        dequeue_batch,
        mark_batch_done,
        mark_batch_failed,
    )

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=CLUSTER_REBUILD_JOB_TYPE,
            )
            if not task:
                return None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            conn.commit()
            payload = json.loads(payload_row["payload"]) if payload_row else {}
            return payload, int(task["progress_total"] or 1)

    claimed = await asyncio.to_thread(_claim_and_load)
    if claimed is None:
        logger.info("全量聚类重建任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    payload, progress_total = claimed
    processed = 0
    total_new = 0
    total_batches = 0
    batch = []

    def _touch(message: str):
        with get_db_connection() as conn:
            touch_job(
                conn,
                job_id,
                worker_id,
                progress_current=processed,
                progress_total=max(progress_total, processed, 1),
                progress_message=message,
            )
            conn.commit()

    def _complete(result):
        with get_db_connection() as conn:
            complete_job(
                conn,
                job_id,
                worker_id,
                result=json.dumps(result, ensure_ascii=False),
            )
            conn.commit()

    def _fail(error):
        with get_db_connection() as conn:
            outcome = fail_job(conn, job_id, worker_id, error)
            conn.commit()
            return outcome

    try:
        while True:
            batch = dequeue_batch(BATCH_SIZE)
            if not batch:
                result = {
                    "status": "done",
                    "batches": total_batches,
                    "new_qb_count": total_new,
                    "processed": processed,
                }
                _complete(result)
                return {"job_id": job_id, **result}

            total_batches += 1
            new_count = await cluster_batch(
                batch,
                user_id=payload.get("user_id"),
                skip_clean=True,
            )
            queue_ids = [item["queue_id"] for item in batch]
            mark_batch_done(queue_ids)
            processed += len(batch)
            total_new += new_count
            _touch(f"已完成 {processed} 道题，处理 {total_batches} 个批次")
            await asyncio.sleep(0.5)
    except Exception as exc:
        if batch:
            mark_batch_failed([item["queue_id"] for item in batch])
        outcome = _fail(str(exc)[:500])
        logger.exception("全量聚类重建任务失败: job_id=%s", job_id)
        return {"status": outcome["status"], "job_id": job_id}


async def interview_reprocess_task(ctx, job_id: int):
    """ARQ task: tag one interview, enqueue its questions and open clustering."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        INTERVIEW_REPROCESS_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
        touch_job,
    )
    from app.services.pipeline import (
        _run_cluster_batch_in_background,
        enqueue_questions,
        tag_interview,
    )

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=INTERVIEW_REPROCESS_JOB_TYPE,
            )
            if not task:
                return None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            payload = json.loads(payload_row["payload"]) if payload_row else {}
            interview = conn.execute(
                "SELECT id, url, company, round, questions_list, job_position "
                "FROM interview WHERE id = ?",
                (payload.get("interview_id"),),
            ).fetchone()
            conn.commit()
            return payload, dict(interview) if interview else None

    claimed = await asyncio.to_thread(_claim_and_load)
    if claimed is None:
        logger.info("面经重分析任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    payload, interview = claimed

    def _set_analysis_status(status: str):
        with get_db_connection() as conn:
            columns = {
                row[1] for row in conn.execute("PRAGMA table_info(interview)").fetchall()
            }
            if "analysis_status" in columns:
                conn.execute(
                    "UPDATE interview SET analysis_status = ?, "
                    "analysis_updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (status, payload.get("interview_id")),
                )
                conn.commit()

    def _touch(message: str):
        with get_db_connection() as conn:
            touch_job(
                conn,
                job_id,
                worker_id,
                progress_current=0,
                progress_total=1,
                progress_message=message,
            )
            conn.commit()

    def _complete(result):
        with get_db_connection() as conn:
            complete_job(
                conn,
                job_id,
                worker_id,
                result=json.dumps(result, ensure_ascii=False),
            )
            conn.commit()

    def _fail(error):
        with get_db_connection() as conn:
            outcome = fail_job(conn, job_id, worker_id, error)
            conn.commit()
            return outcome

    try:
        if not interview:
            raise ValueError("未找到待重分析的面经")
        questions_list = str(interview.get("questions_list") or "")
        if not questions_list.strip():
            raise ValueError("该面经没有可分析的题目清单")

        _set_analysis_status("processing")
        _touch("正在调用 AI 标注题目")
        user_id = payload.get("user_id")
        tagged_rows = await tag_interview(
            interview.get("url") or f"internal://{interview['id']}",
            interview.get("company") or "未提供",
            interview.get("round") or "未提供",
            questions_list,
            job_position=interview.get("job_position") or "",
            user_id=user_id,
            interview_id=interview["id"],
        )
        enqueue_questions(interview["id"])
        scheduled = await _run_cluster_batch_in_background(user_id=user_id)

        details = [
            {
                "question": row[3],
                "cat1": row[4],
                "cat2": row[5],
                "tags": row[6],
                "difficulty": row[7],
            }
            for row in tagged_rows
        ]
        result = {
            "interview_id": interview["id"],
            "tagged_count": len(tagged_rows),
            "details": details,
            "cluster_pending": True,
            "cluster_scheduled": scheduled,
        }
        _set_analysis_status("completed")
        _complete(result)
        return {"job_id": job_id, "status": "completed", **result}
    except Exception as exc:
        _set_analysis_status("failed")
        outcome = _fail(str(exc)[:500])
        logger.exception("面经重分析任务失败: job_id=%s", job_id)
        return {"job_id": job_id, "status": outcome["status"]}


async def refresh_interview_distribution_task(ctx, scope: str, job_position: str):
    """Recompute one distribution hierarchy after its facts were marked stale."""
    from app.db.connection import get_db_connection
    from app.services.interview_distribution import refresh_distribution_scope

    conn = get_db_connection()
    try:
        result = refresh_distribution_scope(conn, scope, job_position)
        conn.commit()
        return {"status": "completed", **result}
    except Exception:
        conn.rollback()
        raise


async def process_chat_side_effects_task(ctx, limit: int = 10):
    """Drain durable chat memory handoffs left by cancelled/restarted API workers."""
    from app.services import chat_service
    from app.agents.chat.nodes import MEMORY_EXTRACT_PROMPT, _call_llm_with_retry, _extract_json

    processed = 0
    for _ in range(max(1, min(int(limit), 50))):
        job = await asyncio.to_thread(
            chat_service.claim_side_effect_job,
            worker_id="arq-chat-side-effects",
            kind="memory_extraction",
        )
        if not job:
            break
        payload = job.get("payload") or {}
        history = (
            f"面试官提问: {str(payload.get('prior_question') or '')[:400]}\n"
            f"候选人回答: {str(payload.get('user_message') or '')[:4000]}\n"
            f"面试官追问: {str(payload.get('assistant_response') or '')[:4000]}"
        )
        try:
            result = await _call_llm_with_retry(
                MEMORY_EXTRACT_PROMPT.format(message_history=history),
                user_id=int(job["user_id"]),
                response_format={"type": "json_object"},
            )
            parsed = _extract_json(result)
            memories = parsed if isinstance(parsed, list) else (
                parsed.get("memories", parsed.get("items", []))
                if isinstance(parsed, dict) else []
            )
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            note_parts = []
            for memory in memories if isinstance(memories, list) else []:
                if isinstance(memory, dict) and memory.get("type") in {"weakness", "strength", "preference"}:
                    note_parts.append(f"[{memory['type']}] {memory.get('content', '')}")
            selected = metadata.get("selected_question")
            if isinstance(selected, dict) and selected.get("question"):
                note_parts.append(f"[asked] #{selected.get('id')}: {str(selected['question'])[:80]}")
            await asyncio.to_thread(
                chat_service.commit_memory_extraction_job,
                job["id"],
                memories if isinstance(memories, list) else [],
                note_parts,
            )
            processed += 1
        except Exception as exc:
            await asyncio.to_thread(chat_service.fail_side_effect_job, job["id"], str(exc), retry=True)
            logger.warning("chat side-effect job failed: %s (%s)", job["id"], exc)
    return {"status": "completed", "processed": processed}


async def build_master_bank_task(ctx, job_id: int):
    """后台任务：重建 master bank 题库"""
    from app.services.pipeline import dequeue_batch, cluster_batch, mark_batch_done, mark_batch_failed, BATCH_SIZE
    from app.db.connection import get_db_connection
    from app.core.config import DB_PATH
    from app.services.job_lifecycle import (
        BUILD_MASTER_BANK_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
    )

    worker_id = default_worker_id()

    def _claim():
        with get_db_connection() as conn:
            claimed = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=BUILD_MASTER_BANK_JOB_TYPE,
            )
            conn.commit()
            return bool(claimed)

    if not await asyncio.to_thread(_claim):
        logger.info("题库重建任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    def _update_progress(current, total, message=''):
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE jobs SET status = 'running', progress_current = ?, progress_total = ?, progress_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (current, total, message, job_id)
            )
            conn.commit()

    def _mark_complete(status, result=None, error=None):
        with get_db_connection() as conn:
            if status == "completed":
                complete_job(conn, job_id, worker_id, result=result)
            else:
                fail_job(conn, job_id, worker_id, error or "题库重建失败")
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
                    "SELECT question, ai_answer, answer_sources FROM question_bank WHERE ai_answer IS NOT NULL AND ai_answer != '' AND job_position = ?",
                    (current_pos,)
                ).fetchall()
                return raw, {
                    r['question']: {"answer": r['ai_answer'], "sources": r['answer_sources']}
                    for r in existing
                }

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
                    saved = existing_answers_map.get(r['question'])
                    ai_answer = saved['answer'] if saved else None
                    answer_sources = saved['sources'] if saved else None
                    if not ai_answer:
                        try:
                            import json
                            oqs = json.loads(r['original_questions'] or '[]')
                            for oq in oqs:
                                saved = existing_answers_map.get(oq)
                                if saved and saved['answer']:
                                    ai_answer = saved['answer']
                                    answer_sources = saved['sources']
                                    break
                        except Exception:
                            pass
                    if ai_answer:
                        conn.execute(
                            "UPDATE question_bank SET ai_answer = ?, answer_sources = ? WHERE id = ?",
                            (ai_answer, answer_sources, r['id'])
                        )
                        restored += 1
                conn.commit()
                return restored

        restored = await asyncio.to_thread(_restore_answers)
        logger.info(f"全量重建完成(ARQ): {total_new} 个聚类，恢复 {restored} 个 AI 答案")
        _mark_complete('completed', result=f'重建完成，新增 {total_new} 个聚类，恢复 {restored} 个 AI 答案')
        from app.core.cache import invalidate_master_bank_cache

        await invalidate_master_bank_cache()
        return {"status": "completed", "total_new": total_new, "restored": restored}

    except Exception as e:
        logger.exception(f"全量重建任务(ARQ)失败: job_id={job_id}")
        _mark_complete('failed', error=str(e)[:500])
        raise


async def submit_import_task(ctx, job_id: int):
    """后台任务：执行上传导入（面经/JD 提取 + 打标 + 聚类）

    从 job_payloads 读取 input_state，调用 LangGraph submit graph，
    将进度写入 jobs 表，最终结果写入 jobs.result。
    """
    from app.db.connection import get_db_connection, run_db
    from app.services.job_lifecycle import (
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
        touch_job,
    )

    worker_id = default_worker_id()

    def _claim():
        with get_db_connection() as conn:
            task = claim_job(conn, job_id, worker_id)
            conn.commit()
            return dict(task) if task else None

    claimed = await asyncio.to_thread(_claim)
    if not claimed:
        logger.info("上传任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    def _complete(result: str | None = None):
        with get_db_connection() as conn:
            completed = complete_job(conn, job_id, worker_id, result=result)
            conn.commit()
            return completed

    def _fail(error: str, terminal: bool = False):
        with get_db_connection() as conn:
            outcome = fail_job(
                conn,
                job_id,
                worker_id,
                error,
                max_attempts=0 if terminal else 3,
            )
            conn.commit()
            return outcome

    def _load_payload():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            return json.loads(row['payload']) if row else None

    payload = await asyncio.to_thread(_load_payload)
    if not payload:
        _fail("任务数据不存在", terminal=True)
        return

    try:
        from app.agents.submit.graph import stream_submit_graph

        # 构建 input_state（将 base64 图片还原为 bytes）
        raw_images = payload.get("image_data", [])
        image_data = []
        for img in raw_images:
            if "content_b64" in img:
                image_data.append({"content": base64.b64decode(img["content_b64"]), "mime": img["mime"]})
            else:
                image_data.append(img)  # 兼容直接传 bytes 的场景

        input_state = {
            "raw_text": payload.get("raw_text", ""),
            "image_data": image_data,
            "url": payload.get("url", ""),
            "season": payload.get("season", ""),
            "content_type_hint": payload.get("content_type_hint", ""),
            "target": payload.get("target", "personal"),
            "user_id": payload.get("user_id"),
            "is_admin": payload.get("is_admin", False),
            "job_position": payload.get("job_position", ""),
        }

        # 阶段映射
        PHASES = ["extract", "fill", "tag", "match", "save", "cluster"]
        phase_index = {p: i for i, p in enumerate(PHASES)}

        def _update_progress(phase, message=''):
            idx = phase_index.get(phase, 0)
            with get_db_connection() as conn:
                if not touch_job(
                    conn,
                    job_id,
                    worker_id,
                    progress_current=idx + 1,
                    progress_total=len(PHASES),
                    progress_message=message,
                ):
                    raise RuntimeError(f"上传任务 lease 已失效: job_id={job_id}")
                conn.commit()

        _update_progress("extract", "正在提取内容...")

        result_collector = {}
        last_phase = ""
        emitted_error = None
        saw_done = False

        # 消费 graph 事件流（只读取事件，不产出 SSE）
        try:
            async for sse_data in stream_submit_graph(input_state, result_collector=result_collector):
                try:
                    # sse_data 格式: "data: {json}\n\n"
                    if sse_data.startswith("data: "):
                        event = json.loads(sse_data[6:].strip())
                        etype = event.get("type", "")

                        if etype == "error":
                            emitted_error = event.get("message") or "处理失败"
                            break

                        if etype == "done":
                            saw_done = True

                        step = event.get("step", "")
                        message = event.get("message", "")
                        if step and step in phase_index:
                            _update_progress(step, message)
                            last_phase = step
                        elif etype == "progress" and message:
                            # 有 message 但没有已知 step
                            _update_progress(last_phase or "extract", message)
                except (json.JSONDecodeError, ValueError):
                    pass
        except Exception as e:
            logger.exception(f"graph 流式执行异常: job_id={job_id}")
            emitted_error = str(e)[:500] or "任务执行异常"

        # 如果 graph yield 了 error 事件，立刻标记失败
        if emitted_error:
            _fail(emitted_error)
            return

        # 读取最终结果（从 result_collector 获取，避免 thread_id 不匹配）
        final_state_values = result_collector.get("final_state") or {}

        if final_state_values.get("error"):
            _fail(final_state_values["error"])
            return

        if not final_state_values and not saw_done:
            _fail("任务未返回有效结果")
            return

        doc_type = final_state_values.get("doc_type", "Interview")
        doc_type = {"jd": "JD", "interview": "Interview"}.get(doc_type, doc_type)
        target = final_state_values.get("target", "personal")
        extracted_data = final_state_values.get("extracted_data", {})

        # 构建结果 JSON（包含尽可能多的有用信息）
        result_data = {
            "doc_type": doc_type,
            "target": target,
            "saved_data": extracted_data,
            "interview_id": final_state_values.get("saved_interview_id"),
            "question_count": len(extracted_data.get("具体题目清单", [])) if extracted_data else 0,
        }

        # 聚类信息（公共题库）
        cluster_result = final_state_values.get("cluster_result", {})
        if cluster_result:
            result_data["new_qb_count"] = cluster_result.get("new_qb_count", 0)

        # 匹配结果摘要（如果 final_state 里有）
        match_result = final_state_values.get("match_result")
        if match_result and isinstance(match_result, dict):
            result_data["match_result"] = {
                "matched_count": match_result.get("matched_count", len(match_result.get("matched", []))),
                "unmatched_count": match_result.get("unmatched_count", len(match_result.get("unmatched", []))),
            }

        # 耗时信息（如果 final_state 里有）
        if final_state_values.get("node_timings"):
            result_data["node_timings"] = final_state_values["node_timings"]
        if final_state_values.get("elapsed_seconds"):
            result_data["elapsed_seconds"] = final_state_values["elapsed_seconds"]

        answer_tasks = final_state_values.get("answer_tasks", [])
        uid = result_collector.get("user_id") or payload.get("user_id")
        answer_job_ids = []
        if answer_tasks and uid is not None:
            from app.services.job_lifecycle import create_answer_generation_jobs

            def _create_answer_jobs():
                with get_db_connection() as conn:
                    ids = create_answer_generation_jobs(
                        conn, job_id, answer_tasks, uid
                    )
                    conn.commit()
                    return ids

            answer_job_ids = await asyncio.to_thread(_create_answer_jobs)
        result_data["answer_job_count"] = len(answer_job_ids)
        _complete(result=json.dumps(result_data, ensure_ascii=False))

    except Exception as e:
        logger.exception(f"上传导入任务失败: job_id={job_id}")
        _fail(str(e)[:500])


async def _refresh_answer_batch_parent(parent_job_id: int):
    """Finalize a batch parent after one child answer job changes state."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import ANSWER_BATCH_JOB_TYPE

    def _refresh():
        with get_db_connection() as conn:
            parent = conn.execute(
                "SELECT id FROM jobs WHERE id = ? AND job_type = ?",
                (parent_job_id, ANSWER_BATCH_JOB_TYPE),
            ).fetchone()
            if not parent:
                return
            counts = conn.execute(
                "SELECT "
                "SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) AS completed, "
                "SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed, "
                "COUNT(*) AS total "
                "FROM jobs WHERE parent_job_id = ?",
                (parent_job_id,),
            ).fetchone()
            completed = int(counts["completed"] or 0)
            failed = int(counts["failed"] or 0)
            total = int(counts["total"] or 0)
            if total and completed + failed == total:
                status = "failed" if failed else "completed"
                result = json.dumps(
                    {"generated": completed, "failed": failed, "total": total},
                    ensure_ascii=False,
                )
                conn.execute(
                    "UPDATE jobs SET status = ?, progress_current = ?, progress_total = ?, "
                    "result = ?, error = ?, completed_at = CURRENT_TIMESTAMP, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status NOT IN ('completed', 'failed')",
                    (
                        status,
                        completed + failed,
                        total,
                        result,
                        "批量答案生成存在失败题目" if failed else None,
                        parent_job_id,
                    ),
                )
            else:
                conn.execute(
                    "UPDATE jobs SET status = 'running', progress_current = ?, progress_total = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND status IN ('pending', 'running')",
                    (completed + failed, total, parent_job_id),
                )
            conn.commit()

    await asyncio.to_thread(_refresh)


async def generate_answer_task(ctx, job_id: int):
    """ARQ task: generate one answer with durable claim/retry semantics."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        ANSWER_GENERATION_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
    )

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=ANSWER_GENERATION_JOB_TYPE,
            )
            if not task:
                return None, None, None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            conn.commit()
            return dict(task), json.loads(payload_row["payload"]) if payload_row else None

    claimed, payload = await asyncio.to_thread(_claim_and_load)
    if not claimed:
        logger.info("答案任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    def _finish(result=None):
        with get_db_connection() as conn:
            completed = complete_job(conn, job_id, worker_id, result=result)
            conn.commit()
            return completed

    def _fail(error: str, terminal: bool = False):
        with get_db_connection() as conn:
            outcome = fail_job(
                conn,
                job_id,
                worker_id,
                error,
                max_attempts=0 if terminal else 3,
            )
            conn.commit()
            return outcome

    if not payload:
        _fail("答案任务数据不存在", terminal=True)
        return {"status": "failed", "job_id": job_id}

    try:
        from app.services.submit_service import background_generate_answer

        answer_result = await background_generate_answer(
            int(payload["question_id"]),
            payload["question_text"],
            payload.get("user_id"),
            raise_on_error=True,
        )
        _finish(
            json.dumps(
                {
                    "question_id": int(payload["question_id"]),
                    **(answer_result or {}),
                },
                ensure_ascii=False,
            )
        )
        if payload.get("parent_job_id"):
            await _refresh_answer_batch_parent(int(payload["parent_job_id"]))
        return {"status": "completed", "job_id": job_id}
    except Exception as exc:
        logger.exception("答案生成任务失败: job_id=%s", job_id)
        outcome = _fail(str(exc)[:500])
        if payload.get("parent_job_id"):
            await _refresh_answer_batch_parent(int(payload["parent_job_id"]))
        return {"status": outcome["status"], "job_id": job_id}


async def generate_recitation_task(ctx, job_id: int):
    """ARQ task: generate and persist one user's recitation answer."""
    from app.db.connection import get_db_connection, run_db
    from app.db.queries import get_user_job_position
    from app.services.answer_enrichment import (
        prepare_recitation_prompt,
    )
    from app.services.job_lifecycle import (
        RECITATION_GENERATION_JOB_TYPE,
        claim_job,
        complete_job,
        default_worker_id,
        fail_job,
    )
    from app.services.llm import _call_llm_with_retry
    from app.services.resume_service import get_resume_text

    worker_id = default_worker_id()

    def _claim_and_load():
        with get_db_connection() as conn:
            task = claim_job(
                conn,
                job_id,
                worker_id,
                job_type=RECITATION_GENERATION_JOB_TYPE,
            )
            if not task:
                return None, None, None
            payload_row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            question = conn.execute(
                "SELECT question, ai_answer FROM question_bank WHERE id = ?",
                (int(json.loads(payload_row["payload"])["question_id"]),),
            ).fetchone() if payload_row else None
            conn.commit()
            return (
                dict(task),
                json.loads(payload_row["payload"]) if payload_row else None,
                dict(question) if question else None,
            )

    claimed, payload, question = await asyncio.to_thread(_claim_and_load)
    if not claimed:
        logger.info("背诵稿任务已被其他 worker 抢占或已结束: job_id=%s", job_id)
        return {"status": "already_claimed_or_finished", "job_id": job_id}

    def _finish(result=None):
        with get_db_connection() as conn:
            complete_job(conn, job_id, worker_id, result=result)
            conn.commit()

    def _fail(error):
        with get_db_connection() as conn:
            outcome = fail_job(conn, job_id, worker_id, error)
            conn.commit()
            return outcome

    if not payload or not question or not question["ai_answer"]:
        _fail("背诵稿任务数据不存在或公共答案为空")
        return {"status": "failed", "job_id": job_id}

    try:
        user_id = int(payload["user_id"])
        _, job_position = get_user_job_position(user_id)
        resume_text = get_resume_text(user_id)
        prompt, search_sources = await prepare_recitation_prompt(
            question=question["question"],
            reference_answer=question["ai_answer"],
            job_position=job_position or "",
            resume_text=resume_text,
            user_id=user_id,
        )
        answer = await _call_llm_with_retry(prompt, user_id=user_id)

        def _upsert():
            with get_db_connection() as conn:
                conn.execute(
                    "INSERT INTO user_question_view "
                    "(user_id, question_bank_id, user_answer, updated_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(user_id, question_bank_id) DO UPDATE SET "
                    "user_answer = ?, updated_at = CURRENT_TIMESTAMP",
                    (user_id, int(payload["question_id"]), answer, answer),
                )
                conn.commit()

        await run_db(_upsert)
        from app.core.cache import invalidate_master_bank_cache

        await invalidate_master_bank_cache()
        _finish(
            json.dumps(
                {
                    "question_id": int(payload["question_id"]),
                    "answer": answer,
                    "search_sources": search_sources,
                },
                ensure_ascii=False,
            )
        )
        return {"status": "completed", "job_id": job_id}
    except Exception as exc:
        logger.exception("背诵稿任务失败: job_id=%s", job_id)
        outcome = _fail(str(exc)[:500])
        return {"status": outcome["status"], "job_id": job_id}


def _mark_job_complete(job_id: int, status: str, result: str = None, error: str = None):
    """标记任务完成/失败"""
    from app.db.connection import get_db_connection
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, result = ?, error = ?, completed_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (status, result, error, job_id)
        )
        conn.commit()


async def scheduled_compaction_task(ctx):
    """定时 compaction 任务：每天凌晨 3 点自动运行"""
    from app.services.pipeline import compact_singletons_in_db

    logger.info("[定时任务] 开始 compaction...")
    start_time = time.time()

    try:
        result = await compact_singletons_in_db()
        elapsed = time.time() - start_time

        # 记录统计日志
        log_entry = {
            "task": "scheduled_compaction",
            "timestamp": datetime.now().isoformat(),
            "result": result,
            "elapsed_seconds": round(elapsed, 2)
        }
        logger.info(f"[定时任务] Compaction 完成: {result}")

        # 写入数据库记录
        def _save_log():
            from app.db.connection import get_db_connection
            conn = get_db_connection()
            try:
                conn.execute(
                    "INSERT INTO task_logs (task_type, result, elapsed_seconds, created_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP)",
                    ("compaction", json.dumps(result, ensure_ascii=False), elapsed)
                )
                conn.commit()
            except Exception as e:
                logger.warning(f"[定时任务] 保存日志失败: {e}")
                conn.rollback()

        await asyncio.to_thread(_save_log)

        return result
    except Exception as e:
        logger.exception(f"[定时任务] Compaction 失败: {e}")
        raise


async def scheduled_quality_audit_task(ctx):
    """定时聚类质量审查：抽查公共题库并生成管理员待审清单。

    误合并率超阈值（10%）时 triggered_cleanup=1，提示清洗（不自动执行）。
    清单生成与代表题检查都只处理公共题库，避免把个人题暴露给管理员。
    """
    from app.services.clustering_maintenance import (
        generate_quality_issues,
        generate_weak_representative_issues,
        run_quality_audit,
    )

    logger.info("[定时任务] 开始聚类质量审查...")
    try:
        audit_result = await run_quality_audit(user_id=None)
        issue_result = await generate_quality_issues(user_id=None, limit=20)
        weak_issue_result = await generate_weak_representative_issues(
            user_id=None, limit=20
        )
        result = {
            "audit": audit_result,
            "quality_issues": issue_result,
            "weak_representative_issues": weak_issue_result,
        }
        logger.info("[定时任务] 质量审查完成: %s", result)
        return result
    except Exception as e:
        logger.exception(f"[定时任务] 质量审查失败: {e}")
        raise


async def scheduled_submit_job_dispatch_task(ctx):
    """Recover and dispatch durable application jobs that were not delivered."""
    from app.db.connection import get_db_connection
    from app.services.job_lifecycle import (
        ANSWER_GENERATION_JOB_TYPE,
        BUILD_MASTER_BANK_JOB_TYPE,
        CLUSTER_BATCH_JOB_TYPE,
        CLUSTER_REBUILD_JOB_TYPE,
        INTERVIEW_REPROCESS_JOB_TYPE,
        DISPATCHABLE_JOB_TYPES,
        RECITATION_GENERATION_JOB_TYPE,
        RECOMPUTE_EMBEDDING_JOB_TYPE,
        SUBMIT_IMPORT_JOB_TYPE,
        QUALITY_REVIEW_SCAN_JOB_TYPE,
        claim_dispatch_batch,
        mark_dispatch_failed,
        mark_job_dispatched,
    )

    def _reserve(job_type):
        with get_db_connection() as conn:
            jobs = claim_dispatch_batch(
                conn, job_type=job_type, limit=10
            )
            conn.commit()
            return jobs

    enqueuers = {
        SUBMIT_IMPORT_JOB_TYPE: enqueue_submit_import_job,
        ANSWER_GENERATION_JOB_TYPE: enqueue_generate_answer_job,
        CLUSTER_BATCH_JOB_TYPE: enqueue_cluster_batch_job,
        CLUSTER_REBUILD_JOB_TYPE: enqueue_cluster_rebuild_job,
        INTERVIEW_REPROCESS_JOB_TYPE: enqueue_interview_reprocess_job,
        BUILD_MASTER_BANK_JOB_TYPE: enqueue_build_job,
        RECOMPUTE_EMBEDDING_JOB_TYPE: enqueue_recompute_embedding_job,
        RECITATION_GENERATION_JOB_TYPE: enqueue_generate_recitation_job,
        QUALITY_REVIEW_SCAN_JOB_TYPE: enqueue_quality_review_scan_job,
    }
    dispatched = 0
    failed = 0
    reserved = 0
    per_type = {}
    for job_type in DISPATCHABLE_JOB_TYPES:
        jobs = await asyncio.to_thread(_reserve, job_type)
        type_dispatched = 0
        type_failed = 0
        reserved += len(jobs)
        for job_row in jobs:
            job_id = job_row["id"]
            try:
                arq_job = await enqueuers[job_type](job_id)
                arq_job_id = getattr(arq_job, "job_id", None)
                if not arq_job_id:
                    raise RuntimeError("ARQ 未返回 job_id")

                def _mark(job_id=job_id, arq_id=str(arq_job_id)):
                    with get_db_connection() as conn:
                        if not mark_job_dispatched(conn, job_id, arq_id):
                            raise RuntimeError(f"任务不可再投递: job_id={job_id}")
                        conn.commit()

                await asyncio.to_thread(_mark)
                dispatched += 1
                type_dispatched += 1
            except Exception as exc:
                failed += 1
                type_failed += 1
                logger.warning("[任务] ARQ 投递失败 type=%s job=%s: %s", job_type, job_id, exc)

                def _reset(job_id=job_id, error=str(exc)):
                    with get_db_connection() as conn:
                        mark_dispatch_failed(conn, job_id, error)
                        conn.commit()

                await asyncio.to_thread(_reset)
        per_type[job_type] = {
            "reserved": len(jobs),
            "dispatched": type_dispatched,
            "failed": type_failed,
        }

    result = {
        "reserved": reserved,
        "dispatched": dispatched,
        "failed": failed,
        "by_type": per_type,
    }
    logger.info("[上传任务] dispatcher 完成: %s", result)
    return result


async def scheduled_cluster_review_dispatch_task(ctx):
    """定时补偿：回填活跃聚类状态，并将持久 outbox 投递到 ARQ。

    回填是幂等的，因此进程长期停止后重新启动也能恢复遗漏的聚类；
    ARQ 只是执行器，任务是否存在、是否过期和是否完成都以 SQLite 为准。
    """
    from app.db.connection import get_db_connection
    from app.services.cluster_review_lifecycle import (
        backfill_cluster_review_state,
        claim_review_dispatch_batch,
        mark_review_task_dispatched,
    )

    def _prepare():
        conn = get_db_connection()
        report = backfill_cluster_review_state(conn, dry_run=False)
        tasks = claim_review_dispatch_batch(conn, limit=10)
        conn.commit()
        return report, tasks

    report, tasks = await asyncio.to_thread(_prepare)
    dispatched = 0
    failed = 0
    for task in tasks:
        try:
            job = await enqueue_cluster_review_task(task["id"])
            arq_job_id = getattr(job, "job_id", None)

            def _mark(task_id=task["id"], job_id=arq_job_id):
                conn = get_db_connection()
                mark_review_task_dispatched(conn, task_id, job_id)
                conn.commit()

            await asyncio.to_thread(_mark)
            if arq_job_id:
                dispatched += 1
            else:
                failed += 1
        except Exception as exc:
            failed += 1
            logger.warning("[聚类质量] ARQ 投递失败 task=%s: %s", task["id"], exc)

            def _reset(task_id=task["id"], error=str(exc)):
                conn = get_db_connection()
                mark_review_task_dispatched(conn, task_id, None)
                conn.execute(
                    "UPDATE cluster_review_tasks SET last_error = ? WHERE id = ?",
                    (error[:500], task_id),
                )
                conn.commit()

            await asyncio.to_thread(_reset)

    result = {
        "backfill": report,
        "reserved": len(tasks),
        "dispatched": dispatched,
        "failed": failed,
    }
    logger.info("[聚类质量] dispatcher 完成: %s", result)
    return result


async def scheduled_source_health_task(ctx):
    """定时来源健康检查：每周日凌晨 3:40 扫同签名重复面经 / internal:// 增长 / JSON 双写不一致。

    只读检查 + 更新 internal 基线文件，发现问题只记日志告警，
    不自动修改数据（修复走 backend/scripts/fix_source_consistency.py）。
    """
    import os

    from app.services.source_health import run_source_health_checks

    baseline = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..",
        "..",
        "data",
        "source_health_baseline.json",
    )
    logger.info("[定时任务] 开始来源健康检查...")
    try:
        report = await asyncio.to_thread(
            run_source_health_checks, None, os.path.normpath(baseline)
        )
        if report["ok"]:
            logger.info("[定时任务] 来源健康检查通过")
        else:
            logger.warning(
                "[定时任务] 来源健康检查发现问题: 同签名重复 "
                "interview=%d 组/jd=%d 组, internal 新增=%d, "
                "JSON 双写不一致=%d 处",
                len(report["duplicate_signature_groups"]["interview"]),
                len(report["duplicate_signature_groups"]["jd"]),
                len(report["internal"]["new_urls"]),
                len(report["dual_write_mismatches"]),
            )
        return report
    except Exception as e:
        logger.exception(f"[定时任务] 来源健康检查失败: {e}")
        raise


class WorkerSettings:
    functions = [
        cluster_batch_task,
        cluster_rebuild_task,
        interview_reprocess_task,
        refresh_interview_distribution_task,
        process_chat_side_effects_task,
        build_master_bank_task,
        submit_import_task,
        generate_answer_task,
        generate_recitation_task,
        quality_review_scan_task,
        scheduled_compaction_task,
        scheduled_quality_audit_task,
        scheduled_submit_job_dispatch_task,
        scheduled_cluster_review_dispatch_task,
        cluster_review_task,
        scheduled_source_health_task,
        recompute_embedding_task
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    job_timeout = 900          # 单任务最长 15 分钟（重建可能较慢）
    max_tries = 2              # 最多重试 2 次（重建任务重试成本高）
    keep_result = 3600         # 结果保留 1 小时
    queue_read_limit = 10      # 每次最多读取 10 个任务

    # 定时任务：每天凌晨 3 点运行 compaction，每周日 3:30 质量审查、3:40 来源健康检查
    cron_jobs = [
        cron(scheduled_compaction_task, hour={3}, minute={0}),
        cron(scheduled_submit_job_dispatch_task, minute=set(range(0, 60))),
        # 质量评估从数据库 outbox 选取“当前版本未审核”的聚类，
        # 不再由固定 frequency 前 20 条的 cron 直接生成清单。
        cron(scheduled_cluster_review_dispatch_task, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        cron(scheduled_source_health_task, hour={3}, minute={40}),
        cron(process_chat_side_effects_task, minute={0, 10, 20, 30, 40, 50}),
    ]
