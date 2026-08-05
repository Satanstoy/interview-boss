"""分享链路：私有题 → 公共 pending（确定性查重，命中则合并删副本）"""

import json
import logging
import re

from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_user
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")

router = APIRouter()


def _normalize_question_text(text: str) -> str:
    """确定性查重用的轻量归一化：去标点/空白/大小写。"""
    if not text:
        return ""
    return re.sub(r"[\W_]+", "", (text or "").strip().lower())


def find_matching_public_question(
    conn, question: str, cat2: str, job_position: str = None
) -> int | None:
    """确定性查重：归一化文本精确匹配同岗位的公共 approved 题。

    返回匹配的 question_bank.id，无匹配返回 None。
    只做确定性匹配（不调 LLM）；审核时 LLM 匹配兜底。
    """
    normalized = _normalize_question_text(question)
    if not normalized:
        return None
    rows = conn.execute(
        "SELECT id, question FROM question_bank "
        "WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL "
        "AND (job_position = ? OR job_position = '' OR job_position IS NULL)",
        (job_position or "",),
    ).fetchall()
    for r in rows:
        if _normalize_question_text(r["question"]) == normalized:
            return r["id"]
    return None


def _merge_private_into_public(conn, public_id: int, private_row) -> None:
    """把私有题合并进公共题：sources 去重追加、original_questions 合并、frequency 更新、软删私有副本。"""
    public = conn.execute(
        "SELECT sources, original_questions, original_question_sources, ai_answer, frequency "
        "FROM question_bank WHERE id = ?",
        (public_id,),
    ).fetchone()
    if not public:
        return

    def _loads(val):
        try:
            parsed = json.loads(val or "[]")
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []

    p_src = _loads(public["sources"])
    p_oqs = _loads(public["original_questions"])
    p_oqs_src = _loads(public["original_question_sources"])

    # sources 去重追加（URL 维度）
    seen_urls = {s.get("url") for s in p_src if isinstance(s, dict)}
    for s in _loads(private_row["sources"]):
        if isinstance(s, dict) and s.get("url") and s["url"] not in seen_urls:
            p_src.append(s)
            seen_urls.add(s["url"])

    # original_questions 合并
    for oq in _loads(private_row["original_questions"]):
        if oq and oq not in p_oqs:
            p_oqs.append(oq)
    if private_row["question"] not in p_oqs:
        p_oqs.append(private_row["question"])

    # original_question_sources 合并
    for item in _loads(private_row["original_question_sources"]):
        if isinstance(item, dict) and item not in p_oqs_src:
            p_oqs_src.append(item)

    conn.execute(
        "UPDATE question_bank SET sources = ?, original_questions = ?, "
        "original_question_sources = ?, frequency = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (
            json.dumps(p_src, ensure_ascii=False),
            json.dumps(p_oqs, ensure_ascii=False),
            json.dumps(p_oqs_src, ensure_ascii=False),
            len(p_oqs),
            public_id,
        ),
    )
    conn.execute(
        "UPDATE question_bank SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (private_row["id"],),
    )


def share_private_question(conn, question_id: int, user_id: int) -> dict:
    """私有题分享到公共题库。

    - 仅本人私有题可分享
    - 确定性查重命中公共题 → 合并删副本（result=merged）
    - 未命中 → 创建公共 pending（submitted_by=me），私有副本保留（result=pending）
    """
    row = conn.execute(
        "SELECT * FROM question_bank WHERE id = ? AND deleted_at IS NULL",
        (question_id,),
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="题目不存在")
    if row["owner_id"] is None:
        raise HTTPException(status_code=400, detail="公共题目无需分享")
    if row["owner_id"] != user_id:
        raise HTTPException(status_code=403, detail="无权分享他人的私有题目")

    match_id = find_matching_public_question(
        conn, row["question"], row["cat2"], row["job_position"]
    )
    if match_id:
        _merge_private_into_public(conn, match_id, row)
        conn.commit()
        logger.info("分享命中公共题 %s，合并并删除私有副本 %s", match_id, question_id)
        return {"result": "merged", "target_id": match_id}

    cur = conn.execute(
        "INSERT INTO question_bank "
        "(question, cat1, cat2, tags, difficulty, frequency, sources, "
        "original_questions, original_question_sources, ai_answer, answer_sources, owner_id, "
        "submitted_by, status, job_position) "
        "VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, NULL, ?, 'pending', ?)",
        (
            row["question"],
            row["cat1"],
            row["cat2"],
            row["tags"],
            row["difficulty"],
            row["sources"],
            row["original_questions"],
            row["original_question_sources"],
            row["ai_answer"],
            row["answer_sources"],
            user_id,
            row["job_position"],
        ),
    )
    conn.commit()
    logger.info(
        "分享未命中，创建公共 pending 题 %s（贡献者 %s）", cur.lastrowid, user_id
    )
    return {"result": "pending", "pending_id": cur.lastrowid}


def get_pending_mine(conn, user_id: int) -> list:
    """我的待审核贡献：公共 pending 且 submitted_by=me。"""
    rows = conn.execute(
        "SELECT id, question, cat1, cat2, tags, difficulty, created_at "
        "FROM question_bank "
        "WHERE owner_id IS NULL AND status = 'pending' AND submitted_by = ? "
        "AND deleted_at IS NULL ORDER BY created_at DESC",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]


@router.post("/api/master-bank/{question_id}/share")
async def share_question(question_id: int, user: dict = Depends(get_current_user)):
    """分享私有题到公共题库（命中则合并，未命中进审核队列）"""

    def _share():
        with get_db_connection() as conn:
            return share_private_question(conn, question_id, user["id"])

    result = await run_db(_share)
    return result


@router.get("/api/master-bank/pending/mine")
async def pending_mine(user: dict = Depends(get_current_user)):
    """我的待审核贡献列表"""

    def _query():
        with get_db_connection() as conn:
            return get_pending_mine(conn, user["id"])

    items = await run_db(_query)
    return {"items": items, "total": len(items)}
