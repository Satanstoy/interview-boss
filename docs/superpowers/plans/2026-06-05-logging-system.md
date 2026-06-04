# 日志系统规范化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将前后端 + Nginx 日志统一为结构化格式，通过 Docker 统一管理，防止磁盘爆满。

**Architecture:** 后端用 structlog 替换 logging.basicConfig（兼容现有 290 处调用），Nginx 输出 JSON 到 stdout，Docker 配置 max-size 轮转，前端 JS 错误通过 sendBeacon 上报到后端。

**Tech Stack:** structlog (Python), FastAPI, Vue 3, Nginx, Docker Compose

**Spec:** `docs/superpowers/specs/2026-06-05-logging-system-design.md`

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `pyproject.toml` | 修改 | 添加 structlog 依赖 |
| `backend/app/core/logging_config.py` | 重写 | structlog 双模式配置（dev 彩色 / prod JSON） |
| `backend/app/middleware/request_log.py` | 重写 | 请求日志 + request_id 绑定到 contextvars |
| `backend/app/routers/error_report.py` | 新增 | 接收前端 JS 错误上报 |
| `backend/app/asgi.py` | 修改 | 注册 error_report 路由 |
| `backend/tests/test_logging.py` | 新增 | structlog + 中间件 + 上报端点测试 |
| `frontend/src/utils/logger.js` | 新增 | 前端日志工具（sendBeacon 上报） |
| `frontend/src/main.js` | 修改 | reportError 接入 logger |
| `nginx/nginx.conf` | 修改 | JSON log_format + stdout |
| `docker-compose.yml` | 修改 | logging driver + ENV=production |

---

### Task 1: 添加 structlog 依赖

**Files:**
- Modify: `pyproject.toml:7-30`

- [ ] **Step 1: 添加 structlog 到 dependencies**

在 `pyproject.toml` 的 `dependencies` 列表末尾添加 `"structlog>=24.1.0"`：

```toml
dependencies = [
    "fastapi==0.104.1",
    "openai>=1.30.0",
    "pydantic>=2.7.4",
    "python-dotenv==1.0.0",
    "python-multipart==0.0.6",
    "tenacity>=9.1.4",
    "uvicorn==0.24.0",
    "passlib[bcrypt]>=1.7.4",
    "bcrypt>=4.0,<4.1",
    "python-jose[cryptography]>=3.3.0",
    "slowapi>=0.1.9",
    "python-magic>=0.4.27",
    "anthropic>=0.100.0",
    "arq>=0.28.0",
    "redis>=5.3.1",
    "langgraph>=1.1.0",
    "pypdf>=6.12.0",
    "httpx[socks]<0.28",
    "pyyaml>=6.0.3",
    "socksio>=1.0.0",
    "sentence-transformers>=5.5.1",
    "faiss-cpu>=1.14.2",
    "structlog>=24.1.0",
]
```

- [ ] **Step 2: 重建 Docker 镜像验证依赖安装**

Run: `docker compose build backend`
Expected: 构建成功，structlog 被安装到镜像中

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "build: add structlog dependency for structured logging"
```

---

### Task 2: 重写 logging_config.py

**Files:**
- Rewrite: `backend/app/core/logging_config.py`
- Create: `backend/tests/test_logging.py`

- [ ] **Step 1: 编写 structlog 配置测试**

```python
# backend/tests/test_logging.py
"""structlog 日志系统测试"""
import json
import logging
import os
import structlog
import pytest


@pytest.fixture(autouse=True)
def _restore_logging():
    """每个测试后恢复日志配置，避免测试间干扰"""
    import structlog
    original_config = structlog.get_config()
    root = logging.getLogger()
    original_handlers = root.handlers[:]
    original_level = root.level
    yield
    structlog.configure(**original_config) if original_config else None
    root.handlers = original_handlers
    root.setLevel(original_level)


