"""题库 CRUD + 搜索端点 — 变异操作和批量操作已拆分到 questions_pkg/"""

import json
import logging
from collections import Counter
from fastapi import APIRouter, HTTPException, Query, Depends
from app.core.auth import get_current_user
from app.db.question_bank_sources import build_api_shapes_batch_filtered
from app.db.connection import get_db_connection, run_db, get_dynamic_frequency_sql
from app.models.schemas import UpdateQuestionRequest

logger = logging.getLogger("interview-boss")

router = APIRouter()


def _build_bank_where_clause(user: dict, table_alias: str = "qb"):
    """根据用户 bank_mode 和当前岗位构建查询子句

    Returns:
        (from_clause, where_clause, params)
        - from_clause: 含 question_position JOIN 的 FROM 子句
        - where_clause: 含 bank_mode 过滤的 WHERE 子句
        - params: 参数列表
    """
    from app.db.connection import get_user_job_position

    prefix = f"{table_alias}." if table_alias else ""
    mode = user.get("bank_mode", "public")
    uid = user["id"]
    pos_id, pos_name = get_user_job_position(uid)

    # 使用 question_position 关联表进行岗位过滤
    from_clause = f"FROM question_bank {table_alias} JOIN question_position qp ON {prefix}id = qp.question_id AND qp.position_id = ?"
    from_params = [pos_id] if pos_id else []

    deleted_filter = f"{prefix}deleted_at IS NULL"

    if not pos_id:
        # fallback: 如果没有 position_id，用旧的 job_position 列
        from_clause = f"FROM question_bank {table_alias}"
        pos_fallback = pos_name
        if mode == "personal":
            return (
                from_clause,
                f"WHERE {prefix}owner_id = ? AND {deleted_filter} AND {prefix}job_position = ?",
                [uid, pos_fallback],
            )
        elif mode == "mixed":
            return (
                from_clause,
                f"WHERE (({prefix}owner_id IS NULL AND {prefix}status = 'approved') OR ({prefix}owner_id = ? AND {prefix}duplicate_of IS NULL)) AND {deleted_filter} AND {prefix}job_position = ?",
                [uid, pos_fallback],
            )
        else:
            return (
                from_clause,
                f"WHERE {prefix}owner_id IS NULL AND {prefix}status = 'approved' AND {deleted_filter} AND {prefix}job_position = ?",
                [pos_fallback],
            )

    if mode == "personal":
        return from_clause, f"WHERE {prefix}owner_id = ? AND {deleted_filter}", from_params + [uid]
    elif mode == "mixed":
        return (
            from_clause,
            f"WHERE (({prefix}owner_id IS NULL AND {prefix}status = 'approved') OR ({prefix}owner_id = ? AND {prefix}duplicate_of IS NULL)) AND {deleted_filter}",
            from_params + [uid],
        )
    else:  # 'public'
        return (
            from_clause,
            f"WHERE {prefix}owner_id IS NULL AND {prefix}status = 'approved' AND {deleted_filter}",
            from_params,
        )


def _split_join_and_where_params(from_clause: str, params: list):
    """Separate question_position JOIN params from WHERE params for queries with extra JOINs."""
    if "qp.position_id = ?" not in from_clause:
        return [], list(params)
    return list(params[:1]), list(params[1:])


