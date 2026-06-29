# syntax=docker/dockerfile:1.7
# ============================================================
# InterviewBoss Docker 镜像（多 target 构建，内网部署优化）
# app-runtime: FastAPI + ARQ worker 共用运行时镜像
# nginx-runtime: Nginx + 前端静态产物独立镜像
# ============================================================

ARG BUILDKIT_INLINE_CACHE=1

# ── 阶段 1：前端构建 ──
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
RUN npm config set registry https://registry.npmmirror.com
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm \
    npm ci --production=false
COPY frontend/ ./
RUN npm run build

# ── 阶段 2：Python 基础层（系统依赖 + uv）──
FROM python:3.10-slim-bookworm AS python-base
WORKDIR /app
ENV PYTHONUNBUFFERED=1
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt/lists,sharing=locked \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list; \
    apt-get update && \
    apt-get install -y --no-install-recommends curl libmagic1
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com uv

# ── 阶段 3：Python 依赖安装（构建阶段，不进入最终镜像）──
FROM python-base AS deps-builder
COPY pyproject.toml uv.lock ./
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV UV_HTTP_TIMEOUT=120
ENV UV_LINK_MODE=copy
# --mount=type=cache: 保留 uv 下载缓存，依赖不变时零网络请求
# --no-install-project: 只装第三方依赖，不装项目本身（项目代码变化不触发重装）
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project && \
    find /app/.venv -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; \
    find /app/.venv -name '*.pyc' -delete 2>/dev/null; \
    true

# ── 阶段 3b：Python 依赖安装（含 dev 依赖，用于测试）──
FROM python-base AS deps-builder-dev
COPY pyproject.toml uv.lock ./
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV UV_HTTP_TIMEOUT=120
ENV UV_LINK_MODE=copy
# --mount=type=cache: 保留 uv 下载缓存，依赖不变时零网络请求
# --no-install-project: 只装第三方依赖，不装项目本身（项目代码变化不触发重装）
# 不加 --no-dev：安装 dev 依赖（pytest, pytest-asyncio, httpx 等）
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project && \
    find /app/.venv -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; \
    find /app/.venv -name '*.pyc' -delete 2>/dev/null; \
    true

# ── 阶段 4：App 运行时镜像（backend + worker 共用）──
FROM python-base AS app-runtime
WORKDIR /app

# 非 root 用户（在 COPY 之前创建，这样 --chown 才能生效）
RUN useradd --create-home --shell /bin/false appuser && \
    mkdir -p /app/backend/data && \
    chown -R appuser:appuser /app

# 从 builder 复制 Python 依赖（--chown 避免后续 chown -R 的 overlayfs copy-up）
COPY --from=deps-builder --chown=appuser /app/.venv /app/.venv

# 后端代码
COPY --chown=appuser backend/ ./backend/

# Entrypoint（以 root 修复 bind mount 权限，然后切换到 appuser）
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 环境变量
ENV PYTHONPATH=/app/backend
ENV REDIS_URL=redis://redis:6379/0
ENV PATH="/app/.venv/bin:$PATH"

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]

# 双 worker 利用 2c4g 双核（SQLite WAL 模式支持并发读）
CMD ["uv", "run", "uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]

# ── 阶段 4b：Test 运行时镜像（含 dev 依赖，用于 pytest）──
FROM python-base AS test-runtime
WORKDIR /app

RUN useradd --create-home --shell /bin/false appuser && \
    mkdir -p /app/backend/data && \
    chown -R appuser:appuser /app

COPY --from=deps-builder-dev --chown=appuser /app/.venv /app/.venv

COPY --chown=appuser backend/ ./backend/
COPY --chown=appuser backend/tests/ ./backend/tests/
COPY --chown=appuser Dockerfile docker-compose.yml .dockerignore ./
COPY --chown=appuser nginx/ ./nginx/
COPY --chown=appuser deploy/ ./deploy/

COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENV PYTHONPATH=/app/backend
ENV REDIS_URL=redis://redis:6379/0
ENV PATH="/app/.venv/bin:$PATH"

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uv", "run", "pytest", "backend/tests/", "-v"]

# ── 阶段 5：Nginx 运行时镜像（静态产物内置，部署不依赖宿主机 dist）──
FROM nginx:1.27-alpine AS nginx-runtime
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY --from=frontend-builder /app/frontend/dist /usr/share/nginx/html
RUN chmod -R a+rX /usr/share/nginx/html
EXPOSE 80
