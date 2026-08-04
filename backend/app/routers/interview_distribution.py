"""Read the materialized public interview-distribution default."""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import get_current_user
from app.db.connection import get_db_connection, get_user_job_position, run_db
from app.services.interview_distribution import (
    DistributionStatsUnavailable,
    get_distribution_default,
    refresh_distribution_scope,
)


router = APIRouter()


@router.get("/api/interview/distribution/default")
async def get_interview_distribution_default(
    job_position: str | None = Query(None), user: dict = Depends(get_current_user)
):
    """Return a complete versioned system default for the requested position."""
    position = job_position or get_user_job_position(user["id"])[1]

    def _load():
        with get_db_connection() as conn:
            try:
                return get_distribution_default(conn, position)
            except DistributionStatsUnavailable:
                # First use has no worker result yet; materialize one complete version.
                result = refresh_distribution_scope(conn, "public_job_position", position)
                conn.commit()
                return get_distribution_default(conn, position) if result else None

    try:
        result = await run_db(_load)
    except DistributionStatsUnavailable as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "success", "data": {**result, "stale": False}}
