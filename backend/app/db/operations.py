import json
import logging
import os
import sqlite3
from app.db.connection import get_db_connection
from app.db.question_bank_sources import (
    insert_source,
    insert_original_item,
    sync_question_bank_sources,
)
from app.db.utils import _extract_url_signature, normalize_category
from app.services.interview_distribution import (
    map_dimension,
    map_question_type,
    mark_distribution_refresh,
)
from app.services.question_bank_integrity import (
    canonicalize_question_bank_payload,
    claim_public_original_questions,
    sync_question_bank_projections,
)
from app.services.question_variant_reconciliation import normalize_original_question

logger = logging.getLogger("interview-boss")


def _mark_cluster_review_pending_if_available(cursor, cluster_id: int, reason: str):
    """Keep legacy/lightweight schemas usable without weakening source cleanup."""
    connection = getattr(cursor, "connection", None)
    if not isinstance(connection, sqlite3.Connection):
        return
    required = {"quality_issue", "cluster_review_state", "cluster_review_tasks"}
    rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN (?, ?, ?)",
        tuple(required),
    ).fetchall()
    if {row[0] for row in rows} != required:
        return
    from app.services.cluster_review_lifecycle import mark_cluster_review_pending

    mark_cluster_review_pending(connection, cluster_id, reason)


# ═══════════════════════════════════════════════════
#  通用工具
# ═══════════════════════════════════════════════════


def _purge_soft_deleted(url: str, owner_id=None):
    """物理删除指定 URL 的软删除记录及其关联数据，让重新上传能干净进行。"""
    sig = _extract_url_signature(url)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        # 找到匹配的软删除记录
        conditions = []
        params = []
        if owner_id is not None:
            conditions.append("owner_id = ?")
            params.append(owner_id)
        else:
            conditions.append("owner_id IS NULL")
        conditions.append("deleted_at IS NOT NULL")

        where = " AND ".join(conditions)

        # 清理 interview 及其关联数据
        old_interviews = cursor.execute(
            f"SELECT id, url FROM interview WHERE url = ? AND {where}", [url, *params]
        ).fetchall()
        if sig:
            old_interviews += cursor.execute(
                f"SELECT id, url FROM interview WHERE url_signature = ? AND {where}",
                [sig, *params],
            ).fetchall()

        for row in old_interviews:
            old_url = row["url"]
            if old_url:
                cursor.execute(
                    "DELETE FROM questions_detail WHERE url = ? AND deleted_at IS NOT NULL",
                    (old_url,),
                )
            cursor.execute(
                "DELETE FROM analysis_queue WHERE interview_id = ?", (row["id"],)
            )
            cursor.execute("DELETE FROM interview WHERE id = ?", (row["id"],))

        # 清理 jd 及其关联数据
        old_jds = cursor.execute(
            f"SELECT id, url FROM jd WHERE url = ? AND {where}", [url, *params]
        ).fetchall()
        if sig:
            old_jds += cursor.execute(
                f"SELECT id, url FROM jd WHERE url_signature = ? AND {where}",
                [sig, *params],
            ).fetchall()

        for row in old_jds:
            old_url = row["url"]
            if old_url:
                cursor.execute(
                    "DELETE FROM questions_detail WHERE url = ? AND deleted_at IS NOT NULL",
                    (old_url,),
                )
                cursor.execute(
                    "DELETE FROM analysis_queue WHERE interview_id IN (SELECT id FROM interview WHERE url = ? AND deleted_at IS NOT NULL)",
                    (old_url,),
                )
                cursor.execute(
                    "DELETE FROM interview WHERE url = ? AND deleted_at IS NOT NULL",
                    (old_url,),
                )
            cursor.execute("DELETE FROM jd WHERE id = ?", (row["id"],))

        conn.commit()


