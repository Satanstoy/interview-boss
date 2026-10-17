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
from app.services.pipeline.queue import (
    _run_cluster_batch_in_background,
    enqueue_questions,
    has_active_rootless_cluster_job,
)

from app.services.public_contribution_projection import (
    _insert_dynamic as _insert_dynamic,
    _materialize_public_interview as _materialize_public_interview,
    _materialize_public_jd as _materialize_public_jd,
    build_review_projection as build_review_projection,
    _now_iso as _now_iso,
    materialize_public_interview_from_projection as materialize_public_interview_from_projection,
    SENSITIVE_SOURCE_FIELDS as SENSITIVE_SOURCE_FIELDS,
)

from app.services.public_contribution_publication import (
    _promote_private_source_canonical as _promote_private_source_canonical,
    _restore_private_sources_after_withdrawal as _restore_private_sources_after_withdrawal,
    publish_items_with_resolutions as publish_items_with_resolutions,
    refresh_public_interview_projection as refresh_public_interview_projection,
    request_publish_status as request_publish_status,
)

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
        "revision": int(row["revision"]),
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
    conn, source_type: str, source_id: int, requester_id: int, *, commit: bool = True
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
    if source_type == "interview":
        previously_projected = {
            int(row["source_item_id"])
            for row in conn.execute(
                "SELECT DISTINCT item.source_item_id "
                "FROM public_contribution_items item "
                "JOIN public_contribution_requests request "
                "ON request.id = item.request_id "
                "WHERE request.source_type = 'interview' AND request.source_id = ? "
                "AND request.requester_id = ? AND item.source_item_type = 'question' "
                "AND item.source_item_id IS NOT NULL "
                "AND (item.status = 'published' OR (item.public_detail_id IS NOT NULL "
                "AND request.status != 'withdrawn'))",
                (source_id, requester_id),
            ).fetchall()
        }
        snapshot["items"] = [
            item
            for item in snapshot.get("items", [])
            if int(item.get("id") or 0) not in previously_projected
        ]
        if not snapshot["items"]:
            raise ValueError("该面经没有新增的可提交题目")
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
    if commit:
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


def bind_contribution_request_to_root(
    conn, *, import_id: str, contribution_request_id: int
) -> None:
    """F-PUBLIC：share 完成后把公共化申请回写根任务
    ``upload_imports.contribution_request_id``（此前该列全库零写入，
    导致快照 review_status 恒空）。同事务幂等；请求不存在不报错。"""

    conn.execute(
        "UPDATE upload_imports SET contribution_request_id = ?, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (contribution_request_id, import_id),
    )


