import re
import json
import logging
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from app.core.auth import get_current_user, get_admin_user
from app.db.connection import get_db_connection, run_db
from app.db.operations import _cleanup_old_sources, _replace_details
from app.routers.submit import tag_questions_batch, incremental_update_master_bank

logger = logging.getLogger("interview-boss")

router = APIRouter()


@router.post("/api/interview/{interview_id}/re-process")
async def reprocess_interview(interview_id: int, bg_tasks: BackgroundTasks, user: dict = Depends(get_admin_user)):
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
    q_list = []
    for line in raw_lines:
        clean_q = re.sub(r'^\d+[\.\)\]、-]\s*', '', line).strip()
        if clean_q:
            q_list.append(clean_q)

    if not q_list:
        raise HTTPException(status_code=400, detail="解析题目清单失败，未能提取到有效题目")

    try:
        url = row['url'] or f"internal://{row['id']}"
        company = row['company'] or "未提供"
        round_ = row['round'] or "未提供"

        # 先清理 master_bank 中该面经的旧来源（与 delete_data 逻辑一致）
        await run_db(lambda: _cleanup_old_sources(url))

        tagged_rows = await tag_questions_batch(url, company, round_, q_list)

        await run_db(lambda: _replace_details(url, tagged_rows))
        original_owner_id = row['owner_id']
        await incremental_update_master_bank(
            tagged_rows, bg_tasks,
            submitter_is_admin=True,
            user_id=original_owner_id,
            is_personal=(original_owner_id is not None)
        )

        return {
            "status": "success",
            "message": f"成功重新分析了 {len(q_list)} 道题目，并已加入精炼题库！",
            "extracted_count": len(q_list)
        }

    except Exception as e:
        logger.exception("重新分析失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")