def _check_duplicate_url_sync(url: str, owner_id=None) -> bool:
    """检查 URL 是否已存在活跃记录。

    owner_id=None（公共上传）：检查所有活跃记录（全局唯一）。
    owner_id=int（个人上传）：只检查该用户自己的活跃记录。
    """
    if not url:
        return False
    sig = _extract_url_signature(url)
    with get_db_connection() as conn:
        cursor = conn.cursor()
        if owner_id is not None:
            # 个人上传：仅检查该用户自己的活跃记录
            cursor.execute(
                "SELECT 1 FROM jd WHERE url = ? AND owner_id = ? AND deleted_at IS NULL",
                (url, owner_id),
            )
            if cursor.fetchone():
                return True
            cursor.execute(
                "SELECT 1 FROM interview WHERE url = ? AND owner_id = ? AND deleted_at IS NULL",
                (url, owner_id),
            )
            if cursor.fetchone():
                return True
            if sig:
                cursor.execute(
                    "SELECT 1 FROM jd WHERE url_signature = ? AND owner_id = ? AND deleted_at IS NULL",
                    (sig, owner_id),
                )
                if cursor.fetchone():
                    return True
                cursor.execute(
                    "SELECT 1 FROM interview WHERE url_signature = ? AND owner_id = ? AND deleted_at IS NULL",
                    (sig, owner_id),
                )
                if cursor.fetchone():
                    return True
        else:
            # 公共上传：检查所有活跃记录（URL 全局唯一，不管 owner）
            cursor.execute(
                "SELECT 1 FROM jd WHERE url = ? AND deleted_at IS NULL", (url,)
            )
            if cursor.fetchone():
                return True
            cursor.execute(
                "SELECT 1 FROM interview WHERE url = ? AND deleted_at IS NULL", (url,)
            )
            if cursor.fetchone():
                return True
            if sig:
                cursor.execute(
                    "SELECT 1 FROM jd WHERE url_signature = ? AND deleted_at IS NULL",
                    (sig,),
                )
                if cursor.fetchone():
                    return True
                cursor.execute(
                    "SELECT 1 FROM interview WHERE url_signature = ? AND deleted_at IS NULL",
                    (sig,),
                )
                if cursor.fetchone():
                    return True

    # 活跃记录不存在，清理可能残留的软删除记录
    _purge_soft_deleted(url, owner_id)
    return False


# ═══════════════════════════════════════════════════
#  事务内原子操作（接受外部 cursor）
# ═══════════════════════════════════════════════════


def _table_columns(cursor, table_name: str) -> set[str]:
    """Return table columns, tolerating lightweight pre-migration test schemas."""
    try:
        return {
            row[1]
            for row in cursor.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
    except (sqlite3.DatabaseError, TypeError, AttributeError, KeyError):
        return set()


def _distribution_storage_available(cursor) -> bool:
    columns = _table_columns(cursor, "questions_detail")
    return {"interview_id", "question_type", "dimension"} <= columns and bool(
        cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'interview_distribution_refresh_jobs'"
        ).fetchone()
    )


def _insert_interview_txn(
    cursor, saved_url, data, questions, season, owner_id, status, job_position
):
    sig = _extract_url_signature(saved_url)
    cursor.execute(
        "INSERT INTO interview (url, company, round, focus, questions_list, difficulty, season, owner_id, status, url_signature, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            saved_url,
            data.get("公司", "未提供"),
            data.get("面试轮次", "未提供"),
            data.get("考察重点", "未提供"),
            questions,
            data.get("难易程度", "未提供"),
            season,
            owner_id,
            status,
            sig,
            job_position,
        ),
    )


def _mark_distribution_refresh_for_interview_txn(
    cursor, interview_id: int | None
) -> None:
    """Mark a public approved interview's position stale in the current transaction."""
    if interview_id is None or not _distribution_storage_available(cursor):
        return
    interview = cursor.execute(
        """
        SELECT owner_id, status, deleted_at, job_position
        FROM interview WHERE id = ?
        """,
        (interview_id,),
    ).fetchone()
    if (
        interview
        and interview["owner_id"] is None
        and interview["status"] == "approved"
        and interview["deleted_at"] is None
    ):
        mark_distribution_refresh(cursor, interview["job_position"] or "")


def _mark_distribution_refresh_for_detail_ids_txn(cursor, detail_ids) -> None:
    """Mark public scopes before a detail is soft- or hard-deleted."""
    if not _distribution_storage_available(cursor):
        return
    ids = list(detail_ids or [])
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    rows = cursor.execute(
        f"""
        SELECT DISTINCT i.job_position
        FROM questions_detail qd
        JOIN interview i ON i.id = qd.interview_id
        WHERE qd.id IN ({placeholders})
          AND i.owner_id IS NULL AND i.status = 'approved' AND i.deleted_at IS NULL
        """,
        ids,
    ).fetchall()
    for row in rows:
        mark_distribution_refresh(cursor, row["job_position"] or "")