def create_admin_public_import_approval(
    conn,
    *,
    import_id: str | None,
    admin_id: int,
    interview_id: int,
    detail_ids: list[int],
    source_snapshot: dict,
) -> int:
    """Persist the authorization and safe public projection for admin imports.

    The caller owns the surrounding transaction, so the interview, details,
    approval event, root link, and queue rows can become visible atomically.
    """
    import hashlib

    admin = conn.execute(
        "SELECT is_admin FROM users WHERE id = ?", (int(admin_id),)
    ).fetchone()
    if not admin or not admin["is_admin"]:
        raise PermissionError("公共直导必须由当前管理员执行")

    if import_id:
        root = conn.execute(
            "SELECT requester_id, target_intent, policy_json FROM upload_imports WHERE id = ?",
            (import_id,),
        ).fetchone()
        if not root or int(root["requester_id"]) != int(admin_id):
            raise PermissionError("上传根任务与管理员主体不匹配")
        policy = _loads(root["policy_json"], {})
        if root["target_intent"] != "share" or not policy.get("audit_public_import"):
            raise PermissionError("上传根任务没有管理员公共导入授权")

    snapshot = source_snapshot or {}
    raw_source = snapshot.get("source") or {}
    raw_items = snapshot.get("items") or []
    if len(detail_ids) != len(raw_items) or not detail_ids:
        raise ValueError("管理员公共导入的审核题目与公共明细必须一一对应")
    reviewed_at = _now_iso()
    source_projection = {
        "company": raw_source.get("company"),
        "round": raw_source.get("round"),
        "focus": raw_source.get("focus"),
        "difficulty": raw_source.get("difficulty"),
        "season": raw_source.get("season"),
        "source_url": None,
    }

    cursor = conn.execute(
        "INSERT INTO public_contribution_requests "
        "(source_type, source_id, requester_id, status, snapshot_json, review_json, "
        "review_projection_json, projection_hash, public_interview_id, reviewed_by, reviewed_at) "
        "VALUES ('interview', ?, ?, 'approved_for_processing', ?, ?, ?, ?, ?, ?, ?)",
        (
            int(interview_id),
            int(admin_id),
            _json(snapshot),
            _json({"action": "admin_import_approved", "import_id": import_id}),
            "{}",
            "pending",
            int(interview_id),
            int(admin_id),
            reviewed_at,
        ),
    )
    request_id = int(cursor.lastrowid)

    projection_items = []
    for index, (detail_id, item) in enumerate(zip(detail_ids, raw_items)):
        source_ordinal = item.get("source_ordinal")
        safe_item = {
            "question": item.get("question"),
            "cat1": item.get("cat1"),
            "cat2": item.get("cat2"),
            "tags": item.get("tags"),
            "difficulty": item.get("difficulty"),
            "source_ordinal": source_ordinal,
        }
        item_cursor = conn.execute(
            "INSERT INTO public_contribution_items "
            "(request_id, source_item_type, source_item_id, ordinal, status, "
            "snapshot_json, review_json, public_detail_id) "
            "VALUES (?, 'question', ?, ?, 'approved_for_processing', ?, ?, ?)",
            (
                request_id,
                int(detail_id),
                index,
                _json(item),
                _json(safe_item),
                int(detail_id),
            ),
        )
        projection_items.append(
            {
                "item_id": int(item_cursor.lastrowid),
                "ordinal": index,
                **safe_item,
            }
        )

    hash_material = {
        "source": source_projection,
        "items": projection_items,
        "excluded_item_ids": [],
    }
    projection_hash = hashlib.sha256(
        json.dumps(
            hash_material, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
    ).hexdigest()
    projection = {
        "schema_version": 1,
        "source_type": "interview",
        "source": source_projection,
        "items": projection_items,
        "excluded_item_ids": [],
        "reviewer_id": int(admin_id),
        "reviewed_at": reviewed_at,
        "source_snapshot_unchanged": snapshot,
        "hash": projection_hash,
    }
    conn.execute(
        "UPDATE public_contribution_requests SET review_projection_json = ?, "
        "projection_hash = ? WHERE id = ?",
        (_json(projection), projection_hash, request_id),
    )
    _event(
        conn,
        request_id,
        int(admin_id),
        "admin_import_approved",
        None,
        "approved_for_processing",
        {"import_id": import_id, "projection_hash": projection_hash},
    )
    if import_id:
        bind_contribution_request_to_root(
            conn, import_id=import_id, contribution_request_id=request_id
        )
    return request_id


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


def preview_public_contribution(conn, request_id, admin_id, payload):
    """Read-only projection using the same immutable inputs and builder as approval."""
    from app.models.upload_contracts import build_review_projection_request

    conn.execute("BEGIN")
    row = _request_row(conn, request_id)
    request = build_review_projection_request(payload, source_type=row["source_type"])
    revision = int(row["revision"])
    if request.expected_revision != revision:
        raise StateConflict("申请版本已变化，请重新读取审核详情")
    if row["status"] not in APPROVABLE_STATES:
        raise StateConflict("该申请已不在待审核状态")
    items = []
    for item in conn.execute(
        "SELECT id, ordinal, snapshot_json FROM public_contribution_items WHERE request_id=? ORDER BY ordinal",
        (request_id,),
    ).fetchall():
        data = _loads(item["snapshot_json"], {}) or {}
        data.setdefault("item_id", int(item["id"]))
        data.setdefault("ordinal", item["ordinal"])
        items.append(data)
    projection = build_review_projection(
        snapshot=_loads(row["snapshot_json"], {}), items=items, request=request,
        reviewer_id=admin_id, source_type=row["source_type"],
    )
    # The preview contains only publishable fields, never the retained private snapshot.
    projection.pop("source_snapshot_unchanged", None)
    return {"revision": revision, "projection": projection}


class StateConflict(Exception):
    """状态迁移冲突（contracts §3.2）：映射为 HTTP 409 ``STATE_CONFLICT``。"""

    code = "STATE_CONFLICT"


# contracts §3.2：允许 pending_review/changes_requested → approved_for_processing；
# failed 是技术状态，必须走公共处理 retry 入口，不得重新 approve（否则会重复物化明细）。
APPROVABLE_STATES = ("pending_review", "changes_requested", "approved_for_processing")
WITHDRAWABLE_STATES = (
    "pending_review",
    "changes_requested",
    "approved_for_processing",
    "queued",
    "processing",
    "partially_published",
)


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

        idempotent_approval_statuses = {"approved_for_processing", "published"}
        if (
            row["status"] not in APPROVABLE_STATES
            and row["status"] not in idempotent_approval_statuses
        ):
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

        if row["status"] in idempotent_approval_statuses:
            # 相同 revision、相同投影的重复批准保持幂等；不能让 JD 即时
            # materialize 到 published 后失去此语义，也不能接受不同投影。
            if row["projection_hash"] != projection["hash"]:
                raise StateConflict("申请版本已批准为不同投影")
            _finish(conn, commit=True)
            return {
                "status": row["status"],
                "revision": current_revision,
                "public_interview_id": row["public_interview_id"],
                "public_jd_id": row["public_jd_id"],
                "projection_hash": row["projection_hash"],
            }

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
            "WHERE id = ? AND revision = ? AND status IN ('pending_review','changes_requested')",
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

        # 按 source_type 分派物化（R11）：JD 只产生公共 JD，不走面经/题目分支；
        # 岗位从源快照冻结，不允许在 approve 中偷偷换岗位（contracts §3.1）。
        source_base = snapshot.get("source") if isinstance(snapshot, dict) else {}
        if not isinstance(source_base, dict):
            source_base = {}
        if row["source_type"] == "jd":
            public_jd_id = _materialize_public_jd(
                conn, {"source": projection["source"]}, job_position=source_base.get("job_position") or ""
            )
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
            _event(
                conn,
                request_id,
                admin_id,
                "public_projection_created",
                "approved_for_processing",
                "published",
                {"projection_hash": projection["hash"]},
            )
            _finish(conn, commit=True)
            return {
                "status": "published",
                "revision": int(
                    conn.execute(
                        "SELECT revision FROM public_contribution_requests WHERE id = ?",
                        (request_id,),
                    ).fetchone()["revision"]
                ),
                "public_jd_id": public_jd_id,
                "projection_hash": projection["hash"],
            }

        public_interview_id, detail_ids = materialize_public_interview_from_projection(
            conn,
            projection,
            source_id=int(row["source_id"]),
            requester_id=int(row["requester_id"]),
            job_position=source_base.get("job_position") or "",
        )
        conn.execute(
            "UPDATE public_contribution_requests SET public_interview_id = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (public_interview_id, request_id),
        )

        # 把每个保留 item 显式关联到物化出的 public detail（AC-015 依据，
        # 不能只靠 source_item_id 或 URL；顺序与 projection.items 一致）
        for item_id, detail_id in zip(approved_item_ids, detail_ids):
            conn.execute(
                "UPDATE public_contribution_items SET status = 'queued', "
                "public_detail_id = ?, error_message = NULL, updated_at = CURRENT_TIMESTAMP "
                "WHERE id = ?",
                (detail_id, item_id),
            )

        # A user-share upload used the user's model for private preparation.
        # Public clustering must pass a fresh system-model probe before its
        # durable queue can be consumed; the upload worker may have completed
        # long before this approval happens.
        linked_root = conn.execute(
            "SELECT id, requester_id, policy_json FROM upload_imports "
            "WHERE contribution_request_id = ? ORDER BY created_at DESC, id DESC LIMIT 1",
            (request_id,),
        ).fetchone()
        if linked_root:
            policy = _loads(linked_root["policy_json"], {}) or {}
            credential_scope = policy.get("post_approval_credential_scope") or "global"
            attempt = conn.execute(
                "SELECT id FROM upload_attempts WHERE import_id = ? "
                "ORDER BY attempt_no DESC LIMIT 1",
                (linked_root["id"],),
            ).fetchone()
            from app.services.credential_preflight import create_credential_preflight_job

            create_credential_preflight_job(
                conn,
                root_import_id=str(linked_root["id"]),
                requester_id=int(linked_root["requester_id"]),
                credential_scope=credential_scope,
                user_id=(
                    int(linked_root["requester_id"])
                    if credential_scope == "user"
                    else None
                ),
                attempt_id=int(attempt["id"]) if attempt else None,
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
            "WHERE id = ? AND revision = ? AND status IN "
            "('pending_review','changes_requested','approved_for_processing','queued',"
            "'processing','partially_published')",
            (request_id, current_revision),
        )
        if updated.rowcount != 1:
            raise StateConflict("申请状态已被其他操作修改")

        # 撤回成功后不得留下本申请新建的可执行公共工作
        conn.execute(
            "UPDATE analysis_queue SET status = 'cancelled', processed_at = CURRENT_TIMESTAMP "
            "WHERE contribution_request_id = ? AND status IN ('pending','processing')",
            (request_id,),
        )
        # items 状态枚举没有 withdrawn；撤回的条目归入 rejected（不再执行）
        conn.execute(
            "UPDATE public_contribution_items SET status = 'rejected', "
            "updated_at = CURRENT_TIMESTAMP WHERE request_id = ? "
            "AND status IN ('pending_review','approved_for_processing','queued','processing')",
            (request_id,),
        )
        _restore_private_sources_after_withdrawal(
            conn, request_id=request_id, requester_id=requester_id
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


APPROVED_PROCESSING_STATES = (
    "approved_for_processing",
    "queued",
    "processing",
    "partially_published",
    "failed",
)


def retry_failed_public_items(conn, *, request_id: int, admin_id: int) -> dict:
    """Retry failed children under the same rootless queue lock as dispatch."""

    _begin_immediate(conn)
    try:
        result = _retry_failed_public_items_in_transaction(
            conn, request_id=request_id, admin_id=admin_id
        )
        _finish(conn, commit=True)
        return result
    except Exception:
        _finish(conn, commit=False)
        raise


def _retry_failed_public_items_in_transaction(
    conn, *, request_id: int, admin_id: int
) -> dict:
    """重试已批准申请的失败公共子项（AC-015 / contracts §4.1）。

    规则（contracts.md §3.3、§4.1）：

    - 仅批准后进入处理流程的申请可重试：``pending_review``/``changes_requested``
      拒绝为 ``STATE_CONFLICT``；
    - 复用同一审核投影，**不修改** review 状态/revision/projection_hash；
    - 只把 ``status='failed'`` 且有 ``public_detail_id`` 的子项重新入队并复位为
      ``queued``，已成功（published）子项不触碰；
    - 无失败子项时返回空列表，不假装执行了工作。
    """

    row = _request_row(conn, request_id)
    if row is None:
        raise ValueError("公共化申请不存在")
    if row["status"] not in APPROVED_PROCESSING_STATES:
        raise StateConflict(f"只有已批准且进入处理流程的申请可以重试失败子项: {row['status']}")

    failed_items = conn.execute(
        "SELECT id, public_detail_id FROM public_contribution_items "
        "WHERE request_id = ? AND status = 'failed' AND public_detail_id IS NOT NULL "
        "ORDER BY ordinal",
        (request_id,),
    ).fetchall()

    reprocessed: list[int] = []
    if failed_items:
        public_interview_id = row["public_interview_id"]
        for item in failed_items:
            detail_id = int(item["public_detail_id"])
            # 复用同一投影：把该 public_detail 重新放回分析队列（幂等去重）
            if public_interview_id is not None:
                enqueue_questions(
                    int(public_interview_id),
                    owner_id=None,
                    question_detail_ids=[detail_id],
                    contribution_request_id=request_id,
                    conn=conn,
                    retry_existing=True,
                )
            conn.execute(
                "UPDATE public_contribution_items SET status = 'queued', "
                "error_message = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (item["id"],),
            )
            reprocessed.append(int(item["id"]))
        if reprocessed:
            conn.execute(
                "UPDATE public_contribution_requests SET status = 'queued', "
                "error_message = NULL, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (request_id,),
            )
            # Root-bound upload rows get an independently fenced cluster job;
            # rootless legacy requests keep a compatible durable generic job.
            root_rows = conn.execute(
                "SELECT DISTINCT root_import_id FROM analysis_queue "
                "WHERE contribution_request_id = ? AND status = 'pending' "
                "AND root_import_id IS NOT NULL",
                (request_id,),
            ).fetchall()
            if root_rows:
                from app.services.upload_queue import collect_pending_buckets, ensure_bucket_job
                from app.services.credential_preflight import create_credential_preflight_job

                roots = {str(root["root_import_id"]) for root in root_rows}
                for root_id in roots:
                    root = conn.execute(
                        "SELECT id, requester_id, policy_json FROM upload_imports WHERE id = ?",
                        (root_id,),
                    ).fetchone()
                    if root is None:
                        continue
                    try:
                        policy = _loads(root["policy_json"], {}) or {}
                    except (TypeError, ValueError):
                        policy = {}
                    credential_scope = policy.get("post_approval_credential_scope") or "global"
                    attempt = conn.execute(
                        "SELECT id FROM upload_attempts WHERE import_id = ? "
                        "ORDER BY attempt_no DESC LIMIT 1",
                        (root_id,),
                    ).fetchone()
                    # Retry is a new public execution boundary: probe the
                    # current public model config before the dispatcher can
                    # release its cluster job. This also lets a root blocked
                    # on system credentials resume without replaying private
                    # extraction or changing the review projection.
                    create_credential_preflight_job(
                        conn,
                        root_import_id=root_id,
                        requester_id=int(root["requester_id"]),
                        credential_scope=credential_scope,
                        user_id=(
                            int(root["requester_id"])
                            if credential_scope == "user"
                            else None
                        ),
                        attempt_id=int(attempt["id"]) if attempt else None,
                    )
                for bucket in collect_pending_buckets(conn):
                    if str(bucket["root_import_id"]) in roots:
                        ensure_bucket_job(conn, bucket=bucket, created_by=admin_id)
            else:
                # A legacy generic rootless job can already be queued or
                # running and can dequeue these public rows. Let it finish
                # under the shared lock; its worker schedules a scoped
                # continuation after observing any remaining contributions.
                if not has_active_rootless_cluster_job(conn):
                    from app.services.job_lifecycle import CLUSTER_BATCH_JOB_TYPE
                    from uuid import uuid4 as _uuid4

                    cursor = conn.execute(
                        "INSERT INTO jobs (job_type, status, progress_total, created_by, "
                        "available_at, idempotency_key) "
                        "VALUES (?, 'pending', ?, ?, CURRENT_TIMESTAMP, ?)",
                        (
                            CLUSTER_BATCH_JOB_TYPE,
                            max(1, len(reprocessed)),
                            admin_id,
                            f"retry:{request_id}:{_uuid4().hex}",
                        ),
                    )
                    conn.execute(
                        "INSERT INTO job_payloads (job_id, payload) VALUES (?, ?)",
                        (
                            int(cursor.lastrowid),
                            _json(
                                {
                                    "user_id": admin_id,
                                    "queue_scope": "public_contribution",
                                }
                            ),
                        ),
                    )
        _event(
            conn,
            request_id,
            admin_id,
            "failed_items_retried",
            row["status"],
            "queued" if reprocessed else row["status"],
            {"reprocessed_item_ids": reprocessed},
        )

    return {
        "request_id": request_id,
        "status": "queued" if reprocessed else row["status"],
        "reprocessed_item_ids": [int(item_id) for item_id in reprocessed],
        "revision": int(row["revision"]),
        "projection_hash": row["projection_hash"],
    }


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
    expected_revision: int | None = None,
) -> dict:
    """审批落库并在进入聚类队列时调度后台攒批（v2 CAS，服务层统一入口）。

    路由层只调用本函数，不直接接触 pipeline 调度；聚类攒批沿用
    ``_run_cluster_batch_in_background`` 的持久化 job + ARQ best-effort 语义。

    ``expected_revision`` 缺省时取当前 revision（兼容旧 UI 空参数批准）；
    显式传入时按 CAS 校验，并发/过期批准返回 ``StateConflict``（HTTP 409）。
    审核请求经 ``build_review_projection_request`` 严格解析：未知字段拒绝，
    敏感来源字段默认不公开，只有显式确认才公开（AC-014）。
    """

    from app.models.upload_contracts import build_review_projection_request

    def _approve():
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT revision, source_type FROM public_contribution_requests WHERE id = ?",
                (request_id,),
            ).fetchone()
            if row is None:
                raise ValueError("公共化申请不存在")
            current_revision = int(row["revision"])
            revision = expected_revision if expected_revision is not None else current_revision
            review_request = build_review_projection_request(
                {
                    "expected_revision": revision,
                    "excluded_item_ids": excluded_item_ids or [],
                    "review_fields": review_fields or {},
                },
                source_type=row["source_type"],
            )
            return approve_public_contribution_v2(
                conn,
                request_id=request_id,
                admin_id=admin_id,
                review_request=review_request,
            )

    result = await run_db(_approve)
    if result.get("public_interview_id"):
        def _find_root_import_id():
            with get_db_connection() as conn:
                row = conn.execute(
                    "SELECT id FROM upload_imports WHERE contribution_request_id = ? "
                    "ORDER BY created_at DESC, id DESC LIMIT 1",
                    (request_id,),
                ).fetchone()
                return str(row["id"]) if row else None

        root_import_id = await run_db(_find_root_import_id)
        result["cluster_scheduled"] = await _run_cluster_batch_in_background(
            user_id=admin_id,
            root_import_id=root_import_id,
            queue_scope="public_contribution" if root_import_id is None else None,
        )
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


