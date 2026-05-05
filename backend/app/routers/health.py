import logging
from fastapi import APIRouter, HTTPException
from app.db.connection import get_db_connection, run_db

logger = logging.getLogger("interview-boss")

router = APIRouter()


@router.get("/api/health")
async def health_check():
    """健康检查端点，供 Nginx/负载均衡器探活"""
    try:
        def _ping():
            with get_db_connection() as conn:
                conn.execute("SELECT 1").fetchone()
        await run_db(_ping)
        return {"status": "ok", "db": "connected"}
    except Exception as e:
        logger.error(f"健康检查失败: {e}")
        raise HTTPException(status_code=503, detail="数据库连接异常")
