import json
import re
import logging
import sqlite3
from fastapi import APIRouter, HTTPException, Query, Depends
from app.core.config import ALLOWED_UPDATE_COLUMNS
from app.core.auth import get_current_user, get_admin_user
from app.core.validation import validate_source_url
from app.db.connection import (
    get_db_connection,
    run_db,
)
from app.db.question_bank_sources import (
    restore_source_for_url,
    sync_question_bank_sources,
    get_original_question_sources,
    get_original_questions,
    get_sources,
)
from app.models.schemas import GenericUpdateRequest, BatchDataDeleteRequest
from app.db.operations import (
    _mark_distribution_refresh_for_detail_ids_txn,
    _mark_distribution_refresh_for_interview_txn,
    _retype_distribution_details_txn,
)

logger = logging.getLogger("interview-boss")

router = APIRouter()

# ── 表名白名单：防止 SQL 注入 ──
_ALLOWED_TABLES = {"jd", "interview", "questions_detail", "question_bank"}


def _row_value(row, key, default=None):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _safe_table_name(name: str) -> str:
    """验证表名是否在白名单中，防止 SQL 注入"""
    if name not in _ALLOWED_TABLES:
        raise ValueError(f"不被允许的表名: {name}")
    return name


def _cleanup_sources_for_url(cursor, url: str, owner_scope=None):
    """清理 question_bank 中指向指定 URL 的所有贡献：sources、original_questions、original_question_sources。

    只清理 owner_scope 限定范围内的题（`owner_id IS ?`，NULL 匹配公共题），
    绝不触碰他人私有题或公共题。frequency=0 的目标 QB 及其 question_position 一并删除。
    """
    # Normalized rows are the fast path, while the JSON columns remain the
    # repair path.  A previous delete can leave one representation updated
    # and the other untouched, so using only one of them is not sufficient.
    affected_ids = set()
    try:
        normalized_rows = cursor.execute(
            "SELECT DISTINCT qs.question_bank_id FROM question_sources qs "
            "JOIN question_bank qb ON qb.id = qs.question_bank_id "
            "WHERE qs.url = ? AND qb.owner_id IS ?",
            (url, owner_scope),
        ).fetchall()
        for row in normalized_rows:
            try:
                affected_ids.add(row[0])
            except (KeyError, TypeError, IndexError):
                # Keep lightweight legacy mocks/databases on the JSON path.
                continue
    except sqlite3.OperationalError:
        # Older/test databases may not have the normalized source table yet.
        pass
    try:
        normalized_original_rows = cursor.execute(
            "SELECT DISTINCT qoi.question_bank_id "
            "FROM question_original_item_sources qois "
            "JOIN question_original_items qoi ON qoi.id = qois.original_item_id "
            "JOIN question_bank qb ON qb.id = qoi.question_bank_id "
            "WHERE qois.url = ? AND qb.owner_id IS ?",
            (url, owner_scope),
        ).fetchall()
        for row in normalized_original_rows:
            try:
                affected_ids.add(row[0])
            except (KeyError, TypeError, IndexError):
                continue
    except sqlite3.OperationalError:
        pass

    try:
        json_rows = cursor.execute(
            "SELECT id, owner_id, sources, original_questions, original_question_sources "
            "FROM question_bank WHERE (sources LIKE ? OR original_question_sources LIKE ?) "
            "AND owner_id IS ?",
            (f"%{url}%", f"%{url}%", owner_scope),
        ).fetchall()
    except sqlite3.OperationalError:
        json_rows = []
    affected = {r["id"]: r for r in json_rows}

    if affected_ids:
        placeholders = ",".join("?" * len(affected_ids))
        normalized_qb_rows = cursor.execute(
            f"SELECT id, owner_id, sources, original_questions, original_question_sources "
            f"FROM question_bank WHERE id IN ({placeholders})",
            tuple(affected_ids),
        ).fetchall()
        affected.update({r["id"]: r for r in normalized_qb_rows})

    ids_to_delete = []
    for r in affected.values():
        try:
            sources = json.loads(r["sources"]) if r["sources"] else []
        except Exception:
            sources = []
        try:
            oqs = json.loads(r["original_questions"]) if r["original_questions"] else []
        except Exception:
            oqs = []
        try:
            oqs_sources = (
                json.loads(r["original_question_sources"])
                if r["original_question_sources"]
                else []
            )
        except Exception:
            oqs_sources = []

        new_sources = [s for s in sources if s.get("url") != url]
        # oqs_sources 结构: [{question, sources: [{url, ...}]}]
        new_oqs_sources = []
        removed_questions = set()
        for item in oqs_sources:
            item_sources = item.get("sources", []) if isinstance(item, dict) else []
            remaining_sources = [
                source for source in item_sources if source.get("url") != url
            ]
            if remaining_sources:
                new_oqs_sources.append({**item, "sources": remaining_sources})
            elif any(source.get("url") == url for source in item_sources):
                removed_questions.add(item.get("question", ""))
            else:
                # Keep malformed/source-less legacy entries intact.  They are
                # not evidence that this URL contributed the original item.
                new_oqs_sources.append(item)
        new_oqs = [q for q in oqs if q not in removed_questions]

        sources_changed = len(new_sources) != len(sources)
        oqs_sources_changed = len(new_oqs_sources) != len(oqs_sources)
        oqs_changed = len(new_oqs) != len(oqs)

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
                    r["id"],
                ),
            )
        if len(new_sources) == 0 and r["id"] not in ids_to_delete:
            # The JSON projection can already be stale or empty after an
            # earlier half-write.  Normalized rows still identify this QB as
            # affected, so an empty repaired source set must also soft-delete
            # the source-less public row.
            ids_to_delete.append(r["id"])

        # Keep the normalized tables and JSON compatibility fields in the
        # same outer transaction.  This also repairs a previous half-write
        # where only one representation had lost the URL.
        sync_question_bank_sources(
            cursor,
            r["id"],
            new_sources,
            new_oqs,
            new_oqs_sources,
        )
        if r["owner_id"] is None and (sources_changed or oqs_sources_changed):
            _mark_cluster_review_pending_if_available(cursor, r["id"], "source_removed")

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