def mark_public_contribution_queue_done(
    conn,
    queue_ids: list[int],
    *,
    job_fence: tuple[int, int] | None = None,
    scope_fence: tuple[str, str, int] | None = None,
) -> int:
    """Close contribution items only when clustering wrote a valid resolution."""
    if not queue_ids:
        return 0
    owns_transaction = not conn.in_transaction
    _begin_immediate(conn)
    try:
        _assert_contribution_write_fences(conn, job_fence, scope_fence)
    except Exception:
        if owns_transaction:
            conn.rollback()
        raise
    queue_columns = {
        row[1] for row in conn.execute("PRAGMA table_info('analysis_queue')").fetchall()
    }
    if "contribution_request_id" not in queue_columns:
        if owns_transaction:
            conn.commit()
        return 0
    root_projection = (
        "root_import_id" if "root_import_id" in queue_columns else "NULL AS root_import_id"
    )
    placeholders = ",".join("?" * len(queue_ids))
    rows = conn.execute(
        "SELECT DISTINCT contribution_request_id, question_detail_id, interview_id, "
        f"{root_projection} "
        f"FROM analysis_queue WHERE id IN ({placeholders}) "
        "AND contribution_request_id IS NOT NULL",
        queue_ids,
    ).fetchall()
    request_interviews: dict[int, set[int]] = {}
    root_import_ids: set[str] = set()
    updated = 0
    for row in rows:
        if row["root_import_id"]:
            root_import_ids.add(str(row["root_import_id"]))
        request_id = int(row["contribution_request_id"])
        if not row["root_import_id"]:
            linked_root = conn.execute(
                "SELECT id FROM upload_imports WHERE contribution_request_id = ? "
                "ORDER BY created_at DESC, id DESC LIMIT 1",
                (request_id,),
            ).fetchone()
            if linked_root:
                root_import_ids.add(str(linked_root["id"]))
        request_interviews.setdefault(request_id, set()).add(int(row["interview_id"]))
        before = conn.execute(
            "SELECT status FROM public_contribution_items WHERE request_id = ? "
            "AND public_detail_id = ?",
            (request_id, row["question_detail_id"]),
        ).fetchone()
        publish_items_with_resolutions(conn, request_id=request_id)
        after = conn.execute(
            "SELECT status FROM public_contribution_items WHERE request_id = ? "
            "AND public_detail_id = ?",
            (request_id, row["question_detail_id"]),
        ).fetchone()
        if after and after["status"] != "published" and after["status"] != "rejected":
            conn.execute(
                "UPDATE public_contribution_items SET status = 'failed', "
                "error_message = '题目处理结束，但没有有效的公共题库 resolution', "
                "updated_at = CURRENT_TIMESTAMP WHERE request_id = ? "
                "AND public_detail_id = ? AND status != 'rejected'",
                (request_id, row["question_detail_id"]),
            )
            after = {"status": "failed"}
        if before and before["status"] != after["status"]:
            updated += 1

    for request_id, interview_ids in request_interviews.items():
        states = conn.execute(
            "SELECT status FROM public_contribution_items WHERE request_id = ?",
            (request_id,),
        ).fetchall()
        statuses = {state["status"] for state in states}
        for interview_id in interview_ids:
            refresh_public_interview_projection(conn, public_interview_id=interview_id)
        if statuses & {"queued", "processing", "approved_for_processing"}:
            continue
        if "failed" in statuses:
            # Failed children are retryable; keep a mixed request partially
            # published, or failed when no item has a valid public resolution.
            published_count = conn.execute(
                "SELECT COUNT(*) FROM public_contribution_items "
                "WHERE request_id = ? AND status = 'published'",
                (request_id,),
            ).fetchone()[0]
            final_status = "partially_published" if published_count else "failed"
            current = _request_row(conn, request_id)
            if current and current["status"] != final_status:
                conn.execute(
                    "UPDATE public_contribution_requests SET status = ?, "
                    "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (final_status, request_id),
                )
                _event(
                    conn,
                    request_id,
                    None,
                    "public_queue_completed_with_failures",
                    current["status"],
                    final_status,
                    {},
                )
            continue
        final_status = "partially_published" if "rejected" in statuses else "published"
        current = _request_row(conn, request_id)
        conn.execute(
            "UPDATE public_contribution_requests SET status = ?, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND status IN ('queued', 'processing', 'approved_for_processing', 'failed')",
            (final_status, request_id),
        )
        if current and current["status"] != final_status:
            _event(conn, request_id, None, "public_queue_completed", current["status"], final_status, {})
    if root_import_ids:
        from app.services.upload_lifecycle import refresh_completed_upload_roots

        refresh_completed_upload_roots(conn, root_import_ids)
    if owns_transaction:
        conn.commit()
    return updated


