"""Publish contribution items using durable canonical resolutions."""

def _promote_private_source_canonical(
    conn,
    *,
    requester_id: int,
    source_detail_id: int,
    public_detail_id: int,
) -> int | None:
    """Retire the submitter's private cluster after its public item resolves."""

    source = conn.execute(
        "SELECT * FROM question_resolutions WHERE detail_id = ? "
        "AND invalidated_at IS NULL LIMIT 1",
        (source_detail_id,),
    ).fetchone()
    if (
        source is None
        or source["occurrence_scope"] != "private"
        or int(source["occurrence_owner_id"] or -1) != int(requester_id)
        or source["canonical_scope"] != "private"
        or source["status"] not in ("matched", "created")
        or source["canonical_id"] is None
    ):
        return None

    public = conn.execute(
        "SELECT r.canonical_id, r.pipeline_version, r.taxonomy_version, r.input_version, "
        "r.confidence FROM question_resolutions r "
        "JOIN question_bank qb ON qb.id = r.canonical_id "
        "WHERE r.detail_id = ? AND r.invalidated_at IS NULL "
        "AND r.occurrence_scope = 'public' AND r.occurrence_owner_id IS NULL "
        "AND r.canonical_scope = 'public' AND r.status IN ('matched','created') "
        "AND qb.owner_id IS NULL AND qb.status = 'approved' AND qb.deleted_at IS NULL "
        "LIMIT 1",
        (public_detail_id,),
    ).fetchone()
    if public is None:
        return None

    private_canonical_id = int(source["canonical_id"])
    private_canonical = conn.execute(
        "SELECT owner_id, deleted_at FROM question_bank WHERE id = ?",
        (private_canonical_id,),
    ).fetchone()
    if (
        private_canonical is None
        or int(private_canonical["owner_id"] or -1) != int(requester_id)
    ):
        return None

    from app.services.question_resolution import record_resolution

    private_occurrences = conn.execute(
        "SELECT detail_id FROM question_resolutions WHERE canonical_id = ? "
        "AND occurrence_scope = 'private' AND occurrence_owner_id = ? "
        "AND canonical_scope = 'private' AND status IN ('matched','created') "
        "AND invalidated_at IS NULL ORDER BY detail_id",
        (private_canonical_id, requester_id),
    ).fetchall()
    for occurrence in private_occurrences:
        record_resolution(
            conn,
            detail_id=int(occurrence["detail_id"]),
            occurrence_scope="private",
            occurrence_owner_id=int(requester_id),
            canonical_id=int(public["canonical_id"]),
            canonical_scope="public",
            status="matched",
            pipeline_version=public["pipeline_version"],
            taxonomy_version=public["taxonomy_version"],
            input_version=int(public["input_version"] or 1),
            confidence=public["confidence"],
            reason="public_promotion",
        )

    conn.execute(
        "UPDATE question_bank SET deleted_at = CURRENT_TIMESTAMP, "
        "updated_at = CURRENT_TIMESTAMP WHERE id = ? AND owner_id = ? AND deleted_at IS NULL",
        (private_canonical_id, requester_id),
    )
    return private_canonical_id

def _restore_private_sources_after_withdrawal(conn, *, request_id: int, requester_id: int):
    """Restore this request's private sources without undoing another request's promotion."""

    source_rows = conn.execute(
        "SELECT i.source_item_id FROM public_contribution_items i "
        "WHERE i.request_id = ? AND i.source_item_type = 'question' "
        "AND i.source_item_id IS NOT NULL "
        "AND NOT EXISTS ("
        "SELECT 1 FROM public_contribution_items published "
        "WHERE published.source_item_type = 'question' "
        "AND published.source_item_id = i.source_item_id "
        "AND published.status = 'published' AND published.request_id != i.request_id"
        ")",
        (request_id,),
    ).fetchall()
    source_detail_ids = {int(row["source_item_id"]) for row in source_rows}
    if not source_detail_ids:
        return

    private_canonical_ids = set()
    for source_row in source_rows:
        previous = conn.execute(
            "SELECT canonical_id FROM question_resolutions WHERE detail_id = ? "
            "AND occurrence_scope = 'private' AND occurrence_owner_id = ? "
            "AND canonical_scope = 'private' AND canonical_id IS NOT NULL "
            "ORDER BY id DESC LIMIT 1",
            (int(source_row["source_item_id"]), requester_id),
        ).fetchone()
        if previous:
            private_canonical_ids.add(int(previous["canonical_id"]))
    if not private_canonical_ids:
        return

    from app.services.question_resolution import record_resolution

    detail_placeholders = ",".join("?" for _ in source_detail_ids)
    promoted = conn.execute(
        "SELECT * FROM question_resolutions WHERE occurrence_scope = 'private' "
        "AND occurrence_owner_id = ? AND canonical_scope = 'public' "
        "AND reason = 'public_promotion' AND invalidated_at IS NULL "
        f"AND detail_id IN ({detail_placeholders})",
        (requester_id, *sorted(source_detail_ids)),
    ).fetchall()
    for current in promoted:
        previous = conn.execute(
            "SELECT * FROM question_resolutions WHERE detail_id = ? "
            "AND occurrence_scope = 'private' AND occurrence_owner_id = ? "
            "AND canonical_scope = 'private' AND canonical_id IS NOT NULL "
            "AND invalidated_at IS NOT NULL ORDER BY id DESC LIMIT 1",
            (int(current["detail_id"]), requester_id),
        ).fetchone()
        if previous is None or int(previous["canonical_id"]) not in private_canonical_ids:
            continue

        conn.execute(
            "UPDATE question_bank SET deleted_at = NULL, updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND owner_id = ?",
            (int(previous["canonical_id"]), requester_id),
        )
        record_resolution(
            conn,
            detail_id=int(current["detail_id"]),
            occurrence_scope="private",
            occurrence_owner_id=int(requester_id),
            canonical_id=int(previous["canonical_id"]),
            canonical_scope="private",
            status=previous["status"],
            pipeline_version=previous["pipeline_version"],
            taxonomy_version=previous["taxonomy_version"],
            input_version=int(previous["input_version"] or 1),
            confidence=previous["confidence"],
            reason="promotion_withdrawn",
        )