def _mark_cluster_review_pending_if_available(cursor, cluster_id: int, reason: str):
    """Mark review metadata only when the complete review schema is present.

    Review metadata is optional on legacy/test databases.  Source cleanup is
    still strict: any error from the review tables that do exist propagates to
    the outer transaction and rolls the deletion back.
    """
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


def _cleanup_sources_in_txn(cursor, url: str, owner_scope=None):
    """Clean source projections as part of the caller's transaction.

    There is intentionally no best-effort savepoint here.  A source cleanup
    failure must roll back the interview and detail soft-delete as well, so a
    successful response never advertises a half-deleted record.
    """
    if url:
        _cleanup_sources_for_url(cursor, url, owner_scope)


def _delete_interview_txn(cursor, record_id: int, target_row):
    """Soft-delete one interview and all of its derived data in one txn.

    Details are scoped by interview_id whenever available.  URL is only the
    legacy fallback for rows that predate that relation, preventing two
    interviews that happen to share a URL from deleting each other's details.
    """
    _mark_distribution_refresh_for_interview_txn(cursor, record_id)

    detail_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(questions_detail)").fetchall()
    }
    url = target_row["url"]
    owner_scope = target_row["owner_id"]
    if "interview_id" in detail_columns:
        if url and "owner_id" in detail_columns:
            cursor.execute(
                "UPDATE questions_detail SET deleted_at = CURRENT_TIMESTAMP "
                "WHERE deleted_at IS NULL AND "
                "(interview_id = ? OR (interview_id IS NULL AND url = ? AND owner_id IS ?))",
                (record_id, url, owner_scope),
            )
        elif url:
            # Current production migrations have interview_id but do not have
            # a detail-level owner_id.  Use the durable interview relation and
            # only fall back to URL for legacy orphan details.
            cursor.execute(
                "UPDATE questions_detail SET deleted_at = CURRENT_TIMESTAMP "
                "WHERE deleted_at IS NULL AND "
                "(interview_id = ? OR (interview_id IS NULL AND url = ?))",
                (record_id, url),
            )
        else:
            cursor.execute(
                "UPDATE questions_detail SET deleted_at = CURRENT_TIMESTAMP "
                "WHERE interview_id = ? AND deleted_at IS NULL",
                (record_id,),
            )
    elif url:
        # Compatibility with databases created before interview_id was added.
        if "owner_id" in detail_columns:
            cursor.execute(
                "UPDATE questions_detail SET deleted_at = CURRENT_TIMESTAMP "
                "WHERE url = ? AND owner_id IS ? AND deleted_at IS NULL",
                (url, owner_scope),
            )
        else:
            cursor.execute(
                "UPDATE questions_detail SET deleted_at = CURRENT_TIMESTAMP "
                "WHERE url = ? AND deleted_at IS NULL",
                (url,),
            )

    cursor.execute(
        "UPDATE interview SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP) "
        "WHERE id = ?",
        (record_id,),
    )
    has_active_sibling = bool(
        url
        and cursor.execute(
            "SELECT 1 FROM interview WHERE id != ? AND url = ? AND owner_id IS ? "
            "AND deleted_at IS NULL LIMIT 1",
            (record_id, url, owner_scope),
        ).fetchone()
    )
    if not has_active_sibling:
        _cleanup_sources_in_txn(cursor, url, owner_scope)


