import logging
import time

from app.agents.shared.state import SubmitState
from app.agents.shared.events import emit_progress, NodeTimer

logger = logging.getLogger("interview-boss")


async def persist_public_node(state: SubmitState) -> dict:
    """公共题库: 写入 interview + questions_detail + 入队"""
    from app.db.operations import submit_interview_txn_tag_only
    from app.db.connection import run_db, get_current_job_position
    from app.services.pipeline import enqueue_questions

    with NodeTimer() as timer:
        data = state.get("extracted_data", {})
        tagged_rows = state.get("tagged_rows", [])
        current_pos = state.get("job_position") or get_current_job_position()
        saved_url = state.get("saved_url", "")
        season = state.get("season", "")
        is_admin = state.get("is_admin", False)
        user_id = state["user_id"]
        record_owner_id = None
        record_status = 'approved' if is_admin else 'pending'

        questions = "\n".join(f"{i+1}. {q}" for i, q in enumerate(data.get("具体题目清单", [])))
        interview_id = await run_db(lambda: submit_interview_txn_tag_only(
            saved_url, data, questions, season, record_owner_id, record_status, current_pos, tagged_rows
        ))
        enqueue_questions(interview_id)

    emit_progress(state, "match", "已保存面经并加入聚类队列")
    return {
        "saved_interview_id": interview_id,
        "record_owner_id": record_owner_id,
        "record_status": record_status,
        "node_timings": {**state.get("node_timings", {}), "persist_public": timer.elapsed},
    }


async def cluster_public_node(state: SubmitState) -> dict:
    """公共题库: 同步完成聚类（必须聚类成功才算提交完成）"""
    from app.services.pipeline import dequeue_batch, cluster_batch, mark_batch_done, mark_batch_failed

    with NodeTimer() as timer:
        new_count = 0
        batch = dequeue_batch()
        if batch:
            try:
                new_count = await cluster_batch(batch, user_id=state["user_id"])
                queue_ids = [item['queue_id'] for item in batch]
                mark_batch_done(queue_ids)
            except Exception as e:
                logger.error(f"聚类失败，回退队列状态: {e}")
                queue_ids = [item['queue_id'] for item in batch]
                mark_batch_failed(queue_ids)
                return {
                    "error": f"聚类失败: {str(e)[:100]}",
                    "node_timings": {**state.get("node_timings", {}), "cluster": timer.elapsed},
                }

    emit_progress(state, "save", f"聚类完成，新增 {new_count} 个聚类" if new_count else "聚类完成，无新增聚类")
    return {
        "cluster_result": {"new_qb_count": new_count},
        "node_timings": {**state.get("node_timings", {}), "cluster": timer.elapsed},
    }
