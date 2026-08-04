import re
import json
import asyncio
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from app.core.auth import get_admin_user, get_current_user
from app.db.connection import get_db_connection, run_db, get_current_job_position
from app.services.submit_service import background_generate_answer
from app.services.pipeline import (
    tag_interview, enqueue_questions, should_trigger_clustering,
    dequeue_batch, cluster_batch, mark_batch_done, mark_batch_failed,
    process_interview_tag_then_maybe_cluster
)

logger = logging.getLogger("interview-boss")

router = APIRouter()


@router.get("/api/interview/experiences")
async def list_experiences(user: dict = Depends(get_current_user)):
    """获取可用的面经列表（用于模拟面试选择）"""

    def _query():
        with get_db_connection() as conn:
            deleted_at_clause = "AND deleted_at IS NULL" if _has_column(conn, "interview", "deleted_at") else ""
            rows = conn.execute(
                f"""
                SELECT id, company, round, job_position, difficulty, questions_list
                FROM interview
                WHERE status = 'approved'
                  AND questions_list IS NOT NULL
                  AND questions_list != ''
                  {deleted_at_clause}
                  AND (owner_id = ? OR owner_id IS NULL)
                ORDER BY company, round
                """,
                (user["id"],),
            ).fetchall()
            return rows

    rows = await run_db(_query)
    result = []
    for row in rows:
        questions = [q.strip() for q in str(row["questions_list"] or "").splitlines() if q.strip()]
        result.append({
            "id": row["id"],
            "company": row["company"] or "未知公司",
            "round": row["round"] or "未知轮次",
            "job_position": row["job_position"] or "",
            "difficulty": row["difficulty"] or "",
            "question_count": len(questions),
        })
    return {"status": "success", "data": result}