def _restore_sources_for_url(cursor, url: str, owner_scope=None):
    """Restore normalized source links, then rebuild the JSON projections."""
    normalized_ids = restore_source_for_url(cursor, url, owner_scope)
    if normalized_ids:
        placeholders = ",".join("?" * len(normalized_ids))
        rows = cursor.execute(
            f"SELECT id, owner_id, deleted_at FROM question_bank WHERE id IN ({placeholders})",
            normalized_ids,
        ).fetchall()
        for row in rows:
            qb_id = row["id"]
            sources = get_sources(cursor, qb_id)
            original_questions = get_original_questions(cursor, qb_id)
            original_question_sources = get_original_question_sources(cursor, qb_id)
            cursor.execute(
                "UPDATE question_bank SET deleted_at = NULL, frequency = ?, sources = ?, "
                "original_questions = ?, original_question_sources = ?, "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (
                    max(1, len(original_questions)),
                    json.dumps(sources, ensure_ascii=False),
                    json.dumps(original_questions, ensure_ascii=False),
                    json.dumps(original_question_sources, ensure_ascii=False),
                    qb_id,
                ),
            )
            if row["deleted_at"] is not None:
                pos_row = cursor.execute(
                    "SELECT id FROM job_positions WHERE name = ("
                    "SELECT job_position FROM question_bank WHERE id = ?)",
                    (qb_id,),
                ).fetchone()
                if pos_row:
                    cursor.execute(
                        "INSERT OR IGNORE INTO question_position (question_id, position_id) VALUES (?, ?)",
                        (qb_id, pos_row[0]),
                    )
            if row["owner_id"] is None:
                _mark_cluster_review_pending_if_available(
                    cursor, qb_id, "source_restored"
                )
        return

    # Legacy fallback: before normalized source rows existed, the source was
    # recoverable only from JSON.  Keep this path for old databases, but keep
    # the same owner scope and transaction semantics.
    rows = cursor.execute(
        "SELECT id, owner_id, sources, original_questions, original_question_sources, deleted_at "
        "FROM question_bank WHERE original_question_sources LIKE ? AND owner_id IS ?",
        (f"%{url}%", owner_scope),
    ).fetchall()
    for row in rows:
        try:
            sources = json.loads(_row_value(row, "sources") or "[]")
            original_questions = json.loads(
                _row_value(row, "original_questions") or "[]"
            )
            original_question_sources = json.loads(
                _row_value(row, "original_question_sources") or "[]"
            )
        except (TypeError, ValueError):
            continue
        source_by_url = {
            source.get("url"): source
            for item in original_question_sources
            for source in item.get("sources", [])
            if source.get("url")
        }
        source = source_by_url.get(url)
        if not source or any(item.get("url") == url for item in sources):
            continue
        sources.append(source)
        cursor.execute(
            "UPDATE question_bank SET deleted_at = NULL, frequency = ?, sources = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (
                max(1, len(original_questions)),
                json.dumps(sources, ensure_ascii=False),
                _row_value(row, "id"),
            ),
        )


