import re
import json
import asyncio
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.responses import StreamingResponse
from app.core.auth import get_admin_user
from app.db.connection import get_db_connection, run_db, get_current_job_position
from app.db.operations import sync_interview_details
from app.routers.submit import tag_questions_batch, background_generate_answer
from app.services.clustering import match_new_questions

logger = logging.getLogger("interview-boss")

router = APIRouter()


@router.post("/api/interview/{interview_id}/re-process")
async def reprocess_interview(interview_id: int, bg_tasks: BackgroundTasks, user: dict = Depends(get_admin_user)):
    """重新分析单条面经：刷新 questions_detail 并同步增量聚类到 question_bank。"""
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

    if not q_list:
        raise HTTPException(status_code=400, detail="解析题目清单失败，未能提取到有效题目")

    try:
        url = row['url'] or f"internal://{row['id']}"
        company = row['company'] or "未提供"
        round_ = row['round'] or "未提供"
        current_pos = get_current_job_position()

        # ── 阶段 1：LLM 打标（事务外） ──
        tagged_rows = await tag_questions_batch(url, company, round_, q_list)

        # ── 阶段 1.5：LLM 增量匹配（事务外） ──
        def _load_existing_bank():
            with get_db_connection() as conn:
                rows = conn.execute(
                    "SELECT id, question, cat2, sources, original_questions, original_question_sources FROM question_bank "
                    "WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL AND job_position = ?",
                    (current_pos,)
                ).fetchall()
                return [dict(r) for r in rows]

        existing_bank = await run_db(_load_existing_bank)
        existing_by_cat2 = {}
        for r in existing_bank:
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

        valid_rows = [r for r in tagged_rows if r[3].strip()]
        new_rows_for_match = [
            {"id": idx, "question": r[3], "cat2": r[5] if len(r) > 5 else '', "_orig_row": r}
            for idx, r in enumerate(valid_rows)
        ]
        match_result = await match_new_questions(new_rows_for_match, existing_by_cat2)
        idx_to_row = {idx: r for idx, r in enumerate(valid_rows)}

        # ── 阶段 2：单事务（cleanup + replace_details + incremental_update） ──
        answer_tasks = sync_interview_details(
            url, tagged_rows, current_pos,
            matched=match_result["matched"],
            unmatched_rows=match_result["unmatched"],
            idx_to_row=idx_to_row,
            submitter_is_admin=True, user_id=user['id'],
        )

        # ── 阶段 3：后台生成 AI 答案（事务已提交） ──
        for qid, qtext in answer_tasks:
            bg_tasks.add_task(background_generate_answer, qid, qtext, user['id'])

        return {
            "status": "success",
            "message": f"成功重新分析了 {len(q_list)} 道题目，已同步更新题库。",
            "extracted_count": len(q_list)
        }

    except Exception as e:
        logger.exception("重新分析失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")


