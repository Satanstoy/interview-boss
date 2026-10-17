"""Immutable review projections and their public-only materialization."""

import json

from app.services.public_contribution_publication import refresh_public_interview_projection

SENSITIVE_SOURCE_FIELDS = ("company", "round", "source_url", "salary")

def _json(value):
    return json.dumps(value, ensure_ascii=False, default=str)

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

def _materialize_public_jd(conn, snapshot: dict, *, job_position: str | None = None) -> int:
    source = snapshot["source"]
    # 审核投影的源使用 source_url 字段（contracts §3.1）；旧直写路径用 url，兼容两者
    url = source.get("source_url") or source.get("url") or ""
    existing = conn.execute(
        "SELECT id FROM jd WHERE owner_id IS NULL AND url = ? "
        "AND deleted_at IS NULL ORDER BY id LIMIT 1",
        (url,),
    ).fetchone() if url else None
    if existing:
        return int(existing["id"])

    # 字段白名单：与 _materialize_public_interview 同口径。私有快照里的
    # 任何非白名单列（含未来新增列）都不得被连带公开（audit D5）。
    from app.db.utils import _extract_url_signature

    values = {
        "url": url,
        "company": source.get("company"),
        "tech_stack": source.get("tech_stack"),
        "position": source.get("position"),
        "salary": source.get("salary"),
        "job_title": source.get("job_title"),
        "bonus": source.get("bonus"),
        # 岗位从源冻结：投影 JD 源不含 job_position（contracts §3.1），
        # 旧直写路径携带时透传，避免公共 JD 丢失岗位信息（R11）
        "job_position": job_position if job_position is not None else source.get("job_position") or "",
        "season": source.get("season") or "",
        "url_signature": source.get("url_signature") or _extract_url_signature(url),
    }
    values.update({"owner_id": None, "status": "approved", "deleted_at": None})
    return _insert_dynamic(conn, "jd", values)

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

    - 面经 company/round 默认继承，显式 null/空串仍删除；
      source_url/salary 和 JD company 默认不公开，只有显式确认才公开；
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
    # 真实快照是 {source: {...}, items: [...]}，非敏感字段缺省需从 source 层级继承
    source_base = snapshot.get("source") if isinstance(snapshot, dict) else None
    if not isinstance(source_base, dict):
        source_base = {}
    source: dict = {}
    for field in sorted(allowed):
        requires_confirmation = field in SENSITIVE_SOURCE_FIELDS and not (
            source_type == "interview" and field in ("company", "round")
        )
        if requires_confirmation:
            value = getattr(source_model, field) if field in provided else None
        else:
            value = (
                getattr(source_model, field)
                if field in provided
                else source_base.get(field)
            )
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
            if field == "tags" and isinstance(value, list):
                if not all(isinstance(tag, str) for tag in value):
                    raise ValueError("审核标签数组必须只包含文本")
                # Normalize before hashing/preview so SQLite receives the exact
                # same tag text that the reviewer confirmed in the projection.
                value = ", ".join(tag.strip() for tag in value if tag.strip())
            if field != "tags" and isinstance(value, str):
                value = value.strip() or None
            fields[field] = value
        final_items.append(
            {
                "item_id": item_id,
                "ordinal": item.get("ordinal"),
                # Preserve the input ordinal through the immutable review
                # projection. Contribution-item ordinals are their own
                # zero-based sequence and cannot replace this source identity.
                "source_ordinal": (
                    int(item["source_ordinal"])
                    if item.get("source_ordinal") is not None
                    else (
                        int(item["ordinal"]) + 1
                        if item.get("ordinal") is not None
                        else None
                    )
                ),
                **fields,
            }
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
        # AC-015/README §5.3：审批通过 ≠ published，公共处理落定前不可被公开读取
        "publish_status": "pending",
        "url_signature": url_signature,
        "job_position": job_position,
    }
    # R10/AC-016：同 URL 已有公共面经时复用而不重复建（追加贡献一致）
    if source_url:
        existing = conn.execute(
            "SELECT id FROM interview WHERE owner_id IS NULL AND url = ? "
            "AND deleted_at IS NULL ORDER BY id LIMIT 1",
            (source_url,),
        ).fetchone()
        if existing is not None:
            interview_id = int(existing["id"])
            # contracts §3.3 / AC-016：清单只能由「已发布明细」投影决定。
            # 这里不能用本次投影覆盖 questions_list——那会丢掉既有已发布题目，
            # 并让尚未 published 的子项提前出现在公开清单里。
            # 复用分支只追加明细，清单交给 refresh_public_interview_projection 重建。
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
                            "source_ordinal": item.get("source_ordinal"),
                            "job_position": job_position,
                        },
                    )
                )
            # 用「已发布明细」重建清单：既保留既有已发布题目，也不会提前暴露
            # 本次尚未 published 的子项（此时 approve 还没把 items 关联到新明细）。
            refresh_public_interview_projection(conn, public_interview_id=interview_id)
            return interview_id, detail_ids
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
                    "source_ordinal": item.get("source_ordinal"),
                    "job_position": job_position,
                },
            )
        )
    return interview_id, detail_ids
