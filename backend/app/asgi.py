import os
import traceback
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.request_ip import get_client_ip
from app.core.logging_config import logger
from app.db.connection import init_db
from app.middleware.request_log import log_requests
from app.routers import (
    health,
    submit,
    data,
    questions,
    answers,
    practice,
    admin_quality,
    admin_assistant,
    admin_review,
    admin_source_health,
    bank_build,
    interview,
    interview_distribution,
    analytics,
    insights,
    profile,
    auth,
    chat,
    coding,
    error_report,
)
from app.routers.profile_pkg import router as profile_pkg_router
from app.routers.questions_pkg import router as questions_pkg_router
from app.core.config import _reload_from_db
from app.core.auth import cleanup_expired_refresh_tokens
from app.mcp_server.app import mcp, mcp_app

init_db()
_reload_from_db()

# 同步 embedding 配置（DB 优先，env 兜底）：容器重启后保持管理员保存的配置
from app.services.embedding_service import reload_embedding_config

reload_embedding_config()

# ── 环境配置 ──
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
ALLOWED_ORIGINS = [
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()
]

# ── 速率限制 ──
limiter = Limiter(key_func=get_client_ip, default_limits=["200/minute"])

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
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Requested-With",
            "X-Request-ID",
        ],
    )

# ── GZip 压缩 ──
# 由 nginx 处理压缩（http 块 gzip on + /api/ location gzip off for SSE）
# 应用层不再使用 GZipMiddleware，避免其内部缓冲破坏 SSE 流式传输


# ── 安全响应头（纯 ASGI 实现，避免 BaseHTTPMiddleware 缓冲 SSE 响应）──
_SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"referrer-policy", b"strict-origin-when-cross-origin"),
    (b"permissions-policy", b"camera=(), microphone=(), geolocation=()"),
    (
        b"content-security-policy",
        b"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        b"img-src 'self' data: https://www.google.com https://*.gstatic.com; font-src 'self' data:; connect-src 'self'; "
        b"frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    ),
]
_HSTS_HEADER = (
    b"strict-transport-security",
    b"max-age=31536000; includeSubDomains; preload",
)


class SecurityHeadersMiddleware:
    """纯 ASGI 中间件：注入安全响应头，不缓冲响应体（SSE 友好）"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.extend(_SECURITY_HEADERS)
                if not DEBUG:
                    headers.append(_HSTS_HEADER)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


app.add_middleware(SecurityHeadersMiddleware)


# ── 全局速率限制中间件：强制执行 limiter 的 default_limits（200/min）──
# slowapi 的 default_limits 只有在 in_middleware=True 的请求中间件里才会被
# 应用（slowapi_startup 仅注册 state/exceptions 不挂中间件）。这里用纯 http
# 中间件调用 _check_request_limit(in_middleware=True)，使未单独 @limiter.limit
# 的路由也受全局默认限速约束，避免任意公开路由被无限制打满。
# 说明：限速存储为进程内内存（未配置 Redis），多 worker 下按 worker 各自计数。
import ipaddress


class GlobalRateLimitMiddleware:
    """纯 http 中间件：按 limiter 默认限速对每个请求 pre-check。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request = Request(scope)
        # 测试/直连 dev 下 get_client_ip 可能是非 IP 字符串（如 "testclient"），
        # 此时不做限流计数，避免测试套件把全部请求折叠到同一 key 触发误限。
        # 生产经受信代理时返回真实客户端 IP，才进入全局限速。
        try:
            ipaddress.ip_address(get_client_ip(request))
        except ValueError:
            await self.app(scope, receive, send)
            return
        # in_middleware=True 才会应用 _default_limits；已 @limiter.limit 的路由
        # 会被 auth.limiter 等自己的装饰器再检查一次（两套实例独立计数）。
        try:
            limiter._check_request_limit(request, None, in_middleware=True)
        except RateLimitExceeded as exc:
            response = _rate_limit_exceeded_handler(request, exc)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


app.add_middleware(GlobalRateLimitMiddleware)


# ── CSRF 中间件：在中间件层面拦截缺少自定义头的跨域请求 ──
_CSRF_EXEMPT_PATHS = {
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/login-form",
    "/api/health",
}


