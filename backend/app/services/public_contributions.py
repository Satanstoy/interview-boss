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


SENSITIVE_SOURCE_FIELDS = ("company", "round", "source_url")


def build_review_projection(
    *,
    snapshot: dict,
    items: list,
    request,
    reviewer_id: int,
    source_type: str = "interview",
    reviewed_at: str | None = None,
) -> dict:
    """审核预览与物化共用的唯一构造函数（AC-014）。

    规则（contracts §3.1）：

    - 可识别来源字段 company/round/source_url 默认不公开，只有显式确认才公开；
      null/空串表示删除公开字段，**不得**回落原始 snapshot；
    - 题干/分类未修改时继承该项快照；排除项按 item_id；
    - 未知 item_id / 未知字段直接拒绝。
    """
    import hashlib as _hashlib

    from app.models.upload_contracts import REVIEW_SOURCE_ALLOWED_FIELDS

    if source_type not in REVIEW_SOURCE_ALLOWED_FIELDS:
        raise ValueError(f"不支持的 source_type: {source_type!r}")

    allowed = REVIEW_SOURCE_ALLOWED_FIELDS[source_type]
    source_model = request.review_fields.source
    provided = set(getattr(source_model, "model_fields_set", set()))
    source: dict = {}
    for field in sorted(allowed):
        if field in SENSITIVE_SOURCE_FIELDS:
            value = getattr(source_model, field) if field in provided else None
        else:
            value = getattr(source_model, field) if field in provided else snapshot.get(field)
        source[field] = value

    item_models = {int(item.item_id): item for item in request.review_fields.items}
    known_ids = {int(item["item_id"]) for item in items}
    unknown = set(item_models) - known_ids
    if unknown:
        raise ValueError(f"审核项不属于本申请: {sorted(unknown)}")
    excluded = {int(item_id) for item_id in request.excluded_item_ids}
    unknown_excluded = excluded - known_ids
    if unknown_excluded:
        raise ValueError(f"排除项不属于本申请: {sorted(unknown_excluded)}")

    final_items = []
    for item in items:
        item_id = int(item["item_id"])
        if item_id in excluded:
            continue
        reviewed = item_models.get(item_id)
        reviewed_fields = set(getattr(reviewed, "model_fields_set", set())) if reviewed else set()
        fields = {}
        for field in ("question", "cat1", "cat2", "tags", "difficulty"):
            value = (
                getattr(reviewed, field)
                if reviewed is not None and field in reviewed_fields
                else item.get(field)
            )
            if field != "tags" and isinstance(value, str):
                value = value.strip() or None
            fields[field] = value
        final_items.append(
            {"item_id": item_id, "ordinal": item.get("ordinal"), **fields}
        )

    projection = {
        "schema_version": 1,
        "source_type": source_type,
        "source": source,
        "items": final_items,
        "excluded_item_ids": sorted(excluded),
        "reviewer_id": reviewer_id,
        "reviewed_at": reviewed_at or _now_iso(),
        "source_snapshot_unchanged": dict(snapshot),
    }
    digest = _hashlib.sha256(
        _json(
            {
                "source": source,
                "items": final_items,
                "excluded_item_ids": sorted(excluded),
            },
        ).encode("utf-8")
    ).hexdigest()
    projection["hash"] = digest
    return projection


def _now_iso() -> str:
    from datetime import datetime, timezone

    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def materialize_public_interview_from_projection(
    conn, projection: dict, *, source_id: int, requester_id: int, job_position: str = ""
):
    """只按 reviewed_projection 物化公共面经与明细（AC-014）。

    物化路径**禁止**回读原始 snapshot 补敏感字段：投影里是 null 的字段就是不公开。
    """

    source = projection.get("source") or {}
    items = projection.get("items") or []

    questions_list = "\n".join(
        f"{index}. {item['question']}"
        for index, item in enumerate(items, start=1)
        if item.get("question")
    )
    source_url = source.get("source_url") or ""
    try:
        from app.db.operations import _extract_url_signature

        url_signature = _extract_url_signature(source_url) if source_url else ""
    except Exception:  # pragma: no cover - 兼容轻量测试 schema
        url_signature = ""

    interview_values = {
        "url": source_url,
        "company": source.get("company") or "",
        "round": source.get("round") or "",
        "focus": source.get("focus") or "",
        "questions_list": questions_list,
        "difficulty": source.get("difficulty") or "",
        "season": source.get("season") or "",
        "owner_id": None,
        "status": "approved",
        "url_signature": url_signature,
        "job_position": job_position,
    }
    interview_id = _insert_dynamic(conn, "interview", interview_values)

    detail_ids = []
    for item in items:
        detail_ids.append(
            _insert_dynamic(
                conn,
                "questions_detail",
                {
                    "interview_id": interview_id,
                    "url": source_url,
                    "company": source.get("company") or "",
                    "round": source.get("round") or "",
                    "question": item.get("question") or "",
                    "cat1": item.get("cat1") or "",
                    "cat2": item.get("cat2") or "",
                    "tags": item.get("tags") or "",
                    "diff_tag": item.get("difficulty") or "",
                    "job_position": job_position,
                },
            )
        )
    return interview_id, detail_ids


