# App — 后端应用入口

FastAPI 应用初始化、中间件、路由注册。

## 文件职责

| 文件 | 职责 |
|------|------|
| `asgi.py` | FastAPI app 创建、中间件注册、路由注册、生命周期事件 |
| `worker.py` | ARQ 后台任务 worker |
| `__init__.py` | 包初始化 |

## asgi.py 中间件顺序

```
注册顺序：可选 CORS → SecurityHeadersMiddleware → CSRFMiddleware → log_requests
```

`SecurityHeadersMiddleware` 和 `CSRFMiddleware` 是纯 ASGI 中间件，避免 `BaseHTTPMiddleware` 缓冲 SSE。`log_requests` 通过 `app.middleware("http")` 注册；不要把会缓冲响应体的中间件放到 SSE 路径外层。

## 修改后必做

1. 新增路由：在 `asgi.py` 添加 `app.include_router()`
2. 新增中间件：注意顺序（安全头在外层）
3. 更新本文件
