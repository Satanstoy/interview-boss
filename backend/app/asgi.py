import os
import traceback
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from app.core.logging_config import logger
from app.db.connection import init_db
from app.middleware.request_log import log_requests
from app.routers import health, submit, data, master_bank, interview, analytics, profile, auth
from app.core.config import _reload_from_db

init_db()
_reload_from_db()

# ── 环境配置 ──
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]

# ── 速率限制 ──
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])

app = FastAPI(
    title="InterviewBoss",
    docs_url="/docs" if DEBUG else None,
    redoc_url="/redoc" if DEBUG else None,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# ── CORS：默认只允许同源（nginx 代理下前端和 API 同域） ──
# 生产环境无需额外 origin；开发时设置 ALLOWED_ORIGINS=http://localhost:3000
if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

# ── GZip 压缩（>500B 的响应自动压缩）──
app.add_middleware(GZipMiddleware, minimum_size=500)


# ── 安全响应头 ──
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if not DEBUG:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


app.add_middleware(SecurityHeadersMiddleware)

app.middleware("http")(log_requests)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """捕获所有未处理的异常，返回统一 JSON 格式"""
    logger.error("未捕获异常: %s %s → %s\n%s", request.method, request.url.path, str(exc), traceback.format_exc())
    return JSONResponse(
        status_code=500,
        content={"status": "error", "detail": "服务器内部错误，请稍后重试"},
    )

app.include_router(health.router)
app.include_router(auth.router)
app.include_router(submit.router)
app.include_router(data.router)
app.include_router(master_bank.router)
app.include_router(interview.router)
app.include_router(analytics.router)
app.include_router(profile.router)
