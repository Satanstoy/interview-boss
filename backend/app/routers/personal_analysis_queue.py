"""Owner-facing endpoints for personal rootless analysis recovery."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.core.auth import get_current_user
from app.db.connection import get_db_connection, run_db
from app.services.personal_analysis_recovery import (
    MAX_SQLITE_INTEGER,
    MAX_PERSONAL_FAILURE_REFRESH_ITEMS,
    PersonalAnalysisRetryError,
    list_personal_analysis_failures,
    refresh_personal_analysis_failures,
    retry_personal_analysis_failure,
)

logger = logging.getLogger("interview-boss")
router = APIRouter()


class PersonalAnalysisFailureCursor(BaseModel):
    created_at: str
    queue_id: int = Field(ge=1, le=MAX_SQLITE_INTEGER)


class RefreshPersonalAnalysisFailuresRequest(BaseModel):
    loaded_count: int = Field(ge=1, le=MAX_PERSONAL_FAILURE_REFRESH_ITEMS)
    cursor: PersonalAnalysisFailureCursor | None = None


@router.get("/api/personal-analysis-queue/failed")
async def list_personal_analysis_queue_failures(
    user: dict = Depends(get_current_user),
    page: int = 1,
    page_size: int = 20,
):
    """List this user's readable terminal personal queue failures."""

    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    return await run_db(
        lambda: list_personal_analysis_failures(
            get_db_connection(),
            owner_id=int(user["id"]),
            page=page,
            page_size=page_size,
        )
    )


@router.post("/api/personal-analysis-queue/failed/refresh")
async def refresh_personal_analysis_queue_failures(
    request: RefreshPersonalAnalysisFailuresRequest,
    user: dict = Depends(get_current_user),
):
    """Refresh the current owner-scoped loaded range in one request."""

    return await run_db(
        lambda: refresh_personal_analysis_failures(
            get_db_connection(),
            owner_id=int(user["id"]),
            loaded_count=request.loaded_count,
            cursor=request.cursor.model_dump() if request.cursor else None,
        )
    )


@router.post("/api/personal-analysis-queue/{queue_id}/retry")
async def retry_personal_analysis_queue_failure(
    queue_id: int = Path(ge=1, le=MAX_SQLITE_INTEGER),
    user: dict = Depends(get_current_user),
):
    """Retry one queue row without making an upload root or upload attempt."""

    def _retry():
        try:
            return retry_personal_analysis_failure(
                get_db_connection(),
                queue_id=int(queue_id),
                owner_id=int(user["id"]),
            )
        except PersonalAnalysisRetryError as exc:
            raise HTTPException(status_code=exc.status_code, detail=exc.detail) from None

    result = await run_db(_retry)
    if result["status"] in ("pending", "processing"):
        try:
            # The durable rootless scheduler is idempotent; an existing active
            # cluster job consumes the row, otherwise its outbox is dispatched.
            from app.services.pipeline.queue import _run_cluster_batch_in_background

            await _run_cluster_batch_in_background(user_id=int(user["id"]))
        except Exception:
            logger.exception(
                "个人 rootless 队列重试保留待调度: queue_id=%s owner_id=%s",
                queue_id,
                user["id"],
            )

    return JSONResponse(
        status_code=202 if result["created"] else 200,
        content=result,
    )