def _retype_distribution_details_txn(cursor, detail_ids) -> None:
    """Refresh canonical types after an in-place taxonomy or text mutation."""
    if not _distribution_storage_available(cursor):
        return
    ids = list(detail_ids or [])
    if not ids:
        return
    placeholders = ",".join("?" * len(ids))
    rows = cursor.execute(
        f"""
        SELECT qd.id, qd.cat1, qd.cat2, qd.tags, qd.question
        FROM questions_detail qd
        WHERE qd.id IN ({placeholders}) AND qd.deleted_at IS NULL
        """,
        ids,
    ).fetchall()
    for row in rows:
        question_type = map_question_type(
            row["cat1"], row["cat2"], row["tags"], row["question"]
        )
        cursor.execute(
            "UPDATE questions_detail SET question_type = ?, dimension = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (question_type.value, map_dimension(question_type), row["id"]),
        )
    _mark_distribution_refresh_for_detail_ids_txn(cursor, [row["id"] for row in rows])


def _insert_details_txn(
    cursor, tagged_rows, job_position="", *, interview_id: int | None = None
):
    """Write typed facts for one already-known interview inside its transaction."""
    if not _distribution_storage_available(cursor):
        for tr in tagged_rows:
            cursor.execute(
                "INSERT INTO questions_detail (url, company, round, question, cat1, cat2, tags, diff_tag, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (*tr, job_position),
            )
        return
    for tr in tagged_rows:
        question_type = map_question_type(tr[4], tr[5], tr[6], tr[3])
        cursor.execute(
            """
            INSERT INTO questions_detail (
                interview_id, url, company, round, question, cat1, cat2, tags,
                diff_tag, job_position, question_type, dimension
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                interview_id,
                *tr,
                job_position,
                question_type.value,
                map_dimension(question_type),
            ),
        )
    _mark_distribution_refresh_for_interview_txn(cursor, interview_id)


def _cleanup_old_sources_txn(cursor, url: str):
    """移除某面经对 question_bank 的所有贡献，frequency=0 直接删除。

    Delegates to _cleanup_old_sources_txn_v2 for complete cleanup.
    """
    _cleanup_old_sources_txn_v2(cursor, url)


def _cleanup_old_sources_txn_v2(cursor, url: str, job_position: str = ""):
    """彻底移除某面经对 question_bank 的所有贡献。

    比 v1 多清理：
    - original_questions 中属于该 URL 的条目
    - original_question_sources 中属于该 URL 的条目
    - 被删除 QB 记录的 question_position 映射
    """
    # Use normalized question_sources table with indexed url column instead of LIKE scan
    try:
        affected_ids = cursor.execute(
            "SELECT DISTINCT question_bank_id FROM question_sources WHERE url = ?",
            (url,),
        ).fetchall()
        if affected_ids:
            id_placeholders = ",".join("?" * len(affected_ids))
            affected_rows = cursor.execute(
                f"SELECT id, sources, original_questions, original_question_sources FROM question_bank WHERE id IN ({id_placeholders})",
                [r[0] for r in affected_ids],
            ).fetchall()
        else:
            affected_rows = []
        original_ids = cursor.execute(
            "SELECT DISTINCT qoi.question_bank_id "
            "FROM question_original_item_sources qois "
            "JOIN question_original_items qoi ON qoi.id = qois.original_item_id "
            "WHERE qois.url = ?",
            (url,),
        ).fetchall()
        existing_ids = {r["id"] for r in affected_rows}
        missing_ids = [row[0] for row in original_ids if row[0] not in existing_ids]
        if missing_ids:
            placeholders = ",".join("?" * len(missing_ids))
            affected_rows.extend(
                cursor.execute(
                    f"SELECT id, sources, original_questions, original_question_sources "
                    f"FROM question_bank WHERE id IN ({placeholders})",
                    missing_ids,
                ).fetchall()
            )
    except Exception:
        # Fallback for tests / missing normalized tables
        affected_rows = cursor.execute(
            "SELECT id, sources, original_questions, original_question_sources FROM question_bank WHERE sources LIKE ?",
            (f"%{url}%",),
        ).fetchall()

    ids_to_delete = []
    for mr in affected_rows:
        try:
            sources = json.loads(mr["sources"]) if mr["sources"] else []
        except Exception:
            sources = []
        try:
            oqs = (
                json.loads(mr["original_questions"]) if mr["original_questions"] else []
            )
        except Exception:
            oqs = []
        try:
            oqs_sources = (
                json.loads(mr["original_question_sources"])
                if mr["original_question_sources"]
                else []
            )
        except Exception:
            oqs_sources = []

        # 移除属于该 URL 的 source
        new_sources = [s for s in sources if s.get("url") != url]
        # 移除属于该 URL 的 original_question_sources（嵌套格式：{"question":"...","sources":[{"url":"..."}]}），并同步移除对应的 original_questions
        new_oqs_sources = []
        removed_questions = set()
        for item in oqs_sources:
            item_sources = item.get("sources", [])
            # 过滤掉属于该 URL 的 source
            remaining_sources = [s for s in item_sources if s.get("url") != url]
            if remaining_sources:
                new_oqs_sources.append({**item, "sources": remaining_sources})
            else:
                # 该条目的所有 source 都被移除，标记其 question 为待移除
                removed_questions.add(item.get("question", ""))
        new_oqs = [q for q in oqs if q not in removed_questions]

        sources_changed = new_sources != sources
        oqs_sources_changed = new_oqs_sources != oqs_sources
        oqs_changed = new_oqs != oqs
        if sources_changed or oqs_sources_changed or oqs_changed:
            cursor.execute(
                "UPDATE question_bank SET frequency = ?, sources = ?, "
                "original_questions = ?, original_question_sources = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (
                    max(1, len(new_oqs)),
                    json.dumps(new_sources, ensure_ascii=False),
                    json.dumps(new_oqs, ensure_ascii=False),
                    json.dumps(new_oqs_sources, ensure_ascii=False),
                    mr["id"],
                ),
            )
        if len(new_sources) == 0 and mr["id"] not in ids_to_delete:
            # The JSON projection may already be stale or empty after an
            # earlier half-write.  A normalized source hit still identifies
            # this QB as affected, so an empty repaired source set must be
            # soft-deleted as well.
            ids_to_delete.append(mr["id"])
        sync_question_bank_sources(
            cursor,
            mr["id"],
            new_sources,
            new_oqs,
            new_oqs_sources,
        )
        if sources_changed or oqs_sources_changed:
            _mark_cluster_review_pending_if_available(
                cursor, mr["id"], "source_removed"
            )

    if ids_to_delete:
        placeholders = ",".join("?" * len(ids_to_delete))
        cursor.execute(
            f"UPDATE question_bank SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE id IN ({placeholders}) AND deleted_at IS NULL",
            ids_to_delete,
        )
        cursor.execute(
            f"DELETE FROM question_position WHERE question_id IN ({placeholders})",
            ids_to_delete,
        )

    cursor.execute(
        "UPDATE question_bank SET deleted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE frequency <= 0 AND owner_id IS NULL AND deleted_at IS NULL"
    )
    cursor.execute(
        "DELETE FROM question_position WHERE question_id IN "
        "(SELECT id FROM question_bank WHERE frequency <= 0 AND owner_id IS NULL)"
    )


def _replace_details_txn(cursor, interview_id: int, url, tagged_rows, job_position=""):
    """Replace only the known interview's facts; never fan out by a shared URL."""
    if _distribution_storage_available(cursor):
        cursor.execute(
            "DELETE FROM questions_detail WHERE interview_id = ?", (interview_id,)
        )
    else:
        cursor.execute("DELETE FROM questions_detail WHERE url = ?", (url,))
    _insert_details_txn(cursor, tagged_rows, job_position, interview_id=interview_id)


def _apply_incremental_txn(
    cursor,
    matched,
    unmatched_rows,
    idx_to_row,
    submitter_is_admin,
    user_id,
    current_pos,
    owner_id=None,
):
    """增量更新 question_bank（matched 增频，unmatched 新建）。

    owner_id: 传入时用于 unmatched 新建行的 owner_id（个人题库场景）。
    返回需要后台生成 AI 答案的 (question_id, question_text) 列表。
    """
    submitter_id = user_id
    if not submitter_id:
        admin_username = os.getenv("ADMIN_USERNAME", "sj")
        admin_row = cursor.execute(
            "SELECT id FROM users WHERE username = ?", (admin_username,)
        ).fetchone()
        submitter_id = admin_row[0] if admin_row else None
    status = "approved" if submitter_is_admin else "pending"

    answer_tasks = []

    for m in matched:
        new_idx = m["new_id"]
        qb_id = m["question_bank_id"]
        row = idx_to_row.get(new_idx)
        if not row:
            continue
        url, company, round_ = row[0], row[1], row[2]
        new_q_text = row[3] if len(row) > 3 else ""
        new_source = {"url": url, "company": company, "round": round_}
        existing = cursor.execute(
            "SELECT sources, original_questions, original_question_sources, owner_id, status "
            "FROM question_bank WHERE id = ?",
            (qb_id,),
        ).fetchone()
        if existing:
            try:
                sources = json.loads(existing["sources"]) if existing["sources"] else []
            except Exception:
                sources = []
            try:
                orig_qs = (
                    json.loads(existing["original_questions"])
                    if existing["original_questions"]
                    else []
                )
                orig_qs_src = (
                    json.loads(existing["original_question_sources"])
                    if existing["original_question_sources"]
                    else []
                )
            except Exception:
                orig_qs, orig_qs_src = [], []
            old_urls = {
                source.get("url")
                for source in sources
                if isinstance(source, dict) and source.get("url")
            }
            old_questions = {
                normalize_original_question(question) for question in orig_qs
            }
            sources.append(new_source)
            if new_q_text:
                orig_qs.append(new_q_text)
                orig_qs_src.append({"question": new_q_text, "sources": [new_source]})
            sources, orig_qs, orig_qs_src = canonicalize_question_bank_payload(
                sources, orig_qs, orig_qs_src
            )
            url_is_new = bool(url and url not in old_urls)
            q_is_new = bool(
                new_q_text
                and normalize_original_question(new_q_text) not in old_questions
            )
            cursor.execute(
                "UPDATE question_bank SET frequency = ?, sources = ?, original_questions = ?, "
                "original_question_sources = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (
                    len(orig_qs),
                    json.dumps(sources, ensure_ascii=False),
                    json.dumps(orig_qs, ensure_ascii=False),
                    json.dumps(orig_qs_src, ensure_ascii=False),
                    qb_id,
                ),
            )
            claim_public_original_questions(
                cursor.connection,
                qb_id,
                existing["owner_id"],
                existing["status"],
                orig_qs,
            )
            sync_question_bank_projections(
                cursor, qb_id, sources, orig_qs, orig_qs_src
            )
            if url_is_new or q_is_new:
                from app.services.cluster_review_lifecycle import mark_cluster_review_pending

                mark_cluster_review_pending(cursor.connection, qb_id, "new_variant_matched")

    # Cache job_positions lookup before loop (current_pos doesn't change)
    pos_row_cache = cursor.execute(
        "SELECT id FROM job_positions WHERE name = ?", (current_pos,)
    ).fetchone()
    for item in unmatched_rows:
        row = item.get("_orig_row") if isinstance(item, dict) else item
        item_id = item.get("id") if isinstance(item, dict) else None
        url, company, round_, q_text = row[0], row[1], row[2], row[3]
        cat1 = normalize_category(row[4])
        cat2 = normalize_category(row[5]) if len(row) > 5 else ""
        tags = row[6] if len(row) > 6 else ""
        diff_tag = row[7] if len(row) > 7 else "未知"
        sources_json = json.dumps(
            [{"url": url, "company": company, "round": round_}], ensure_ascii=False
        )
        sources, original_questions, original_question_sources = (
            canonicalize_question_bank_payload(
                [{"url": url, "company": company, "round": round_}],
                [q_text],
                [
                    {
                        "question": q_text,
                        "sources": [
                            {"url": url, "company": company, "round": round_}
                        ],
                    }
                ],
            )
        )
        oqs_json = json.dumps(original_question_sources, ensure_ascii=False)
        cursor.execute(
            "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, sources, original_questions, original_question_sources, owner_id, submitted_by, status, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                q_text,
                cat1,
                cat2,
                tags,
                diff_tag,
                json.dumps(sources, ensure_ascii=False),
                json.dumps(original_questions, ensure_ascii=False),
                oqs_json,
                owner_id,
                submitter_id,
                status,
                current_pos,
            ),
        )
        new_id = cursor.lastrowid
        # 设置 cluster_id = 自身 id（新建题目自己就是聚类代表）
        cursor.execute(
            "UPDATE question_bank SET cluster_id = ? WHERE id = ?", (new_id, new_id)
        )
        # BUG-008: 同步 question_position 关联表，否则新题在主库 INNER JOIN 查询中不可见
        if pos_row_cache:
            cursor.execute(
                "INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, ?)",
                (new_id, pos_row_cache[0]),
            )
        claim_public_original_questions(
            cursor.connection, new_id, owner_id, status, original_questions
        )
        sync_question_bank_projections(
            cursor,
            new_id,
            sources,
            original_questions,
            original_question_sources,
        )
        if status == "approved" and owner_id is None:
            from app.services.cluster_review_lifecycle import mark_cluster_review_pending

            mark_cluster_review_pending(cursor.connection, new_id, "new_cluster")
        if status == "approved":
            answer_tasks.append((new_id, q_text))

    return answer_tasks