def test_structlog_json_output(monkeypatch, capsys):
    """生产环境：日志输出为 JSON 格式，包含 event/level/timestamp"""
    monkeypatch.setenv("ENV", "production")

    from app.core.logging_config import setup_logging
    setup_logging()

    logger = logging.getLogger("interview-boss")
    logger.info("test_event", extra={"key": "value"})

    captured = capsys.readouterr()
    lines = [l for l in captured.out.strip().split('\n') if l.strip()]
    assert len(lines) >= 1

    log_entry = json.loads(lines[-1])
    assert log_entry["event"] == "test_event"
    assert log_entry["level"] == "info"
    assert "timestamp" in log_entry


def test_structlog_console_output(monkeypatch, capsys):
    """开发环境：日志输出为彩色人类可读格式"""
    monkeypatch.delenv("ENV", raising=False)

    from app.core.logging_config import setup_logging
    setup_logging()

    logger = logging.getLogger("interview-boss")
    logger.info("dev_test_event")

    captured = capsys.readouterr()
    assert "dev_test_event" in captured.out
    lines = [l for l in captured.out.strip().split('\n') if l.strip()]
    assert not lines[-1].startswith('{')


def test_existing_logger_calls_work():
    """现有 290 处 logging.getLogger('interview-boss') 调用无需修改"""
    logger = logging.getLogger("interview-boss")
    logger.info("compatibility_test")
    logger.warning("compatibility_warning")
    logger.error("compatibility_error")


def test_contextvars_request_id_propagation(monkeypatch, capsys):
    """request_id 通过 contextvars 自动传播到所有日志"""
    monkeypatch.setenv("ENV", "production")

    from app.core.logging_config import setup_logging
    setup_logging()

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="test123")

    logger = logging.getLogger("interview-boss")
    logger.info("context_test")

    captured = capsys.readouterr()
    lines = [l for l in captured.out.strip().split('\n') if l.strip()]
    log_entry = json.loads(lines[-1])
    assert log_entry.get("request_id") == "test123"

    structlog.contextvars.clear_contextvars()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose exec backend pytest backend/tests/test_logging.py -v`
Expected: FAIL（setup_logging 函数还不存在）

- [ ] **Step 3: 重写 logging_config.py**

```python
# backend/app/core/logging_config.py
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

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose exec backend pytest backend/tests/test_logging.py -v`
Expected: 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/logging_config.py backend/tests/test_logging.py
git commit -m "feat(backend): replace logging.basicConfig with structlog dual-mode config"
```

---

### Task 3: 升级请求日志中间件

**Files:**
- Rewrite: `backend/app/middleware/request_log.py`
- Modify: `backend/tests/test_logging.py`

- [ ] **Step 1: 编写中间件测试**

在 `backend/tests/test_logging.py` 末尾追加：

```python
# ── 请求日志中间件测试 ──

import asyncio
import json
import logging
from starlette.requests import Request
from starlette.responses import Response


@pytest.mark.asyncio
async def test_request_log_adds_request_id_to_response():
    """中间件应在响应头中添加 X-Request-ID"""
    from app.middleware.request_log import log_requests

    async def mock_call_next(request):
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/test",
        "query_string": b"",
        "headers": [],
    }
    request = Request(scope)

    response = await log_requests(request, mock_call_next)

    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) == 8


@pytest.mark.asyncio
async def test_request_log_binds_contextvars(monkeypatch, capsys):
    """中间件应将 request_id 绑定到 contextvars"""
    monkeypatch.setenv("ENV", "production")
    from app.core.logging_config import setup_logging
    setup_logging()

    from app.middleware.request_log import log_requests

    async def mock_call_next(request):
        logger = logging.getLogger("interview-boss")
        logger.info("inside_handler")
        return Response("ok", status_code=200)

    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/test",
        "query_string": b"",
        "headers": [],
    }
    request = Request(scope)

    response = await log_requests(request, mock_call_next)

    captured = capsys.readouterr()
    lines = [l for l in captured.out.strip().split('\n') if l.strip()]
    handler_logs = [l for l in lines if "inside_handler" in l]
    assert len(handler_logs) >= 1
    log_entry = json.loads(handler_logs[0])
    assert "request_id" in log_entry
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose exec backend pytest backend/tests/test_logging.py::test_request_log_adds_request_id_to_response backend/tests/test_logging.py::test_request_log_binds_contextvars -v`
Expected: FAIL（新版中间件还没实现）