class CSRFMiddleware:
    """纯 ASGI CSRF 中间件：不缓冲响应体（SSE 友好）"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if scope["method"] in ("POST", "PUT", "DELETE"):
            path = scope.get("path", "")
            if (
                path not in _CSRF_EXEMPT_PATHS
                and not path.startswith("/mcp/")
                and path != "/mcp"
            ):
                headers = dict(scope.get("headers", []))
                has_custom_header = b"x-requested-with" in headers
                ct = headers.get(b"content-type", b"").decode("utf-8", errors="ignore")
                has_json_content_type = "application/json" in ct
                if not has_custom_header and not has_json_content_type:
                    response = JSONResponse(
                        status_code=403,
                        content={"detail": "缺少必要的请求头，请通过前端发起请求"},
                    )
                    await response(scope, receive, send)
                    return

        await self.app(scope, receive, send)


app.add_middleware(CSRFMiddleware)

app.middleware("http")(log_requests)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """捕获所有未处理的异常，返回统一 JSON 格式"""
    logger.error(
        "未捕获异常: %s %s → %s\n%s",
        request.method,
        request.url.path,
        str(exc),
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=500,
        content={"status": "error", "detail": "服务器内部错误，请稍后重试"},
    )


app.include_router(health.router)
app.include_router(auth.router)
app.include_router(submit.router)
app.include_router(data.router)
app.include_router(questions.router)
app.include_router(questions_pkg_router)
app.include_router(answers.router)
app.include_router(practice.router)
app.include_router(admin_quality.router)
app.include_router(admin_assistant.router)
app.include_router(admin_review.router)
app.include_router(admin_source_health.router)
app.include_router(bank_build.router)
app.include_router(interview.router)
app.include_router(interview_distribution.router)
app.include_router(analytics.router)
app.include_router(insights.router)
app.include_router(profile.router)
app.include_router(profile_pkg_router)
app.include_router(chat.router)
app.include_router(coding.router)
app.include_router(error_report.router)
app.mount("/mcp", mcp_app)


@app.on_event("startup")
async def startup_cleanup():
    """启动时清理过期的 refresh token"""
    # Mounted ASGI applications do not receive lifespan events from FastAPI.
    # FastMCP's Streamable HTTP transport requires its session manager to run
    # for the full lifetime of this worker, even in stateless HTTP mode.
    app.state.mcp_session_manager = mcp.session_manager.run()
    await app.state.mcp_session_manager.__aenter__()

    try:
        cleanup_expired_refresh_tokens()
        logger.info("已清理过期的 refresh token")
    except Exception as e:
        logger.warning(f"清理过期 refresh token 失败: {e}")

    # 初始化 Redis 连接池（ARQ 任务队列）
    try:
        from arq.connections import create_pool, RedisSettings
        from app.core.config import REDIS_QUEUE_URL, redact_redis_url

        app.state.redis = await create_pool(RedisSettings.from_dsn(REDIS_QUEUE_URL))
        logger.info(f"Redis queue 连接池已初始化: {redact_redis_url(REDIS_QUEUE_URL)}")
    except Exception as e:
        logger.warning(f"Redis 连接池初始化失败（ARQ 将不可用）: {e}")
        app.state.redis = None

    # 初始化独立 Redis cache。缓存不可用时接口继续回退 SQLite。
    try:
        from redis.asyncio import from_url
        from app.core.cache import set_cache_client
        from app.core.config import REDIS_CACHE_URL, redact_redis_url

        cache = from_url(REDIS_CACHE_URL, decode_responses=True)
        await cache.ping()
        set_cache_client(cache)
        app.state.redis_cache = cache
        logger.info(f"Redis cache 连接池已初始化: {redact_redis_url(REDIS_CACHE_URL)}")
    except Exception as e:
        logger.warning(f"Redis cache 初始化失败（题库接口将回退 SQLite）: {e}")
        app.state.redis_cache = None


@app.on_event("shutdown")
async def shutdown_cleanup():
    """关闭时清理数据库连接"""
    mcp_session_manager = getattr(app.state, "mcp_session_manager", None)
    if mcp_session_manager is not None:
        await mcp_session_manager.__aexit__(None, None, None)

    from app.db.connection import _local

    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
            logger.info("数据库连接已关闭")
        except Exception as e:
            logger.warning(f"关闭数据库连接失败: {e}")

    # 关闭 Redis 连接池
    redis = getattr(app.state, "redis", None)
    if redis is not None:
        try:
            await redis.close()
            logger.info("Redis 连接池已关闭")
        except Exception as e:
            logger.warning(f"关闭 Redis 连接池失败: {e}")

    from app.core.cache import close_cache_client

    await close_cache_client()
