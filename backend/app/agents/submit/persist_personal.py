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
    from app.services.clustering import match_outcomes
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

        # Phase 1: 匹配个人题库（AC-006 三态：matched / no_match / failed——模型失败归
        # failed 绝不当作 no_match 去新建规范题）
        personal_outcomes = await match_outcomes(
            new_rows_for_match,
            personal_by_cat2,
            user_id=user_id,
            strict=True,
            llm_scope=state.get("credential_scope", "user"),
        )
        personal_results = personal_outcomes.get("results", [])
        personal_matched = [
            r for r in personal_results if r["outcome"] == "matched"
        ]
        personal_no_match = [
            r for r in personal_results if r["outcome"] == "no_match"
        ]
        personal_failed = [r for r in personal_results if r["outcome"] == "failed"]
        personal_matched_ids = {
            int(m["new_id"]) for m in personal_matched
        }
        personal_no_match_ids = {int(m["new_id"]) for m in personal_no_match}
        personal_failed_ids = {int(m["new_id"]) for m in personal_failed}

        # Phase 2: no_match 的再匹配公共题库（failed 不重试公共库，避免重复消耗预算）
        unmatched_for_public = [
            r
            for r in new_rows_for_match
            if r["id"] in personal_no_match_ids
        ]
        public_results = []
        public_failed_ids: set[int] = set()
        if unmatched_for_public and public_by_cat2:
            public_outcomes = await match_outcomes(
                unmatched_for_public,
                public_by_cat2,
                user_id=user_id,
                strict=True,
                llm_scope=state.get("credential_scope", "user"),
            )
            public_results = public_outcomes.get("results", [])
        public_failed_ids = {
            int(m["new_id"]) for m in public_results if m["outcome"] == "failed"
        }
        public_matched = [m for m in public_results if m["outcome"] == "matched"]
        public_no_match = [m for m in public_results if m["outcome"] == "no_match"]

        # 合并结果：匹配到公共库的题不再写镜像副本
        # （duplicate_of 镜像机制已废除，all 视图可见公共题本身）
        pub_dup_ids = {int(m["new_id"]) for m in public_matched}
        truly_unmatched = public_no_match  # 仅真正的新题写入个人库
        # failed 集合：两阶段模型失败的题（不得进聚类队列/不得建 canonical）
        failed_outcome_ids = personal_failed_ids | public_failed_ids

        match_result = {
            "matched": personal_matched,  # 匹配个人题的走合并路径
            "unmatched": truly_unmatched,  # 仅真正的新题写入个人库
            "failed": personal_failed + [
                m for m in public_results if m["outcome"] == "failed"
            ],
        }
        match_failed_count = len(failed_outcome_ids)
        idx_to_row = {idx: r for idx, r in enumerate(valid_rows)}

        dup_msg = f"，{len(pub_dup_ids)} 道已收录公共库" if pub_dup_ids else ""
        new_msg = f"{len(truly_unmatched)} 道新题" if truly_unmatched else ""
        combined = (
            "、".join(
                filter(
                    None,
                    [
                        f"{len(personal_matched)} 道已有题目"
                        if personal_matched
                        else "",
                        new_msg,
                        f"{match_failed_count} 道匹配失败待恢复"
                        if match_failed_count
                        else "",
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

        # 写入（F08：import_id 已有关联时幂等复用——恢复执行不重复建面经/明细）
        saved_url = state.get("saved_url", "")
        season = state.get("season", "")
        is_admin = state.get("is_admin", False)
        record_owner_id = user_id
        record_status = "approved"

        import_id = state.get("import_id")

        # match_outcomes 返回 canonical_id；旧事务写入器消费 question_bank_id。
        # 在节点边界适配两种 DTO，避免命中已有规范题时入库失败。
        matched_for_persist = []
        for outcome in match_result["matched"]:
            question_bank_id = outcome.get("question_bank_id")
            if question_bank_id is None:
                question_bank_id = outcome.get("canonical_id")
            if question_bank_id is None:
                raise ValueError("匹配结果缺少规范题 ID")
            matched_for_persist.append(
                {**outcome, "question_bank_id": int(question_bank_id)}
            )

        def _persist_new():
            return run_db(
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
                    matched_for_persist,
                    match_result["unmatched"],
                    idx_to_row,
                    bool(is_admin),
                    user_id,
                    qb_owner_id=user_id,
                    persist_unmatched=False,
                )
            )

        if import_id:
            def _find_existing_linked():
                with get_db_connection() as conn:
                    rows = conn.execute(
                        "SELECT interview_id, id FROM questions_detail "
                        "WHERE import_id = ? AND deleted_at IS NULL "
                        "ORDER BY source_ordinal",
                        (import_id,),
                    ).fetchall()
                    if not rows:
                        return None
                    return {
                        "interview_id": int(rows[0]["interview_id"]),
                        "detail_ids": [int(r["id"]) for r in rows],
                    }

            existing_linked = await run_db(_find_existing_linked)
            if existing_linked is not None:
                # F08：该 import 已落库（前次 attempt 成功），恢复执行幂等复用
                interview_id = existing_linked["interview_id"]
                detail_ids = existing_linked["detail_ids"]
                answer_tasks = []
                match_result = {"matched": [], "unmatched": []}
            else:
                answer_tasks, interview_id, detail_ids = await _persist_new()
        else:
            answer_tasks, interview_id, detail_ids = await _persist_new()

        # 只有真正未匹配的个人题进入个人聚类队列。命中公共题的题目仍保留
        # 在个人面经的 questions_detail 中，但不复制成个人题，也不再次聚类。
        from app.services.pipeline import enqueue_questions

        excluded_ids = personal_matched_ids | pub_dup_ids | failed_outcome_ids
        queue_detail_ids = []
        valid_index = 0
        for row, detail_id in zip(tagged_rows, detail_ids):
            if not row[3].strip():
                continue
            if valid_index not in excluded_ids:
                queue_detail_ids.append(detail_id)
            valid_index += 1
        enqueue_questions(
            interview_id,
            owner_id=user_id,
            question_detail_ids=queue_detail_ids,
            root_import_id=state.get("import_id"),
        )

        # R05：v2 root 上下文存在时，为逐题明细写 import_id/source_ordinal
        # 并登记 resolution（匹配失败持久化为 failed，不落 phantom canonical）。
        import_id = state.get("import_id")
        if import_id:
            from app.services.upload_resolution_link import (
                link_details_to_import,
            )

            matches: dict[int, dict | None] = {}
            matched_new_ids = {
                int(m["new_id"])
                for m in list(personal_matched) + list(public_matched)
            }
            # 匹配结果的 new_id 是“非空行序号”；与 submit_interview_txn 的
            # valid_index 语义一致，逐行映射回 detail_id。
            valid_index = 0
            detail_new_id_map: dict[int, int] = {}
            for detail_id, row in zip(detail_ids, tagged_rows):
                if not row[3].strip():
                    continue
                detail_new_id_map[int(detail_id)] = valid_index
                valid_index += 1

            for detail_id, new_id in detail_new_id_map.items():
                if new_id in matched_new_ids:
                    canonical_id = next(
                        (
                            int(m["canonical_id"]) or int(m["question_bank_id"])
                            for m in list(personal_matched) + list(public_matched)
                            if int(m["new_id"]) == new_id
                        ),
                        None,
                    )
                    if canonical_id:
                        canonical_scope = (
                            "private"
                            if any(
                                int(m["new_id"]) == new_id
                                for m in personal_matched
                            )
                            else "public"
                        )
                        matches[detail_id] = {
                            "canonical_id": canonical_id,
                            "canonical_scope": canonical_scope,
                            "status": "matched",
                        }
                    else:
                        matches[detail_id] = None
                elif new_id in failed_outcome_ids:
                    # AC-006：模型失败 → resolution 记 failed（可恢复失败），
                    # 由 link 持久化，不产生 phantom canonical。
                    error_code = next(
                        (
                            m.get("error_code", "UPSTREAM_UNAVAILABLE")
                            for m in match_result["failed"]
                            if int(m["new_id"]) == new_id
                        ),
                        "UPSTREAM_UNAVAILABLE",
                    )
                    matches[detail_id] = {
                        "status": "failed",
                        "error_code": error_code,
                    }
                else:
                    # 未命中且 persist_unmatched=False → 由 link 记 failed
                    matches[detail_id] = None

            # ordinal：提取节点写出的“题目 ordinal”（有序）；缺省按明细序兜底
            extracted_ordinals = (state.get("extracted_data") or {}).get(
                "题目 ordinal", []
            )
            ordinals = {}
            for index, detail_id in enumerate(detail_ids):
                if extracted_ordinals and index < len(extracted_ordinals):
                    ordinals[int(detail_id)] = int(extracted_ordinals[index])
                else:
                    ordinals[int(detail_id)] = index + 1

            def _link():
                with get_db_connection() as conn:
                    return link_details_to_import(
                        conn,
                        import_id=import_id,
                        detail_ids=list(detail_ids),
                        ordinals=ordinals,
                        actor_id=user_id,
                        matches=matches,
                        write_unmatched=False,
                    )

            await run_db(_link)

        contribution_request_id = None
        if state.get("request_public_review"):
            from app.services.public_contributions import create_public_contribution_request

            def _create_contribution():
                with get_db_connection() as conn:
                    return create_public_contribution_request(
                        conn, "interview", interview_id, user_id
                    )

            contribution = await run_db(_create_contribution)
            contribution_request_id = contribution["id"]

            def _bind_root():
                from app.services.public_contributions import (
                    bind_contribution_request_to_root,
                )

                with get_db_connection() as conn:
                    if state.get("import_id"):
                        bind_contribution_request_to_root(
                            conn,
                            import_id=state["import_id"],
                            contribution_request_id=int(contribution_request_id),
                        )

            await run_db(_bind_root)
            emit_progress(state, "review", "面经已保留在个人题库，已提交公共化审核")

    if state.get("import_id") and queue_detail_ids:
        from app.services.pipeline.queue import _run_cluster_batch_in_background

        await _run_cluster_batch_in_background(
            user_id=user_id,
            root_import_id=str(state["import_id"]),
        )

    emit_progress(state, "save", "个人题库写入完成")

    return {
        "match_result": match_result,
        "saved_interview_id": interview_id,
        "answer_tasks": answer_tasks,
        "record_owner_id": record_owner_id,
        "record_status": record_status,
        "public_contribution_request_id": contribution_request_id,
        "match_failed": match_failed_count,
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

        jd_id = await run_db(
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

        contribution_request_id = None
        if state.get("request_public_review"):
            from app.db.connection import get_db_connection
            from app.services.public_contributions import create_public_contribution_request

            def _create_contribution():
                with get_db_connection() as conn:
                    return create_public_contribution_request(conn, "jd", jd_id, user_id)

            contribution = await run_db(_create_contribution)
            contribution_request_id = contribution["id"]

    emit_progress(
        state,
        "save",
        "JD 保存完成，已提交公共化审核"
        if contribution_request_id
        else "JD 保存完成",
    )
    return {
        "node_timings": {**state.get("node_timings", {}), "jd_persist": timer.elapsed},
        "public_contribution_request_id": contribution_request_id,
        "match_failed": 0,
    }


async def error_empty_node(state: SubmitState) -> dict:
    """空题错误节点：提取重试后仍无题目"""
    emit_error(state, "大模型未能从内容中提取到面试题目")
    return {
        "error": "大模型未能从内容中提取到面试题目",
    }
