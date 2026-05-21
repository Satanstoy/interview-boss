import logging
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from app.core.auth import get_current_user, get_admin_user
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")
router = APIRouter(prefix="/api/master-bank")


@router.get("/analysis-status")
async def analysis_status(user: dict = Depends(get_admin_user)):
    """检查面经分析完整性：返回已分析和未分析的面经数量及详情。"""
    def _check():
        with get_db_connection() as conn:
            # 已分析：有 detail 记录的面经
            analyzed = conn.execute(
                "SELECT i.id, i.company, i.round FROM interview i "
                "WHERE i.deleted_at IS NULL AND EXISTS (SELECT 1 FROM questions_detail qd WHERE qd.url = i.url)"
            ).fetchall()
            # 未分析：没有 detail 记录的面经
            unanalyzed = conn.execute(
                "SELECT i.id, i.company, i.round, LENGTH(i.questions_list) as ql_len FROM interview i "
                "WHERE i.deleted_at IS NULL AND NOT EXISTS (SELECT 1 FROM questions_detail qd WHERE qd.url = i.url)"
            ).fetchall()
            return {
                "analyzed_count": len(analyzed),
                "unanalyzed_count": len(unanalyzed),
                "unanalyzed": [{"id": r['id'], "company": r['company'], "round": r['round'], "has_content": (r['ql_len'] or 0) > 10} for r in unanalyzed]
            }
    return await run_db(_check)


@router.get("/pending")
async def get_pending_questions(admin: dict = Depends(get_admin_user)):
    """获取待审核题目列表"""
    def _query():
        with get_db_connection() as conn:
            rows = conn.execute(
                "SELECT qb.id, qb.question, qb.cat1, qb.cat2, qb.tags, qb.difficulty, qb.created_at, u.username as submitted_by_name "
                "FROM question_bank qb LEFT JOIN users u ON qb.submitted_by = u.id "
                "WHERE qb.owner_id IS NULL AND qb.status = 'pending' ORDER BY qb.created_at DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    items = await run_db(_query)
    return {"items": items, "total": len(items)}


@router.post("/approve/{question_id}")
async def approve_question(question_id: int, admin: dict = Depends(get_admin_user), bg_tasks: BackgroundTasks = None):
    """审核通过题目"""
    def _approve():
        with get_db_connection() as conn:
            row = conn.execute("SELECT id, status, cat2, job_position FROM question_bank WHERE id = ? AND owner_id IS NULL", (question_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该待审核题目")
            conn.execute("UPDATE question_bank SET status = 'approved', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (question_id,))
            conn.commit()
            return dict(row)

    question = await run_db(_approve)
    # 异步反向扫描：标记个人题库中的语义重复
    if bg_tasks and question.get('cat2'):
        from app.services.clustering import scan_personal_duplicates
        bg_tasks.add_task(scan_personal_duplicates, question_id, question['cat2'], question.get('job_position', ''))
    return {"status": "success", "message": "已通过审核"}


@router.post("/reject/{question_id}")
async def reject_question(question_id: int, admin: dict = Depends(get_admin_user)):
    """拒绝题目"""
    def _reject():
        with get_db_connection() as conn:
            row = conn.execute("SELECT id, status FROM question_bank WHERE id = ? AND owner_id IS NULL", (question_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="未找到该待审核题目")
            conn.execute("UPDATE question_bank SET status = 'rejected', updated_at = CURRENT_TIMESTAMP WHERE id = ?", (question_id,))
            conn.commit()

    await run_db(_reject)
    return {"status": "success", "message": "已拒绝"}
