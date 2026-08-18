import json
import logging
import openai
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, Depends
from app.core.auth import get_current_user
from app.core.cache import invalidate_master_bank_cache
from app.core.prompts import EVAL_PROMPT
from app.db.connection import get_db_connection, run_db
from app.models.schemas import (
    EvaluateAnswerRequest,
    PracticeDeckCreateRequest,
    PracticeDeckItemRequest,
    PracticeDeckUpdateRequest,
    PracticeReviewCorrectionRequest,
    PracticeReviewRequest,
)
from app.db.queries import build_bank_where_clause
from app.services.practice_deck_service import (
    add_deck_item,
    create_custom_deck,
    delete_custom_deck,
    list_deck_questions,
    list_decks,
    remove_deck_item,
    update_custom_deck,
)
from app.services.practice_review_service import (
    ReviewCorrectionError,
    correct_review,
    record_review,
)
from app.services.question_draw_service import draw_questions
from app.services.llm import _call_llm_with_retry, _extract_json
from app.services.llm_quota import check_and_record
from app.services.recruitment_milestones import compute_urgency, get_season_windows

logger = logging.getLogger("interview-boss")
router = (
    APIRouter()
)  # NO prefix - paths are mixed (/api/master-bank/... and /api/evaluate-answer)


def _assert_question_visible(conn, user: dict, question_id: int):
    # all 口径：公共题 + 自己的题（与列表可见范围一致）
    from_clause, where_clause, params = build_bank_where_clause(user["id"], "all")
    row = conn.execute(
        f"SELECT qb.id {from_clause} {where_clause} AND qb.id = ?",
        params + [question_id],
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="题目不存在或无权访问")


def _user_urgency(user_id: int, today=None) -> float:
    """从用户招聘偏好计算 urgency（机会窗口 + 节奏偏移；无偏好 → base 0.2）"""
    from datetime import datetime as dt

    today = today or dt.utcnow().date()
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT graduation_year, pace FROM user_recruitment_pref WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if not row or not row["graduation_year"]:
        return 0.2
    windows = get_season_windows(int(row["graduation_year"]))
    info = compute_urgency(windows, today, str(row["pace"] or "standard"))
    return float(info["urgency"])


@router.get("/api/practice/decks")
async def get_practice_decks(
    filter: str = Query(
        "all", pattern="^(all|public|mine)$", description="题库可见范围"
    ),
    user: dict = Depends(get_current_user),
):
    """Return live LeetCode-style study plans linked to the high-frequency bank."""

    def _query():
        with get_db_connection() as conn:
            return list_decks(conn, user["id"], filter)

    return {"items": await run_db(_query), "algorithm": "sm2_lite"}


@router.post("/api/practice/decks")
async def create_practice_deck(
    req: PracticeDeckCreateRequest, user: dict = Depends(get_current_user)
):
    def _create():
        with get_db_connection() as conn:
            deck = create_custom_deck(
                conn,
                user["id"],
                name=req.name,
                description=req.description,
                visibility=req.visibility,
            )
            conn.commit()
            return deck

    return await run_db(_create)


@router.put("/api/practice/decks/{deck_key}")
async def update_practice_deck(
    deck_key: str,
    req: PracticeDeckUpdateRequest,
    user: dict = Depends(get_current_user),
):
    def _update():
        with get_db_connection() as conn:
            try:
                deck = update_custom_deck(
                    conn,
                    user["id"],
                    deck_key,
                    req.model_dump(exclude_unset=True),
                )
            except KeyError:
                raise HTTPException(status_code=404, detail="题单不存在或无权操作")
            conn.commit()
            return deck

    return await run_db(_update)


@router.delete("/api/practice/decks/{deck_key}")
async def delete_practice_deck(deck_key: str, user: dict = Depends(get_current_user)):
    def _delete():
        with get_db_connection() as conn:
            try:
                delete_custom_deck(conn, user["id"], deck_key)
            except KeyError:
                raise HTTPException(
                    status_code=404, detail="题单不存在或系统题单不可删除"
                )
            conn.commit()

    await run_db(_delete)
    return {"status": "success", "deck_key": deck_key}


@router.post("/api/practice/decks/{deck_key}/items")
async def add_practice_deck_item(
    deck_key: str,
    req: PracticeDeckItemRequest,
    user: dict = Depends(get_current_user),
):
    def _add():
        with get_db_connection() as conn:
            _assert_question_visible(conn, user, req.question_id)
            try:
                item = add_deck_item(conn, user["id"], deck_key, req.question_id)
            except KeyError:
                raise HTTPException(status_code=404, detail="自定义题单不存在")
            conn.commit()
            return item

    return await run_db(_add)


@router.delete("/api/practice/decks/{deck_key}/items/{question_id}")
async def remove_practice_deck_item(
    deck_key: str, question_id: int, user: dict = Depends(get_current_user)
):
    def _remove():
        with get_db_connection() as conn:
            try:
                remove_deck_item(conn, user["id"], deck_key, question_id)
            except KeyError:
                raise HTTPException(status_code=404, detail="自定义题单不存在")
            conn.commit()

    await run_db(_remove)
    return {"status": "success", "question_id": question_id}


