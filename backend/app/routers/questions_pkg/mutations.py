"""聚类变异操作 — 拆分、合并、重新打标"""
import json
import logging
import openai
from fastapi import APIRouter, HTTPException, Depends
from app.core.auth import get_admin_user
from app.core.cache import invalidate_master_bank_cache
from app.core.prompts import build_tagging_prompt, TAGGING_PROMPT
from app.db.connection import get_db_connection, run_db, get_current_job_position, get_taxonomy_for_position
from app.models.schemas import SplitQuestionRequest, MergeOriginalQuestionRequest
from app.services.llm import _extract_json, get_llm_client_for_user, raw_llm_call
from app.services.clustering import generate_unified_question
from app.services.utils import normalize_category
from app.services.question_bank_integrity import (
    canonicalize_question_bank_payload,
    claim_public_original_questions,
    sync_question_bank_projections,
)
from app.services.question_variant_reconciliation import (
    assert_no_other_variant_owner,
    normalize_original_question,
    transfer_original_question_owner,
)

logger = logging.getLogger("interview-boss")

router = APIRouter()


@router.post("/api/master-bank/split-question/{question_id}")
async def split_question(question_id: int, req: SplitQuestionRequest, admin: dict = Depends(get_admin_user)):
    """从聚类中拆出指定的原始题目，成为独立题目"""

    original_q = req.original_question.strip()
    if not original_q:
        raise HTTPException(status_code=400, detail="original_question 不能为空")

    def _split():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            try:
                row = cursor.execute(
                    "SELECT id, question, sources, original_questions, original_question_sources, cat1, cat2, tags, difficulty, job_position, owner_id FROM question_bank WHERE id = ?",
                    (question_id,)
                ).fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="未找到该题目")

                orig_qs = json.loads(row['original_questions']) if row['original_questions'] else []
                orig_qs_src = json.loads(row['original_question_sources']) if row['original_question_sources'] else []

                if not orig_qs:
                    raise HTTPException(status_code=400, detail="该题目是独立题目，无需拆分")

                if original_q not in orig_qs:
                    raise HTTPException(status_code=400, detail="该原始题目不在此聚类中")

                # 找到该题的来源
                split_sources = []
                for item in orig_qs_src:
                    if item.get('question') == original_q:
                        split_sources = item.get('sources', [])
                        break

                # 如果来源为空，从 questions_detail 查询原始来源
                if not split_sources:
                    qd_row = cursor.execute(
                        "SELECT url, company, round, cat1, cat2, tags, diff_tag FROM questions_detail WHERE question = ? AND deleted_at IS NULL LIMIT 1",
                        (original_q,)
                    ).fetchone()
                    if qd_row:
                        split_sources = [{"url": qd_row['url'], "company": qd_row['company'], "round": qd_row['round']}]
                        # 如果分类也为空，使用 questions_detail 的分类
                        if not row['cat1'] and qd_row['cat1']:
                            row = dict(row)
                            row['cat1'] = qd_row['cat1']
                            row['cat2'] = qd_row['cat2']
                            row['tags'] = qd_row['tags'] or row['tags']

                # 创建新的独立题目（继承原题的 job_position）
                admin_id = admin['id'] if isinstance(admin, dict) else admin.id
                orig_job_position = row['job_position'] if 'job_position' in row.keys() else get_current_job_position()
                cursor.execute(
                    "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, sources, original_questions, original_question_sources, ai_answer, owner_id, submitted_by, status, job_position) VALUES (?, ?, ?, ?, ?, 1, ?, '[]', '[]', NULL, ?, ?, 'approved', ?)",
                    (original_q, row['cat1'], row['cat2'], row['tags'], row['difficulty'],
                     json.dumps(split_sources, ensure_ascii=False), row['owner_id'], admin_id, orig_job_position)
                )
                new_id = cursor.execute("SELECT last_insert_rowid()").fetchone()[0]
                # 设置 cluster_id = 自身 id（拆分出的新题目自己就是聚类代表）
                cursor.execute("UPDATE question_bank SET cluster_id = ? WHERE id = ?", (new_id, new_id))

                split_sources, _, _ = canonicalize_question_bank_payload(
                    split_sources, [], []
                )
                sync_question_bank_projections(
                    cursor, new_id, split_sources, [], []
                )

                # 同步 question_position 关联表
                pos_row = cursor.execute("SELECT id FROM job_positions WHERE name = ?", (orig_job_position,)).fetchone()
                if pos_row:
                    cursor.execute(
                        "INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, ?)",
                        (new_id, pos_row[0])
                    )

                # 从原聚类中移除该题
                new_orig = [q for q in orig_qs if q != original_q]
                new_orig_src = [item for item in orig_qs_src if item.get('question') != original_q]

                # 重新计算原聚类的 sources
                remaining_sources = []
                seen = set()
                for item in new_orig_src:
                    for s in item.get('sources', []):
                        key = (s.get('url', ''), s.get('company', ''), s.get('round', ''))
                        if key not in seen:
                            seen.add(key)
                            remaining_sources.append(s)

                remaining_sources, new_orig, new_orig_src = (
                    canonicalize_question_bank_payload(
                        remaining_sources, new_orig, new_orig_src
                    )
                )

                parent_sync_orig = new_orig
                parent_sync_orig_src = new_orig_src
                if len(new_orig) == 0:
                    cursor.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
                elif len(new_orig) == 1:
                    parent_sync_orig = []
                    parent_sync_orig_src = []
                    cursor.execute(
                        "UPDATE question_bank SET question = ?, original_questions = '[]', original_question_sources = '[]', frequency = ?, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (new_orig[0], 1, json.dumps(remaining_sources, ensure_ascii=False), question_id)
                    )
                else:
                    cursor.execute(
                        "UPDATE question_bank SET original_questions = ?, original_question_sources = ?, frequency = ?, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (json.dumps(new_orig, ensure_ascii=False), json.dumps(new_orig_src, ensure_ascii=False),
                         len(new_orig), json.dumps(remaining_sources, ensure_ascii=False), question_id)
                    )

                if len(new_orig) >= 1:
                    sync_question_bank_projections(
                        cursor, question_id, remaining_sources, parent_sync_orig, parent_sync_orig_src
                    )

                from app.services.cluster_review_lifecycle import mark_clusters_review_pending

                mark_clusters_review_pending(conn, [question_id, new_id], "split_cluster")

                conn.commit()
                return new_id, new_orig, new_orig_src, question_id
            except Exception:
                conn.rollback()
                raise

    try:
        new_id, remaining_orig, remaining_orig_src, old_id = await run_db(_split)

        # 如果原聚类还有多题，重新生成统一问题（跳过手动编辑过的）
        if len(remaining_orig) >= 2:
            def _check_manual():
                with get_db_connection() as conn:
                    row = conn.execute("SELECT question_manually_edited FROM question_bank WHERE id = ?", (old_id,)).fetchone()
                    return row and row['question_manually_edited']
            is_manual = await run_db(_check_manual)
            if is_manual:
                logger.info(f"聚类 {old_id} 代表题已手动编辑，跳过自动重新生成")
            else:
                try:
                    # 构建来源上下文
                    sources_ctx = []
                    for item in remaining_orig_src:
                        s = item.get("sources", [{}])[0] if item.get("sources") else {}
                        sources_ctx.append({"question": item.get("question", ""), "company": s.get("company", ""), "round": s.get("round", "")})
                    unified = await generate_unified_question(remaining_orig, sources_context=sources_ctx, user_id=admin['id'])
                    def _update_unified():
                        with get_db_connection() as conn:
                            conn.execute(
                                "UPDATE question_bank SET question = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                                (unified, old_id)
                            )
                            from app.services.cluster_review_lifecycle import mark_cluster_review_pending

                            mark_cluster_review_pending(conn, old_id, "representative_changed")
                            conn.commit()
                    await run_db(_update_unified)
                except Exception as e:
                    logger.warning(f"拆分后重新生成统一问题失败: {e}")

        await invalidate_master_bank_cache()
        return {"status": "success", "new_id": new_id, "message": "题目已拆分为独立题目"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("拆分题目失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")


@router.post("/api/master-bank/merge-question/{question_id}")
async def merge_question(question_id: int, req: MergeOriginalQuestionRequest, admin: dict = Depends(get_admin_user)):
    """将指定的原始题目从一个聚类移动到另一个聚类"""

    original_q = req.original_question.strip()
    if not original_q:
        raise HTTPException(status_code=400, detail="original_question 不能为空")
    if question_id == req.target_id:
        raise HTTPException(status_code=400, detail="不能合并到同一个聚类")
    requested_original_q = original_q

    def _merge():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("BEGIN")
            try:
                source = conn.execute(
                    "SELECT id, question, sources, original_questions, original_question_sources, ai_answer, answer_sources, owner_id, status FROM question_bank WHERE id = ?",
                    (question_id,)
                ).fetchone()
                target = conn.execute(
                    "SELECT id, question, sources, original_questions, original_question_sources, ai_answer, answer_sources, owner_id, status FROM question_bank WHERE id = ?",
                    (req.target_id,)
                ).fetchone()
                if not source:
                    raise HTTPException(status_code=404, detail="未找到源聚类")
                if not target:
                    raise HTTPException(status_code=404, detail="未找到目标聚类")

                src_orig = json.loads(source['original_questions']) if source['original_questions'] else []
                src_orig_src = json.loads(source['original_question_sources']) if source['original_question_sources'] else []

                source_original_q = next(
                    (
                        question
                        for question in src_orig
                        if normalize_original_question(question)
                        == normalize_original_question(requested_original_q)
                    ),
                    None,
                )
                is_standalone_merge = (
                    not src_orig
                    and normalize_original_question(requested_original_q)
                    == normalize_original_question(source['question'])
                )
                if source_original_q:
                    original_q = source_original_q
                if not is_standalone_merge and not source_original_q:
                    raise HTTPException(status_code=400, detail="该原始题目不在源聚类中")

                # 找到要移动的题目的来源
                moving_src = []
                if is_standalone_merge:
                    moving_src = json.loads(source['sources']) if source['sources'] else []
                else:
                    for item in src_orig_src:
                        if normalize_original_question(item.get('question')) == normalize_original_question(original_q):
                            moving_src = item.get('sources', [])
                            break

                # 更新目标聚类
                tgt_orig = json.loads(target['original_questions']) if target['original_questions'] else []
                tgt_orig_src = json.loads(target['original_question_sources']) if target['original_question_sources'] else []
                tgt_sources = json.loads(target['sources']) if target['sources'] else []

                tgt_orig.append(original_q)
                tgt_orig_src.append({"question": original_q, "sources": moving_src})

                # 更新目标的 sources
                seen = {(s.get('url', ''), s.get('company', ''), s.get('round', '')) for s in tgt_sources}
                for s in moving_src:
                    key = (s.get('url', ''), s.get('company', ''), s.get('round', ''))
                    if key not in seen:
                        seen.add(key)
                        tgt_sources.append(s)

                tgt_sources, tgt_orig, tgt_orig_src = canonicalize_question_bank_payload(
                    tgt_sources, tgt_orig, tgt_orig_src
                )
                if target["owner_id"] is None and target["status"] == "approved":
                    assert_no_other_variant_owner(
                        conn, original_q, {question_id, req.target_id}
                    )

                # 可选：更新目标聚类类别
                cat_set = ""
                cat_params = []
                if req.target_cat1:
                    cat_set += ", cat1 = ?"
                    cat_params.append(req.target_cat1)
                if req.target_cat2:
                    cat_set += ", cat2 = ?"
                    cat_params.append(req.target_cat2)

                conn.execute(
                    f"UPDATE question_bank SET original_questions = ?, original_question_sources = ?, sources = ?, frequency = ?, updated_at = CURRENT_TIMESTAMP{cat_set} WHERE id = ?",
                    [json.dumps(tgt_orig, ensure_ascii=False), json.dumps(tgt_orig_src, ensure_ascii=False),
                     json.dumps(tgt_sources, ensure_ascii=False), len(tgt_orig), *cat_params, req.target_id]
                )

                if target["owner_id"] is None and target["status"] == "approved":
                    if source["owner_id"] is None and source["status"] == "approved":
                        transfer_original_question_owner(
                            conn, original_q, question_id, req.target_id
                        )
                    else:
                        claim_public_original_questions(
                            conn,
                            req.target_id,
                            target["owner_id"],
                            target["status"],
                            tgt_orig,
                        )
                sync_question_bank_projections(
                    cursor, req.target_id, tgt_sources, tgt_orig, tgt_orig_src
                )

                # 转移 ai_answer（目标没有答案时才转移）
                if source['ai_answer'] and not target['ai_answer']:
                    conn.execute(
                        "UPDATE question_bank SET ai_answer = ?, answer_sources = ? WHERE id = ?",
                        (source['ai_answer'], source['answer_sources'], req.target_id)
                    )

                # 转移收藏记录（跳过用户已在目标题目上的记录）
                conn.execute(
                    "INSERT INTO user_question_view (user_id, question_bank_id, is_starred, personal_tags, note) "
                    "SELECT uqv.user_id, ?, uqv.is_starred, uqv.personal_tags, uqv.note "
                    "FROM user_question_view uqv WHERE uqv.question_bank_id = ? "
                    "AND NOT EXISTS (SELECT 1 FROM user_question_view t WHERE t.user_id = uqv.user_id AND t.question_bank_id = ?)",
                    (req.target_id, question_id, req.target_id)
                )

                # 转移练习记录（跳过用户已在目标题目上的记录）
                conn.execute(
                    "INSERT INTO user_practice_history (user_id, question_bank_id, user_answer, evaluation_result, score, created_at) "
                    "SELECT uph.user_id, ?, uph.user_answer, uph.evaluation_result, uph.score, uph.created_at "
                    "FROM user_practice_history uph WHERE uph.question_bank_id = ? "
                    "AND NOT EXISTS (SELECT 1 FROM user_practice_history t WHERE t.user_id = uph.user_id AND t.question_bank_id = ?)",
                    (req.target_id, question_id, req.target_id)
                )

                # 双写收敛后: 同步搬迁复习事件与 SRS 状态到目标题(否则拆题丢评估记录)
                conn.execute(
                    "INSERT INTO practice_review_events "
                    "(user_id, question_bank_id, review_id, rating, score, source, reviewed_at, before_state_json) "
                    "SELECT pre.user_id, ?, pre.review_id, pre.rating, pre.score, pre.source, pre.reviewed_at, pre.before_state_json "
                    "FROM practice_review_events pre WHERE pre.question_bank_id = ? "
                    "AND NOT EXISTS (SELECT 1 FROM practice_review_events t "
                    "WHERE t.user_id = pre.user_id AND t.question_bank_id = ? "
                    "AND t.reviewed_at = pre.reviewed_at AND t.score IS pre.score)",
                    (req.target_id, question_id, req.target_id)
                )
                conn.execute(
                    "INSERT OR IGNORE INTO user_question_review "
                    "(user_id, question_bank_id, state, proficiency, review_count, lapse_count, "
                    "last_rating, last_score, last_reviewed_at, next_review_at, interval_days, "
                    "ease_factor, stability_days, difficulty, algorithm, updated_at) "
                    "SELECT uqr.user_id, ?, uqr.state, uqr.proficiency, uqr.review_count, uqr.lapse_count, "
                    "uqr.last_rating, uqr.last_score, uqr.last_reviewed_at, uqr.next_review_at, uqr.interval_days, "
                    "uqr.ease_factor, uqr.stability_days, uqr.difficulty, uqr.algorithm, uqr.updated_at "
                    "FROM user_question_review uqr WHERE uqr.question_bank_id = ?",
                    (req.target_id, question_id)
                )

                # 从源聚类中移除
                original_norm = normalize_original_question(original_q)
                new_src_orig = [
                    q for q in src_orig
                    if normalize_original_question(q) != original_norm
                ]
                new_src_orig_src = [
                    item for item in src_orig_src
                    if normalize_original_question(item.get('question')) != original_norm
                ]

                remaining_sources = []
                seen2 = set()
                for item in new_src_orig_src:
                    for s in item.get('sources', []):
                        key = (s.get('url', ''), s.get('company', ''), s.get('round', ''))
                        if key not in seen2:
                            seen2.add(key)
                            remaining_sources.append(s)

                remaining_sources, new_src_orig, new_src_orig_src = (
                    canonicalize_question_bank_payload(
                        remaining_sources, new_src_orig, new_src_orig_src
                    )
                )

                source_sync_orig = new_src_orig
                source_sync_orig_src = new_src_orig_src
                if is_standalone_merge:
                    # 独立题合并后删除源（已完整并入目标）
                    conn.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
                    conn.execute("DELETE FROM question_position WHERE question_id = ?", (question_id,))
                elif len(new_src_orig) == 0:
                    conn.execute("DELETE FROM question_bank WHERE id = ?", (question_id,))
                    conn.execute("DELETE FROM question_position WHERE question_id = ?", (question_id,))
                elif len(new_src_orig) == 1:
                    source_sync_orig = []
                    source_sync_orig_src = []
                    conn.execute(
                        "UPDATE question_bank SET question = ?, original_questions = '[]', original_question_sources = '[]', frequency = ?, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (new_src_orig[0], 1, json.dumps(remaining_sources, ensure_ascii=False), question_id)
                    )
                else:
                    conn.execute(
                        "UPDATE question_bank SET original_questions = ?, original_question_sources = ?, frequency = ?, sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (json.dumps(new_src_orig, ensure_ascii=False), json.dumps(new_src_orig_src, ensure_ascii=False),
                         len(new_src_orig), json.dumps(remaining_sources, ensure_ascii=False), question_id)
                    )

                if not is_standalone_merge and len(new_src_orig) >= 1:
                    sync_question_bank_projections(
                        cursor,
                        question_id,
                        remaining_sources,
                        source_sync_orig,
                        source_sync_orig_src,
                    )

                from app.services.cluster_review_lifecycle import mark_clusters_review_pending

                mark_clusters_review_pending(conn, [question_id, req.target_id], "merge_variant")

                conn.commit()
            except Exception:
                conn.rollback()
                raise
            return new_src_orig, new_src_orig_src, question_id, tgt_orig, tgt_orig_src, req.target_id

    def _build_sources_ctx(orig_src_list):
        """从 original_question_sources 格式构建 generate_unified_question 所需的 sources_context"""
        ctx = []
        for item in orig_src_list:
            s = item.get("sources", [{}])[0] if item.get("sources") else {}
            ctx.append({"question": item.get("question", ""), "company": s.get("company", ""), "round": s.get("round", "")})
        return ctx

    try:
        src_remaining, src_remaining_src, src_id, tgt_all, tgt_all_src, tgt_id = await run_db(_merge)

        # 检查哪些聚类被手动编辑过
        def _check_manual_flags():
            with get_db_connection() as conn:
                flags = {}
                for qid in [src_id, tgt_id]:
                    row = conn.execute("SELECT question_manually_edited FROM question_bank WHERE id = ?", (qid,)).fetchone()
                    flags[qid] = bool(row and row['question_manually_edited'])
                return flags
        manual_flags = await run_db(_check_manual_flags)

        # 重新生成源聚类的统一问题（跳过手动编辑过的）
        if len(src_remaining) >= 2:
            if manual_flags.get(src_id):
                logger.info(f"源聚类 {src_id} 代表题已手动编辑，跳过自动重新生成")
            else:
                try:
                    sources_ctx = _build_sources_ctx(src_remaining_src)
                    unified = await generate_unified_question(src_remaining, sources_context=sources_ctx, user_id=admin['id'])
                    def _update_src():
                        with get_db_connection() as conn:
                            conn.execute("UPDATE question_bank SET question = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (unified, src_id))
                            from app.services.cluster_review_lifecycle import mark_cluster_review_pending

                            mark_cluster_review_pending(conn, src_id, "representative_changed")
                            conn.commit()
                    await run_db(_update_src)
                except Exception as e:
                    logger.warning(f"合并后重新生成源聚类统一问题失败: {e}")

        # 重新生成目标聚类的统一问题（跳过手动编辑过的）
        if len(tgt_all) >= 2:
            if manual_flags.get(tgt_id):
                logger.info(f"目标聚类 {tgt_id} 代表题已手动编辑，跳过自动重新生成")
            else:
                try:
                    sources_ctx = _build_sources_ctx(tgt_all_src)
                    unified = await generate_unified_question(tgt_all, sources_context=sources_ctx, user_id=admin['id'])
                    def _update_tgt():
                        with get_db_connection() as conn:
                            conn.execute("UPDATE question_bank SET question = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (unified, tgt_id))
                            from app.services.cluster_review_lifecycle import mark_cluster_review_pending

                            mark_cluster_review_pending(conn, tgt_id, "representative_changed")
                            conn.commit()
                    await run_db(_update_tgt)
                except Exception as e:
                    logger.warning(f"合并后重新生成目标聚类统一问题失败: {e}")

        await invalidate_master_bank_cache()
        return {"status": "success", "message": "题目已移动到目标聚类"}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("合并题目失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")


@router.post("/api/master-bank/re-tag/{question_id}")
async def retag_master_question(question_id: int, user: dict = Depends(get_admin_user)):
    def _get():
        with get_db_connection() as conn:
            return conn.execute("SELECT question, cat1, cat2, tags, difficulty FROM question_bank WHERE id = ?", (question_id,)).fetchone()

    row = await run_db(_get)

    if not row or not row['question']:
        raise HTTPException(status_code=404, detail="未找到该题目")

    question_text = row['question']
    current_cat1 = row['cat1'] or '未分类'
    current_cat2 = row['cat2'] or '未分类'
    current_tags = row['tags'] or ''
    current_diff = row['difficulty'] or '未知'

    # 读取当前岗位的分类体系
    taxonomy_config = await run_db(get_taxonomy_for_position)

    # 在 prompt 中告知当前分类，要求 LLM 重新审视并给出更准确的分类
    input_data = [{"id": question_id, "题目": question_text}]
    q_json = json.dumps(input_data, ensure_ascii=False)
    prompt = build_tagging_prompt(taxonomy_config) if taxonomy_config else TAGGING_PROMPT
    user_msg = prompt.replace("{questions}", q_json)
    user_msg += f"""

## ⚠️ 重要：重新审视请求
该题目当前的分类结果如下，请仔细重新审视是否准确：
- 当前一级大类：{current_cat1}
- 当前二级子类：{current_cat2}
- 当前考点标签：{current_tags}
- 当前难度：{current_diff}

如果当前分类不准确，请给出更合适的分类。如果当前分类已经准确，请保持不变。
请特别注意：
1. 一级大类和二级子类必须严格匹配（如选了A则二级必须是A1-A4）
2. 考点标签应选择与题目内容最直接相关的技术领域
3. 难度应根据题目实际考察深度判断
"""

    try:
        _c, _m, _t, _bu, _provider = get_llm_client_for_user(user['id'])
        response_text = await raw_llm_call(
            user['id'],
            model=_m,
            messages=[
                {"role": "system", "content": "你是一个严格输出 JSON 对象的助手，格式必须为 {\"questions\": [...]}。必须输出输入数据中每一项对应的 \"id\" 字段，以便于与原输入一一对应。请仔细分析题目内容，给出最准确的分类。"},
                {"role": "user", "content": user_msg}
            ],
            temperature=0.2,
        )

        parsed_result = _extract_json(response_text)
        items = parsed_result.get("questions", [])

        if not items:
            raise ValueError("大模型未返回有效的分类数据")

        item = items[0]
        cat1 = normalize_category(item.get("一级大类", "未分类"))
        cat2 = normalize_category(item.get("二级子类", "未分类"))
        tags = item.get("考点标签", "")
        diff = item.get("难度标签", "未知")

        def _update():
            with get_db_connection() as conn:
                conn.execute(
                    "UPDATE question_bank SET cat1 = ?, cat2 = ?, tags = ?, difficulty = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (cat1, cat2, tags, diff, question_id)
                )
                conn.execute(
                    "UPDATE questions_detail SET cat1 = ?, cat2 = ?, tags = ?, diff_tag = ?, updated_at = CURRENT_TIMESTAMP WHERE question = ?",
                    (cat1, cat2, tags, diff, question_text)
                )
                from app.db.operations import _retype_distribution_details_txn
                detail_rows = conn.execute(
                    "SELECT id FROM questions_detail WHERE question = ? AND deleted_at IS NULL",
                    (question_text,),
                ).fetchall()
                _retype_distribution_details_txn(conn.cursor(), [detail["id"] for detail in detail_rows])
                from app.services.cluster_review_lifecycle import mark_cluster_review_pending

                mark_cluster_review_pending(conn, question_id, "category_changed")
                conn.commit()

        await run_db(_update)
        await invalidate_master_bank_cache()

        return {
            "status": "success",
            "message": "题目重新打标成功",
            "data": {"cat1": cat1, "cat2": cat2, "tags": tags, "difficulty": diff}
        }

    except openai.AuthenticationError:
        raise HTTPException(status_code=500, detail="API Key 无效，请在系统配置中更新 API Key。")
    except openai.APIConnectionError:
        raise HTTPException(status_code=500, detail="无法连接 LLM 服务，请检查系统配置中的 Base URL。")
    except openai.APITimeoutError:
        raise HTTPException(status_code=500, detail="LLM 服务响应超时，请增大超时时间或稍后重试。")
    except Exception as e:
        logger.exception("重新打标失败")
        raise HTTPException(status_code=500, detail="服务器内部错误，请查看服务端日志")