def mark_public_contribution_queue_failed(
    conn,
    queue_ids: list[int],
    error: str,
    *,
    job_fence: tuple[int, int] | None = None,
    scope_fence: tuple[str, str, int] | None = None,
) -> int:
    """Keep failed public contribution children visible for retry/audit."""
    if not queue_ids:
        return 0
    owns_transaction = not conn.in_transaction
    _begin_immediate(conn)
    try:
        _assert_contribution_write_fences(conn, job_fence, scope_fence)
    except Exception:
        if owns_transaction:
            conn.rollback()
        raise
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
        states = conn.execute(
            "SELECT status FROM public_contribution_items WHERE request_id = ?",
            (request_id,),
        ).fetchall()
        statuses = {state["status"] for state in states}
        if statuses & {"queued", "processing", "approved_for_processing"}:
            final_status = "processing"
        else:
            published_count = conn.execute(
                "SELECT COUNT(*) FROM public_contribution_items "
                "WHERE request_id = ? AND status = 'published'",
                (request_id,),
            ).fetchone()[0]
            final_status = "partially_published" if published_count else "failed"

        current = _request_row(conn, request_id)
        conn.execute(
            "UPDATE public_contribution_requests SET status = ?, error_message = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (final_status, error[:500], request_id),
        )
        _event(
            conn,
            request_id,
            None,
            "public_queue_failed",
            current["status"],
            final_status,
            {"error": error[:500]},
        )
        if current["public_interview_id"] is not None:
            # A terminal failed item may be the last in-flight child. Refresh
            # the parent now so successful siblings become publicly visible.
            refresh_public_interview_projection(
                conn, public_interview_id=int(current["public_interview_id"])
            )
    if owns_transaction:
        conn.commit()
    return updated


def _assert_contribution_write_fences(conn, job_fence, scope_fence):
    if job_fence is not None:
        from app.services.job_lifecycle import assert_job_fence

        assert_job_fence(conn, int(job_fence[0]), int(job_fence[1]))
    if scope_fence is not None:
        from app.services.upload_scope_leases import assert_upload_scope_lease

        assert_upload_scope_lease(
            conn,
            scope_fence[0],
            holder_token=scope_fence[1],
            generation=int(scope_fence[2]),
        )