@router.get("/api/master-bank")
async def get_master_bank(
    sort: str = "frequency_desc",
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=1000),
    cat1: str = Query(None, description="Filter by cat1 category"),
    compact: bool = Query(
        False, description="Return compact response without full text fields"
    ),
    user: dict = Depends(get_current_user),
):
    bank_mode = user.get("bank_mode", "public")
    dyn_freq_sql = get_dynamic_frequency_sql(bank_mode, user["id"])
    order_clause = (
        f"ORDER BY ({dyn_freq_sql}) DESC" if sort != "recent" else "ORDER BY qb.id DESC"
    )
    offset = (page - 1) * page_size
    from_clause, where_clause, params = _build_bank_where_clause(user)

    # Save original where_clause and params for popular_tags query (before cat1 filter)
    original_where_clause = where_clause
    original_params = list(params)

    if cat1 and cat1 != "全部":
        where_clause = f"WHERE ({where_clause.removeprefix('WHERE ').strip()}) AND qb.cat1 LIKE ?"
        params = params + [f"%{cat1}%"]
    join_params, where_params = _split_join_and_where_params(from_clause, params)

    def _query():
        with get_db_connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) {from_clause} {where_clause}", params
            ).fetchone()[0]
            # 注意：JOIN 的 user_id 参数必须在 WHERE 的 params 之前
            full_sql = f"SELECT qb.id, qb.question, qb.cat1, qb.cat2, qb.tags, qb.difficulty, ({dyn_freq_sql}) as dyn_frequency, qb.ai_answer, qb.sources, qb.original_questions, qb.original_question_sources, COALESCE(uqv.is_starred, 0) as is_starred, COALESCE(uqv.user_answer, '') as user_answer, qb.owner_id, qb.status, qb.job_position {from_clause} LEFT JOIN user_question_view uqv ON uqv.question_bank_id = qb.id AND uqv.user_id = ? {where_clause} {order_clause} LIMIT ? OFFSET ?"
            full_params = join_params + [user["id"]] + where_params + [page_size, offset]
            rows = conn.execute(full_sql, full_params).fetchall()
            return total, rows

    total, rows = await run_db(_query)

    # Collect all qb_ids for batch fetching from normalized tables
    qb_ids = [r["id"] for r in rows]

    def _fetch_normalized():
        with get_db_connection() as conn2:
            try:
                return build_api_shapes_batch_filtered(
                    conn2, qb_ids, bank_mode, user["id"]
                )
            except Exception:
                return {}

    normalized_map = await run_db(_fetch_normalized)

    result = []
    for r in rows:
        d = dict(r)
        d["frequency"] = d.pop("dyn_frequency", d.get("frequency", 0))
        norm = normalized_map.get(d["id"], {})
        d["sources"] = norm.get("sources", [])
        d["original_questions"] = norm.get("original_questions", [])
        d["original_question_sources"] = norm.get("original_question_sources", [])
        d["frequency"] = norm.get("frequency", d["frequency"])
        d["is_personal"] = d.get("owner_id") is not None
        d["has_reference_answer"] = bool(
            d.get("ai_answer") and "生成失败" not in d["ai_answer"]
        )
        d["user_answer"] = d.get("user_answer", "")
        d.pop("status", None)  # Frontend doesn't use this
        if compact:
            d["ai_answer"] = None
            d["user_answer"] = ""
            # Replace original_question_sources with a flat source_labels map
            source_labels = {}
            for item in d.get("original_question_sources", []):
                for s in item.get("sources", []):
                    if s.get("url"):
                        source_labels[s["url"]] = item.get("question", "")
            d["source_labels"] = source_labels
            d.pop("original_question_sources", None)
        result.append(d)

    # Compute filter counts server-side (based on entire bank, not just current page)
    def _query_filter_counts():
        with get_db_connection() as conn:
            rows = conn.execute(
                f"SELECT qb.cat1, qb.tags {from_clause} {original_where_clause}",
                original_params,
            ).fetchall()
            category_counts = Counter()
            tag_counts = Counter()
            for row in rows:
                cats = [
                    cat.strip()
                    for cat in (row["cat1"] or "未分类").split(",")
                    if cat.strip()
                ]
                if cats:
                    category_counts.update(cats)
                else:
                    category_counts["未分类"] += 1
                for tag in (row["tags"] or "").split(","):
                    tag = tag.strip()
                    if tag:
                        tag_counts[tag] += 1
            filtered_tag_rows = conn.execute(
                f"SELECT qb.tags {from_clause} {where_clause}",
                params,
            ).fetchall()
            filtered_tag_counts = Counter()
            for row in filtered_tag_rows:
                for tag in (row["tags"] or "").split(","):
                    tag = tag.strip()
                    if tag:
                        filtered_tag_counts[tag] += 1

            return {
                "overall_total": len(rows),
                "category_counts": [
                    {"category": category, "count": count}
                    for category, count in category_counts.most_common()
                ],
                "popular_tags": [
                    {"tag": tag, "count": count}
                    for tag, count in tag_counts.most_common(20)
                ],
                "filtered_tag_counts": [
                    {"tag": tag, "count": count}
                    for tag, count in filtered_tag_counts.most_common()
                ],
            }

    response = {
        "items": result,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
    if page == 1:
        filter_counts = await run_db(_query_filter_counts)
        response.update(
            {
                "overall_total": filter_counts["overall_total"],
                "category_counts": filter_counts["category_counts"],
                "popular_tags": filter_counts["popular_tags"],
                "filtered_tag_counts": filter_counts["filtered_tag_counts"],
            }
        )
    return response


@router.get("/api/master-bank/{question_id}/detail")
async def get_question_detail(question_id: int, user: dict = Depends(get_current_user)):
    """Get full details for a single question (ai_answer, user_answer, original_question_sources)."""

    def _query():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT qb.id, qb.ai_answer, COALESCE(uqv.user_answer, '') as user_answer, "
                "qb.original_question_sources "
                "FROM question_bank qb "
                "LEFT JOIN user_question_view uqv ON uqv.question_bank_id = qb.id AND uqv.user_id = ? "
                "WHERE qb.id = ?",
                (user["id"], question_id),
            ).fetchone()
            if not row:
                return None
            d = dict(row)
            # Build original_question_sources from normalized tables
            try:
                from app.db.question_bank_sources import get_original_question_sources

                with get_db_connection() as conn2:
                    d["original_question_sources"] = get_original_question_sources(
                        conn2, question_id
                    )
            except Exception:
                try:
                    d["original_question_sources"] = json.loads(
                        d.get("original_question_sources", "[]")
                    )
                except Exception:
                    d["original_question_sources"] = []
            return d

    result = await run_db(_query)
    if not result:
        raise HTTPException(status_code=404, detail="题目不存在")
    return result


