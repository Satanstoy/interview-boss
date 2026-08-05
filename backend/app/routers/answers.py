import json
import logging
import asyncio
import openai
from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import StreamingResponse
from app.core.auth import get_current_user, get_admin_user
from app.db.connection import get_db_connection, run_db
from app.models.schemas import BatchGenerateAnswersRequest
from app.routers.questions import _build_bank_where_clause
from app.services.llm import _call_llm_with_retry
from app.services.answer_enrichment import (
    prepare_answer_prompt,
    prepare_recitation_prompt,
)
from app.db.queries import get_user_job_position
from app.services.resume_service import get_resume_text

logger = logging.getLogger("interview-boss")
router = APIRouter(prefix="/api/master-bank")


@router.put("/save-user-answer/{question_id}")
async def save_user_answer(
    question_id: int, body: dict, user: dict = Depends(get_current_user)
):
    """保存用户的背诵稿（手动编辑）"""
    answer = body.get("answer", "")

    def _check_visible():
        with get_db_connection() as conn:
            # all 口径：公共题 + 自己的题（背诵稿保存须对用户可见）
            from app.db.queries import build_bank_where_clause

            from_clause, where_clause, params = build_bank_where_clause(
                user["id"], "all"
            )
            return conn.execute(
                f"SELECT 1 {from_clause} {where_clause} AND qb.id = ?",
                params + [question_id],
            ).fetchone()

    if not await run_db(_check_visible):
        raise HTTPException(status_code=404, detail="题目不存在或无权访问")

    def _upsert():
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO user_question_view (user_id, question_bank_id, user_answer, updated_at) "
                "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                "ON CONFLICT(user_id, question_bank_id) DO UPDATE SET user_answer = ?, updated_at = CURRENT_TIMESTAMP",
                (user["id"], question_id, answer, answer),
            )
            conn.commit()
            return True

    await run_db(_upsert)
    return {"status": "success"}


@router.post("/generate-answer/{question_id}")
async def generate_master_answer(
    question_id: int, user: dict = Depends(get_current_user)
):
    """生成公共参考答案（仅管理员，全局共享）"""
    if not user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="公共参考答案仅管理员可生成")

    def _get():
        with get_db_connection() as conn:
            from_clause, where_clause, params = _build_bank_where_clause(user)
            return conn.execute(
                f"SELECT qb.question, qb.ai_answer {from_clause} {where_clause} AND qb.id = ?",
                params + [question_id],
            ).fetchone()

    row = await run_db(_get)
    if not row:
        raise HTTPException(status_code=404)

    is_admin = user.get("is_admin", False)

    # 管理员：如果已有有效答案，直接返回（兼容旧行为）
    if is_admin and row["ai_answer"] and "生成失败" not in row["ai_answer"]:
        return {"status": "success", "answer": row["ai_answer"]}

    try:
        prompt, search_sources = await prepare_answer_prompt(
            row["question"], user_id=user["id"]
        )
        answer = await _call_llm_with_retry(prompt, user_id=user["id"])

        if is_admin:
            # 管理员：存入 question_bank.ai_answer（全局）
            def _update():
                with get_db_connection() as conn:
                    conn.execute(
                        "UPDATE question_bank SET ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (answer, question_id),
                    )
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
                        (user["id"], question_id, answer, answer),
                    )
                    conn.commit()

            await run_db(_upsert)

        return {"status": "success", "answer": answer, "search_sources": search_sources}
    except openai.AuthenticationError:
        raise HTTPException(
            status_code=500, detail="API Key 无效，请在系统配置中更新 API Key。"
        )
    except openai.APIConnectionError:
        raise HTTPException(
            status_code=500, detail="无法连接 LLM 服务，请检查系统配置中的 Base URL。"
        )
    except openai.APITimeoutError:
        raise HTTPException(
            status_code=500, detail="LLM 服务响应超时，请增大超时时间或稍后重试。"
        )
    except Exception as e:
        logger.error(f"手动生成答案失败（已重试3次）[ID:{question_id}]: {e}")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")