# ═══════════════════════════════════════════════════
#  事务编排器（三个业务操作各对应一个）
# ═══════════════════════════════════════════════════


def submit_interview_txn(
    saved_url,
    data,
    questions,
    season,
    owner_id,
    status,
    job_position,
    tagged_rows,
    matched,
    unmatched_rows,
    idx_to_row,
    submitter_is_admin,
    user_id,
    qb_owner_id=None,
):
    """操作3 提交新面经：insert_interview + insert_details + incremental_update。

    qb_owner_id: question_bank 中 unmatched 新建行的 owner_id（个人题库传 user_id）。
    单事务，全部成功或全部回滚。
    返回 (answer_tasks, interview_id)。
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN")
            _insert_interview_txn(
                cursor,
                saved_url,
                data,
                questions,
                season,
                owner_id,
                status,
                job_position,
            )
            interview_id = cursor.lastrowid
            _insert_details_txn(
                cursor, tagged_rows, job_position, interview_id=interview_id
            )
            answer_tasks = _apply_incremental_txn(
                cursor,
                matched,
                unmatched_rows,
                idx_to_row,
                submitter_is_admin,
                user_id,
                job_position,
                owner_id=qb_owner_id,
            )
            conn.commit()
            return answer_tasks, interview_id
        except Exception as e:
            conn.rollback()
            if "UNIQUE" in str(e):
                raise ValueError("该 URL 已存在，不可重复上传")
            raise


def submit_interview_txn_tag_only(
    saved_url, data, questions, season, owner_id, status, job_position, tagged_rows
):
    """提交新面经（仅打标签）：insert_interview + insert_details，不做聚类。

    聚类由两阶段流水线的阶段2负责。
    单事务，返回 interview_id。
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN")
            _insert_interview_txn(
                cursor,
                saved_url,
                data,
                questions,
                season,
                owner_id,
                status,
                job_position,
            )
            interview_id = cursor.lastrowid
            _insert_details_txn(
                cursor, tagged_rows, job_position, interview_id=interview_id
            )
            conn.commit()
            return interview_id
        except Exception as e:
            conn.rollback()
            if "UNIQUE" in str(e):
                raise ValueError("该 URL 已存在，不可重复上传")
            raise


