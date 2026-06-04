# 日志系统规范化设计

**日期**: 2026-06-05
**状态**: 已实现
**范围**: 后端 structlog 升级 + 前端错误上报 + Nginx JSON 日志 + Docker 日志轮转

## 背景与目标

### 现状问题

| 层 | 问题 |
|---|------|
| 后端 | `logging.basicConfig` 8 行极简配置，纯文本格式无结构化，无 request_id 上下文 |
| 前端 | 23 处 `console.*` 直接输出，`reportError()` 的 `sendBeacon` 是 TODO 未实现 |
| Nginx | 无显式日志配置，写入容器 `/var/log/nginx/`，容器重建即丢失 |
| Docker | 无 logging driver 配置，无 `max-size`/`max-file`，磁盘爆满风险 |

### 目标

**规范化 + 防风险**：统一日志出口、结构化格式、防磁盘爆满、前端错误可远程查看。

### 非目标

- 不接入外部日志服务（Sentry/Loki/ELK）
- 不做链路追踪（OpenTelemetry traces）
- 不全量迁移现有 290 处 logging 调用
- 不增加日志文件持久化（依赖 Docker json-file 即可）

## 架构概览

```
[浏览器]
  ├── API 请求 → Nginx(JSON stdout) → Backend(structlog JSON stdout)
  ├── JS 异常  → sendBeacon → Backend /api/error-report → structlog stdout
  └── SSE 流   → 同 API 请求

[Docker json-file] ← 所有 stdout 统一采集
  ├── backend  最多 30MB (10m × 3)
  ├── worker   最多 30MB
  ├── nginx    最多 30MB
  └── redis    最多 30MB
```

### 核心原则

1. 所有层统一输出到 stdout/stderr → Docker 统一管理
2. 后端双模式：生产环境 JSON，开发环境彩色可读
3. Nginx 始终 JSON（开发环境直接看 Nginx 日志的机会少）
4. 前端 `sendBeacon` 上报，不阻塞页面
5. 现有 290 处 `logging.getLogger("interview-boss")` 调用零改动

## 详细设计

### 1. 后端 structlog 配置

**文件**: `backend/app/core/logging_config.py`（重写）

```python
import structlog
import logging
import sys
import os

def setup_logging():
    """配置 structlog 双模式：开发彩色可读 / 生产 JSON"""
    is_production = os.getenv("ENV") == "production"

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]

    renderer = (
        structlog.processors.JSONRenderer()
        if is_production
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        structlog.stdlib.ProcessorFormatter(
            processor=renderer,
            foreign_pre_chain=shared_processors,
        )
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)

setup_logging()
logger = logging.getLogger("interview-boss")
```

**设计决策**:
- `cache_logger_on_first_use=True`：所有 290 处 `logging.getLogger("interview-boss")` 调用零改动
- `merge_contextvars`：request_id 通过 contextvars 自动传播，不需手动传递
- 输出到 stdout：与 Docker json-file 驱动配合
- 环境判断 `os.getenv("ENV") == "production"`：docker-compose.yml 已设置

**新增依赖**: `structlog`（`cd backend && uv add structlog`）

### 2. 请求日志中间件升级

**文件**: `backend/app/middleware/request_log.py`（修改）

```python
import structlog
import time
import uuid

logger = structlog.stdlib.get_logger("middleware")

async def log_requests(request, call_next):
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
```

**生产环境输出**:
```json
{"event":"request_completed","level":"info","timestamp":"2026-06-05T14:30:00.123Z","request_id":"a3f2b1c9","method":"POST","path":"/api/master-bank/compact","status":200,"duration_ms":156.3,"logger":"middleware"}
```

### 3. 前端日志工具

**文件**: `frontend/src/utils/logger.js`（新增）

```javascript
class Logger {
  constructor() {
    this._queue = []
    this._timer = null
  }

  error(message, context = {}) {
    const entry = this._build('error', message, context)
    console.error(`[${message}]`, context)
    this._enqueue(entry)
  }

  warn(message, context = {}) {
    console.warn(`[${message}]`, context)
  }

  info(message, context = {}) {
    console.info(`[${message}]`, context)
  }

  _build(level, message, context) {
    return {
      level,
      message,
      timestamp: new Date().toISOString(),
      url: window.location.href,
      userAgent: navigator.userAgent,
      ...context,
    }
  }

  _enqueue(entry) {
    this._queue.push(entry)
    if (this._queue.length >= 5) this._flush()
    if (!this._timer) this._timer = setTimeout(() => this._flush(), 10000)
  }

  _flush() {
    clearTimeout(this._timer)
    this._timer = null
    if (!this._queue.length) return

    const batch = this._queue.splice(0)
    try {
      navigator.sendBeacon?.(
        '/api/error-report',
        new Blob([JSON.stringify({ errors: batch })], { type: 'application/json' })
      )
    } catch {
      // sendBeacon 失败静默忽略
    }
  }
}

export const logger = new Logger()
```