@router.get("/api/data/{file_type}")
async def get_data(
    file_type: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_current_user),
):
    table_map = {"jd": "jd", "interview": "interview", "tagged": "questions_detail"}
    table_name = table_map.get(file_type.lower())
    if not table_name:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    offset = (page - 1) * page_size

    def _query():
        safe_name = _safe_table_name(table_name)
        with get_db_connection() as conn:
            if table_name in ("jd", "interview"):
                # all 口径：公共 + 自己的（管理员也遵守）
                from app.db.connection import get_user_job_position

                _, current_pos = get_user_job_position(user["id"])
                where = "(owner_id = ? OR (owner_id IS NULL AND status = 'approved')) AND deleted_at IS NULL AND (job_position = ? OR job_position = '' OR job_position IS NULL)"
                params = (user["id"], current_pos)
                total = conn.execute(
                    f"SELECT COUNT(*) FROM {safe_name} WHERE {where}", params
                ).fetchone()[0]
                if table_name == "jd":
                    rows = conn.execute(
                        f"SELECT id, url, company, job_title, salary, tech_stack, bonus, season, owner_id FROM {safe_name} WHERE {where} ORDER BY id ASC LIMIT ? OFFSET ?",
                        (*params, page_size, offset),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        f"SELECT id, url, company, round, focus, questions_list, difficulty, season, owner_id, created_at FROM {safe_name} WHERE {where} ORDER BY id ASC LIMIT ? OFFSET ?",
                        (*params, page_size, offset),
                    ).fetchall()
            else:  # questions_detail
                join_where = "(iv.owner_id = ? OR (iv.owner_id IS NULL AND iv.status = 'approved')) AND iv.deleted_at IS NULL AND qd.deleted_at IS NULL"
                params = (user["id"],)
                total = conn.execute(
                    f"SELECT COUNT(*) FROM {safe_name} qd JOIN interview iv ON qd.url = iv.url WHERE {join_where}",
                    params,
                ).fetchone()[0]
                rows = conn.execute(
                    f"SELECT qd.id, qd.url, qd.company, qd.round, qd.question, qd.cat1, qd.cat2, qd.tags, qd.diff_tag "
                    f"FROM {safe_name} qd JOIN interview iv ON qd.url = iv.url "
                    f"WHERE {join_where} ORDER BY qd.id ASC LIMIT ? OFFSET ?",
                    (*params, page_size, offset),
                ).fetchall()
            return total, rows

    total, rows = await run_db(_query)

    result = []
    for r in rows:
        d = dict(r)
        if table_name == "jd":
            result.append(
                {
                    "id": d["id"],
                    "来源链接": d["url"],
                    "公司": d["company"],
                    "岗位名称": d["job_title"],
                    "薪资范围": d["salary"],
                    "核心技术要求": d["tech_stack"],
                    "加分项": d["bonus"],
                    "season": d.get("season", ""),
                    "owner_id": d.get("owner_id"),
                }
            )
        elif table_name == "interview":
            result.append(
                {
                    "id": d["id"],
                    "来源链接": d["url"],
                    "公司": d["company"],
                    "面试轮次": d["round"],
                    "考察重点": d["focus"],
                    "具体题目清单": d["questions_list"],
                    "难易程度": d["difficulty"],
                    "season": d.get("season", ""),
                    "owner_id": d.get("owner_id"),
                    "created_at": d.get("created_at", ""),
                }
            )
        elif table_name == "questions_detail":
            result.append(
                {
                    "id": d["id"],
                    "来源链接": d["url"],
                    "公司": d["company"],
                    "面试轮次": d["round"],
                    "题目": d["question"],
                    "一级大类": d["cat1"],
                    "二级子类": d["cat2"],
                    "考点标签": d["tags"],
                    "难度标签": d["diff_tag"],
                }
            )
    return {"items": result, "total": total, "page": page, "page_size": page_size}