class StateConflict(Exception):
    """状态迁移冲突（contracts §3.2）：映射为 HTTP 409 ``STATE_CONFLICT``。"""

    code = "STATE_CONFLICT"


APPROVABLE_STATES = ("pending_review", "changes_requested", "approved_for_processing", "failed")
WITHDRAWABLE_STATES = ("pending_review", "changes_requested")


def _begin_immediate(conn):
    """进入写事务；若调用方已在事务中则复用（不嵌套 BEGIN）。"""

    if not conn.in_transaction:
        conn.execute("BEGIN IMMEDIATE")


def _finish(conn, commit: bool):
    if commit:
        if not conn.in_transaction:
            return
        conn.execute("COMMIT")
    else:
        if conn.in_transaction:
            conn.execute("ROLLBACK")


def approve_public_contribution_v2(
    conn,
    *,
    request_id: int,
    admin_id: int,
    review_request,
    expected_revision: int | None = None,
) -> dict:
    """原子批准：CAS 校验 revision → 投影物化 → 同事务写事件与公共工作（AC-014/020）。"""

    _begin_immediate(conn)
    try:
        if expected_revision is None:
            expected_revision = getattr(review_request, "expected_revision", None)
        row = conn.execute(
            "SELECT * FROM public_contribution_requests WHERE id = ?", (request_id,)
        ).fetchone()
        if row is None:
            raise ValueError("公共化申请不存在")
        current_revision = int(row["revision"])
        if expected_revision is not None and current_revision != int(expected_revision):
            raise StateConflict(
                f"申请版本已变化: expected={expected_revision} current={current_revision}"
            )

        if row["status"] == "approved_for_processing":
            # 同 revision 重复批准：幂等返回，不追加事件/实体
            _finish(conn, commit=True)
            return {
                "status": row["status"],
                "revision": current_revision,
                "public_interview_id": row["public_interview_id"],
            }
        if row["status"] not in APPROVABLE_STATES:
            raise StateConflict(f"当前状态不可批准: {row['status']}")

        snapshot = _loads(row["snapshot_json"], {})
        item_rows = conn.execute(
            "SELECT id, ordinal, snapshot_json FROM public_contribution_items "
            "WHERE request_id = ? ORDER BY ordinal",
            (request_id,),
        ).fetchall()
        item_payloads = []
        for item in item_rows:
            payload = _loads(item["snapshot_json"], {}) or {}
            payload.setdefault("item_id", int(item["id"]))
            payload.setdefault("ordinal", item["ordinal"])
            item_payloads.append(payload)

        projection = build_review_projection(
            snapshot=snapshot,
            items=item_payloads,
            request=review_request,
            reviewer_id=admin_id,
            source_type=row["source_type"],
        )

        excluded = set(projection["excluded_item_ids"])
        approved_item_ids = [item["item_id"] for item in projection["items"]]
        for item in item_rows:
            item_id = int(item["id"])
            if item_id in excluded:
                conn.execute(
                    "UPDATE public_contribution_items SET status = 'rejected', "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (item_id,),
                )
            else:
                conn.execute(
                    "UPDATE public_contribution_items SET status = 'approved_for_processing', "
                    "review_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (_json(projection), item_id),
                )
        if not approved_item_ids:
            raise ValueError("至少保留一个可公开内容")

        updated = conn.execute(
            "UPDATE public_contribution_requests SET status = 'approved_for_processing', "
            "revision = revision + 1, review_json = ?, review_projection_json = ?, "
            "projection_hash = ?, reviewed_by = ?, reviewed_at = CURRENT_TIMESTAMP, "
            "updated_at = CURRENT_TIMESTAMP, error_message = NULL "
            "WHERE id = ? AND revision = ? AND status IN ('pending_review','changes_requested','failed')",
            (
                _json({"excluded_item_ids": sorted(excluded), "fields": projection["source"]}),
                _json(projection),
                projection["hash"],
                admin_id,
                request_id,
                current_revision,
            ),
        )
        if updated.rowcount != 1:
            raise StateConflict("申请状态已被其他操作修改")

        public_interview_id, detail_ids = materialize_public_interview_from_projection(
            conn,
            projection,
            source_id=int(row["source_id"]),
            requester_id=int(row["requester_id"]),
        )
        conn.execute(
            "UPDATE public_contribution_requests SET public_interview_id = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (public_interview_id, request_id),
        )

        from app.services.pipeline.queue import enqueue_questions

        enqueue_questions(
            public_interview_id,
            owner_id=None,
            question_detail_ids=detail_ids,
            contribution_request_id=request_id,
            conn=conn,
        )

        _event(
            conn,
            request_id,
            admin_id,
            "approved_for_processing",
            row["status"],
            "approved_for_processing",
            {"projection_hash": projection["hash"], "excluded_item_ids": sorted(excluded)},
        )
        new_revision = int(
            conn.execute(
                "SELECT revision FROM public_contribution_requests WHERE id = ?",
                (request_id,),
            ).fetchone()["revision"]
        )
        _finish(conn, commit=True)
        return {
            "status": "approved_for_processing",
            "revision": new_revision,
            "public_interview_id": public_interview_id,
            "projection_hash": projection["hash"],
        }
    except Exception:
        _finish(conn, commit=False)
        raise


