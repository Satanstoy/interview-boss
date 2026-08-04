"""Authenticated per-position interview-distribution preferences."""

import json

from fastapi import APIRouter, Depends, HTTPException, Query

from app.core.auth import get_current_user
from app.db.connection import get_db_connection, get_user_job_position, run_db
from app.models.schemas import DistributionPreferenceRequest


router = APIRouter()


def _response_from_row(row):
    if not row:
        return {
            "mode": "system_default",
            "target_question_count": None,
            "custom_distribution": None,
            "selected_experience_id": None,
            "style_strength": "normal",
        }
    return {
        "mode": row["mode"],
        "target_question_count": row["target_question_count"],
        "custom_distribution": json.loads(row["custom_distribution"]) if row["custom_distribution"] else None,
        "selected_experience_id": row["selected_experience_id"],
        "style_strength": row["style_strength"],
    }


@router.get("/api/profile/interview-distribution-preference")
async def get_interview_distribution_preference(
    job_position: str | None = Query(None), user: dict = Depends(get_current_user)
):
    position = job_position or get_user_job_position(user["id"])[1]

    def _load():
        with get_db_connection() as conn:
            return conn.execute(
                "SELECT * FROM user_interview_distribution_preferences WHERE user_id = ? AND job_position = ?",
                (user["id"], position),
            ).fetchone()

    return {"status": "success", "data": _response_from_row(await run_db(_load))}


@router.put("/api/profile/interview-distribution-preference")
async def save_interview_distribution_preference(
    req: DistributionPreferenceRequest,
    job_position: str | None = Query(None),
    user: dict = Depends(get_current_user),
):
    position = job_position or get_user_job_position(user["id"])[1]

    def _save():
        with get_db_connection() as conn:
            if req.selected_experience_id is not None:
                accessible = conn.execute(
                    """
                    SELECT 1 FROM interview
                    WHERE id = ? AND (owner_id = ? OR owner_id IS NULL)
                      AND status = 'approved' AND deleted_at IS NULL
                    """,
                    (req.selected_experience_id, user["id"]),
                ).fetchone()
                if not accessible:
                    raise HTTPException(status_code=422, detail="所选面经不存在、未审批或无权访问")
            conn.execute(
                """
                INSERT INTO user_interview_distribution_preferences (
                    user_id, job_position, mode, target_question_count, custom_distribution,
                    selected_experience_id, style_strength, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(user_id, job_position) DO UPDATE SET
                    mode = excluded.mode,
                    target_question_count = excluded.target_question_count,
                    custom_distribution = excluded.custom_distribution,
                    selected_experience_id = excluded.selected_experience_id,
                    style_strength = excluded.style_strength,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    user["id"], position, req.mode, req.target_question_count,
                    json.dumps(req.custom_distribution, ensure_ascii=False) if req.custom_distribution else None,
                    req.selected_experience_id, req.style_strength,
                ),
            )
            conn.commit()
            return conn.execute(
                "SELECT * FROM user_interview_distribution_preferences WHERE user_id = ? AND job_position = ?",
                (user["id"], position),
            ).fetchone()

    return {"status": "success", "data": _response_from_row(await run_db(_save))}