- [ ] **Step 3: 重写 request_log.py**

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose exec backend pytest backend/tests/test_logging.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/middleware/request_log.py backend/tests/test_logging.py
git commit -m "feat(backend): upgrade request_log middleware with structlog contextvars"
```

---

### Task 4: 创建前端日志工具

**Files:**
- Create: `frontend/src/utils/logger.js`

- [ ] **Step 1: 创建 logger.js**

```javascript
// frontend/src/utils/logger.js
/**
 * 前端日志工具 — 统一错误上报到后端
 *
 * 用法：
 *   import { logger } from '@/utils/logger'
 *   logger.error('LLM 请求失败', { questionId: 42 })
 *   logger.warn('缓存过期')
 */

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

- [ ] **Step 2: 验证前端构建**

Run: `cd frontend && npm run build`
Expected: 构建成功，无报错

- [ ] **Step 3: Commit**

```bash
git add frontend/src/utils/logger.js
git commit -m "feat(frontend): add logger utility with sendBeacon error reporting"
```

---

### Task 5: 接入前端 main.js

**Files:**
- Modify: `frontend/src/main.js:17-27`

- [ ] **Step 1: 替换 reportError 函数**

将 `frontend/src/main.js` 第 17-27 行的 `reportError` 函数替换为：

```javascript
import { logger } from '@/utils/logger'

// 生产环境错误上报（通过 sendBeacon 统一上报到后端）
function reportError(errorInfo) {
  logger.error(errorInfo.message || 'Unknown error', {
    type: errorInfo.type,
    source: errorInfo.source,
    lineno: errorInfo.lineno,
    colno: errorInfo.colno,
    stack: errorInfo.stack,
    componentInfo: errorInfo.componentInfo,
    component: errorInfo.componentName,
  })
}
```

注意：删除原来的 `// 生产环境错误上报` 注释块和 TODO 注释。`import` 语句放在文件顶部（其他 import 之后）。

- [ ] **Step 2: 验证前端构建**

Run: `cd frontend && npm run build`
Expected: 构建成功

- [ ] **Step 3: Commit**

```bash
git add frontend/src/main.js
git commit -m "feat(frontend): integrate logger into main.js error reporting"
```

---

### Task 6: 创建后端错误上报端点

**Files:**
- Create: `backend/app/routers/error_report.py`
- Modify: `backend/tests/test_logging.py`

- [ ] **Step 1: 编写上报端点测试**

在 `backend/tests/test_logging.py` 末尾追加：

```python
# ── 前端错误上报端点测试 ──

from fastapi.testclient import TestClient


def test_error_report_endpoint_accepts_batch(client):
    """POST /api/error-report 应接受批量错误并返回 ok"""
    payload = {
        "errors": [
            {
                "level": "error",
                "message": "Cannot read properties of null",
                "url": "http://localhost/practice",
                "source": "PracticePanel.vue",
                "lineno": 391,
                "timestamp": "2026-06-05T14:30:00Z",
            },
            {
                "level": "error",
                "message": "Network error",
                "url": "http://localhost/chat",
                "timestamp": "2026-06-05T14:30:01Z",
            },
        ]
    }

    response = client.post("/api/error-report", json=payload)
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_error_report_endpoint_handles_empty_body(client):
    """空 errors 数组也应返回 ok"""
    response = client.post("/api/error-report", json={"errors": []})
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_error_report_endpoint_handles_malformed_json(client):
    """畸形 JSON 不应导致 500"""
    response = client.post(
        "/api/error-report",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    # 应返回 ok: False 或 422，不应该是 500
    assert response.status_code in (200, 422)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `docker compose exec backend pytest backend/tests/test_logging.py::test_error_report_endpoint_accepts_batch -v`
Expected: FAIL（路由还不存在）

- [ ] **Step 3: 创建 error_report.py**

```python
# backend/app/routers/error_report.py
"""前端 JS 错误上报端点"""
from fastapi import APIRouter, Request
import structlog

