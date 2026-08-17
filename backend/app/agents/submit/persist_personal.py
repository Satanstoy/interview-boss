import json
import logging

from app.agents.shared.state import SubmitState
from app.agents.shared.events import (
    emit_progress,
    emit_error,
    build_matching_data,
    NodeTimer,
)

logger = logging.getLogger("interview-boss")


async def match_and_persist_personal_node(state: SubmitState) -> dict:
    """个人题库: 匹配 + 写入（跨库匹配：先匹配个人，再匹配公共）"""
    from app.services.clustering import match_new_questions
    from app.db.connection import get_db_connection, run_db, get_current_job_position
    from app.db.operations import submit_interview_txn

    with NodeTimer() as timer:
        data = state.get("extracted_data", {})
        tagged_rows = state.get("tagged_rows", [])
        user_id = state["user_id"]
        current_pos = state.get("job_position") or get_current_job_position()

        # 加载已有个人题库 + 公共 approved 题库
        def _load_existing_bank():
            with get_db_connection() as conn:
                # 个人题
                personal_rows = conn.execute(
                    "SELECT id, question, cat2, sources, original_questions, original_question_sources FROM question_bank WHERE owner_id = ? AND job_position = ? AND deleted_at IS NULL",
                    (user_id, current_pos),
                ).fetchall()
                # 公共题
                public_rows = conn.execute(
                    "SELECT id, question, cat2, sources, original_questions, original_question_sources FROM question_bank WHERE owner_id IS NULL AND status = 'approved' AND deleted_at IS NULL AND (job_position = ? OR job_position = '' OR job_position IS NULL)",
                    (current_pos,),
                ).fetchall()
                return [dict(r) for r in personal_rows], [dict(r) for r in public_rows]

        existing_personal, existing_public = await run_db(_load_existing_bank)

        # 构建个人题 by cat2
        personal_by_cat2 = {}
        for r in existing_personal:
            cat2 = r.get("cat2") or ""
            if cat2 not in personal_by_cat2:
                personal_by_cat2[cat2] = []
            all_qs = [r["question"]]
            try:
                orig = json.loads(r.get("original_questions") or "[]")
                all_qs.extend([q for q in orig if q and q != r["question"]])
            except Exception:
                pass
            personal_by_cat2[cat2].append(
                {
                    "question_bank_id": r["id"],
                    "question": r["question"],
                    "all_questions": all_qs,
                }
            )

        # 构建公共题 by cat2
        public_by_cat2 = {}
        for r in existing_public:
            cat2 = r.get("cat2") or ""
            if cat2 not in public_by_cat2:
                public_by_cat2[cat2] = []
            all_qs = [r["question"]]
            try:
                orig = json.loads(r.get("original_questions") or "[]")
                all_qs.extend([q for q in orig if q and q != r["question"]])
            except Exception:
                pass
            public_by_cat2[cat2].append(
                {
                    "question_bank_id": r["id"],
                    "question": r["question"],
                    "all_questions": all_qs,
                }
            )

        valid_rows = [r for r in tagged_rows if r[3].strip()]
        new_rows_for_match = [
            {
                "id": idx,
                "question": r[3],
                "cat2": r[5] if len(r) > 5 else "",
                "_orig_row": r,
            }
            for idx, r in enumerate(valid_rows)
        ]

        # Phase 1: 匹配个人题库
        personal_match = await match_new_questions(
            new_rows_for_match, personal_by_cat2, user_id=user_id
        )
        personal_matched_ids = {m["new_id"] for m in personal_match["matched"]}

        # Phase 2: 未匹配的再匹配公共题库
        unmatched_for_public = [
            r for r in new_rows_for_match if r["id"] not in personal_matched_ids
        ]
        public_match = {"matched": [], "unmatched": unmatched_for_public}
        if unmatched_for_public and public_by_cat2:
            public_match = await match_new_questions(
                unmatched_for_public, public_by_cat2, user_id=user_id
            )

        # 合并结果：匹配到公共库的题不再写镜像副本
        # （duplicate_of 镜像机制已废除，all 视图可见公共题本身）
        pub_dup_ids = {m["new_id"] for m in public_match["matched"]}
        truly_unmatched = public_match["unmatched"]

        match_result = {
            "matched": personal_match["matched"],  # 匹配个人题的走合并路径
            "unmatched": truly_unmatched,  # 仅真正的新题写入个人库
        }
        idx_to_row = {idx: r for idx, r in enumerate(valid_rows)}

        dup_msg = f"，{len(pub_dup_ids)} 道已收录公共库" if pub_dup_ids else ""
        new_msg = f"{len(truly_unmatched)} 道新题" if truly_unmatched else ""
        combined = (
            "、".join(
                filter(
                    None,
                    [
                        f"{len(personal_match['matched'])} 道已有题目"
                        if personal_match["matched"]
                        else "",
                        new_msg,
                    ],
                )
            )
            or "0 道新题"
        )
        emit_progress(
            state,
            "match",
            f"匹配完成：{combined}{dup_msg}",
            build_matching_data(match_result, timer.elapsed),
        )

        # 写入
        saved_url = state.get("saved_url", "")
        season = state.get("season", "")
        is_admin = state.get("is_admin", False)
        record_owner_id = user_id
        record_status = "approved"

        answer_tasks, interview_id = await run_db(
            lambda: submit_interview_txn(
                saved_url,
                data,
                "\n".join(
                    f"{i + 1}. {q}" for i, q in enumerate(data.get("具体题目清单", []))
                ),
                season,
                record_owner_id,
                record_status,
                current_pos,
                tagged_rows,
                match_result["matched"],
                match_result["unmatched"],
                idx_to_row,
                bool(is_admin),
                user_id,
                qb_owner_id=user_id,
            )
        )

        # 统一入库路径：个人题也入 analysis_queue（owner_id 隔离），
        # 由 cluster_batch 在个人题库范围内做后续聚类/跨面经去重。
        from app.services.pipeline import enqueue_questions

        enqueue_questions(interview_id, owner_id=user_id)

    emit_progress(state, "save", "个人题库写入完成")

    return {
        "match_result": match_result,
        "saved_interview_id": interview_id,
        "answer_tasks": answer_tasks,
        "record_owner_id": record_owner_id,
        "record_status": record_status,
        "node_timings": {
            **state.get("node_timings", {}),
            "match_persist": timer.elapsed,
        },
    }


