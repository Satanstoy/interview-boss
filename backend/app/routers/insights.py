"""洞察工作台 API。"""

from fastapi import APIRouter, Depends

from app.core.auth import get_current_user
from app.db.connection import run_db
from app.services.insights import build_insights_snapshot


router = APIRouter()


@router.get("/api/insights")
async def get_insights(user: dict = Depends(get_current_user)):
    """返回当前用户当前岗位的洞察快照。"""

    return await run_db(lambda: build_insights_snapshot(user))
