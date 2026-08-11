"""聚合质量审查清单 API（管理员）：清单查询 / 审批 / 批量审批。

清单数据固化在 quality_issue 表（审查生成，永不删除），管理员审批后
执行对应操作（split/dedupe/refine_representative），状态流转留痕。

业务逻辑（序列化/执行/单条批量审批）在 `app.services.quality_issue_ops`，
本路由仅做 HTTP 感知。
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.concurrency import run_in_threadpool

from app.core.auth import get_admin_user
from app.db.connection import get_db_connection, run_db
from app.services.quality_issue_ops import (
    approve_issue as approve_quality_issue,
    batch_approve as batch_approve_quality_issues,
    reject_issue as reject_quality_issue,
    serialize_issue,
)

logger = logging.getLogger("interview-boss")

router = APIRouter(prefix="/api/admin/quality-issues", tags=["admin-quality"])


@router.post("/generate-all")
async def generate_all_quality_issues(
    mismerge_limit: int = Query(1000, ge=1, le=5000),
    singleton_limit: int = Query(1000, ge=1, le=5000),
    candidate_limit: int = Query(3, ge=1, le=10),
    similarity_threshold: float = Query(0.30, ge=0, le=1),
    admin: dict = Depends(get_admin_user),
):
    """创建全量 AI 聚合质量扫描任务。

    任务由持久化 jobs + ARQ 执行，扫描误合并与漏合并后只写入 pending
    审查清单，不直接修改题库。已有运行中的全量扫描会幂等复用。
    """
    from app.services.job_lifecycle import (
        create_quality_review_scan_job,
        mark_job_dispatched,
    )

    def _create():
        with get_db_connection() as conn:
            # Serialize the active-job check with the insert so two admins
            # clicking the trigger concurrently cannot create two scans.
            conn.execute("BEGIN IMMEDIATE")
            try:
                result = create_quality_review_scan_job(
                    conn,
                    user_id=admin["id"],
                    mismerge_limit=mismerge_limit,
                    singleton_limit=singleton_limit,
                    candidate_limit=candidate_limit,
                    similarity_threshold=similarity_threshold,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    job_id, status, reused = await run_db(_create)
    if reused or status != "pending":
        return {
            "job_id": job_id,
            "status": status,
            "reused": reused,
            "message": "已有聚合质量扫描正在执行",
        }

    dispatch_error = None
    try:
        from app.worker import enqueue_quality_review_scan_job

        arq_job = await enqueue_quality_review_scan_job(job_id)
        arq_job_id = getattr(arq_job, "job_id", None)
        if not arq_job_id:
            raise RuntimeError("ARQ 未返回 job_id")

        def _mark():
            with get_db_connection() as conn:
                if not mark_job_dispatched(conn, job_id, str(arq_job_id)):
                    raise RuntimeError(f"聚合质量扫描任务不可再投递: job_id={job_id}")
                conn.commit()

        await run_db(_mark)
        status = "queued"
    except Exception as exc:
        dispatch_error = str(exc)[:300]
        logger.warning("聚合质量扫描 ARQ 调度失败，保留 pending 等待 dispatcher: %s", exc)

    return {
        "job_id": job_id,
        "status": status,
        "reused": False,
        "dispatch_error": dispatch_error,
        "message": (
            "误合并与漏合并 AI 扫描已进入后台"
            if status == "queued"
            else "扫描任务已创建，等待后台 worker 调度"
        ),
    }


@router.post("/generate-unmerged")
async def generate_unmerged_issues(
    limit: int = Query(200, ge=1, le=1000),
    candidate_limit: int = Query(3, ge=1, le=10),
    similarity_threshold: float = Query(0.30, ge=0, le=1),
    admin: dict = Depends(get_admin_user),
):
    """扫描公共孤岛题，将 LLM 判定应合并的候选放入 pending 清单。

    该端点只生成 `quality_issue`，不直接修改题库；管理员仍需在清单中审批。
    """
    from app.services.unmerged_quality import generate_unmerged_quality_issues

    return await generate_unmerged_quality_issues(
        user_id=admin["id"],
        limit=limit,
        candidate_limit=candidate_limit,
        similarity_threshold=similarity_threshold,
    )


@router.get("")
async def list_issues(
    status: str = Query(
        "pending", pattern="^(pending|approved|rejected|done|superseded)$"
    ),
    admin: dict = Depends(get_admin_user),
):
    """查询审查清单（默认 pending 待审批；done/rejected 历史审计）"""

    def _query():
        conn = get_db_connection()
        rows = conn.execute(
            "SELECT * FROM quality_issue WHERE status = ? ORDER BY confidence DESC, id",
            (status,),
        ).fetchall()
        return [serialize_issue(r, conn) for r in rows]

    return await run_in_threadpool(_query)


@router.post("/{issue_id}/approve")
async def approve_issue(
    issue_id: int,
    admin: dict = Depends(get_admin_user),
):
    """批准 issue：执行对应操作，状态 pending → done（记录审批人）"""

    def _approve():
        conn = get_db_connection()
        return approve_quality_issue(conn, admin["id"], issue_id)

    return await run_in_threadpool(_approve)


@router.post("/{issue_id}/reject")
async def reject_issue(
    issue_id: int,
    admin: dict = Depends(get_admin_user),
):
    """拒绝 issue：记录拒绝（保留为负样本），不执行操作"""

    def _reject():
        conn = get_db_connection()
        result = reject_quality_issue(conn, admin["id"], issue_id)
        conn.commit()
        return result

    return await run_in_threadpool(_reject)


@router.post("/batch-approve")
async def batch_approve_issues(
    body: dict,
    admin: dict = Depends(get_admin_user),
):
    """批量批准高置信 issue（>0.85）：逐个执行，失败的跳过并返回结果。"""
    issue_ids = body.get("issue_ids", [])
    min_confidence = float(body.get("min_confidence", 0.85))
    if not isinstance(issue_ids, list) or not issue_ids:
        raise HTTPException(status_code=400, detail="issue_ids 不能为空")

    def _batch():
        conn = get_db_connection()
        return batch_approve_quality_issues(
            conn, admin["id"], issue_ids, min_confidence=min_confidence
        )

    return await run_in_threadpool(_batch)
