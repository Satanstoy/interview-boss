"""Private-source to public-corpus contribution workflow.

This module intentionally does not copy a private question into
``question_bank`` with ``status='pending'``.  The request and its immutable
snapshot are the review object; only an approved request creates a public
projection and enters the public clustering queue.
"""

from __future__ import annotations

import json
from typing import Any

from app.db.connection import get_db_connection, run_db
from app.services.pipeline.queue import _run_cluster_batch_in_background

REQUEST_ACTIVE_STATUSES = (
    "pending_review",
    "changes_requested",
    "approved_for_processing",
    "queued",
    "processing",
    "failed",
)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _loads(value: str | None, default=None):
    try:
        parsed = json.loads(value or "")
        return parsed if parsed is not None else (default if default is not None else {})
    except (TypeError, ValueError):
        return default if default is not None else {}


def _row_dict(row) -> dict:
    return dict(row) if row is not None else {}


def _event(
    conn,
    request_id: int,
    actor_id: int | None,
    action: str,
    from_status: str | None,
    to_status: str | None,
    metadata=None,
):
    conn.execute(
        "INSERT INTO public_contribution_events "
        "(request_id, actor_id, action, from_status, to_status, metadata_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (request_id, actor_id, action, from_status, to_status, _json(metadata or {})),
    )


def _source_snapshot(conn, source_type: str, source_id: int, requester_id: int) -> dict:
    if source_type == "interview":
        source = conn.execute(
            "SELECT * FROM interview WHERE id = ? AND owner_id = ? AND deleted_at IS NULL",
            (source_id, requester_id),
        ).fetchone()
        if not source:
            raise ValueError("只能提交自己名下的个人面经")
        details = conn.execute(
            "SELECT * FROM questions_detail WHERE interview_id = ? AND deleted_at IS NULL ORDER BY id",
            (source_id,),
        ).fetchall()
        if not details:
            raise ValueError("该面经没有可提交的题目明细")
        return {
            "source": _row_dict(source),
            "items": [_row_dict(row) for row in details],
        }

    if source_type == "jd":
        source = conn.execute(
            "SELECT * FROM jd WHERE id = ? AND owner_id = ? AND deleted_at IS NULL",
            (source_id, requester_id),
        ).fetchone()
        if not source:
            raise ValueError("只能提交自己名下的个人 JD")
        return {"source": _row_dict(source), "items": []}

    raise ValueError("source_type 只能是 interview 或 jd")


def _request_row(conn, request_id: int):
    row = conn.execute(
        "SELECT * FROM public_contribution_requests WHERE id = ?", (request_id,)
    ).fetchone()
    if not row:
        raise ValueError("公共化申请不存在")
    return row


