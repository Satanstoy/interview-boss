"""Review the legacy single-question request without crossing private ownership."""

import json

from fastapi import HTTPException

from app.services.admin_audit import append_admin_audit
from app.services.question_bank_integrity import (
    canonicalize_question_bank_payload,
    claim_public_original_questions,
    sync_question_bank_projections,
)


_SOURCE_FIELDS = (
    "question",
    "cat1",
    "cat2",
    "tags",
    "difficulty",
    "sources",
    "original_questions",
    "original_question_sources",
    "ai_answer",
    "answer_sources",
    "job_position",
)


def retire_submitted_source(conn, promotion, snapshot, target_id):
    source_id = promotion["source_question_id"]
    if source_id is None:
        return  # No text/URL-based inference for historical requests.
    source = conn.execute("SELECT * FROM question_bank WHERE id=?", (source_id,)).fetchone()
    if (
        not source
        or source["owner_id"] != promotion["requester_id"]
        or source["deleted_at"] is not None
        or any(source[field] != snapshot.get(field) for field in _SOURCE_FIELDS)
    ):
        return  # The owner may have changed the private version after submitting.
    conn.execute(
        "UPDATE question_bank SET deleted_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
        (source_id,),
    )
    sync_question_bank_projections(conn.cursor(), source_id, [], [], [])
    from app.services.question_resolution import record_resolution

    links = conn.execute(
        "SELECT r.* FROM question_resolutions r JOIN questions_detail qd ON qd.id=r.detail_id "
        "WHERE r.canonical_id=? AND r.occurrence_scope='private' AND r.occurrence_owner_id=? "
        "AND r.invalidated_at IS NULL AND qd.owner_id=? AND qd.deleted_at IS NULL",
        (source_id, promotion["requester_id"], promotion["requester_id"]),
    ).fetchall()
    for link in links:
        record_resolution(
            conn,
            detail_id=link["detail_id"],
            occurrence_scope="private",
            occurrence_owner_id=promotion["requester_id"],
            canonical_id=target_id,
            canonical_scope="public",
            status="matched",
            pipeline_version=link["pipeline_version"],
            taxonomy_version=link["taxonomy_version"],
            input_version=link["input_version"],
            confidence=link["confidence"],
            reason="public_promotion",
        )


def review_question_promotion(conn, question_id, reviewer_id, *, approve):
    conn.execute("BEGIN IMMEDIATE")
    row = conn.execute(
        "SELECT * FROM question_bank WHERE id=? AND owner_id IS NULL", (question_id,)
    ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="未找到该待审核题目")
    promotion = conn.execute(
        "SELECT * FROM question_promotion_requests WHERE pending_question_id=?", (question_id,)
    ).fetchone()
    if promotion and promotion["status"] != "pending":
        if promotion["status"] == ("approved" if approve else "rejected"):
            conn.commit()
            return
        raise HTTPException(status_code=409, detail="该申请已审核，不能改变审核结果")
    if row["status"] == "approved" and approve:
        conn.commit()
        return
    if row["status"] != "pending" or row["deleted_at"] is not None:
        raise HTTPException(status_code=409, detail="该申请已不在待审核状态")
    if promotion is None:
        # Snapshot only this voluntarily submitted public pending row. Never
        # fetch the requester's unrelated private data to reconstruct old links.
        conn.execute(
            "INSERT INTO question_promotion_requests(pending_question_id,requester_id,snapshot_json) VALUES (?,?,?)",
            (question_id, row["submitted_by"], json.dumps(dict(row), ensure_ascii=False)),
        )
        promotion = conn.execute(
            "SELECT * FROM question_promotion_requests WHERE pending_question_id=?", (question_id,)
        ).fetchone()
    snapshot = json.loads(promotion["snapshot_json"])
    if approve and snapshot.get("owner_id") is not None:
        source = conn.execute(
            "SELECT owner_id,deleted_at FROM question_bank WHERE id=?",
            (promotion["source_question_id"],),
        ).fetchone()
        if (
            not source
            or source["owner_id"] != promotion["requester_id"]
            or source["deleted_at"] is not None
        ):
            raise HTTPException(status_code=409, detail="私人来源已删除或失效，请撤回申请")
    target_id = None
    projection = None
    if approve:
        # Legacy review UI confirms the question, not personal source metadata.
        # Public sources therefore require a separate explicit review mechanism.
        projection = {key: snapshot.get(key) for key in _SOURCE_FIELDS}
        projection.update(
            id=question_id, owner_id=None, status="approved", sources="[]", ai_answer=None, answer_sources="[]"
        )
        originals = json.loads(snapshot.get("original_questions") or "[]")
        originals = originals or [snapshot["question"]]
        sources, originals, original_sources = canonicalize_question_bank_payload(
            [],
            originals,
            [{"question": q, "sources": []} for q in originals],
        )
        projection.update(
            original_questions=json.dumps(originals, ensure_ascii=False),
            original_question_sources=json.dumps(original_sources, ensure_ascii=False),
        )
        from app.routers.questions_pkg.share import (
            find_matching_public_question,
            _merge_private_into_public,
        )

        target_id = find_matching_public_question(
            conn, snapshot["question"], snapshot.get("cat2"), snapshot.get("job_position")
        )
        if target_id:
            _merge_private_into_public(conn, target_id, projection)
            conn.execute(
                "UPDATE question_bank SET status='approved',sources='[]',answer_sources='[]',original_question_sources=?, updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (projection["original_question_sources"], question_id),
            )
        else:
            target_id = question_id
            conn.execute(
                "UPDATE question_bank SET question=?,cat1=?,cat2=?,tags=?,difficulty=?,ai_answer=?, "
                "status='approved',sources='[]',answer_sources='[]',original_questions=?,original_question_sources=?, "
                "frequency=?,cluster_id=COALESCE(cluster_id,id),updated_at=CURRENT_TIMESTAMP WHERE id=?",
                (
                    snapshot["question"],
                    snapshot.get("cat1"),
                    snapshot.get("cat2"),
                    snapshot.get("tags"),
                    snapshot.get("difficulty"),
                    None,
                    projection["original_questions"],
                    projection["original_question_sources"],
                    len(originals),
                    question_id,
                ),
            )
            claim_public_original_questions(conn, question_id, None, "approved", originals)
            sync_question_bank_projections(
                conn.cursor(), question_id, sources, originals, original_sources
            )
            from app.services.cluster_review_lifecycle import mark_cluster_review_pending

            mark_cluster_review_pending(conn, question_id, "public_question_approved")
        retire_submitted_source(conn, promotion, snapshot, target_id)
    else:
        # question_bank permits pending/approved only. Rejection is the request
        # lifecycle; a tombstone removes its pending projection from all lists.
        conn.execute(
            "UPDATE question_bank SET deleted_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=?",
            (question_id,),
        )
        sync_question_bank_projections(conn.cursor(), question_id, [], [], [])
    status = "approved" if approve else "rejected"
    conn.execute(
        "UPDATE question_promotion_requests SET status=?,reviewer_id=?,target_question_id=?,review_projection_json=?,reviewed_at=CURRENT_TIMESTAMP WHERE pending_question_id=?",
        (
            status,
            reviewer_id,
            target_id,
            json.dumps(projection, ensure_ascii=False) if projection else None,
            question_id,
        ),
    )
    append_admin_audit(
        conn,
        f"question_promotion_{status}",
        "success",
        actor_id=reviewer_id,
        metadata={"pending_question_id": question_id, "target_question_id": target_id},
    )
    conn.commit()