async def jd_persist_node(state: SubmitState) -> dict:
    """JD 持久化节点：写入 jd 表"""
    from app.db.operations import _insert_jd
    from app.db.connection import run_db

    with NodeTimer() as timer:
        data = state.get("extracted_data", {})
        saved_url = state.get("saved_url", "")
        season = state.get("season", "")
        user_id = state["user_id"]
        is_admin = state.get("is_admin", False)
        target = state.get("target", "personal")
        job_position = state.get("job_position", "")

        record_owner_id = user_id if target == "personal" else None
        record_status = "approved" if (is_admin or target == "personal") else "pending"

        tech_list = data.get("核心技术要求", [])
        tech_stack = (
            "\n".join(f"{i + 1}. {item}" for i, item in enumerate(tech_list))
            if tech_list
            else "未提供"
        )

        await run_db(
            lambda: _insert_jd(
                saved_url,
                data,
                tech_stack,
                season,
                owner_id=record_owner_id,
                status=record_status,
                job_position=job_position,
            )
        )

    emit_progress(state, "save", "JD 保存完成")
    return {
        "node_timings": {**state.get("node_timings", {}), "jd_persist": timer.elapsed},
    }


async def error_empty_node(state: SubmitState) -> dict:
    """空题错误节点：提取重试后仍无题目"""
    emit_error(state, "大模型未能从内容中提取到面试题目")
    return {
        "error": "大模型未能从内容中提取到面试题目",
    }