@router.post("/generate-recitation/{question_id}")
async def generate_recitation(question_id: int, user: dict = Depends(get_current_user)):
    """定制用户个人背诵稿：以公共参考答案为基座，结合岗位/简历个性化改写。"""

    def _get():
        with get_db_connection() as conn:
            from_clause, where_clause, params = _build_bank_where_clause(user)
            return conn.execute(
                f"SELECT qb.question, qb.ai_answer {from_clause} "
                f"{where_clause} AND qb.id = ?",
                params + [question_id],
            ).fetchone()

    row = await run_db(_get)
    if not row:
        raise HTTPException(status_code=404)
    if not row["ai_answer"] or "生成失败" in row["ai_answer"]:
        raise HTTPException(
            status_code=404, detail="该题目暂无公共参考答案，请等待管理员生成"
        )

    _, job_position = get_user_job_position(user["id"])
    resume_text = get_resume_text(user["id"])

    try:
        prompt, search_sources = await prepare_recitation_prompt(
            question=row["question"],
            reference_answer=row["ai_answer"],
            job_position=job_position or "",
            resume_text=resume_text,
            user_id=user["id"],
        )
        answer = await _call_llm_with_retry(prompt, user_id=user["id"])

        def _upsert():
            with get_db_connection() as conn:
                conn.execute(
                    "INSERT INTO user_question_view (user_id, question_bank_id, user_answer, updated_at) "
                    "VALUES (?, ?, ?, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(user_id, question_bank_id) DO UPDATE SET user_answer = ?, updated_at = CURRENT_TIMESTAMP",
                    (user["id"], question_id, answer, answer),
                )
                conn.commit()

        await run_db(_upsert)
        return {"status": "success", "answer": answer, "search_sources": search_sources}
    except openai.AuthenticationError:
        raise HTTPException(
            status_code=500, detail="API Key 无效，请在系统配置中更新 API Key。"
        )
    except openai.APIConnectionError:
        raise HTTPException(
            status_code=500, detail="无法连接 LLM 服务，请检查系统配置中的 Base URL。"
        )
    except openai.APITimeoutError:
        raise HTTPException(
            status_code=500, detail="LLM 服务响应超时，请增大超时时间或稍后重试。"
        )
    except Exception as e:
        logger.error(f"背诵稿生成失败 [ID:{question_id}]: {e}")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")


@router.post("/batch-generate-answers")
async def batch_generate_answers(
    req: BatchGenerateAnswersRequest, user: dict = Depends(get_current_user)
):
    """批量生成公共参考答案（SSE 流式推送进度，仅管理员）"""
    if not user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="公共参考答案仅管理员可生成")
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    def _load():
        with get_db_connection() as conn:
            placeholders = ",".join("?" * len(req.ids))
            from_clause, where_clause, params = _build_bank_where_clause(user)
            return conn.execute(
                f"SELECT qb.id, qb.question, qb.ai_answer {from_clause} "
                f"{where_clause} AND qb.id IN ({placeholders})",
                params + req.ids,
            ).fetchall()

    rows = await run_db(_load)
    if not rows:
        raise HTTPException(status_code=404, detail="未找到任何匹配题目")

    questions = [
        (r["id"], r["question"])
        for r in rows
        if r["question"] and (not r["ai_answer"] or "生成失败" in r["ai_answer"])
    ]
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
                        prompt, _ = await prepare_answer_prompt(
                            question_text, user_id=user["id"]
                        )
                        answer = await _call_llm_with_retry(prompt, user_id=user["id"])

                        def _update():
                            with get_db_connection() as conn:
                                conn.execute(
                                    "UPDATE question_bank SET ai_answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                    (answer, qid),
                                )
                                conn.commit()

                        await run_db(_update)
                        async with results_lock:
                            generated += 1
                            done_count += 1
                            yield_event = json.dumps(
                                {
                                    "type": "progress",
                                    "current": done_count,
                                    "total": total,
                                    "id": qid,
                                    "success": True,
                                }
                            )
                    except Exception as e:
                        logger.error(f"批量生成答案失败 [ID:{qid}]: {e}")

                        def _mark_failed():
                            with get_db_connection() as conn:
                                conn.execute(
                                    "UPDATE question_bank SET ai_answer = '[生成失败，请手动重试]', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                    (qid,),
                                )
                                conn.commit()

                        await run_db(_mark_failed)
                        async with results_lock:
                            failed += 1
                            done_count += 1
                            yield_event = json.dumps(
                                {
                                    "type": "progress",
                                    "current": done_count,
                                    "total": total,
                                    "id": qid,
                                    "success": False,
                                }
                            )
                return yield_event

            # 并发执行但按完成顺序收集事件
            tasks = [
                _gen_one(i, qid, qtext) for i, (qid, qtext) in enumerate(questions)
            ]

            for coro in asyncio.as_completed(tasks):
                event_data = await coro
                yield f"data: {event_data}\n\n"

            yield f"data: {json.dumps({'type': 'done', 'generated': generated, 'failed': failed, 'skipped': skipped})}\n\n"
        except Exception as e:
            logger.exception("批量生成答案失败")
            yield f"data: {json.dumps({'type': 'error', 'message': f'生成失败: {str(e)[:200]}'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no"},
    )