@router.get("/api/practice/decks/{deck_key}/questions")
async def get_practice_deck_questions(
    deck_key: str,
    filter: str = Query("all", pattern="^(all|public|mine)$"),
    limit: int = Query(100, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user),
):
    """Load one named deck as an ordered review queue."""

    def _query():
        with get_db_connection() as conn:
            try:
                return list_deck_questions(
                    conn,
                    user["id"],
                    deck_key,
                    filter_mode=filter,
                    limit=limit,
                    offset=offset,
                )
            except KeyError:
                raise HTTPException(status_code=404, detail="题单不存在")

    deck, items, total = await run_db(_query)
    return {
        "deck": deck,
        "items": items,
        "total": total,
        "page_size": limit,
        "offset": offset,
    }


@router.post("/api/practice/review")
async def review_practice_question(
    req: PracticeReviewRequest, user: dict = Depends(get_current_user)
):
    """Persist the flashcard rating and calculate the next due time."""

    def _review():
        with get_db_connection() as conn:
            _assert_question_visible(conn, user, req.question_id)
            urgency = _user_urgency(user["id"])
            result = record_review(
                conn,
                user_id=user["id"],
                question_id=req.question_id,
                rating=req.rating,
                score=req.score,
                urgency=urgency,
                idempotency_key=req.idempotency_key,
            )
            conn.commit()
            return result

    result = await run_db(_review)
    await invalidate_master_bank_cache()
    return {"question_id": req.question_id, "review": result}


@router.put("/api/practice/review/{event_id}")
async def correct_practice_review(
    event_id: int,
    req: PracticeReviewCorrectionRequest,
    user: dict = Depends(get_current_user),
):
    """Correct one recent rating without creating a second review event."""

    def _correct():
        with get_db_connection() as conn:
            try:
                question_id, result = correct_review(
                    conn,
                    user_id=user["id"],
                    event_id=event_id,
                    rating=req.rating,
                    score=req.score,
                    urgency=_user_urgency(user["id"]),
                )
            except ReviewCorrectionError as exc:
                raise HTTPException(status_code=409, detail=str(exc)) from exc
            conn.commit()
            return question_id, result

    question_id, result = await run_db(_correct)
    await invalidate_master_bank_cache()
    return {"question_id": question_id, "review": result}


@router.post("/api/master-bank/toggle-star/{question_id}")
async def toggle_star(question_id: int, user: dict = Depends(get_current_user)):
    """切换题目收藏状态（per-user，存储在 user_question_view 表）"""

    def _toggle():
        with get_db_connection() as conn:
            # 检查题目是否在用户可见范围内（all 口径：公共题 + 自己的题）
            from_clause, where_clause, params = build_bank_where_clause(
                user["id"], "all"
            )
            row = conn.execute(
                f"SELECT qb.id {from_clause} {where_clause} AND qb.id = ?",
                params + [question_id],
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目或无权操作")

            existing = conn.execute(
                "SELECT id, is_starred FROM user_question_view WHERE user_id = ? AND question_bank_id = ?",
                (user["id"], question_id),
            ).fetchone()

            if existing:
                new_val = 0 if existing["is_starred"] else 1
                conn.execute(
                    "UPDATE user_question_view SET is_starred = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (new_val, existing["id"]),
                )
            else:
                new_val = 1
                conn.execute(
                    "INSERT INTO user_question_view (user_id, question_bank_id, is_starred) VALUES (?, ?, 1)",
                    (user["id"], question_id),
                )
            conn.commit()
            return new_val

    try:
        new_val = await run_db(_toggle)
        await invalidate_master_bank_cache()
        return {"status": "success", "is_starred": bool(new_val)}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="操作失败，请稍后重试")


