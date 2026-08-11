"""分享链路：私有题 → 公共 pending（确定性查重，命中则合并删副本）"""

import json
import logging
import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from app.core.auth import get_current_user
from app.db.connection import get_db_connection, run_db
from app.services.question_bank_integrity import (
    canonicalize_question_bank_payload,
    claim_public_original_questions,
    sync_question_bank_projections,
)

logger = logging.getLogger("interview-boss")

router = APIRouter()


def _normalize_question_text(text: str) -> str:
    """确定性查重用的轻量归一化：去标点/空白/大小写。"""
    if not text:
        return ""
    return re.sub(r"[\W_]+", "", (text or "").strip().lower())


def _loads(value):
    try:
        parsed = json.loads(value or "[]")
        return parsed if isinstance(parsed, list) else []
    except (TypeError, ValueError):
        return []


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
    try:
        rows = conn.execute(
            "SELECT id, question, original_questions FROM question_bank "
            "WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL "
            "AND (job_position = ? OR job_position = '' OR job_position IS NULL)",
            (job_position or "",),
        ).fetchall()
    except sqlite3.OperationalError:
        # Lightweight callers may expose only the representative question.
        rows = conn.execute(
            "SELECT id, question FROM question_bank "
            "WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL "
            "AND (job_position = ? OR job_position = '' OR job_position IS NULL)",
            (job_position or "",),
        ).fetchall()
    for r in rows:
        candidates = [r["question"]]
        try:
            candidates.extend(json.loads(r["original_questions"] or "[]"))
        except (IndexError, KeyError, TypeError, ValueError):
            pass
        if any(_normalize_question_text(candidate) == normalized for candidate in candidates):
            return r["id"]
    return None


def _merge_private_into_public(conn, public_id: int, private_row) -> None:
    """把私有题合并进公共题：sources 去重追加、original_questions 合并、frequency 更新、软删私有副本。"""
    public = conn.execute(
        "SELECT sources, original_questions, original_question_sources, ai_answer, frequency, owner_id, status "
        "FROM question_bank WHERE id = ?",
        (public_id,),
    ).fetchone()
    if not public:
        return

    p_src = _loads(public["sources"])
    p_oqs = _loads(public["original_questions"])
    p_oqs_src = _loads(public["original_question_sources"])
    private_src = _loads(private_row["sources"])
    private_oqs = _loads(private_row["original_questions"])
    private_oqs_src = _loads(private_row["original_question_sources"])
    if private_row["question"] and not private_oqs:
        private_oqs = [private_row["question"]]
    if private_row["question"] and not any(
        isinstance(item, dict) and item.get("question") == private_row["question"]
        for item in private_oqs_src
    ):
        private_oqs_src.append(
            {"question": private_row["question"], "sources": private_src}
        )

    p_src.extend(private_src)
    p_oqs.extend(private_oqs)
    p_oqs_src.extend(private_oqs_src)
    p_src, p_oqs, p_oqs_src = canonicalize_question_bank_payload(
        p_src, p_oqs, p_oqs_src
    )

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
    claim_public_original_questions(
        conn, public_id, public["owner_id"], public["status"], p_oqs
    )
    sync_question_bank_projections(
        conn.cursor(), public_id, p_src, p_oqs, p_oqs_src
    )
    conn.execute(
        "UPDATE question_bank SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (private_row["id"],),
    )
    sync_question_bank_projections(
        conn.cursor(), private_row["id"], [], [], []
    )
    from app.services.cluster_review_lifecycle import mark_cluster_review_pending

    mark_cluster_review_pending(conn, public_id, "private_question_merged")


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

    private_sources = _loads(row["sources"])
    private_questions = _loads(row["original_questions"])
    private_question_sources = _loads(row["original_question_sources"])
    if row["question"] and not private_questions:
        private_questions = [row["question"]]
    if row["question"] and not any(
        isinstance(item, dict) and item.get("question") == row["question"]
        for item in private_question_sources
    ):
        private_question_sources.append(
            {"question": row["question"], "sources": private_sources}
        )
    private_sources, private_questions, private_question_sources = (
        canonicalize_question_bank_payload(
            private_sources, private_questions, private_question_sources
        )
    )
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
            json.dumps(private_sources, ensure_ascii=False),
            json.dumps(private_questions, ensure_ascii=False),
            json.dumps(private_question_sources, ensure_ascii=False),
            row["ai_answer"],
            row["answer_sources"],
            user_id,
            row["job_position"],
        ),
    )
    sync_question_bank_projections(
        conn.cursor(),
        cur.lastrowid,
        private_sources,
        private_questions,
        private_question_sources,
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