def _has_column(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


@router.post("/api/interview/{interview_id}/re-process")
async def reprocess_interview(interview_id: int, bg_tasks: BackgroundTasks, user: dict = Depends(get_admin_user)):
    """重新分析单条面经：打标签 → 入队 → 触发聚类（如果条件满足）。"""
    def _load():
        with get_db_connection() as conn:
            return conn.execute("SELECT * FROM interview WHERE id = ?", (interview_id,)).fetchone()

    row = await run_db(_load)
    if not row:
        raise HTTPException(status_code=404, detail="未找到该面经记录")

    questions_str = row['questions_list']
    if not questions_str or not questions_str.strip():
        raise HTTPException(status_code=400, detail="该面经没有具体的题目清单可以分析")

    try:
        url = row['url'] or f"internal://{row['id']}"
        company = row['company'] or "未提供"
        round_ = row['round'] or "未提供"
        job_position = row['job_position'] or get_current_job_position()

        result = await process_interview_tag_then_maybe_cluster(
            interview_id=interview_id,
            url=url,
            company=company,
            round_=round_,
            questions_list=questions_str,
            job_position=job_position,
            user_id=user['id'],
        )

        msg = f"成功标记 {result['tagged_count']} 道题目"
        if result['clustered']:
            msg += f"，并已触发聚类（新增 {result['new_qb_count']} 个聚类）"
        else:
            msg += "，已入队等待聚类"

        return {"status": "success", "message": msg, **result}

    except Exception as e:
        logger.exception("重新分析失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")


@router.post("/api/interview/{interview_id}/re-process-stream")
async def reprocess_interview_stream(interview_id: int, user: dict = Depends(get_admin_user)):
    """SSE 版重新分析单条面经，带阶段进度推送。"""

    def _load():
        with get_db_connection() as conn:
            return conn.execute("SELECT * FROM interview WHERE id = ?", (interview_id,)).fetchone()

    row = await run_db(_load)
    if not row:
        raise HTTPException(status_code=404, detail="未找到该面经记录")

    questions_str = row['questions_list']
    if not questions_str or not questions_str.strip():
        raise HTTPException(status_code=400, detail="该面经没有具体的题目清单可以分析")

    raw_lines = [line.strip() for line in questions_str.split('\n') if line.strip()]
    q_list = [re.sub(r'^\d+[\.\)\]、-]\s*', '', line).strip() for line in raw_lines]
    q_list = [q for q in q_list if q]
    # 过滤非面试题目
    _EXTRACT_BLACKLIST = ["自我介绍", "反问", "想问我", "职业规划", "加班", "薪资", "为什么离职", "优缺点"]
    q_list = [q for q in q_list if not any(b in q for b in _EXTRACT_BLACKLIST)]

    if not q_list:
        raise HTTPException(status_code=400, detail="解析题目清单失败，未能提取到有效题目")

    async def event_stream():
        try:
            url = row['url'] or f"internal://{row['id']}"
            company = row['company'] or "未提供"
            round_ = row['round'] or "未提供"
            job_position = row['job_position'] or get_current_job_position()

            # ── 阶段 1：打标签（只写 questions_detail） ──
            yield f"data: {json.dumps({'step': 'tag', 'message': f'正在标注 {len(q_list)} 道题目...', 'type': 'progress'}, ensure_ascii=False)}\n\n"

            tagged_rows = await tag_interview(
                url, company, round_, questions_str,
                job_position=job_position, user_id=user['id'], interview_id=interview_id,
            )

            tag_details = [
                {"question": r[3], "cat1": r[4], "cat2": r[5], "tags": r[6], "difficulty": r[7]}
                for r in tagged_rows
            ]
            yield f"data: {json.dumps({'step': 'tag', 'message': f'标注完成，共 {len(tagged_rows)} 道题', 'type': 'progress', 'details': tag_details}, ensure_ascii=False)}\n\n"

            # ── 入队 ──
            enqueue_questions(interview_id)
            yield f"data: {json.dumps({'step': 'queue', 'message': '已加入聚类队列', 'type': 'progress'}, ensure_ascii=False)}\n\n"

            # ── 检查是否触发聚类 ──
            if should_trigger_clustering():
                yield f"data: {json.dumps({'step': 'cluster', 'message': '触发批量聚类...', 'type': 'progress'}, ensure_ascii=False)}\n\n"

                batch = dequeue_batch()
                if batch:
                    try:
                        new_count = await cluster_batch(batch, user_id=user['id'])
                        queue_ids = [item['queue_id'] for item in batch]
                        mark_batch_done(queue_ids)
                        yield f"data: {json.dumps({'step': 'cluster', 'message': f'聚类完成，新增 {new_count} 个聚类', 'type': 'progress', 'new_qb_count': new_count}, ensure_ascii=False)}\n\n"
                    except Exception as e:
                        logger.error(f"聚类失败，回退队列状态: {e}")
                        queue_ids = [item['queue_id'] for item in batch]
                        mark_batch_failed(queue_ids)
                        yield f"data: {json.dumps({'step': 'cluster', 'message': f'聚类失败: {str(e)}', 'type': 'error'}, ensure_ascii=False)}\n\n"

            # ── 更新面经分析状态 ──
            def _mark_done():
                with get_db_connection() as conn:
                    conn.execute(
                        "UPDATE interview SET analysis_status = 'completed', analysis_updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (interview_id,)
                    )
                    conn.commit()
            await run_db(_mark_done)

            yield f"data: {json.dumps({'step': 'done', 'message': f'分析完成，共 {len(tagged_rows)} 道题已入队', 'type': 'done', 'extracted_count': len(tagged_rows)}, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.exception("SSE 重新分析失败")
            def _mark_failed():
                with get_db_connection() as conn:
                    conn.execute(
                        "UPDATE interview SET analysis_status = 'failed', analysis_updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (interview_id,)
                    )
                    conn.commit()
            try:
                await run_db(_mark_failed)
            except Exception:
                pass
            yield f"data: {json.dumps({'type': 'error', 'message': f'分析失败: {str(e)}'}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})


@router.post("/api/interview/batch-reprocess-stream")
async def batch_reprocess_stream(user: dict = Depends(get_admin_user)):
    """SSE 版批量分析：逐条打标签，最后触发一次聚类。"""
    def _load_all():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT id, url, company, round, questions_list, job_position "
                "FROM interview WHERE deleted_at IS NULL AND questions_list IS NOT NULL AND questions_list != '' "
                "ORDER BY id"
            ).fetchall()

    interviews = await run_db(_load_all)
    if not interviews:
        raise HTTPException(status_code=400, detail="没有可分析的面经")

    async def event_stream():
        total = len(interviews)
        tagged_total = 0

        yield f"data: {json.dumps({'step': 'init', 'message': f'开始批量分析 {total} 条面经...', 'total': total, 'type': 'progress'}, ensure_ascii=False)}\n\n"

        # 阶段1：逐条打标签（可并发，但为稳定性先串行）
        for idx, iv in enumerate(interviews):
            iv = dict(iv)
            url = iv['url'] or f"internal://{iv['id']}"
            try:
                tagged_rows = await tag_interview(
                    url, iv['company'] or '未提供', iv['round'] or '未提供',
                    iv['questions_list'], job_position=iv.get('job_position', ''),
                    user_id=user['id'], interview_id=iv['id'],
                )
                enqueue_questions(iv['id'])
                tagged_total += len(tagged_rows)

                yield f"data: {json.dumps({'step': 'tag', 'current': idx + 1, 'total': total, 'interview_id': iv['id'], 'tagged_count': len(tagged_rows), 'type': 'progress'}, ensure_ascii=False)}\n\n"
            except Exception as e:
                logger.error(f"面经 {iv['id']} 打标签失败: {e}")
                yield f"data: {json.dumps({'step': 'tag', 'current': idx + 1, 'total': total, 'interview_id': iv['id'], 'error': str(e), 'type': 'error'}, ensure_ascii=False)}\n\n"

        # 阶段2：一次性聚类所有 pending
        yield f"data: {json.dumps({'step': 'cluster', 'message': '打标签完成，开始批量聚类...', 'type': 'progress'}, ensure_ascii=False)}\n\n"

        try:
            from app.services.pipeline import force_cluster_all_pending
            cluster_result = await force_cluster_all_pending(user_id=user['id'])
            batches = cluster_result['batches']
            new_qb = cluster_result['new_qb_count']
            yield f"data: {json.dumps({'step': 'cluster', 'message': f'聚类完成，处理 {batches} 个批次，新增 {new_qb} 个聚类', 'type': 'progress', **cluster_result}, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.error(f"批量聚类失败: {e}")
            yield f"data: {json.dumps({'step': 'cluster', 'message': f'聚类失败: {str(e)}', 'type': 'error'}, ensure_ascii=False)}\n\n"

        yield f"data: {json.dumps({'step': 'done', 'message': f'批量分析完成，共 {total} 条面经，{tagged_total} 道题', 'type': 'done', 'total': total, 'tagged_total': tagged_total}, ensure_ascii=False)}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})