@router.get("/api/master-bank/search")
async def search_master_bank(
    q: str = Query("", min_length=0, max_length=200),
    exclude_id: int = Query(None),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(get_current_user),
):
    """搜索题库（用于合并时选择目标题目）"""
    from_clause, where_clause, params = _build_bank_where_clause(user)
    conditions = []
    search_params = list(params)

    if q.strip():
        conditions.append("qb.question LIKE ?")
        search_params.append(f"%{q.strip()}%")
    if exclude_id is not None:
        conditions.append("qb.id != ?")
        search_params.append(exclude_id)

    if conditions:
        where_with_extra = f"{where_clause} AND {' AND '.join(conditions)}"
    else:
        where_with_extra = where_clause

    def _query():
        bank_mode = user.get("bank_mode", "public")
        dyn_freq_sql = get_dynamic_frequency_sql(bank_mode, user["id"])
        with get_db_connection() as conn:
            rows = conn.execute(
                f"SELECT qb.id, qb.question, ({dyn_freq_sql}) as frequency, qb.cat1, qb.cat2 {from_clause} {where_with_extra} ORDER BY ({dyn_freq_sql}) DESC LIMIT ?",
                search_params + [limit],
            ).fetchall()
            return [dict(r) for r in rows]

    items = await run_db(_query)
    return {"items": items}


@router.put("/api/master-bank/{question_id}")
async def edit_question(
    question_id: int, req: UpdateQuestionRequest, user: dict = Depends(get_current_user)
):
    """编辑题目内容（question, cat1, cat2, tags, difficulty）"""

    def _edit():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT id, question, cat1, cat2, tags, difficulty, owner_id, job_position "
                "FROM question_bank WHERE id = ? AND deleted_at IS NULL",
                (question_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该题目")

            # 权限校验
            is_admin = user.get("is_admin", 0)
            if row["owner_id"] is None and not is_admin:
                raise HTTPException(status_code=403, detail="无权编辑公共题目")
            if (
                row["owner_id"] is not None
                and row["owner_id"] != user["id"]
                and not is_admin
            ):
                raise HTTPException(status_code=403, detail="无权编辑他人的个人题目")

            # 构建更新字段（只更新非 None 的字段）
            updates = {}
            if req.question is not None:
                updates["question"] = req.question
            if req.cat1 is not None:
                updates["cat1"] = req.cat1
            if req.cat2 is not None:
                updates["cat2"] = req.cat2
            if req.tags is not None:
                updates["tags"] = req.tags
            if req.difficulty is not None:
                updates["difficulty"] = req.difficulty

            if not updates:
                return dict(row)

            set_clause = ", ".join(f"{k} = ?" for k in updates)
            values = list(updates.values()) + [question_id]
            # 编辑代表题时标记为手动编辑，防止被自动重新生成覆盖
            if "question" in updates:
                conn.execute(
                    f"UPDATE question_bank SET {set_clause}, question_manually_edited = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    values,
                )
            else:
                conn.execute(
                    f"UPDATE question_bank SET {set_clause}, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    values,
                )

            # 同步 questions_detail
            if "question" in updates:
                conn.execute(
                    "UPDATE questions_detail SET question = ? WHERE question = ?",
                    (updates["question"], row["question"]),
                )

            conn.commit()

            # 返回更新后的数据
            updated = dict(row)
            updated.update(updates)
            return updated

    try:
        result = await run_db(_edit)
        return {"status": "success", "data": result}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("编辑题目失败")
        raise HTTPException(status_code=500, detail="服务器内部错误")
