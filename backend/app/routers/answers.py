import json
import logging
import asyncio
import openai
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from app.core.auth import get_current_user, get_admin_user
from app.core.prompts import ANSWER_PROMPT
from app.db.connection import get_db_connection, run_db
from app.models.schemas import BatchGenerateAnswersRequest
from app.services.llm import _call_llm_with_retry

logger = logging.getLogger("interview-boss")
router = APIRouter(prefix="/api/master-bank")


@router.post("/use-reference-answer/{question_id}")
async def use_reference_answer(question_id: int, user: dict = Depends(get_current_user)):
    """将管理员的参考答案复制为用户的个人答案"""
    def _get_question():
        with get_db_connection() as conn:
            return conn.execute("SELECT id, question, ai_answer FROM question_bank WHERE id = ?", (question_id,)).fetchone()

    row = await run_db(_get_question)
    if not row:
        raise HTTPException(status_code=404, detail="题目不存在")
    if not row['ai_answer'] or '生成失败' in row['ai_answer']:
        raise HTTPException(status_code=404, detail="该题目暂无参考答案")

    def _upsert_user_answer():
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO user_question_view (user_id, question_bank_id, user_answer, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id, question_bank_id) DO UPDATE SET user_answer = ?, updated_at = CURRENT_TIMESTAMP",
                (user['id'], question_id, row['ai_answer'], row['ai_answer'])
            )
            conn.commit()

    await run_db(_upsert_user_answer)
    return {"status": "success", "answer": row['ai_answer']}


@router.put("/save-user-answer/{question_id}")
async def save_user_answer(question_id: int, body: dict, user: dict = Depends(get_current_user)):
    """保存用户的个人答案（手动编辑）"""
    answer = body.get("answer", "")
    def _upsert():
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO user_question_view (user_id, question_bank_id, user_answer, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id, question_bank_id) DO UPDATE SET user_answer = ?, updated_at = CURRENT_TIMESTAMP",
                (user['id'], question_id, answer, answer)
            )
            conn.commit()
    await run_db(_upsert)
    return {"status": "success"}


@router.post("/generate-answer/{question_id}")
async def generate_master_answer(question_id: int, user: dict = Depends(get_current_user)):
    def _get():
        with get_db_connection() as conn:
            return conn.execute("SELECT question, ai_answer FROM question_bank WHERE id = ?", (question_id,)).fetchone()

    row = await run_db(_get)
    if not row:
        raise HTTPException(status_code=404)

    is_admin = user.get('is_admin', False)

    # 管理员：如果已有有效答案，直接返回（兼容旧行为）
    if is_admin and row['ai_answer'] and '生成失败' not in row['ai_answer']:
        return {"status": "success", "answer": row['ai_answer']}

    try:
        prompt = ANSWER_PROMPT.replace("{question}", row['question'])
        answer = await _call_llm_with_retry(prompt, user_id=user['id'])

        if is_admin:
            # 管理员：存入 question_bank.ai_answer（全局）
            def _update():
                with get_db_connection() as conn:
                    conn.execute("UPDATE question_bank SET ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (answer, question_id))
                    conn.commit()
            await run_db(_update)
        else:
            # 普通用户：存入 user_question_view.user_answer（个人）
            def _upsert():
                with get_db_connection() as conn:
                    conn.execute(
                        "INSERT INTO user_question_view (user_id, question_bank_id, user_answer, updated_at) "
                        "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                        "ON CONFLICT(user_id, question_bank_id) DO UPDATE SET user_answer = ?, updated_at = CURRENT_TIMESTAMP",
                        (user['id'], question_id, answer, answer)
                    )
                    conn.commit()
            await run_db(_upsert)

        return {"status": "success", "answer": answer}
    except openai.AuthenticationError:
        raise HTTPException(status_code=500, detail="API Key 无效，请在系统配置中更新 API Key。")
    except openai.APIConnectionError:
        raise HTTPException(status_code=500, detail="无法连接 LLM 服务，请检查系统配置中的 Base URL。")
    except openai.APITimeoutError:
        raise HTTPException(status_code=500, detail="LLM 服务响应超时，请增大超时时间或稍后重试。")
    except Exception as e:
        logger.error(f"手动生成答案失败（已重试3次）[ID:{question_id}]: {e}")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")


@router.post("/batch-generate-answers")
async def batch_generate_answers(req: BatchGenerateAnswersRequest, user: dict = Depends(get_current_user)):
    """批量生成答案（SSE 流式推送进度）"""
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    def _load():
        with get_db_connection() as conn:
            placeholders = ",".join("?" * len(req.ids))
            return conn.execute(
                f"SELECT id, question, ai_answer FROM question_bank WHERE id IN ({placeholders})", req.ids
            ).fetchall()

    rows = await run_db(_load)
    if not rows:
        raise HTTPException(status_code=404, detail="未找到任何匹配题目")

    questions = [(r["id"], r["question"]) for r in rows
                 if r["question"] and (not r["ai_answer"] or '生成失败' in r["ai_answer"])]
    skipped = len(rows) - len(questions)

    async def event_stream():
        try:
            if not questions:
                yield f"data: {json.dumps({'type': 'done', 'generated': 0, 'failed': 0, 'skipped': skipped})}\n\n"
                return

            total = len(questions)
            generated = 0
            failed = 0
            done_count = 0
            results_lock = asyncio.Lock()

            # 先发送 init 事件
            yield f"data: {json.dumps({'type': 'init', 'total': total, 'skipped': skipped})}\n\n"

            semaphore = asyncio.Semaphore(3)

            async def _gen_one(idx, qid, question_text):
                nonlocal generated, failed, done_count
                async with semaphore:
                    try:
                        prompt = ANSWER_PROMPT.replace("{question}", question_text)
                        answer = await _call_llm_with_retry(prompt, user_id=user['id'])
                        def _update():
                            with get_db_connection() as conn:
                                conn.execute(
                                    "UPDATE question_bank SET ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                    (answer, qid)
                                )
                                conn.commit()
                        await run_db(_update)
                        async with results_lock:
                            generated += 1
                            done_count += 1
                            yield_event = json.dumps({'type': 'progress', 'current': done_count, 'total': total, 'id': qid, 'success': True})
                    except Exception as e:
                        logger.error(f"批量生成答案失败 [ID:{qid}]: {e}")
                        def _mark_failed():
                            with get_db_connection() as conn:
                                conn.execute(
                                    "UPDATE question_bank SET ai_answer = '[生成失败，请手动重试]', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                    (qid,)
                                )
                                conn.commit()
                        await run_db(_mark_failed)
                        async with results_lock:
                            failed += 1
                            done_count += 1
                            yield_event = json.dumps({'type': 'progress', 'current': done_count, 'total': total, 'id': qid, 'success': False})
                return yield_event

            # 并发执行但按完成顺序收集事件
            tasks = [_gen_one(i, qid, qtext) for i, (qid, qtext) in enumerate(questions)]

            for coro in asyncio.as_completed(tasks):
                event_data = await coro
                yield f"data: {event_data}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'generated': generated, 'failed': failed, 'skipped': skipped})}\n\n"
        except Exception as e:
            logger.exception("批量生成答案失败")
            yield f"data: {json.dumps({'type': 'error', 'message': f'生成失败: {str(e)[:200]}'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"X-Accel-Buffering": "no"})