@router.delete("/api/data/{file_type}/{record_id}")
async def delete_data(
    file_type: str, record_id: int, user: dict = Depends(get_current_user)
):
    """软删除记录：设置 deleted_at 而非物理删除。管理员可删任何记录，普通用户可删自己的个人记录。"""
    table_map = {"jd": "jd", "interview": "interview", "tagged": "questions_detail"}
    table_name = table_map.get(file_type.lower())
    if not table_name:
        raise HTTPException(status_code=400, detail="不支持的表类型")

    def _soft_delete():
        safe_name = _safe_table_name(table_name)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            target_columns = (
                "id, url, owner_id, status, job_position, deleted_at"
                if table_name in {"jd", "interview"}
                else "id, url, NULL AS owner_id, NULL AS status, '' AS job_position, deleted_at"
            )
            target_row = cursor.execute(
                f"SELECT {target_columns} FROM {safe_name} WHERE id = ?",
                (record_id,),
            ).fetchone()
            if not target_row:
                raise HTTPException(
                    status_code=404, detail="未找到该记录"
                )

            # 权限检查：admin 可删任何，普通用户只能删自己的
            is_admin = user.get("is_admin", 0)
            if (
                not is_admin
                and target_row["owner_id"] is not None
                and target_row["owner_id"] != user["id"]
            ):
                raise HTTPException(status_code=403, detail="无权删除他人的记录")
            if not is_admin and target_row["owner_id"] is None:
                raise HTTPException(status_code=403, detail="无权删除公共记录")

            url = target_row["url"]

            if table_name == "jd":
                if url:
                    # BUG-017: 先清理关联面经在 question_bank 中的 sources（仅限同一 owner 范围）
                    owner_scope = target_row["owner_id"]
                    interview_urls = cursor.execute(
                        "SELECT DISTINCT url FROM interview WHERE url = ? AND deleted_at IS NULL",
                        (url,),
                    ).fetchall()
                    for iu in interview_urls:
                        if iu["url"]:
                            _cleanup_sources_in_txn(cursor, iu["url"], owner_scope)
                    # 级联软删除关联的 interview 和 questions_detail（仅限同一 owner 范围）
                    cursor.execute(
                        "UPDATE interview SET deleted_at = CURRENT_TIMESTAMP "
                        "WHERE url = ? AND owner_id IS ? AND deleted_at IS NULL",
                        (url, owner_scope),
                    )
                    cursor.execute(
                        "UPDATE questions_detail SET deleted_at = CURRENT_TIMESTAMP "
                        "WHERE url = ? AND owner_id IS ? AND deleted_at IS NULL",
                        (url, owner_scope),
                    )

            if table_name == "interview":
                _delete_interview_txn(cursor, record_id, target_row)

            if table_name == "questions_detail":
                _mark_distribution_refresh_for_detail_ids_txn(cursor, [record_id])

            # interview 已由 _delete_interview_txn 完成主记录更新。
            if table_name != "interview":
                cursor.execute(
                    f"UPDATE {safe_name} SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP) WHERE id = ?",
                    (record_id,),
                )
            conn.commit()

    try:
        await run_db(_soft_delete)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("操作失败")
        raise HTTPException(status_code=500, detail="操作失败，请查看服务端日志")