def _serialize_request(row, items=None, include_snapshot=False) -> dict:
    result = {
        "id": row["id"],
        "source_type": row["source_type"],
        "source_id": row["source_id"],
        "requester_id": row["requester_id"],
        "status": row["status"],
        "public_interview_id": row["public_interview_id"],
        "public_jd_id": row["public_jd_id"],
        "reviewed_by": row["reviewed_by"],
        "reviewed_at": row["reviewed_at"],
        "error_message": row["error_message"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    snapshot = _loads(row["snapshot_json"], {})
    source = snapshot.get("source") or {}
    result["summary"] = {
        "company": source.get("company", ""),
        "round": source.get("round", "") or source.get("interview_round", ""),
        "job_title": source.get("job_title", ""),
        "job_position": source.get("job_position", ""),
        "item_count": len(snapshot.get("items") or []),
    }
    if snapshot.get("items"):
        result["summary"]["question_previews"] = [
            {"question": item.get("question", ""), "ordinal": index}
            for index, item in enumerate(snapshot["items"])
            if item.get("question")
        ][:20]
    if include_snapshot:
        result["snapshot"] = snapshot
        result["review"] = _loads(row["review_json"], {})
    if items is not None:
        result["items"] = items
    return result


def create_public_contribution_request(
    conn, source_type: str, source_id: int, requester_id: int
) -> dict:
    """Create or return the active request for one private source."""
    if source_type not in ("interview", "jd"):
        raise ValueError("source_type 只能是 interview 或 jd")

    active_placeholders = ",".join("?" * len(REQUEST_ACTIVE_STATUSES))
    existing = conn.execute(
        "SELECT * FROM public_contribution_requests "
        "WHERE source_type = ? AND source_id = ? AND requester_id = ? "
        f"AND status IN ({active_placeholders}) ORDER BY id DESC LIMIT 1",
        (source_type, source_id, requester_id, *REQUEST_ACTIVE_STATUSES),
    ).fetchone()
    if existing:
        return _serialize_request(existing)

    snapshot = _source_snapshot(conn, source_type, source_id, requester_id)
    cursor = conn.execute(
        "INSERT INTO public_contribution_requests "
        "(source_type, source_id, requester_id, status, snapshot_json) "
        "VALUES (?, ?, ?, 'pending_review', ?)",
        (source_type, source_id, requester_id, _json(snapshot)),
    )
    request_id = int(cursor.lastrowid)
    if source_type == "interview":
        for ordinal, item in enumerate(snapshot["items"]):
            conn.execute(
                "INSERT INTO public_contribution_items "
                "(request_id, source_item_type, source_item_id, ordinal, snapshot_json) "
                "VALUES (?, 'question', ?, ?, ?)",
                (request_id, item.get("id"), ordinal, _json(item)),
            )
    else:
        conn.execute(
            "INSERT INTO public_contribution_items "
            "(request_id, source_item_type, source_item_id, ordinal, snapshot_json) "
            "VALUES (?, 'jd_document', ?, 0, ?)",
            (request_id, source_id, _json(snapshot["source"])),
        )
    _event(conn, request_id, requester_id, "submitted", None, "pending_review")
    conn.commit()
    return _serialize_request(_request_row(conn, request_id))


def list_public_contribution_requests(
    conn, *, status: str | None = "pending_review", source_type: str | None = None
) -> list[dict]:
    where = []
    params = []
    if status:
        where.append("status = ?")
        params.append(status)
    if source_type:
        where.append("source_type = ?")
        params.append(source_type)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    rows = conn.execute(
        f"SELECT * FROM public_contribution_requests {where_sql} ORDER BY created_at DESC, id DESC",
        params,
    ).fetchall()
    return [_serialize_request(row) for row in rows]


def get_public_contribution_request(conn, request_id: int, *, include_snapshot=True) -> dict:
    row = _request_row(conn, request_id)
    item_rows = conn.execute(
        "SELECT * FROM public_contribution_items WHERE request_id = ? ORDER BY ordinal",
        (request_id,),
    ).fetchall()
    items = []
    for item in item_rows:
        item_data = {
            "id": item["id"],
            "source_item_type": item["source_item_type"],
            "source_item_id": item["source_item_id"],
            "ordinal": item["ordinal"],
            "status": item["status"],
            "public_detail_id": item["public_detail_id"],
            "error_message": item["error_message"],
            "snapshot": _loads(item["snapshot_json"], {}),
            "review": _loads(item["review_json"], {}),
        }
        items.append(item_data)
    return _serialize_request(row, items, include_snapshot=include_snapshot)


def _insert_dynamic(conn, table: str, values: dict) -> int:
    columns = {row[1] for row in conn.execute(f"PRAGMA table_info('{table}')").fetchall()}
    filtered = {key: value for key, value in values.items() if key in columns}
    names = list(filtered)
    placeholders = ",".join("?" * len(names))
    cursor = conn.execute(
        f"INSERT INTO {table} ({','.join(names)}) VALUES ({placeholders})",
        [filtered[name] for name in names],
    )
    return int(cursor.lastrowid)


def _materialize_public_interview(
    conn, snapshot: dict, approved_items: list[dict]
) -> tuple[int, list[int], list[bool]]:
    source = snapshot["source"]
    url = source.get("url") or ""
    existing = conn.execute(
        "SELECT id FROM interview WHERE owner_id IS NULL AND url = ? "
        "AND deleted_at IS NULL ORDER BY id LIMIT 1",
        (url,),
    ).fetchone()
    questions = [item.get("question", "") for item in approved_items if item.get("question")]
    questions_text = "\n".join(f"{index + 1}. {text}" for index, text in enumerate(questions))
    if existing:
        public_interview_id = int(existing["id"])
    else:
        from app.db.utils import _extract_url_signature

        public_interview_id = _insert_dynamic(
            conn,
            "interview",
            {
                "url": url,
                "company": source.get("company", "未提供"),
                "round": source.get("round", "未提供"),
                "focus": source.get("focus", "未提供"),
                "questions_list": questions_text,
                "difficulty": source.get("difficulty", "未提供"),
                "season": source.get("season", ""),
                "owner_id": None,
                "status": "approved",
                "url_signature": source.get("url_signature") or _extract_url_signature(url),
                "job_position": source.get("job_position", ""),
            },
        )

    detail_ids = []
    new_detail_flags = []
    for item in approved_items:
        question = item.get("question", "")
        if not question:
            continue
        existing_detail = conn.execute(
            "SELECT id FROM questions_detail WHERE interview_id = ? AND question = ? "
            "AND deleted_at IS NULL ORDER BY id LIMIT 1",
            (public_interview_id, question),
        ).fetchone()
        if existing_detail:
            detail_ids.append(int(existing_detail["id"]))
            new_detail_flags.append(False)
            continue
        values = {
            "interview_id": public_interview_id,
            "url": url,
            "company": source.get("company", "未提供"),
            "round": source.get("round", "未提供"),
            "question": question,
            "cat1": item.get("cat1", ""),
            "cat2": item.get("cat2", ""),
            "tags": item.get("tags", ""),
            "difficulty": item.get("difficulty", ""),
            "diff_tag": item.get("diff_tag", "未知"),
            "job_position": source.get("job_position", ""),
            "owner_id": None,
            "status": "approved",
        }
        detail_ids.append(_insert_dynamic(conn, "questions_detail", values))
        new_detail_flags.append(True)
    return public_interview_id, detail_ids, new_detail_flags


def _materialize_public_jd(conn, snapshot: dict) -> int:
    source = snapshot["source"]
    url = source.get("url") or ""
    existing = conn.execute(
        "SELECT id FROM jd WHERE owner_id IS NULL AND url = ? "
        "AND deleted_at IS NULL ORDER BY id LIMIT 1",
        (url,),
    ).fetchone()
    if existing:
        return int(existing["id"])

    # 字段白名单：与 _materialize_public_interview 同口径。私有快照里的
    # 任何非白名单列（含未来新增列）都不得被连带公开（audit D5）。
    from app.db.utils import _extract_url_signature

    values = {
        key: source.get(key)
        for key in (
            "url",
            "company",
            "season",
            "url_signature",
            "job_position",
            "tech_stack",
            "source",
            "position",
            "salary",
            "job_title",
        )
    }
    values["url_signature"] = values["url_signature"] or _extract_url_signature(url)
    values.update({"owner_id": None, "status": "approved", "deleted_at": None})
    return _insert_dynamic(conn, "jd", values)


def approve_public_contribution(
    conn,
    request_id: int,
    admin_id: int,
    excluded_item_ids: list[int] | None = None,
    review_fields: dict | None = None,
) -> dict:
    """Approve a request and create its public projection/queue entries."""
    row = _request_row(conn, request_id)
    old_status = row["status"]
    if old_status in ("queued", "processing", "published", "partially_published"):
        return get_public_contribution_request(conn, request_id)
    if old_status not in (
        "pending_review",
        "changes_requested",
        "approved_for_processing",
        "failed",
    ):
        raise ValueError(f"当前状态不可通过: {old_status}")

    excluded = {int(item_id) for item_id in (excluded_item_ids or [])}
    items = conn.execute(
        "SELECT id, ordinal, snapshot_json FROM public_contribution_items "
        "WHERE request_id = ? ORDER BY ordinal",
        (request_id,),
    ).fetchall()
    request_item_ids = {int(item["id"]) for item in items}
    unknown_item_ids = excluded - request_item_ids
    if unknown_item_ids:
        raise ValueError("排除项不属于当前公共化申请")
    approved_items = []
    approved_item_ids = []
    for item in items:
        item_id = int(item["id"])
        if item_id in excluded:
            conn.execute(
                "UPDATE public_contribution_items SET status = 'rejected', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (item_id,),
            )
            continue
        payload = _loads(item["snapshot_json"], {})
        approved_items.append(payload)
        approved_item_ids.append(item_id)
        conn.execute(
            "UPDATE public_contribution_items SET status = 'approved_for_processing', "
            "review_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (_json(review_fields or {}), item_id),
        )
    if not approved_items:
        raise ValueError("至少保留一个可公开内容")

    snapshot = _loads(row["snapshot_json"], {})
    review = {"excluded_item_ids": sorted(excluded), "fields": review_fields or {}}
    conn.execute(
        "UPDATE public_contribution_requests SET status = 'approved_for_processing', "
        "review_json = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP, "
        "updated_at = CURRENT_TIMESTAMP, error_message = NULL WHERE id = ?",
        (_json(review), admin_id, request_id),
    )
    _event(
        conn,
        request_id,
        admin_id,
        "approved_for_processing",
        old_status,
        "approved_for_processing",
        review,
    )

    if row["source_type"] == "interview":
        public_interview_id, detail_ids, new_detail_flags = _materialize_public_interview(
            conn, snapshot, approved_items
        )
        conn.execute(
            "UPDATE public_contribution_requests SET public_interview_id = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (public_interview_id, request_id),
        )
        from app.services.pipeline.queue import enqueue_questions

        new_detail_ids = [
            detail_id for detail_id, is_new in zip(detail_ids, new_detail_flags) if is_new
        ]
        if new_detail_ids:
            enqueue_questions(
                public_interview_id,
                owner_id=None,
                question_detail_ids=new_detail_ids,
                contribution_request_id=request_id,
                conn=conn,
            )
        # Keep the source item -> public detail relation explicit.  Queue
        # completion uses this relation, never the private source id or URL.
        for item_id, detail_id, is_new in zip(approved_item_ids, detail_ids, new_detail_flags):
            item_status = "queued" if is_new else "published"
            conn.execute(
                "UPDATE public_contribution_items SET status = ?, "
                "public_detail_id = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (item_status, detail_id, item_id),
            )
        new_status = (
            "queued" if new_detail_ids else ("partially_published" if excluded else "published")
        )
    else:
        public_jd_id = _materialize_public_jd(conn, snapshot)
        conn.execute(
            "UPDATE public_contribution_requests SET public_jd_id = ?, "
            "status = 'published', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (public_jd_id, request_id),
        )
        conn.execute(
            "UPDATE public_contribution_items SET status = 'published', "
            "updated_at = CURRENT_TIMESTAMP WHERE request_id = ? "
            "AND status = 'approved_for_processing'",
            (request_id,),
        )
        new_status = "published"

    conn.execute(
        "UPDATE public_contribution_requests SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (new_status, request_id),
    )
    _event(
        conn,
        request_id,
        admin_id,
        "public_projection_created",
        "approved_for_processing",
        new_status,
        {},
    )
    conn.commit()
    return get_public_contribution_request(conn, request_id)


async def finalize_public_contribution_approval(
    request_id: int,
    admin_id: int,
    *,
    excluded_item_ids: list[int] | None = None,
    review_fields: dict | None = None,
) -> dict:
    """审批落库并在进入聚类队列时调度后台攒批（服务层统一入口）。

    路由层只调用本函数，不直接接触 pipeline 调度；聚类攒批沿用
    ``_run_cluster_batch_in_background`` 的持久化 job + ARQ best-effort 语义。
    """

    def _approve():
        with get_db_connection() as conn:
            return approve_public_contribution(
                conn,
                request_id,
                admin_id,
                excluded_item_ids=excluded_item_ids,
                review_fields=review_fields,
            )

    result = await run_db(_approve)
    if result.get("status") == "queued" and result.get("public_interview_id"):
        result["cluster_scheduled"] = await _run_cluster_batch_in_background(user_id=admin_id)
    return result


def reject_public_contribution(conn, request_id: int, admin_id: int, reason: str = "") -> dict:
    row = _request_row(conn, request_id)
    if row["status"] not in ("pending_review", "changes_requested"):
        raise ValueError("该申请已经进入公共处理，不能直接拒绝")
    if row["status"] == "rejected":
        return get_public_contribution_request(conn, request_id)
    conn.execute(
        "UPDATE public_contribution_requests SET status = 'rejected', reviewed_by = ?, "
        "reviewed_at = CURRENT_TIMESTAMP, error_message = ?, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (admin_id, reason or None, request_id),
    )
    conn.execute(
        "UPDATE public_contribution_items SET status = 'rejected', updated_at = CURRENT_TIMESTAMP "
        "WHERE request_id = ? AND status IN ('pending_review', 'changes_requested')",
        (request_id,),
    )
    _event(
        conn, request_id, admin_id, "rejected", row["status"], "rejected", {"reason": reason or ""}
    )
    conn.commit()
    return get_public_contribution_request(conn, request_id)


def withdraw_public_contribution(conn, request_id: int, requester_id: int) -> dict:
    row = _request_row(conn, request_id)
    if int(row["requester_id"]) != int(requester_id):
        raise ValueError("无权撤回该公共化申请")
    if row["status"] not in ("pending_review", "changes_requested"):
        raise ValueError("申请已进入公共处理，当前不能撤回")
    conn.execute(
        "UPDATE public_contribution_requests SET status = 'withdrawn', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (request_id,),
    )
    conn.execute(
        "UPDATE public_contribution_items SET status = 'rejected', updated_at = CURRENT_TIMESTAMP WHERE request_id = ?",
        (request_id,),
    )
    _event(conn, request_id, requester_id, "withdrawn", row["status"], "withdrawn", {})
    conn.commit()
    return get_public_contribution_request(conn, request_id)


def mark_public_contribution_queue_done(conn, queue_ids: list[int]) -> int:
    """Close contribution child items after their public queue rows finish."""
    if not queue_ids:
        return 0
    placeholders = ",".join("?" * len(queue_ids))
    rows = conn.execute(
        "SELECT DISTINCT contribution_request_id, question_detail_id "
        f"FROM analysis_queue WHERE id IN ({placeholders}) "
        "AND contribution_request_id IS NOT NULL",
        queue_ids,
    ).fetchall()
    request_ids = set()
    updated = 0
    for row in rows:
        request_id = int(row["contribution_request_id"])
        request_ids.add(request_id)
        cursor = conn.execute(
            "UPDATE public_contribution_items SET status = 'published', "
            "updated_at = CURRENT_TIMESTAMP WHERE request_id = ? "
            "AND public_detail_id = ? AND status IN ('queued', 'processing', 'failed')",
            (request_id, row["question_detail_id"]),
        )
        updated += max(cursor.rowcount, 0)

    for request_id in request_ids:
        states = conn.execute(
            "SELECT status FROM public_contribution_items WHERE request_id = ?",
            (request_id,),
        ).fetchall()
        statuses = {state["status"] for state in states}
        if statuses & {"queued", "processing", "approved_for_processing", "failed"}:
            continue
        final_status = "partially_published" if "rejected" in statuses else "published"
        conn.execute(
            "UPDATE public_contribution_requests SET status = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status IN ('queued', 'processing', 'approved_for_processing', 'failed')",
            (final_status, request_id),
        )
        _event(conn, request_id, None, "public_queue_completed", "queued", final_status, {})
    conn.commit()
    return updated


def mark_public_contribution_queue_failed(conn, queue_ids: list[int], error: str) -> int:
    """Keep failed public contribution children visible for retry/audit."""
    if not queue_ids:
        return 0
    placeholders = ",".join("?" * len(queue_ids))
    rows = conn.execute(
        "SELECT DISTINCT contribution_request_id, question_detail_id "
        f"FROM analysis_queue WHERE id IN ({placeholders}) "
        "AND contribution_request_id IS NOT NULL",
        queue_ids,
    ).fetchall()
    request_ids = set()
    updated = 0
    for row in rows:
        request_id = int(row["contribution_request_id"])
        request_ids.add(request_id)
        cursor = conn.execute(
            "UPDATE public_contribution_items SET status = 'failed', error_message = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE request_id = ? "
            "AND public_detail_id = ? AND status IN ('queued', 'processing')",
            (error[:500], request_id, row["question_detail_id"]),
        )
        updated += max(cursor.rowcount, 0)
    for request_id in request_ids:
        conn.execute(
            "UPDATE public_contribution_requests SET status = 'failed', error_message = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (error[:500], request_id),
        )
        _event(
            conn,
            request_id,
            None,
            "public_queue_failed",
            "queued",
            "failed",
            {"error": error[:500]},
        )
    conn.commit()
    return updated
