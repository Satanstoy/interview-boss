# backend/app/middleware/request_log.py
import structlog
import time
import uuid

logger = structlog.stdlib.get_logger("middleware")


async def log_requests(request, call_next):
    """记录请求日志，绑定 request_id 到上下文"""
    request_id = uuid.uuid4().hex[:8]

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )

    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)

    log_fn = logger.warning if response.status_code >= 400 else logger.info
    log_fn(
        "request_completed",
        status=response.status_code,
        duration_ms=duration_ms,
    )

    response.headers["X-Request-ID"] = request_id
    return response