def publish_items_with_resolutions(conn, *, request_id: int) -> dict:
    """把持有**当前有效** public resolution 的 item 标记 published（AC-015）。

    ``public_detail_id`` 存在不是成功证据；失败/失效 resolution 的子项保持待处理，
    恢复时只处理这些子项，不重复已成功的，也不需要新增实体。
    """

    items = conn.execute(
        "SELECT i.id AS id, i.status AS status, i.public_detail_id AS public_detail_id, "
        "i.source_item_type AS source_item_type, i.source_item_id AS source_item_id, "
        "r.requester_id AS requester_id, d.id AS detail_id "
        "FROM public_contribution_items i "
        "JOIN public_contribution_requests r ON r.id = i.request_id "
        "LEFT JOIN questions_detail d ON d.id = i.public_detail_id "
        "WHERE i.request_id = ? ORDER BY i.ordinal",
        (request_id,),
    ).fetchall()

    published: list[int] = []
    pending: list[int] = []
    newly_published: list[int] = []
    for item in items:
        item_id = int(item["id"])
        if item["status"] == "published":
            published.append(item_id)
            continue
        if item["status"] == "rejected":
            # 审核排除项不再参与处理，不算 pending，也不阻塞发布
            continue
        valid = None
        if item["public_detail_id"]:
            valid = conn.execute(
                "SELECT r.id FROM question_resolutions r "
                "JOIN question_bank qb ON qb.id = r.canonical_id "
                "WHERE r.detail_id = ? AND r.invalidated_at IS NULL "
                "AND r.occurrence_scope = 'public' AND r.occurrence_owner_id IS NULL "
                "AND r.canonical_scope = 'public' AND r.status IN ('matched','created') "
                "AND qb.owner_id IS NULL AND qb.status = 'approved' "
                "AND qb.deleted_at IS NULL LIMIT 1",
                (int(item["public_detail_id"]),),
            ).fetchone()
        if valid is not None and item["detail_id"] is not None:
            conn.execute(
                "UPDATE public_contribution_items SET status = 'published', "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (item_id,),
            )
            if item["source_item_type"] == "question" and item["source_item_id"] is not None:
                _promote_private_source_canonical(
                    conn,
                    requester_id=int(item["requester_id"]),
                    source_detail_id=int(item["source_item_id"]),
                    public_detail_id=int(item["public_detail_id"]),
                )
            published.append(item_id)
            newly_published.append(item_id)
        else:
            pending.append(item_id)

    return {
        "published_item_ids": sorted(published),
        "pending_item_ids": sorted(pending),
        "reprocessed_item_ids": sorted(newly_published),
    }

def refresh_public_interview_projection(conn, *, public_interview_id: int) -> dict:
    """重建公共面经 ``questions_list``：只包含 published 且未删除的明细（AC-016）。"""

    rows = conn.execute(
        "SELECT d.question AS question FROM questions_detail d "
        "JOIN public_contribution_items i ON i.public_detail_id = d.id "
        "JOIN question_resolutions r ON r.detail_id = d.id "
        "AND r.invalidated_at IS NULL AND r.status IN ('matched','created') "
        "JOIN question_bank qb ON qb.id = r.canonical_id "
        "AND qb.owner_id IS NULL AND qb.status = 'approved' AND qb.deleted_at IS NULL "
        "WHERE d.interview_id = ? AND d.deleted_at IS NULL AND i.status = 'published' "
        "ORDER BY d.id",
        (public_interview_id,),
    ).fetchall()
    questions_list = "\n".join(
        f"{index}. {row['question']}"
        for index, row in enumerate(rows, start=1)
        if row["question"]
    )
    conn.execute(
        "UPDATE interview SET questions_list = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
        (questions_list, public_interview_id),
    )
    # 发布门槛（AC-015/README §5.3）：该申请的公共子项全部落定后才公开面经行。
    # 仍有 queued/processing 子项时保持 pending；同 URL 复用的既有面经不降级。
    in_flight = conn.execute(
        "SELECT COUNT(*) FROM public_contribution_items i "
        "JOIN public_contribution_requests r ON r.id = i.request_id "
        "WHERE r.public_interview_id = ? "
        "AND i.status IN ('queued', 'processing', 'approved_for_processing')",
        (public_interview_id,),
    ).fetchone()[0]
    if not in_flight:
        conn.execute(
            "UPDATE interview SET publish_status = 'published', "
            "updated_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND publish_status != 'published'",
            (public_interview_id,),
        )
    return {
        "public_interview_id": public_interview_id,
        "published_details": len(rows),
        "questions_list": questions_list,
    }

def request_publish_status(conn, *, request_id: int) -> str:
    """申请的发布状态：全部 item published 才是 published。"""

    total = conn.execute(
        "SELECT COUNT(*) FROM public_contribution_items WHERE request_id = ? "
        "AND status != 'rejected'",
        (request_id,),
    ).fetchone()[0]
    published = conn.execute(
        "SELECT COUNT(*) FROM public_contribution_items WHERE request_id = ? "
        "AND status = 'published'",
        (request_id,),
    ).fetchone()[0]
    if total and published == total:
        return "published"
    if published:
        return "partially_published"
    return "processing"
