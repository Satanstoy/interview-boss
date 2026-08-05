# backend/app/routers/error_report.py
"""前端 JS 错误上报端点"""
from fastapi import APIRouter, Request
import structlog

router = APIRouter()
logger = structlog.stdlib.get_logger("frontend")

MAX_ERRORS = 50
MAX_FIELD_LEN = 2000


def _truncate(value, limit=MAX_FIELD_LEN):
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "…"
    return value


@router.post("/api/error-report")
async def error_report(request: Request):
    """接收前端 JS 错误上报（sendBeacon → JSON body）。

    匿名端点：限制条数与单条大小，防止日志刷写。
    """
    try:
        body = await request.json()
        errors = body.get("errors") if isinstance(body, dict) else None
        if not isinstance(errors, list) or not errors:
            return {"ok": True}  # 空上报静默接受（sendBeacon 偶发空 batch）
        if len(errors) > MAX_ERRORS:
            return {"ok": False}
        for entry in errors[:MAX_ERRORS]:
            if not isinstance(entry, dict):
                continue
            logger.error(
                "frontend_error",
                message=_truncate(entry.get("message")),
                url=_truncate(entry.get("url"), 500),
                source=_truncate(entry.get("source"), 500),
                lineno=entry.get("lineno"),
                stack=_truncate(entry.get("stack")),
                component=_truncate(entry.get("component"), 200),
                client_ip=request.client.host if request.client else None,
            )
        return {"ok": True}
    except Exception:
        return {"ok": False}