def sync_interview_details(
    interview_id,
    url,
    tagged_rows,
    job_position,
    matched,
    unmatched_rows,
    idx_to_row,
    submitter_is_admin,
    user_id,
):
    """操作1 重新分析面经：cleanup + replace_details + incremental_update。

    单事务，全部成功或全部回滚。
    返回 answer_tasks。
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN")
            _cleanup_old_sources_txn(cursor, url)
            _replace_details_txn(cursor, interview_id, url, tagged_rows, job_position)
            answer_tasks = _apply_incremental_txn(
                cursor,
                matched,
                unmatched_rows,
                idx_to_row,
                submitter_is_admin,
                user_id,
                job_position,
            )
            conn.commit()
            return answer_tasks
        except Exception:
            conn.rollback()
            raise


# ═══════════════════════════════════════════════════
#  个人题库（无需聚类，直接插入）
# ═══════════════════════════════════════════════════


def insert_personal_questions_txn(tagged_rows, user_id, job_position):
    """个人题库：直接插入 question_bank，不做聚类匹配。

    返回 answer_tasks。
    """
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            cursor.execute("BEGIN")
            answer_tasks = []
            # Cache job_positions lookup before loop (job_position doesn't change)
            pos_row_cache = cursor.execute(
                "SELECT id FROM job_positions WHERE name = ?", (job_position,)
            ).fetchone()
            for row in tagged_rows:
                url, company, round_, q_text = row[0], row[1], row[2], row[3]
                cat1 = normalize_category(row[4])
                cat2 = normalize_category(row[5]) if len(row) > 5 else ""
                tags = row[6] if len(row) > 6 else ""
                diff_tag = row[7] if len(row) > 7 else "未知"
                sources_json = json.dumps(
                    [{"url": url, "company": company, "round": round_}],
                    ensure_ascii=False,
                )
                cursor.execute(
                    "INSERT INTO question_bank (question, cat1, cat2, tags, difficulty, frequency, sources, owner_id, submitted_by, status, job_position) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, 'approved', ?)",
                    (
                        q_text,
                        cat1,
                        cat2,
                        tags,
                        diff_tag,
                        sources_json,
                        user_id,
                        user_id,
                        job_position,
                    ),
                )
                new_id = cursor.lastrowid
                if pos_row_cache:
                    cursor.execute(
                        "INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, ?)",
                        (new_id, pos_row_cache[0]),
                    )
                sync_question_bank_projections(
                    cursor,
                    new_id,
                    [{"url": url, "company": company, "round": round_}],
                    [],
                    [],
                )
                answer_tasks.append((new_id, q_text))
            conn.commit()
            return answer_tasks
        except Exception:
            conn.rollback()
            raise


# ═══════════════════════════════════════════════════
#  JD 插入（独立操作，不涉及聚类）
# ═══════════════════════════════════════════════════


def _insert_jd(
    saved_url: str,
    data: dict,
    tech_stack: str,
    season: str = "",
    owner_id: int = None,
    status: str = "approved",
    job_position: str = "",
):
    with get_db_connection() as conn:
        sig = _extract_url_signature(saved_url)
        try:
            conn.execute(
                "INSERT INTO jd (url, company, job_title, salary, tech_stack, bonus, season, owner_id, status, url_signature, job_position) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    saved_url,
                    data.get("公司", "未提供"),
                    data.get("岗位名称", "未提供"),
                    data.get("薪资范围", "未提供"),
                    tech_stack,
                    data.get("加分项", "未提供"),
                    season,
                    owner_id,
                    status,
                    sig,
                    job_position,
                ),
            )
            conn.commit()
        except Exception as e:
            if "UNIQUE" in str(e):
                raise ValueError("该 URL 已存在，不可重复上传")
            raise


def _insert_interview(
    saved_url: str,
    data: dict,
    questions: str,
    season: str = "",
    owner_id: int = None,
    status: str = "approved",
    job_position: str = "",
):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        try:
            _insert_interview_txn(
                cursor,
                saved_url,
                data,
                questions,
                season,
                owner_id,
                status,
                job_position,
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            if "UNIQUE" in str(e):
                raise ValueError("该 URL 已存在，不可重复上传")
            raise


# ═══════════════════════════════════════════════════
#  分类体系权限管理
# ═══════════════════════════════════════════════════


def get_taxonomy_by_id(taxonomy_id: int) -> dict:
    """根据ID获取分类体系"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, position_name, categories_json, source, owner_id, is_public FROM taxonomy WHERE id = ?",
            (taxonomy_id,),
        ).fetchone()
        if not row:
            return None
        return {
            "id": row[0],
            "position_name": row[1],
            "categories": json.loads(row[2]) if row[2] else [],
            "source": row[3] or "system",
            "owner_id": row[4],
            "is_public": row[5] or 0,
        }