@router.post("/api/interview/{interview_id}/re-process-stream")
async def reprocess_interview_stream(interview_id: int, user: dict = Depends(get_admin_user)):
    """SSE 版重新分析单条面经，带阶段进度推送，支持断点续传。"""

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

    if not q_list:
        raise HTTPException(status_code=400, detail="解析题目清单失败，未能提取到有效题目")

    async def event_stream():
        try:
            url = row['url'] or f"internal://{row['id']}"
            company = row['company'] or "未提供"
            round_ = row['round'] or "未提供"
            current_pos = get_current_job_position()

            # ── 检查是否有可恢复的中间状态 ──
            analysis_status = row['analysis_status'] if 'analysis_status' in row.keys() else 'idle'
            analysis_stage = row['analysis_stage'] if 'analysis_stage' in row.keys() else None
            analysis_result_raw = row['analysis_result'] if 'analysis_result' in row.keys() else None

            cached_tagged_rows = None
            if analysis_status == 'running' and analysis_stage in ('matching', 'saving') and analysis_result_raw:
                try:
                    cached_tagged_rows = json.loads(analysis_result_raw)
                    logger.info(f"从断点恢复面经 {interview_id} 分析（阶段: {analysis_stage}）")
                    yield f"data: {json.dumps({'step': 'tag', 'message': f'从缓存恢复标注结果（{len(cached_tagged_rows)} 道题）', 'type': 'progress', 'resumed': True}, ensure_ascii=False)}\n\n"
                except Exception:
                    cached_tagged_rows = None

            # ── 持久化分析状态的辅助函数 ──
            def _save_state(status, stage, result_data=None):
                with get_db_connection() as conn:
                    conn.execute(
                        "UPDATE interview SET analysis_status = ?, analysis_stage = ?, analysis_result = ?, analysis_updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (status, stage, json.dumps(result_data, ensure_ascii=False) if result_data else None, interview_id)
                    )
                    conn.commit()

            # ── 阶段 1：LLM 打标（或从缓存恢复） ──
            if cached_tagged_rows is not None:
                tagged_rows = cached_tagged_rows
                tag_details = [
                    {"question": r[3], "cat1": r[4], "cat2": r[5], "tags": r[6], "difficulty": r[7]}
                    for r in tagged_rows
                ]
                yield f"data: {json.dumps({'step': 'tag', 'message': f'标注完成，共 {len(tagged_rows)} 道题（已缓存）', 'type': 'progress', 'details': tag_details, 'resumed': True}, ensure_ascii=False)}\n\n"
            else:
                await run_db(_save_state, 'running', 'tagging', None)
                yield f"data: {json.dumps({'step': 'tag', 'message': f'正在标注 {len(q_list)} 道题目...', 'type': 'progress'}, ensure_ascii=False)}\n\n"
                tagged_rows = await tag_questions_batch(url, company, round_, q_list, user_id=user['id'])
                tag_details = [
                    {"question": r[3], "cat1": r[4], "cat2": r[5], "tags": r[6], "difficulty": r[7]}
                    for r in tagged_rows
                ]
                # 持久化标注结果以支持断点续传
                await run_db(_save_state, 'running', 'matching', tagged_rows)
                yield f"data: {json.dumps({'step': 'tag', 'message': f'标注完成，共 {len(tagged_rows)} 道题', 'type': 'progress', 'details': tag_details}, ensure_ascii=False)}\n\n"

            # ── 阶段 2：聚类匹配 ──
            yield f"data: {json.dumps({'step': 'match', 'message': '正在聚类匹配...', 'type': 'progress'}, ensure_ascii=False)}\n\n"

            def _load_existing_bank():
                with get_db_connection() as conn:
                    rows = conn.execute(
                        "SELECT id, question, cat2, sources, original_questions, original_question_sources FROM question_bank "
                        "WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL AND job_position = ?",
                        (current_pos,)
                    ).fetchall()
                    return [dict(r) for r in rows]

            existing_bank = await run_db(_load_existing_bank)
            existing_by_cat2 = {}
            for r in existing_bank:
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

            valid_rows = [r for r in tagged_rows if r[3].strip()]
            new_rows_for_match = [
                {"id": idx, "question": r[3], "cat2": r[5] if len(r) > 5 else '', "_orig_row": r}
                for idx, r in enumerate(valid_rows)
            ]
            match_result = await match_new_questions(new_rows_for_match, existing_by_cat2)
            idx_to_row = {idx: r for idx, r in enumerate(valid_rows)}

            matched_count = len(match_result["matched"])
            unmatched_count = len(match_result["unmatched"])
            matched_questions = [idx_to_row[m['new_id']][3] for m in match_result['matched'] if m['new_id'] in idx_to_row][:10]
            new_questions = [item[3] if isinstance(item, (list, tuple)) and len(item) > 3 else item.get('_orig_row', [''])[3] for item in match_result['unmatched'][:10]]
            yield f"data: {json.dumps({'step': 'match', 'message': f'匹配完成：{matched_count} 道已有题目，{unmatched_count} 道新题', 'type': 'progress', 'matched': matched_count, 'unmatched': unmatched_count, 'matched_questions': matched_questions, 'new_questions': new_questions}, ensure_ascii=False)}\n\n"

            # ── 阶段 3：写入数据库 ──
            yield f"data: {json.dumps({'step': 'save', 'message': '正在写入数据库...', 'type': 'progress'}, ensure_ascii=False)}\n\n"
            answer_tasks = sync_interview_details(
                url, tagged_rows, current_pos,
                matched=match_result["matched"],
                unmatched_rows=match_result["unmatched"],
                idx_to_row=idx_to_row,
                submitter_is_admin=True, user_id=user['id'],
            )

            # ── 阶段 4：后台生成 AI 答案 ──
            for qid, qtext in answer_tasks:
                asyncio.create_task(background_generate_answer(qid, qtext, user['id']))

            # 标记分析完成
            await run_db(_save_state, 'completed', 'done', None)
            yield f"data: {json.dumps({'step': 'done', 'message': f'分析完成，共 {len(q_list)} 道题，{matched_count} 道匹配已有题目，{unmatched_count} 道新题入库', 'type': 'done', 'extracted_count': len(q_list)}, ensure_ascii=False)}\n\n"

        except Exception as e:
            logger.exception("SSE 重新分析失败")
            # 标记分析失败（不清除中间结果，以便重试时恢复）
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

    return StreamingResponse(event_stream(), media_type="text/event-stream")