@router.post("/api/data/batch-delete")
async def batch_delete_data(
    req: BatchDataDeleteRequest, user: dict = Depends(get_admin_user)
):
    """批量软删除记录"""
    table_map = {"jd": "jd", "interview": "interview"}
    table_name = table_map.get(req.file_type.lower())
    if not table_name:
        raise HTTPException(
            status_code=400, detail="不支持的表类型，仅支持 jd 和 interview"
        )
    if not req.ids:
        raise HTTPException(status_code=400, detail="ids 不能为空")

    def _batch_soft_delete():
        safe_name = _safe_table_name(table_name)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(req.ids))
            rows = cursor.execute(
                (
                    f"SELECT id, url, owner_id, status, job_position, deleted_at "
                    f"FROM {safe_name} WHERE id IN ({placeholders}) AND deleted_at IS NULL"
                    if table_name == "interview"
                    else f"SELECT id, url, owner_id FROM {safe_name} "
                    f"WHERE id IN ({placeholders}) AND deleted_at IS NULL"
                ),
                req.ids,
            ).fetchall()
            if not rows:
                raise HTTPException(status_code=404, detail="未找到任何匹配记录")

            urls_to_delete = {r["url"] for r in rows if r["url"]}

            if table_name == "jd":
                for url in urls_to_delete:
                    # BUG-017: 先清理关联面经在 question_bank 中的 sources
                    owner_scope = next(
                        (row["owner_id"] for row in rows if row["url"] == url), None
                    )
                    _cleanup_sources_in_txn(cursor, url, owner_scope)
                    cursor.execute(
                        "UPDATE interview SET deleted_at = CURRENT_TIMESTAMP "
                        "WHERE url = ? AND owner_id IS ? AND deleted_at IS NULL",
                        (url, owner_scope),
                    )
                    cursor.execute(
                        "UPDATE questions_detail SET deleted_at = CURRENT_TIMESTAMP "
                        "WHERE url = ? AND owner_id IS ? AND deleted_at IS NULL",
                        (url, owner_scope),
                    )

            if table_name == "interview":
                for row in rows:
                    _delete_interview_txn(cursor, row["id"], row)

            # jd 批量删除一次性更新主记录；interview 已逐条复用幂等删除逻辑。
            found_ids = [r["id"] for r in rows]
            if table_name == "jd":
                ph2 = ",".join("?" * len(found_ids))
                cursor.execute(
                    f"UPDATE {safe_name} SET deleted_at = COALESCE(deleted_at, CURRENT_TIMESTAMP) WHERE id IN ({ph2})",
                    found_ids,
                )
            conn.commit()
            return len(found_ids)

    try:
        deleted = await run_db(_batch_soft_delete)
        return {"status": "success", "deleted": deleted}
    except HTTPException:
        raise
    except Exception:
        logger.exception("批量删除失败")
        raise HTTPException(status_code=500, detail="操作失败，请查看服务端日志")


@router.post("/api/data/restore/{file_type}/{record_id}")
async def restore_data(
    file_type: str, record_id: int, user: dict = Depends(get_admin_user)
):
    """恢复软删除的记录"""
    table_map = {"jd": "jd", "interview": "interview", "tagged": "questions_detail"}
    table_name = table_map.get(file_type.lower())
    if not table_name:
        raise HTTPException(status_code=400, detail="不支持的表类型")

    def _restore():
        safe_name = _safe_table_name(table_name)
        with get_db_connection() as conn:
            cursor = conn.cursor()
            target_row = cursor.execute(
                f"SELECT id, url, owner_id FROM {safe_name} WHERE id = ? AND deleted_at IS NOT NULL",
                (record_id,),
            ).fetchone()
            if not target_row:
                raise HTTPException(status_code=404, detail="未找到该已删除记录")

            url = target_row["url"]
            owner_scope = target_row["owner_id"]

            # 恢复目标记录
            cursor.execute(
                f"UPDATE {safe_name} SET deleted_at = NULL WHERE id = ?", (record_id,)
            )

            if table_name == "jd" and url:
                # JD 恢复时级联恢复关联的 interview 和 questions_detail
                cursor.execute(
                    "UPDATE interview SET deleted_at = NULL WHERE url = ?", (url,)
                )
                cursor.execute(
                    "UPDATE questions_detail SET deleted_at = NULL WHERE url = ?",
                    (url,),
                )

            if table_name == "interview" and url:
                # interview 恢复时级联恢复关联的 questions_detail
                cursor.execute(
                    "UPDATE questions_detail SET deleted_at = NULL WHERE url = ?",
                    (url,),
                )
                # BUG-018: 从 original_question_sources 中恢复该 URL 对应的 source 条目
                _restore_sources_for_url(cursor, url, owner_scope)

            if table_name == "interview":
                _mark_distribution_refresh_for_interview_txn(cursor, record_id)
            if table_name == "questions_detail":
                _mark_distribution_refresh_for_detail_ids_txn(cursor, [record_id])

            if table_name == "jd" and url:
                # JD 恢复时级联恢复关联面经的 sources
                interview_urls = cursor.execute(
                    "SELECT DISTINCT url FROM interview WHERE url = ? AND deleted_at IS NULL",
                    (url,),
                ).fetchall()
                for iu in interview_urls:
                    if iu["url"]:
                        _restore_sources_for_url(cursor, iu["url"], owner_scope)

            conn.commit()

    try:
        await run_db(_restore)
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception:
        logger.exception("恢复失败")
        raise HTTPException(status_code=500, detail="操作失败，请查看服务端日志")