async def update_taxonomy_permissions(
    taxonomy_id: int, categories: list, user: dict
) -> dict:
    """更新分类体系（带权限检查）"""
    taxonomy = get_taxonomy_by_id(taxonomy_id)
    if not taxonomy:
        raise ValueError("分类体系不存在")

    # 权限检查
    if taxonomy["source"] == "system" and not user.get("is_admin"):
        raise PermissionError("只有管理员可以编辑系统分类")

    if taxonomy["source"] == "user" and taxonomy["owner_id"] != user["id"]:
        raise PermissionError("无权编辑此分类")

    # 更新分类
    categories_json = json.dumps(categories, ensure_ascii=False)
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE taxonomy SET categories_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (categories_json, taxonomy_id),
        )
        conn.commit()

    return {
        "success": True,
        "taxonomy": {
            "id": taxonomy_id,
            "categories": categories,
            "source": taxonomy["source"],
            "owner_id": taxonomy["owner_id"],
        },
    }


async def create_personal_taxonomy(position: str, categories: list, user: dict) -> dict:
    """创建个人分类体系"""
    categories_json = json.dumps(categories, ensure_ascii=False)
    with get_db_connection() as conn:
        # 检查用户是否已有该岗位的个人分类
        existing = conn.execute(
            "SELECT id FROM taxonomy WHERE position_name = ? AND source = 'user' AND owner_id = ?",
            (position, user["id"]),
        ).fetchone()

        if existing:
            # 更新现有分类
            conn.execute(
                "UPDATE taxonomy SET categories_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (categories_json, existing[0]),
            )
            taxonomy_id = existing[0]
        else:
            # 创建新分类
            cursor = conn.execute(
                "INSERT INTO taxonomy (position_name, categories_json, source, owner_id) VALUES (?, ?, 'user', ?)",
                (position, categories_json, user["id"]),
            )
            taxonomy_id = cursor.lastrowid

        conn.commit()

    return {
        "success": True,
        "taxonomy": {
            "id": taxonomy_id,
            "position_name": position,
            "categories": categories,
            "source": "user",
            "owner_id": user["id"],
        },
    }


