# backend/app/routers/error_report.py
"""前端 JS 错误上报端点"""
from fastapi import APIRouter, Request
import structlog

router = APIRouter()
logger = structlog.stdlib.get_logger("frontend")


@router.post("/api/error-report")
async def error_report(request: Request):
    """接收前端 JS 错误上报（sendBeacon → JSON body）"""
    try:
        body = await request.json()
        for entry in body.get("errors", []):
            logger.error(
                "frontend_error",
                message=entry.get("message"),
                url=entry.get("url"),
                source=entry.get("source"),
                lineno=entry.get("lineno"),
                stack=entry.get("stack"),
                component=entry.get("component"),
                client_ip=request.client.host if request.client else None,
            )
        return {"ok": True}
    except Exception:
        return {"ok": False}