def withdraw_public_contribution_v2(
    conn,
    *,
    request_id: int,
    requester_id: int,
    expected_revision: int | None = None,
) -> dict:
    """原子撤回：CAS 校验 + 清除本申请新建的可执行公共工作（AC-020）。"""

    _begin_immediate(conn)
    try:
        row = conn.execute(
            "SELECT * FROM public_contribution_requests WHERE id = ?", (request_id,)
        ).fetchone()
        if row is None:
            raise ValueError("公共化申请不存在")
        if int(row["requester_id"]) != int(requester_id):
            raise ValueError("无权撤回该申请")
        current_revision = int(row["revision"])
        if expected_revision is not None and current_revision != int(expected_revision):
            raise StateConflict(
                f"申请版本已变化: expected={expected_revision} current={current_revision}"
            )
        if row["status"] == "withdrawn":
            _finish(conn, commit=True)
            return {"status": "withdrawn", "revision": current_revision}
        if row["status"] not in WITHDRAWABLE_STATES:
            raise StateConflict(f"当前状态不可撤回: {row['status']}")

        updated = conn.execute(
            "UPDATE public_contribution_requests SET status = 'withdrawn', "
            "revision = revision + 1, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND revision = ? AND status IN ('pending_review','changes_requested')",
            (request_id, current_revision),
        )
        if updated.rowcount != 1:
            raise StateConflict("申请状态已被其他操作修改")

        # 撤回成功后不得留下本申请新建的可执行公共工作
        conn.execute(
            "UPDATE analysis_queue SET status = 'cancelled', processed_at = CURRENT_TIMESTAMP "
            "WHERE contribution_request_id = ? AND status = 'pending'",
            (request_id,),
        )
        # items 状态枚举没有 withdrawn；撤回的条目归入 rejected（不再执行）
        conn.execute(
            "UPDATE public_contribution_items SET status = 'rejected', "
            "updated_at = CURRENT_TIMESTAMP WHERE request_id = ? "
            "AND status IN ('pending_review','approved_for_processing','queued','processing')",
            (request_id,),
        )
        _event(
            conn,
            request_id,
            requester_id,
            "withdrawn",
            row["status"],
            "withdrawn",
            None,
        )
        new_revision = int(
            conn.execute(
                "SELECT revision FROM public_contribution_requests WHERE id = ?",
                (request_id,),
            ).fetchone()["revision"]
        )
        _finish(conn, commit=True)
        return {"status": "withdrawn", "revision": new_revision}
    except Exception:
        _finish(conn, commit=False)
        raise


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