@router.get("/api/data/{file_type}/trash")
async def get_trash(
    file_type: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_admin_user),
):
    """获取已软删除的记录（回收站）"""
    table_map = {"jd": "jd", "interview": "interview", "tagged": "questions_detail"}
    table_name = table_map.get(file_type.lower())
    if not table_name:
        return {"items": [], "total": 0, "page": page, "page_size": page_size}

    offset = (page - 1) * page_size

    def _query():
        safe_name = _safe_table_name(table_name)
        with get_db_connection() as conn:
            where = "deleted_at IS NOT NULL"
            total = conn.execute(
                f"SELECT COUNT(*) FROM {safe_name} WHERE {where}"
            ).fetchone()[0]
            if table_name == "jd":
                rows = conn.execute(
                    f"SELECT id, url, company, job_title, salary, tech_stack, bonus, season, deleted_at FROM {safe_name} WHERE {where} ORDER BY deleted_at DESC LIMIT ? OFFSET ?",
                    (page_size, offset),
                ).fetchall()
            elif table_name == "interview":
                rows = conn.execute(
                    f"SELECT id, url, company, round, focus, questions_list, difficulty, season, deleted_at FROM {safe_name} WHERE {where} ORDER BY deleted_at DESC LIMIT ? OFFSET ?",
                    (page_size, offset),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"SELECT id, url, company, round, question, cat1, cat2, tags, diff_tag, deleted_at FROM {safe_name} WHERE {where} ORDER BY deleted_at DESC LIMIT ? OFFSET ?",
                    (page_size, offset),
                ).fetchall()
            return total, rows

    total, rows = await run_db(_query)

    result = []
    for r in rows:
        d = dict(r)
        if table_name == "jd":
            result.append(
                {
                    "id": d["id"],
                    "来源链接": d["url"],
                    "公司": d["company"],
                    "岗位名称": d["job_title"],
                    "薪资范围": d["salary"],
                    "核心技术要求": d["tech_stack"],
                    "加分项": d["bonus"],
                    "season": d.get("season", ""),
                    "deleted_at": d.get("deleted_at", ""),
                }
            )
        elif table_name == "interview":
            result.append(
                {
                    "id": d["id"],
                    "来源链接": d["url"],
                    "公司": d["company"],
                    "面试轮次": d["round"],
                    "考察重点": d["focus"],
                    "具体题目清单": d["questions_list"],
                    "难易程度": d["difficulty"],
                    "season": d.get("season", ""),
                    "deleted_at": d.get("deleted_at", ""),
                }
            )
        elif table_name == "questions_detail":
            result.append(
                {
                    "id": d["id"],
                    "来源链接": d["url"],
                    "公司": d["company"],
                    "面试轮次": d["round"],
                    "题目": d["question"],
                    "一级大类": d["cat1"],
                    "二级子类": d["cat2"],
                    "考点标签": d["tags"],
                    "难度标签": d["diff_tag"],
                    "deleted_at": d.get("deleted_at", ""),
                }
            )
    return {"items": result, "total": total, "page": page, "page_size": page_size}


