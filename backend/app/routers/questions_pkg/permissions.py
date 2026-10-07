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
