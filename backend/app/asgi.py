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
from app.core.auth import cleanup_expired_refresh_tokens

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
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Requested-With", "X-Request-ID"],
    )

# ── GZip 压缩（>500B 的响应自动压缩）──
app.add_middleware(GZipMiddleware, minimum_size=500)


# ── 安全响应头 ──
class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if not DEBUG:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains; preload"
        return response


app.add_middleware(SecurityHeadersMiddleware)


# ── CSRF 中间件：在中间件层面拦截缺少自定义头的跨域请求 ──
_CSRF_EXEMPT_PATHS = {'/api/auth/login', '/api/auth/register', '/api/auth/login-form', '/api/health'}


class CSRFMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # 只检查状态变更方法
        if request.method in ('POST', 'PUT', 'DELETE'):
            if request.url.path not in _CSRF_EXEMPT_PATHS:
                has_custom_header = bool(request.headers.get("X-Requested-With"))
                ct = request.headers.get("content-type", "")
                has_json_content_type = "application/json" in ct
                if not has_custom_header and not has_json_content_type:
                    return JSONResponse(status_code=403, content={"detail": "缺少必要的请求头，请通过前端发起请求"})
        return await call_next(request)


app.add_middleware(CSRFMiddleware)

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


@app.on_event("startup")
async def startup_cleanup():
    """启动时清理过期的 refresh token"""
    try:
        cleanup_expired_refresh_tokens()
        logger.info("已清理过期的 refresh token")
    except Exception as e:
        logger.warning(f"清理过期 refresh token 失败: {e}")


@app.on_event("shutdown")
async def shutdown_cleanup():
    """关闭时清理数据库连接"""
    from app.db.connection import _local
    conn = getattr(_local, 'conn', None)
    if conn is not None:
        try:
            conn.close()
            logger.info("数据库连接已关闭")
        except Exception as e:
            logger.warning(f"关闭数据库连接失败: {e}")