@router.get("/api/master-bank/random")
async def get_random_questions(
    count: int = Query(5, ge=1, le=50),
    cat1: Optional[str] = Query(None),
    difficulty: Optional[str] = Query(None),
    user: dict = Depends(get_current_user),
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
async def evaluate_answer(
    req: EvaluateAnswerRequest, user: dict = Depends(get_current_user)
):
    """对比用户答案与 AI 参考答案，返回多维度评估结果"""
    if not req.user_answer.strip():
        raise HTTPException(status_code=400, detail="用户答案不能为空")
    if not req.reference_answer.strip():
        raise HTTPException(status_code=400, detail="参考答案不能为空")

    # per-user 每日 LLM 配额
    if not await check_and_record(user["id"]):
        raise HTTPException(status_code=429, detail="今日 AI 调用次数已达上限")

    # 超出 3000 字符的输入会被静默截断——记录日志，避免误判为评估遗漏
    truncated = len(req.user_answer) > 3000 or len(req.reference_answer) > 3000
    if truncated:
        logger.info(
            "evaluate-answer 输入截断: question_id=%s user_answer=%s reference_answer=%s",
            req.question_id,
            len(req.user_answer),
            len(req.reference_answer),
        )

    prompt = EVAL_PROMPT.format(
        question=req.question_text,
        user_answer=req.user_answer[:3000],
        reference_answer=req.reference_answer[:3000],
    )

    try:
        raw = await _call_llm_with_retry(
            prompt=prompt,
            system_msg="你是一名专业的技术面试评估专家。",
            user_id=user["id"],
            model=req.model if req.model and req.model.strip() else None,
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
        result["truncated"] = truncated

        # 记录自评评估（只写 review 体系，双写收敛后 user_practice_history 不再写入）
        if req.question_id:

            def _record():
                with get_db_connection() as conn:
                    from_clause, where_clause, params = build_bank_where_clause(
                        user["id"], "all"
                    )
                    visible = conn.execute(
                        f"SELECT qb.id {from_clause} {where_clause} AND qb.id = ?",
                        params + [req.question_id],
                    ).fetchone()
                    if not visible:
                        raise PermissionError("question_not_visible")
                    # 双写收敛(audit D9): 评估只写 review 体系(user_question_review +
                    # practice_review_events), 不再写 user_practice_history。
                    # 旧表仅保留存量; 读端已全部迁移到 practice_review_events。
                    rating = (
                        "easy"
                        if result["overall_score"] >= 85
                        else "good"
                        if result["overall_score"] >= 65
                        else "again"
                    )
                    urgency = _user_urgency(user["id"])
                    record_review(
                        conn,
                        user_id=user["id"],
                        question_id=req.question_id,
                        rating=rating,
                        score=result["overall_score"],
                        source="self_check",
                        urgency=urgency,
                        user_answer=req.user_answer,
                        evaluation_result=json.dumps(result, ensure_ascii=False),
                    )
                    conn.commit()

            try:
                await run_db(_record)
                await invalidate_master_bank_cache()
            except PermissionError:
                raise HTTPException(status_code=404, detail="题目不存在或无权访问")
            except Exception as e:
                logger.warning(f"记录练习历史失败（不影响评估结果）: {e}")

        return result

    except json.JSONDecodeError as e:
        logger.error(f"评估结果 JSON 解析失败: {e}")
        raise HTTPException(
            status_code=500, detail="评估结果解析失败，LLM 未返回有效 JSON，请重试"
        )
    except openai.AuthenticationError:
        logger.error("评估失败: API Key 无效")
        raise HTTPException(
            status_code=500, detail="API Key 无效或已过期，请在系统配置中更新 API Key。"
        )
    except openai.APIConnectionError:
        logger.error("评估失败: LLM 连接失败")
        raise HTTPException(
            status_code=500,
            detail="无法连接 LLM 服务，请检查系统配置中的 Base URL 是否正确。",
        )
    except openai.APITimeoutError:
        logger.error("评估失败: LLM 调用超时")
        raise HTTPException(
            status_code=500,
            detail="LLM 服务响应超时，请在系统配置中增大超时时间或稍后重试。",
        )
    except HTTPException:
        raise
    except Exception:
        logger.exception("答案评估失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")


@router.get("/api/practice/practiced")
async def get_practiced_questions(user: dict = Depends(get_current_user)):
    """当前用户刷过的题（按最近复习时间倒序，最多 50 条）"""

    def _query():
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT qb.id, qb.question, qb.cat1, qb.cat2, qb.difficulty, "
                "uqr.state, uqr.proficiency, uqr.review_count, uqr.last_rating, "
                "uqr.last_reviewed_at, uqr.next_review_at "
                "FROM user_question_review uqr "
                "JOIN question_bank qb ON qb.id = uqr.question_bank_id "
                "WHERE uqr.user_id = ? AND qb.deleted_at IS NULL "
                "ORDER BY uqr.updated_at DESC LIMIT 50",
                (user["id"],),
            ).fetchall()
            return rows

    rows = await run_db(_query)
    return {"items": [dict(r) for r in rows]}


@router.get("/api/practice-history/{question_id}")
async def get_practice_history(
    question_id: int, user: dict = Depends(get_current_user)
):
    """获取指定题目的练习历史（当前用户的，读 review 体系）。

    user_practice_history 已停写（双写收敛），history 改读
    practice_review_events（self_check 源含 user_answer 快照）。
    """

    def _query():
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT id, question_bank_id, user_answer, evaluation_result, "
                "score, rating, source, reviewed_at AS created_at "
                "FROM practice_review_events "
                "WHERE question_bank_id = ? AND user_id = ? "
                "ORDER BY reviewed_at DESC",
                (question_id, user["id"]),
            ).fetchall()
            return rows

    rows = await run_db(_query)
    result = []
    for r in rows:
        d = dict(r)
        # 评估明细以 JSON 快照落到 review event；解析失败降级为 None
        try:
            d["evaluation_result"] = (
                json.loads(d["evaluation_result"])
                if d["evaluation_result"]
                else None
            )
        except (json.JSONDecodeError, TypeError):
            d["evaluation_result"] = None
        result.append(d)
    return result
