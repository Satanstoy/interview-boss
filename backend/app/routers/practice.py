import json
import logging
import openai
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from app.core.auth import get_current_user
from app.core.prompts import EVAL_PROMPT
from app.db.connection import get_db_connection, run_db
from app.models.schemas import EvaluateAnswerRequest
from app.routers.questions import _build_bank_where_clause
from app.services.question_draw_service import draw_questions
from app.services.llm import _call_llm_with_retry, _extract_json

logger = logging.getLogger("interview-boss")
router = APIRouter()  # NO prefix - paths are mixed (/api/master-bank/... and /api/evaluate-answer)


@router.post("/api/master-bank/toggle-star/{question_id}")
async def toggle_star(question_id: int, user: dict = Depends(get_current_user)):
    """切换题目收藏状态（per-user，存储在 user_question_view 表）"""
    def _toggle():
        with get_db_connection() as conn:
            # 检查题目是否在用户可见范围内
            from_clause, where_clause, params = _build_bank_where_clause(user)
            row = conn.execute(
                f"SELECT qb.id {from_clause} {where_clause} AND qb.id = ?",
                params + [question_id]
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目或无权操作")

            existing = conn.execute(
                "SELECT id, is_starred FROM user_question_view WHERE user_id = ? AND question_bank_id = ?",
                (user['id'], question_id)
            ).fetchone()

            if existing:
                new_val = 0 if existing['is_starred'] else 1
                conn.execute(
                    "UPDATE user_question_view SET is_starred = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_val, existing['id'])
                )
            else:
                new_val = 1
                conn.execute(
                    "INSERT INTO user_question_view (user_id, question_bank_id, is_starred) VALUES (?, ?, 1)",
                    (user['id'], question_id)
                )
            conn.commit()
            return new_val

    try:
        new_val = await run_db(_toggle)
        return {"status": "success", "is_starred": bool(new_val)}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail="操作失败，请稍后重试")


@router.get("/api/master-bank/random")
async def get_random_questions(
    count: int = Query(5, ge=1, le=50),
    cat1: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    user: dict = Depends(get_current_user)
):
    """加权随机抽题，避免重复抽取近期练过的题目"""
    return await run_db(
        lambda: draw_questions(
            user=user,
            count=count,
            cat1=cat1,
            difficulty=difficulty,
        )
    )


@router.post("/api/evaluate-answer")
async def evaluate_answer(req: EvaluateAnswerRequest, user: dict = Depends(get_current_user)):
    """对比用户答案与 AI 参考答案，返回多维度评估结果"""
    if not req.user_answer.strip():
        raise HTTPException(status_code=400, detail="用户答案不能为空")
    if not req.reference_answer.strip():
        raise HTTPException(status_code=400, detail="参考答案不能为空")

    prompt = EVAL_PROMPT.format(
        question=req.question_text,
        user_answer=req.user_answer[:3000],
        reference_answer=req.reference_answer[:3000]
    )

    try:
        raw = await _call_llm_with_retry(
            prompt=prompt,
            system_msg="你是一名专业的技术面试评估专家。",
            user_id=user['id'],
        )
        result = _extract_json(raw)

        # 防御性解析：确保必要字段存在
        result.setdefault("overall_score", 0)
        result.setdefault("dimensions", {})
        result.setdefault("strengths", [])
        result.setdefault("weaknesses", [])
        result.setdefault("suggestions", "")

        for dim_key in ("completeness", "depth", "accuracy", "logic"):
            result["dimensions"].setdefault(dim_key, {"score": 0, "comment": ""})

        # 钳制分数范围
        result["overall_score"] = max(0, min(100, int(result["overall_score"])))
        for dim in result["dimensions"].values():
            dim["score"] = max(0, min(100, int(dim.get("score", 0))))

        # 自动记录练习历史（写入 user_practice_history，关联用户）
        if req.question_id:
            def _record():
                with get_db_connection() as conn:
                    from_clause, where_clause, params = _build_bank_where_clause(user)
                    visible = conn.execute(
                        f"SELECT qb.id {from_clause} {where_clause} AND qb.id = ?",
                        params + [req.question_id],
                    ).fetchone()
                    if not visible:
                        raise PermissionError("question_not_visible")
                    conn.execute(
                        "INSERT INTO user_practice_history (user_id, question_bank_id, user_answer, evaluation_result, score) VALUES (?, ?, ?, ?, ?)",
                        (user['id'], req.question_id, req.user_answer, json.dumps(result, ensure_ascii=False), result["overall_score"])
                    )
                    conn.commit()
            try:
                await run_db(_record)
            except PermissionError:
                raise HTTPException(status_code=404, detail="题目不存在或无权访问")
            except Exception as e:
                logger.warning(f"记录练习历史失败（不影响评估结果）: {e}")

        return result

    except json.JSONDecodeError as e:
        logger.error(f"评估结果 JSON 解析失败: {e}")
        raise HTTPException(status_code=500, detail="评估结果解析失败，LLM 未返回有效 JSON，请重试")
    except openai.AuthenticationError:
        logger.error("评估失败: API Key 无效")
        raise HTTPException(status_code=500, detail="API Key 无效或已过期，请在系统配置中更新 API Key。")
    except openai.APIConnectionError:
        logger.error("评估失败: LLM 连接失败")
        raise HTTPException(status_code=500, detail="无法连接 LLM 服务，请检查系统配置中的 Base URL 是否正确。")
    except openai.APITimeoutError:
        logger.error("评估失败: LLM 调用超时")
        raise HTTPException(status_code=500, detail="LLM 服务响应超时，请在系统配置中增大超时时间或稍后重试。")
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("答案评估失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")


@router.get("/api/practice-history/{question_id}")
async def get_practice_history(question_id: int, user: dict = Depends(get_current_user)):
    """获取指定题目的练习历史（当前用户的）"""
    def _query():
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, question_bank_id, user_answer, evaluation_result, score, created_at FROM user_practice_history WHERE question_bank_id = ? AND user_id = ? ORDER BY created_at DESC",
                (question_id, user['id'])
            ).fetchall()
            return rows

    rows = await run_db(_query)
    result = []
    for r in rows:
        d = dict(r)
        try:
            d['evaluation_result'] = json.loads(d['evaluation_result']) if d['evaluation_result'] else None
        except Exception:
            d['evaluation_result'] = None
        result.append(d)
    return result