async def share_taxonomy(taxonomy_id: int, user: dict) -> dict:
    """分享分类体系（设为公开）"""
    taxonomy = get_taxonomy_by_id(taxonomy_id)
    if not taxonomy:
        raise ValueError("分类体系不存在")

    # 只能分享自己的分类
    if taxonomy["source"] != "user" or taxonomy["owner_id"] != user["id"]:
        raise PermissionError("只能分享自己的分类")

    with get_db_connection() as conn:
        conn.execute(
            "UPDATE taxonomy SET is_public = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (taxonomy_id,),
        )
        conn.commit()

    return {"success": True, "taxonomy": {"id": taxonomy_id, "is_public": 1}}


def delete_taxonomy_by_id(taxonomy_id: int) -> bool:
    """删除分类体系（管理员用）"""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id FROM taxonomy WHERE id = ?", (taxonomy_id,)
        ).fetchone()
        if not row:
            return False
        conn.execute("DELETE FROM taxonomy WHERE id = ?", (taxonomy_id,))
        conn.commit()
        return True


async def get_public_shared_taxonomies(user: dict) -> list:
    """获取公开分享的分类体系列表"""
    with get_db_connection() as conn:
        rows = conn.execute(
            """SELECT t.id, t.position_name, t.categories_json, t.source, t.owner_id, t.is_public, u.username
               FROM taxonomy t
               LEFT JOIN users u ON t.owner_id = u.id
               WHERE t.is_public = 1"""
        ).fetchall()

    return [
        {
            "id": row[0],
            "position_name": row[1],
            "categories": json.loads(row[2]) if row[2] else [],
            "source": row[3] or "system",
            "is_public": row[5] or 0,
            "owner_name": row[6] or "匿名",
        }
        for row in rows
    ]