router = APIRouter()
logger = structlog.stdlib.get_logger("frontend")


@router.post("/error-report")
async def error_report(request: Request):
    """接收前端 JS 错误上报（sendBeacon → JSON body）"""
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

- [ ] **Step 4: 运行测试确认通过**

Run: `docker compose exec backend pytest backend/tests/test_logging.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/routers/error_report.py backend/tests/test_logging.py
git commit -m "feat(backend): add /api/error-report endpoint for frontend JS errors"
```

---

### Task 7: 注册路由到 asgi.py

**Files:**
- Modify: `backend/app/asgi.py:13-14`（import）和 `backend/app/asgi.py:137-152`（include_router）

- [ ] **Step 1: 添加 import**

在 `backend/app/asgi.py` 第 13 行的 import 列表中，追加 error_report：

```python
from app.routers import health, submit, data, questions, answers, practice, admin_review, bank_build, interview, analytics, profile, auth, chat, coding, error_report
```

- [ ] **Step 2: 注册路由**

在 `backend/app/asgi.py` 第 152 行（`app.include_router(coding.router)` 之后）添加：

```python
app.include_router(error_report.router)
```

- [ ] **Step 3: 运行全量测试确认无回归**

Run: `docker compose exec backend pytest backend/tests/test_logging.py -v`
Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/asgi.py
git commit -m "feat(backend): register error_report router in asgi.py"
```

---

### Task 8: Nginx JSON 日志格式

**Files:**
- Modify: `nginx/nginx.conf:7-23`（http 块）

- [ ] **Step 1: 添加 JSON 日志格式和输出配置**

在 `nginx/nginx.conf` 的 `http` 块中，在 `server_tokens off;` 之后、`gzip on;` 之前添加：

```nginx
    # 结构化 JSON 日志（输出到 stdout，由 Docker 统一管理）
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
```

完整 http 块应为：

```nginx
http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    sendfile    on;
    tcp_nopush  on;
    keepalive_timeout 65;

    # 隐藏 Nginx 版本号（安全加固）
    server_tokens off;

    # 结构化 JSON 日志（输出到 stdout，由 Docker 统一管理）
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

    # Gzip 压缩
    gzip on;
    gzip_types text/css application/javascript application/json image/svg+xml font/woff2;
    gzip_min_length 1000;
    gzip_vary on;

    # 限流（2c4g 服务器适度限制）
    limit_req_zone $binary_remote_addr zone=api:10m rate=30r/s;

    server {
        # ... server 块不变 ...
    }
}
```

- [ ] **Step 2: 验证 Nginx 配置语法**

Run: `docker compose exec nginx nginx -t`
Expected: `syntax is ok` / `test is successful`

- [ ] **Step 3: 重启 Nginx 验证**

Run: `docker compose restart nginx`
然后发送一个请求，验证日志输出：
Run: `docker compose logs --tail=5 nginx`
Expected: JSON 格式的访问日志

- [ ] **Step 4: Commit**

```bash
git add nginx/nginx.conf
git commit -m "feat(nginx): add JSON structured log format with stdout output"
```

---

### Task 9: Docker Compose 日志轮转 + 环境变量

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: 更新 docker-compose.yml**

完整修改后的 `docker-compose.yml`：

```yaml
# InterviewBoss Docker Compose（2c4g 优化版）
# 用法：
#   首次部署: docker compose up -d --build
#   更新部署: docker compose up -d --build backend worker nginx
#   查看日志: docker compose logs -f
#   停止服务: docker compose down

