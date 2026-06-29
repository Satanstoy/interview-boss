# Middleware — 请求中间件

FastAPI ASGI 中间件层，负责请求/响应的横切关注点。

## 文件清单

| 文件 | 职责 |
|------|------|
| `request_log.py` | 请求日志：记录方法、路径、状态码、耗时（ms），4xx/5xx 用 WARNING 级别 |

## 中间件注册顺序

在 `asgi.py` 中注册：可选 CORS → `SecurityHeadersMiddleware` → `CSRFMiddleware` → `log_requests`。安全头和 CSRF 是纯 ASGI 中间件，避免缓冲 SSE；新增中间件时要确认不会破坏 `text/event-stream`。

## 核心规则

- 中间件必须是 `async def`，签名 `(request: Request, call_next)`
- 日志使用 `logging.getLogger("interview-boss")`，禁止 print
- 4xx/5xx 响应用 `logging.WARNING`，其余用 `logging.INFO`
- 不要在中间件中做业务逻辑

## 修改后必做

1. 新增中间件后在 `asgi.py` 中按正确顺序注册
2. 更新本文件
