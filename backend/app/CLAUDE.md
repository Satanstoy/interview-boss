# App — 后端应用入口

FastAPI 应用初始化、中间件、路由注册。

## 文件职责

| 文件 | 职责 |
|------|------|
| `asgi.py` | FastAPI app 创建、中间件注册、路由注册、生命周期事件 |
| `mcp_server/` | 后端内嵌 MCP 工具服务，承载稳定的搜索、抽题、选题执行边界 |
| `worker.py` | ARQ 后台任务 worker；包括可重试的面试分布统计刷新和 durable chat side-effect 任务 |
| `__init__.py` | 包初始化 |

## asgi.py 中间件顺序

```
注册顺序：可选 CORS → SecurityHeadersMiddleware → CSRFMiddleware → log_requests
```

`SecurityHeadersMiddleware` 和 `CSRFMiddleware` 是纯 ASGI 中间件，避免 `BaseHTTPMiddleware` 缓冲 SSE。`log_requests` 通过 `app.middleware("http")` 注册；不要把会缓冲响应体的中间件放到 SSE 路径外层。

`/mcp` 路径已在 `CSRFMiddleware` 中豁免，避免外部 MCP client 因缺少自定义头被拦截。`mcp_app` 外层包有 fail-closed 的 `MCPAuthMiddleware`：生产环境默认要求用户在设置页生成的账户级 MCP Bearer Token；旧部署可继续配置 `MCP_API_KEY` 并携带正确的 `X-MCP-API-Key` 头或 `mcp_api_key` 查询参数，再使用 Bearer access token。开发/测试只有显式设置 `MCP_ALLOW_ANONYMOUS=true` 才允许匿名请求。MCP principal 决定工具使用的 user_id/bank_mode，不能由工具参数覆盖。

## 修改后必做

1. 新增路由：在 `asgi.py` 添加 `app.include_router()`；新增 MCP 服务：在 `asgi.py` 添加 `app.mount()`
2. 新增中间件：注意顺序（安全头在外层）
3. 更新本文件
