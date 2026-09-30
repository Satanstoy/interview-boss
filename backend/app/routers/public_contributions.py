"""Private interview/JD contribution requests and unified admin review API."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.auth import get_admin_user, get_current_user
from app.db.connection import get_db_connection, run_db
from app.models.upload_contracts import ReviewFieldError
from app.services.public_contributions import (
    StateConflict,
    create_public_contribution_request,
    finalize_public_contribution_approval,
    get_public_contribution_request,
    list_public_contribution_requests,
    reject_public_contribution,
    retry_failed_public_items,
    withdraw_public_contribution_v2,
)


class ContributionCreateRequest(BaseModel):
    source_type: Literal["interview", "jd"]
    source_id: int = Field(gt=0)


class ContributionApproveRequest(BaseModel):
    excluded_item_ids: list[int] = Field(default_factory=list)
    review_fields: dict = Field(default_factory=dict)
    expected_revision: int | None = Field(default=None, ge=1)


class ContributionRejectRequest(BaseModel):
    reason: str = Field(default="", max_length=500)


router = APIRouter(tags=["public-contributions"])


def _bad_request(error: ValueError):
    raise HTTPException(status_code=400, detail=str(error))


@router.post("/api/public-contributions")
async def create_contribution(
    request: ContributionCreateRequest,
    user: dict = Depends(get_current_user),
):
    def _create():
        with get_db_connection() as conn:
            return create_public_contribution_request(
                conn, request.source_type, request.source_id, user["id"]
            )

    try:
        return await run_db(_create)
    except ValueError as error:
        _bad_request(error)


@router.get("/api/public-contributions/mine")
async def list_my_contributions(user: dict = Depends(get_current_user)):
    def _list():
        with get_db_connection() as conn:
            return [
                item
                for item in list_public_contribution_requests(conn, status=None)
                if item["requester_id"] == user["id"]
            ]

    items = await run_db(_list)
    return {"items": items, "total": len(items)}


@router.get("/api/public-contributions/{request_id}")
async def get_my_contribution(request_id: int, user: dict = Depends(get_current_user)):
    def _get():
        with get_db_connection() as conn:
            result = get_public_contribution_request(conn, request_id)
            if result["requester_id"] != user["id"]:
                raise PermissionError("无权查看该公共化申请")
            return result

    try:
        return await run_db(_get)
    except PermissionError as error:
        raise HTTPException(status_code=403, detail=str(error))
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.post("/api/public-contributions/{request_id}/withdraw")
async def withdraw_contribution(request_id: int, user: dict = Depends(get_current_user)):
    def _withdraw():
        with get_db_connection() as conn:
            return withdraw_public_contribution_v2(
                conn,
                request_id=request_id,
                requester_id=user["id"],
            )

    try:
        return await run_db(_withdraw)
    except StateConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except ValueError as error:
        _bad_request(error)


@router.get("/api/admin/public-contributions")
async def list_admin_contributions(
    status: str | None = Query("pending_review"),
    source_type: Literal["interview", "jd"] | None = Query(None),
    admin: dict = Depends(get_admin_user),
):
    def _list():
        with get_db_connection() as conn:
            items = list_public_contribution_requests(conn, status=status, source_type=source_type)

            # Keep legacy single-question pending rows visible until the old
            # endpoint is retired; they belong to the question-bank tab.
            legacy = []
            if (not source_type or source_type == "interview") and status in (
                None,
                "pending_review",
            ):
                legacy = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT qb.id, qb.question, qb.cat1, qb.cat2, qb.tags, "
                        "qb.difficulty, qb.created_at, u.username AS submitted_by_name "
                        "FROM question_bank qb LEFT JOIN users u ON qb.submitted_by = u.id "
                        "WHERE qb.owner_id IS NULL AND qb.status = 'pending' "
                        "AND qb.deleted_at IS NULL ORDER BY qb.created_at DESC"
                    ).fetchall()
                ]
            return items, legacy

    items, legacy = await run_db(_list)
    return {"items": items, "total": len(items) + len(legacy)}


@router.get("/api/admin/public-contributions/{request_id}")
async def get_admin_contribution(request_id: int, admin: dict = Depends(get_admin_user)):
    def _get():
        with get_db_connection() as conn:
            return get_public_contribution_request(conn, request_id)

    try:
        return await run_db(_get)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))


@router.post("/api/admin/public-contributions/{request_id}/approve")
async def approve_contribution(
    request_id: int,
    request: ContributionApproveRequest,
    admin: dict = Depends(get_admin_user),
):
    try:
        return await finalize_public_contribution_approval(
            request_id,
            admin["id"],
            excluded_item_ids=request.excluded_item_ids,
            review_fields=request.review_fields,
            expected_revision=request.expected_revision,
        )
    except StateConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except ReviewFieldError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    except ValueError as error:
        _bad_request(error)


@router.post("/api/admin/public-contributions/{request_id}/reject")
async def reject_contribution(
    request_id: int,
    request: ContributionRejectRequest,
    admin: dict = Depends(get_admin_user),
):
    def _reject():
        with get_db_connection() as conn:
            return reject_public_contribution(conn, request_id, admin["id"], request.reason)

    try:
        return await run_db(_reject)
    except ValueError as error:
        _bad_request(error)


@router.post("/api/admin/public-contributions/{request_id}/retry")
async def retry_contribution(
    request_id: int,
    admin: dict = Depends(get_admin_user),
):
    """重试已批准申请的失败公共子项（AC-015）：复用同一投影，不改审核状态。"""

    def _retry():
        with get_db_connection() as conn:
            return retry_failed_public_items(conn, request_id=request_id, admin_id=admin["id"])

    try:
        return await run_db(_retry)
    except StateConflict as error:
        raise HTTPException(status_code=409, detail=str(error)) from None
    except ValueError as error:
        _bad_request(error)
