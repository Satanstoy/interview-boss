import os
import json
import time
import logging
import asyncio
from fastapi import APIRouter, HTTPException, Depends, Query
from fastapi.responses import StreamingResponse
from app.core.config import DB_PATH
from app.core.auth import get_current_user, get_admin_user
from app.db.connection import get_db_connection, run_db, get_current_job_position
from app.db.question_bank_sources import insert_source, insert_original_item
from app.services.clustering import match_new_questions

logger = logging.getLogger("interview-boss")
router = APIRouter()  # NO prefix - paths include both /api/jobs/... and /api/master-bank/...


@router.get("/api/jobs/{job_id}/stream")
async def stream_job_progress(job_id: int, user: dict = Depends(get_current_user)):
    """Stream job progress via SSE."""
    is_admin = user.get("is_admin", 0)
    user_id = user["id"]

    async def event_generator():
        last_update = None
        while True:
            def _check():
                with get_db_connection() as conn:
                    return conn.execute(
                        "SELECT status, progress_current, progress_total, progress_message, result, error "
                        "FROM jobs WHERE id = ? AND (? = 1 OR created_by = ?)",
                        (job_id, is_admin, user_id)
                    ).fetchone()

            job = await run_db(_check)
            if not job:
                yield f"data: {json.dumps({'type': 'error', 'message': '任务不存在'})}\n\n"
                break

            update = {
                'type': 'progress' if job['status'] == 'running' else job['status'],
                'status': job['status'],
                'current': job['progress_current'],
                'total': job['progress_total'],
                'message': job['progress_message']
            }

            current_update = json.dumps(update)
            if current_update != last_update:
                yield f"data: {current_update}\n\n"
                last_update = current_update

            if job['status'] in ('completed', 'failed'):
                if job['error']:
                    yield f"data: {json.dumps({'type': 'error', 'status': 'failed', 'job_id': job_id, 'message': job['error']}, ensure_ascii=False)}\n\n"
                elif job['result']:
                    # 尝试解析 JSON result（submit_import 等任务会存 JSON）
                    try:
                        result_data = json.loads(job['result'])
                        yield f"data: {json.dumps({'type': 'done', 'status': 'completed', 'job_id': job_id, 'result': result_data}, ensure_ascii=False)}\n\n"
                    except (json.JSONDecodeError, TypeError):
                        yield f"data: {json.dumps({'type': 'done', 'status': 'completed', 'job_id': job_id, 'message': job['result']}, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps({'type': 'done', 'status': 'completed', 'job_id': job_id, 'message': '任务完成'}, ensure_ascii=False)}\n\n"
                break

            await asyncio.sleep(2)  # Poll every 2 seconds

    return StreamingResponse(event_generator(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@router.get("/api/jobs/{job_id}")
async def get_job_status(job_id: int, user: dict = Depends(get_current_user)):
    """Get job status (non-streaming)."""
    is_admin = user.get("is_admin", 0)
    user_id = user["id"]

    def _query():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, job_type, status, progress_current, progress_total, progress_message, error, created_at, completed_at "
                "FROM jobs WHERE id = ? AND (? = 1 OR created_by = ?)",
                (job_id, is_admin, user_id)
            ).fetchone()

    job = await run_db(_query)
    if not job:
        raise HTTPException(status_code=404, detail="任务不存在")
    return dict(job)


@router.post("/api/master-bank/build")
async def build_master_bank(user: dict = Depends(get_admin_user)):
    """Submit a master bank rebuild job (async via ARQ worker)."""
    def _create_job():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            try:
                # Check for existing running build
                existing = cursor.execute(
                    "SELECT id FROM jobs WHERE job_type = 'build_master_bank' AND status IN ('pending', 'running') AND created_by = ?",
                    (user['id'],)
                ).fetchone()
                if existing:
                    return None  # Already running

                cursor.execute(
                    "INSERT INTO jobs (job_type, status, created_by) VALUES ('build_master_bank', 'pending', ?)",
                    (user['id'],)
                )
                job_id = cursor.lastrowid
                conn.commit()
                return job_id
            except Exception:
                conn.rollback()
                raise

    job_id = await run_db(_create_job)
    if job_id is None:
        raise HTTPException(status_code=409, detail="已有重建任务在执行中，请等待完成")

    # Schedule via ARQ
    arq_scheduled = False
    try:
        from app.worker import enqueue_build_job
        await enqueue_build_job(job_id)
        arq_scheduled = True
        logger.info(f"重建任务已通过 ARQ 调度: job_id={job_id}")
    except Exception as e:
        logger.warning(f"ARQ 调度失败，回退到内联执行: {e}")

    if not arq_scheduled:
        # Fallback: run inline in background task
        async def _fallback():
            await _run_build_inline(job_id, user['id'])
        asyncio.create_task(_fallback())

    return {"job_id": job_id, "status": "pending", "message": "重建任务已提交，请通过 SSE 监听进度"}


async def _run_build_inline(job_id: int, user_id: int):
    """Fallback inline build logic (used when ARQ is unavailable).

    Same logic as the ARQ task but runs in the FastAPI process.
    Updates the jobs table with progress for SSE monitoring.
    """
    import shutil as _shutil

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
        backup_path = f"{DB_PATH}.bak.build.{int(time.time())}"
        try:
            _shutil.copy2(DB_PATH, backup_path)
        except Exception as e:
            logger.warning(f"创建备份失败: {e}")
        try:
            import glob
            backups = sorted(glob.glob(f"{DB_PATH}.bak.build.*"), key=os.path.getmtime, reverse=True)
            for old in backups[3:]:
                os.remove(old)
        except Exception:
            pass

        current_pos = get_current_job_position()

        # Step 2: 加载数据
        _update_progress(0, 0, '加载题目数据...')
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

        raw_questions, existing_answers_map = await run_db(_load)
        if not raw_questions:
            _mark_complete('completed', result='没有数据')
            return

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

        await run_db(_clear_bank)

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

        enqueued = await run_db(_enqueue_all)
        _update_progress(0, enqueued, f'已入队 {enqueued} 道题目，开始批量聚类...')
        logger.info(f"重建题库(内联): 已入队 {enqueued} 道题目")

        # Step 5: 分批聚类
        from app.services.pipeline import dequeue_batch, cluster_batch, mark_batch_done, mark_batch_failed, BATCH_SIZE

        total_new = 0
        batch_num = 0
        while True:
            batch = dequeue_batch(BATCH_SIZE)
            if not batch:
                break
            batch_num += 1
            try:
                new_count = await cluster_batch(batch, user_id=user_id, skip_clean=True)
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

        restored = await run_db(_restore_answers)
        logger.info(f"全量重建完成(内联): {total_new} 个聚类，恢复 {restored} 个 AI 答案")
        _mark_complete('completed', result=f'重建完成，新增 {total_new} 个聚类，恢复 {restored} 个 AI 答案')

    except Exception as e:
        logger.exception(f"全量重建失败(内联): job_id={job_id}")
        _mark_complete('failed', error=str(e)[:500])


@router.post("/api/master-bank/compact")
async def compact_singletons(
    admin: dict = Depends(get_admin_user),
    match_existing: bool = Query(False, description="是否先匹配已有聚类"),
):
    """孤岛碎片整理：对独立题做二次合并（SSE 流式推送）

    Args:
        match_existing: True 时先将孤岛匹配到已有聚类（RAG+LLM），再做内部合并
    """
    async def event_stream():
        try:
            from app.services.pipeline import compact_singletons_in_db
            mode = "匹配已有聚类+内部合并" if match_existing else "仅内部合并"
            yield f"data: {json.dumps({'type': 'init', 'step': 'compact', 'message': f'开始孤岛碎片整理（{mode}）...'})}\n\n"
            result = await compact_singletons_in_db(user_id=None, match_existing=match_existing, operator_id=admin['id'])
            yield f"data: {json.dumps({'type': 'done', **result})}\n\n"
        except Exception as e:
            logger.exception("孤岛碎片整理失败")
            yield f"data: {json.dumps({'type': 'error', 'message': f'整理失败: {str(e)[:200]}'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@router.post("/api/master-bank/build-personal")
async def build_personal_bank(user: dict = Depends(get_current_user)):
    """个人题库与公共题库聚类合并（SSE 流式推送进度）"""

    async def event_stream():
        try:
            uid = user['id']
            yield f"data: {json.dumps({'type': 'init', 'total': 0, 'step': 'prepare', 'message': '正在加载数据...'})}\n\n"

            from app.db.connection import get_user_job_position
            _, current_pos = get_user_job_position(uid)
            if not current_pos:
                current_pos = get_current_job_position()

            def _load():
                with get_db_connection() as conn:
                    # 加载用户的个人题目
                    personal = conn.execute(
                        "SELECT id, question, cat1, cat2, tags, difficulty, frequency, sources, job_position "
                        "FROM question_bank WHERE owner_id = ? AND job_position = ?",
                        (uid, current_pos)
                    ).fetchall()
                    # 加载公共题库（含 original_questions 用于匹配上下文）
                    public = conn.execute(
                        "SELECT id, question, cat2, sources, original_questions FROM question_bank "
                        "WHERE owner_id IS NULL AND status = 'approved' AND job_position = ?",
                        (current_pos,)
                    ).fetchall()
                    return [dict(r) for r in personal], [dict(r) for r in public]

            personal_rows, public_rows = await run_db(_load)

            if not personal_rows:
                yield f"data: {json.dumps({'type': 'done', 'error': '没有个人题目需要合并'})}\n\n"
                return

            if not public_rows:
                yield f"data: {json.dumps({'type': 'done', 'error': '公共题库为空，无法合并'})}\n\n"
                return

            yield f"data: {json.dumps({'type': 'init', 'total': len(personal_rows), 'message': f'开始合并: {len(personal_rows)} 道个人题目 vs {len(public_rows)} 道公共题目'})}\n\n"

            # 按 cat2 构建公共题库聚类上下文
            existing_by_cat2 = {}
            for r in public_rows:
                cat2 = r.get('cat2') or ''
                if cat2 not in existing_by_cat2:
                    existing_by_cat2[cat2] = []
                all_qs = [r['question']]
                try:
                    orig = json.loads(r.get('original_questions') or '[]')
                    all_qs.extend([q for q in orig if q and q != r['question']])
                except Exception:
                    pass
                existing_by_cat2[cat2].append({
                    "question_bank_id": r['id'],
                    "question": r['question'],
                    "all_questions": all_qs,
                })

            # 为个人题目分配临时 id 用于匹配
            new_rows_for_match = []
            for idx, row in enumerate(personal_rows):
                new_rows_for_match.append({
                    "id": idx,
                    "question": row['question'],
                    "cat2": row.get('cat2') or '',
                })

            yield f"data: {json.dumps({'type': 'progress', 'step': 'match', 'current': 0, 'total': 1, 'message': 'LLM 匹配中...'})}\n\n"

            match_result = await match_new_questions(new_rows_for_match, existing_by_cat2, user_id=user['id'])
            matched = match_result["matched"]
            unmatched = match_result["unmatched"]

            # 执行合并：匹配到的个人题目 → 增加公共题目的 frequency，追加 sources
            merged_count = 0

            def _merge():
                nonlocal merged_count
                with get_db_connection() as conn:
                    for m in matched:
                        new_id = m["new_id"]
                        qb_id = m["question_bank_id"]
                        personal_row = personal_rows[new_id]
                        existing = conn.execute("SELECT sources, original_questions, original_question_sources FROM question_bank WHERE id = ?", (qb_id,)).fetchone()
                        if existing:
                            try:
                                sources = json.loads(existing['sources']) if existing['sources'] else []
                            except (json.JSONDecodeError, TypeError):
                                sources = []
                            personal_sources = []
                            try:
                                personal_sources = json.loads(personal_row.get('sources', '[]')) if personal_row.get('sources') else []
                            except (json.JSONDecodeError, TypeError):
                                pass
                            # BUG-012: URL-based 去重
                            existing_urls = {s.get('url') for s in sources}
                            for s in personal_sources:
                                if s.get('url') not in existing_urls:
                                    sources.append(s)
                                    existing_urls.add(s.get('url'))
                            # BUG-013: 回写 original_questions
                            try:
                                orig_qs = json.loads(existing['original_questions']) if existing['original_questions'] else []
                                orig_qs_src = json.loads(existing['original_question_sources']) if existing['original_question_sources'] else []
                            except (json.JSONDecodeError, TypeError):
                                orig_qs, orig_qs_src = [], []
                            personal_q_text = personal_row['question']
                            if personal_q_text and personal_q_text not in orig_qs:
                                orig_qs.append(personal_q_text)
                                orig_qs_src.append({"question": personal_q_text, "sources": personal_sources})
                            conn.execute(
                                "UPDATE question_bank SET frequency = ?, sources = ?, original_questions = ?, original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (len(orig_qs), json.dumps(sources, ensure_ascii=False), json.dumps(orig_qs, ensure_ascii=False), json.dumps(orig_qs_src, ensure_ascii=False), qb_id)
                            )
                            # Dual-write: insert personal question's sources into target's normalized tables
                            # INSERT OR IGNORE handles dedup with existing sources
                            for s in personal_sources:
                                try:
                                    insert_source(conn, qb_id, s.get('url', ''), s.get('company', ''), s.get('round', ''))
                                except Exception:
                                    pass
                            try:
                                insert_original_item(conn, qb_id, personal_q_text, personal_sources)
                            except Exception:
                                pass
                        merged_count += 1
                        # 删除已合并的个人题目
                        conn.execute("DELETE FROM question_bank WHERE id = ?", (personal_row['id'],))
                    conn.commit()

            await run_db(_merge)

            yield f"data: {json.dumps({'type': 'progress', 'step': 'done', 'current': 0, 'total': 0, 'message': '合并完成'})}\n\n"
            yield f"data: {json.dumps({'type': 'done', 'merged': merged_count, 'kept': len(unmatched), 'total_personal': len(personal_rows)})}\n\n"
        except Exception as e:
            logger.exception("个人题库构建失败")
            yield f"data: {json.dumps({'type': 'error', 'message': f'构建失败: {str(e)[:200]}'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})