**设计决策**:
- 只有 `error` 上报，`warn`/`info` 只本地输出，避免噪声
- 批量上报：累积 5 条或 10 秒，减少 HTTP 请求
- `sendBeacon`：页面关闭前也能发送，不阻塞用户操作
- 静默失败：上报失败不影响页面功能

### 4. 前端 main.js 接入

**文件**: `frontend/src/main.js`（修改）

替换现有 `reportError()` 函数：

```javascript
import { logger } from '@/utils/logger'

function reportError(errorInfo) {
  logger.error(errorInfo.message || 'Unknown error', {
    source: errorInfo.source,
    lineno: errorInfo.lineno,
    stack: errorInfo.stack,
    component: errorInfo.componentName,
  })
}
```

三层全局捕获机制保持不变（`window.onerror`、`unhandledrejection`、`app.config.errorHandler`），它们收集的信息通过 `reportError` → `logger.error` → `sendBeacon` 上报。

### 5. 后端错误上报端点

**文件**: `backend/app/routers/error_report.py`（新增）

```python
from fastapi import APIRouter, Request
import structlog

router = APIRouter()
logger = structlog.stdlib.get_logger("frontend")

@router.post("/error-report")
async def error_report(request: Request):
    """接收前端 JS 错误上报"""
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
```

**路由注册**: 在 `backend/app/asgi.py` 中注册，无需认证（前端匿名上报）。

**CSRF 兼容性**: `sendBeacon` 发送 `Blob` 时 Content-Type 为 `application/json`，现有 CSRF 中间件（`asgi.py:113-114`）检查 `application/json` in content-type 即放行，无需额外豁免。

### 6. Nginx JSON 日志

**文件**: `nginx/nginx.conf`（修改 http 块）

```nginx
http {
    log_format json_log escape=json
        '{'
            '"time":"$time_iso8601",'
            '"remote_addr":"$remote_addr",'
            '"method":"$request_method",'
            '"uri":"$request_uri",'
            '"status":$status,'
            '"body_bytes":$body_bytes_sent,'
            '"request_time":$request_time,'
            '"upstream_time":"$upstream_response_time",'
            '"user_agent":"$http_user_agent"'
        '}';

    access_log /dev/stdout json_log;
    error_log  /dev/stderr warn;

    # ... 其余配置不变
}
```

**关键字段**:
- `$request_time`：Nginx 侧总耗时（含等待上游）
- `$upstream_response_time`：后端实际处理耗时
- 两者差异 = 网络延迟 + 队列等待

### 7. Docker Compose 日志轮转 + 环境变量

**文件**: `docker-compose.yml`（修改）

```yaml
services:
  backend:
    environment:
      - ENV=production  # 新增：structlog 双模式判断依据
    logging: &default-logging
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
  worker:
    environment:
      - ENV=production  # 新增：worker 共享同一镜像，同样受益
    logging: *default-logging
  nginx:
    logging: *default-logging
  redis:
    logging: *default-logging
```

**效果**: 每服务最多 30MB，四服务总计最多 120MB。使用 YAML anchor 避免重复配置。

**注意**: backend 和 worker 共享同一 Docker 镜像，`logging_config.py` 在模块导入时初始化，两个进程都会受益于 structlog 配置。

## 文件变更清单

| 文件 | 操作 | 改动量 |
|------|------|--------|
| `backend/pyproject.toml` | 修改 | +1 依赖 (structlog) |
| `backend/app/core/logging_config.py` | 重写 | ~40 行 |
| `backend/app/middleware/request_log.py` | 修改 | ~25 行 |
| `backend/app/routers/error_report.py` | 新增 | ~25 行 |
| `backend/app/asgi.py` | 修改 | +3 行（注册路由） |
| `frontend/src/utils/logger.js` | 新增 | ~55 行 |
| `frontend/src/main.js` | 修改 | ~8 行 |
| `nginx/nginx.conf` | 修改 | +15 行 |
| `docker-compose.yml` | 修改 | +16 行（ENV=production + logging driver） |

## 日常使用

```bash
# 实时查看后端日志
docker compose logs -f backend

# 只看错误
docker compose logs backend | jq 'select(.level=="error")'

# 按 request_id 追踪请求链路
docker compose logs backend | jq 'select(.request_id=="a3f2b1c9")'

# 看前端报错
docker compose logs backend | jq 'select(.logger=="frontend")'

# 看 Nginx 慢请求（> 2 秒）
docker compose logs nginx | jq 'select(.request_time > 2)'

# 部署脚本查看（保持不变）
./deploy/docker-deploy.sh logs backend
```

## 测试策略

- **后端**: 验证 structlog 输出格式（开发环境可读、生产环境 JSON）
- **后端**: 验证 request_id 在日志上下文中自动传播
- **后端**: 验证 `/api/error-report` 端点接收和记录前端错误
- **前端**: 验证 `logger.error` 触发 `sendBeacon` 调用
- **Nginx**: 验证 `docker compose logs nginx` 输出 JSON 格式
- **Docker**: 验证日志文件不超过 30MB（长期运行后检查）