services:
  # ── Redis ──
  redis:
    image: redis:7.4-alpine
    restart: always
    command: redis-server --maxmemory 96mb --maxmemory-policy allkeys-lru --appendonly yes
    volumes:
      - redis-data:/data
    mem_limit: 128m
    cpus: 0.25
    networks:
      - app-network
    security_opt:
      - no-new-privileges:true
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 3s
      retries: 3
    logging: &default-logging
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  # ── FastAPI 后端 ──
  backend:
    build:
      context: .
      dockerfile: Dockerfile
    restart: always
    env_file: backend/.env
    environment:
      - REDIS_URL=redis://redis:6379/0
      - HF_HUB_OFFLINE=1
      - ENV=production
    volumes:
      - ./backend/data:/app/backend/data
      - /home/ubuntu/.cache/huggingface:/root/.cache/huggingface:ro
    mem_limit: 512m
    cpus: 0.75
    networks:
      - app-network
    security_opt:
      - no-new-privileges:true
    depends_on:
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/health"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 10s
    logging: *default-logging

  # ── ARQ Worker ──
  worker:
    build:
      context: .
      dockerfile: Dockerfile
    restart: always
    env_file: backend/.env
    environment:
      - REDIS_URL=redis://redis:6379/0
      - HF_HUB_OFFLINE=1
      - ENV=production
    volumes:
      - ./backend/data:/app/backend/data
      - /home/ubuntu/.cache/huggingface:/root/.cache/huggingface:ro
    command: ["uv", "run", "arq", "app.worker.WorkerSettings"]
    mem_limit: 256m
    cpus: 0.5
    networks:
      - app-network
    security_opt:
      - no-new-privileges:true
    depends_on:
      redis:
        condition: service_healthy
    logging: *default-logging

  # ── Nginx（前端 + 反向代理）──
  nginx:
    image: nginx:1.27-alpine
    restart: always
    ports:
      - "80:80"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./frontend/dist:/usr/share/nginx/html:ro
    mem_limit: 64m
    cpus: 0.25
    networks:
      - app-network
    security_opt:
      - no-new-privileges:true
    depends_on:
      backend:
        condition: service_healthy
    logging: *default-logging

networks:
  app-network:
    driver: bridge

volumes:
  redis-data:
```

- [ ] **Step 2: 验证 YAML 语法**

Run: `docker compose config`
Expected: 输出完整的解析后配置，无报错

- [ ] **Step 3: Commit**

```bash
git add docker-compose.yml
git commit -m "feat(deploy): add Docker log rotation and ENV=production for structlog"
```

---

### Task 10: 端到端验证 + 文档更新

**Files:**
- Modify: `backend/app/core/CLAUDE.md`（修正 loguru 描述）
- Modify: `CLAUDE.md`（更新日志相关信息）

- [ ] **Step 1: 全量部署验证**

```bash
./deploy/docker-deploy.sh update
```

等待所有容器健康后：

```bash
# 验证后端 structlog 输出
docker compose logs --tail=5 backend
# Expected: JSON 格式日志（含 event, level, timestamp 字段）

# 验证 Nginx JSON 日志
curl http://localhost/api/health
docker compose logs --tail=5 nginx
# Expected: JSON 格式访问日志

# 验证前端错误上报端点
curl -X POST http://localhost/api/error-report \
  -H "Content-Type: application/json" \
  -d '{"errors":[{"message":"test","url":"http://localhost"}]}'
# Expected: {"ok":true}

# 验证后端日志中出现了前端上报
docker compose logs --tail=5 backend | grep frontend_error
# Expected: JSON 日志含 frontend_error event
```

- [ ] **Step 2: 更新 backend/app/core/CLAUDE.md**

将 `logging_config.py` 的描述从"loguru"修正为"structlog"：

搜索 `logging_config.py（loguru）` 或类似描述，替换为 `logging_config.py（structlog 双模式）`。

- [ ] **Step 3: 更新根 CLAUDE.md**

在 Gotchas 部分追加：

```markdown
- 日志系统使用 structlog（生产 JSON / 开发彩色），前端错误通过 sendBeacon 上报到 `/api/error-report`
- Docker 日志轮转：每服务 max-size 10m × max-file 3，用 `docker compose logs backend | jq .` 查看结构化日志
```

- [ ] **Step 4: 更新 spec 状态**

将 `docs/superpowers/specs/2026-06-05-logging-system-design.md` 第 3 行的 `状态: 待审阅` 改为 `状态: 已实现`。

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/CLAUDE.md CLAUDE.md docs/superpowers/specs/2026-06-05-logging-system-design.md
git commit -m "docs: update logging system documentation after implementation"
```