def query_public_taxonomies() -> list:
    """查询公开分享的分类体系"""
    with get_db_connection() as conn:
        rows = conn.execute(
            """SELECT t.id, t.position_name, t.categories_json, t.source, t.owner_id, t.is_public, u.username
               FROM taxonomy t
               LEFT JOIN users u ON t.owner_id = u.id
               WHERE t.is_public = 1"""
        ).fetchall()

    return [
        {
            "id": row[0],
            "position_name": row[1],
            "categories": json.loads(row[2]) if row[2] else [],
            "source": row[3] or "system",
            "owner_id": row[4],
            "is_public": row[5] or 0,
            "owner_name": row[6] or "匿名",
        }
        for row in rows
    ]


# ── Cross-conversation question dedup ────────────────────────────────────────


def record_asked_question(conn, user_id: int, conversation_id: str, question_id: int):
    """Record that a question was asked to a user (for cross-conversation dedup)."""
    conn.execute(
        "INSERT INTO interview_asked_questions (user_id, conversation_id, question_id) "
        "VALUES (?, ?, ?)",
        (user_id, conversation_id, question_id),
    )


def get_asked_question_ids(conn, user_id: int) -> set[int]:
    """Get all question IDs ever asked to a user across all conversations."""
    rows = conn.execute(
        "SELECT DISTINCT question_id FROM interview_asked_questions WHERE user_id = ?",
        (user_id,),
    ).fetchall()
    return {row[0] for row in rows}