@router.put("/api/data/update")
async def update_generic_data(
    req: GenericUpdateRequest,
    user: dict = Depends(get_admin_user),
):
    try:
        _safe_table_name(req.table_name)
    except ValueError:
        raise HTTPException(
            status_code=400, detail=f"安全拦截：不被允许操作的数据表 '{req.table_name}'"
        )

    if not req.update_data:
        raise HTTPException(status_code=400, detail="更新数据不能为空")

    # 白名单校验：只允许更新指定字段
    allowed_cols = ALLOWED_UPDATE_COLUMNS.get(req.table_name, set())
    for col in req.update_data.keys():
        if col not in allowed_cols:
            raise HTTPException(
                status_code=400,
                detail=f"安全拦截：不允许更新字段 '{col}'，允许的字段: {allowed_cols}",
            )

    # 来源链接校验：interview/questions_detail/jd 的 url 字段非空时必须为 http(s)
    if req.table_name in ("interview", "questions_detail", "jd") and "url" in req.update_data:
        validate_source_url(str(req.update_data["url"]))

    # Bug #5: 通用更新接口添加所有权校验 — admin 不能修改个人题目
    if req.table_name == "question_bank":

        def _check_owner():
            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT owner_id FROM question_bank WHERE id = ?", (req.record_id,)
                ).fetchone()
                if row and row["owner_id"] is not None:
                    raise HTTPException(
                        status_code=403,
                        detail="不能通过此接口修改个人题目，请使用题目编辑功能",
                    )

        await run_db(_check_owner)

    # 防止通过通用更新接口意外清空 ai_answer
    if req.table_name == "question_bank" and "ai_answer" in req.update_data:
        new_val = req.update_data["ai_answer"]
        if not new_val or (isinstance(new_val, str) and not new_val.strip()):
            raise HTTPException(
                status_code=400,
                detail="不允许将 ai_answer 设置为空值，请使用 /api/master-bank/generate-answer 接口重新生成答案",
            )

    # 安全校验：列名必须只含 [a-z_0-9]，防止 SQL 注入
    _COL_RE = re.compile(r"^[a-z_][a-z_0-9]*$")
    for col in req.update_data.keys():
        if not _COL_RE.match(col):
            raise HTTPException(status_code=400, detail=f"安全拦截：非法列名 '{col}'")

    set_clauses = [f"{col} = ?" for col in req.update_data.keys()]
    values = list(req.update_data.values())

    if req.table_name == "question_bank" and "updated_at" not in req.update_data:
        set_clauses.append("updated_at = CURRENT_TIMESTAMP")

    values.append(req.record_id)

    sql = f"UPDATE {req.table_name} SET {', '.join(set_clauses)} WHERE id = ?"

    def _update():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            previous_interview = None
            if req.table_name == "interview":
                previous_interview = cursor.execute(
                    "SELECT id, owner_id, status, deleted_at, job_position FROM interview WHERE id = ?",
                    (req.record_id,),
                ).fetchone()
            cursor.execute(sql, tuple(values))
            if cursor.rowcount == 0:
                raise HTTPException(
                    status_code=404, detail="未找到对应的记录，可能已被删除"
                )
            if req.table_name == "questions_detail" and {
                "question",
                "cat1",
                "cat2",
                "tags",
            } & set(req.update_data):
                _retype_distribution_details_txn(cursor, [req.record_id])
            if req.table_name == "interview":
                if (
                    previous_interview
                    and previous_interview["owner_id"] is None
                    and previous_interview["status"] == "approved"
                    and previous_interview["deleted_at"] is None
                ):
                    from app.services.interview_distribution import (
                        mark_distribution_refresh,
                    )

                    mark_distribution_refresh(
                        cursor, previous_interview["job_position"] or ""
                    )
                _mark_distribution_refresh_for_interview_txn(cursor, req.record_id)
            conn.commit()

    try:
        await run_db(_update)

        reprocess_job = None
        # ── 面经 questions_list 变更时，创建 durable 重分析任务 ──
        if req.table_name == "interview" and "questions_list" in req.update_data:
            from app.services.interview_reprocess import submit_interview_reprocess_job

            reprocess_job = await submit_interview_reprocess_job(
                req.record_id, user_id=user["id"]
            )

        response = {"status": "success", "message": f"{req.table_name} 表数据更新成功"}
        if reprocess_job:
            response["reprocess_job"] = reprocess_job
        return response
    except HTTPException:
        raise
    except Exception:
        logger.exception("操作失败")
        raise HTTPException(status_code=500, detail="数据库更新失败，请查看服务端日志")
