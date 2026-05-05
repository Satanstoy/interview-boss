import time
import logging
from fastapi import Request

logger = logging.getLogger("interview-boss")


async def log_requests(request: Request, call_next):
    """记录每个请求的方法、路径、状态码、耗时"""
    start = time.time()
    response = await call_next(request)
    elapsed = round((time.time() - start) * 1000, 1)
    level = logging.WARNING if response.status_code >= 400 else logging.INFO
    logger.log(level, "%s %s → %d (%.1fms)", request.method, request.url.path, response.status_code, elapsed)
    return response
