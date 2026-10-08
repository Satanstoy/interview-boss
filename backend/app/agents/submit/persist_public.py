import logging

from app.agents.shared.state import SubmitState
from app.agents.shared.events import emit_progress, NodeTimer

logger = logging.getLogger("interview-boss")


async def persist_public_node(state: SubmitState) -> dict:
    """公共题库: 写入 interview + questions_detail + 入队"""
    from app.db.operations import submit_interview_txn_tag_only
    from app.db.connection import run_db, get_current_job_position

    with NodeTimer() as timer:
        data = state.get("extracted_data", {})
        tagged_rows = state.get("tagged_rows", [])
        current_pos = state.get("job_position") or get_current_job_position()
        saved_url = state.get("saved_url", "")
        season = state.get("season", "")
        is_admin = state.get("is_admin", False)
        import_id = state.get("import_id")
        if not is_admin:
            raise PermissionError("普通用户的公共化必须先创建审核申请")
        if import_id and not state.get("user_id"):
            raise PermissionError("上传根任务的公共导入缺少管理员主体")
        audited_admin_import = bool(is_admin and import_id)
        record_owner_id = None
        record_status = "approved" if is_admin else "pending"

        questions = "\n".join(
            f"{i + 1}. {q}" for i, q in enumerate(data.get("具体题目清单", []))
        )
        source_ordinals = data.get("题目 ordinal") or None
        # Direct administrator publication is still an explicit reviewed
        # projection. Until a field is separately confirmed, identifiable
        # source metadata must not leak through the public interview/detail.
        public_data = dict(data)
        public_rows = tagged_rows
        source_snapshot = None
        if audited_admin_import:
            public_data["公司"] = ""
            public_data["面试轮次"] = ""
            public_rows = [["", "", "", *row[3:]] for row in tagged_rows]
            source_snapshot = {
                "source": {
                    "company": data.get("公司"),
                    "round": data.get("面试轮次"),
                    "focus": data.get("考察重点"),
                    "difficulty": data.get("难易程度"),
                    "season": season,
                    "source_url": saved_url,
                    "job_position": current_pos,
                },
                "items": [
                    {
                        "question": row[3],
                        "cat1": row[4],
                        "cat2": row[5],
                        "tags": row[6],
                        "difficulty": row[7],
                        "source_ordinal": (
                            int(source_ordinals[index])
                            if source_ordinals is not None and index < len(source_ordinals)
                            else index + 1
                        ),
                    }
                    for index, row in enumerate(tagged_rows)
                ],
            }
        interview_id, _detail_ids = await run_db(
            lambda: submit_interview_txn_tag_only(
                "" if audited_admin_import else saved_url,
                public_data,
                questions,
                season,
                record_owner_id,
                record_status,
                current_pos,
                public_rows,
                import_id=import_id,
                job_id=state.get("job_id"),
                lease_generation=state.get("_lease_generation"),
                input_version=state.get("_input_version"),
                source_ordinals=source_ordinals,
                enqueue=True,
                return_detail_ids=True,
                admin_public_import_actor_id=(
                    int(state["user_id"]) if audited_admin_import else None
                ),
                admin_public_source_snapshot=source_snapshot,
            )
        )

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
        schedule_kwargs = {"user_id": state.get("user_id")}
        if state.get("import_id"):
            schedule_kwargs["root_import_id"] = str(state["import_id"])
        scheduled = await _run_cluster_batch_in_background(**schedule_kwargs)

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
