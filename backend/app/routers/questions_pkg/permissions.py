"""Ownership checks for canonical question mutations."""

from fastapi import HTTPException

from app.db.queries import can_edit_question


def assert_question_writable(
    owner_id, user: dict, *, not_found: str, public_forbidden: str = "无权修改公共题目"
):
    """Hide foreign private questions; only their owner can mutate them."""
    if can_edit_question(owner_id, user["id"], bool(user.get("is_admin", 0))):
        return
    if owner_id is not None:
        raise HTTPException(status_code=404, detail=not_found)
    raise HTTPException(status_code=403, detail=public_forbidden)


def assert_question_lifecycle_mutable(conn, question_id: int):
    """Request projections and retired redirects have their own lifecycle."""
    promotion = conn.execute(
        "SELECT status,target_question_id FROM question_promotion_requests WHERE pending_question_id=?",
        (question_id,),
    ).fetchone()
    projection = conn.execute(
        "SELECT owner_id,status FROM question_bank WHERE id=?", (question_id,)
    ).fetchone()
    if projection and projection["owner_id"] is None and projection["status"] == "pending":
        raise HTTPException(status_code=409, detail="请使用发布申请的审核或撤回操作")
    if promotion and (
        promotion["status"] != "approved" or promotion["target_question_id"] != question_id
    ):
        raise HTTPException(status_code=409, detail="请使用发布申请的审核或撤回操作")
