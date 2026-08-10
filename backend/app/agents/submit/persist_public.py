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
        record_status = "approved" if is_admin else "pending"

        questions = "\n".join(
            f"{i + 1}. {q}" for i, q in enumerate(data.get("具体题目清单", []))
        )
        interview_id = await run_db(
            lambda: submit_interview_txn_tag_only(
                saved_url,
                data,
                questions,
                season,
                record_owner_id,
                record_status,
                current_pos,
                tagged_rows,
            )
        )
        enqueue_questions(interview_id)

    emit_progress(state, "match", "已保存面经并加入聚类队列")
    return {
        "saved_interview_id": interview_id,
        "record_owner_id": record_owner_id,
        "record_status": record_status,
        "node_timings": {
            **state.get("node_timings", {}),
            "persist_public": timer.elapsed,
        },
    }


async def cluster_public_node(state: SubmitState) -> dict:
    """公共题库: 聚类异步化（实验结论 P3）。

    不再同步 await cluster_batch（曾使单次导入等待 30-90s）；改为调度后台
    攒批任务（pending ≥ BATCH_SIZE 立即聚，否则延迟 CLUSTER_DELAY_SECONDS
    合并连续导入）。SSE 到 save 阶段即完成，聚类结果稍后出现。
    """
    from app.services.pipeline.queue import _run_cluster_batch_in_background

    with NodeTimer() as timer:
        scheduled = await _run_cluster_batch_in_background(user_id=state.get("user_id"))

    emit_progress(
        state,
        "save",
        "题目已保存，聚类后台进行中"
        if scheduled
        else "题目已保存（聚类队列已有任务在跑）",
    )
    return {
        "cluster_result": {"new_qb_count": 0, "scheduled": scheduled},
        "node_timings": {**state.get("node_timings", {}), "cluster": timer.elapsed},
    }
