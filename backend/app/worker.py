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


async def enqueue_submit_import_job(job_id: int):
    """将上传导入任务入队"""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("submit_import_task", job_id)
    finally:
        await pool.close()


async def enqueue_interview_distribution_refresh(scope: str, job_position: str):
    """Queue a durable materialized-statistics refresh."""
    pool = await _get_redis_pool()
    try:
        return await pool.enqueue_job("refresh_interview_distribution_task", scope, job_position)
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


async def force_cluster_all_task(ctx, user_id: int = None):
    """全量重建任务 — 直接处理队列，不通过 ARQ 再次调度"""
    from app.services.pipeline import dequeue_batch, cluster_batch, mark_batch_done, mark_batch_failed, BATCH_SIZE
    import asyncio

    total_new = 0
    total_batches = 0

    while True:
        batch = dequeue_batch(BATCH_SIZE)
        if not batch:
            break
        total_batches += 1
        try:
            new_count = await cluster_batch(batch, user_id=user_id, skip_clean=True)
            queue_ids = [item['queue_id'] for item in batch]
            mark_batch_done(queue_ids)
            total_new += new_count
        except Exception as e:
            logger.error(f"聚类批次 {total_batches} 失败: {e}")
            queue_ids = [item['queue_id'] for item in batch]
            mark_batch_failed(queue_ids)
            raise
        await asyncio.sleep(0.5)

    return {"batches": total_batches, "new_qb_count": total_new}


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


async def submit_import_task(ctx, job_id: int):
    """后台任务：执行上传导入（面经/JD 提取 + 打标 + 聚类）

    从 job_payloads 读取 input_state，调用 LangGraph submit graph，
    将进度写入 jobs 表，最终结果写入 jobs.result。
    """
    from app.db.connection import get_db_connection, run_db

    def _load_payload():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT payload FROM job_payloads WHERE job_id = ?", (job_id,)
            ).fetchone()
            return json.loads(row['payload']) if row else None

    payload = await asyncio.to_thread(_load_payload)
    if not payload:
        _mark_job_complete(job_id, 'failed', error='任务数据不存在')
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
                conn.execute(
                    "UPDATE jobs SET status = 'running', progress_current = ?, progress_total = ?, progress_message = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (idx + 1, len(PHASES), message, job_id)
                )
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
            _mark_job_complete(job_id, 'failed', error=emitted_error)
            return

        # 读取最终结果（从 result_collector 获取，避免 thread_id 不匹配）
        final_state_values = result_collector.get("final_state") or {}

        if final_state_values.get("error"):
            _mark_job_complete(job_id, 'failed', error=final_state_values["error"])
            return

        if not final_state_values and not saw_done:
            _mark_job_complete(job_id, 'failed', error="任务未返回有效结果")
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

        _mark_job_complete(job_id, 'completed', result=json.dumps(result_data, ensure_ascii=False))

        # 派发后台答案生成
        answer_tasks = final_state_values.get("answer_tasks", [])
        uid = result_collector.get("user_id") or payload.get("user_id")
        if answer_tasks and uid:
            from app.services.submit_service import background_generate_answer
            for qid, qtext in answer_tasks:
                try:
                    await background_generate_answer(qid, qtext, uid)
                except Exception as e:
                    logger.warning(f"后台答案生成失败 [ID:{qid}]: {e}")

    except Exception as e:
        logger.exception(f"上传导入任务失败: job_id={job_id}")
        _mark_job_complete(job_id, 'failed', error=str(e)[:500])


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


class WorkerSettings:
    functions = [
        cluster_questions_task,
        refresh_interview_distribution_task,
        process_chat_side_effects_task,
        force_cluster_all_task,
        build_master_bank_task,
        submit_import_task,
        scheduled_compaction_task
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(REDIS_URL)
    job_timeout = 900          # 单任务最长 15 分钟（重建可能较慢）
    max_tries = 2              # 最多重试 2 次（重建任务重试成本高）
    keep_result = 3600         # 结果保留 1 小时
    queue_read_limit = 10      # 每次最多读取 10 个任务

    # 定时任务：每天凌晨 3 点运行 compaction
    cron_jobs = [
        cron(scheduled_compaction_task, hour={3}, minute={0}),
        cron(process_chat_side_effects_task, minute={0, 10, 20, 30, 40, 50}),
    ]
