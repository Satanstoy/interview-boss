# ============================================================
# InterviewBoss Docker 镜像（多阶段构建，国内镜像加速）
# ============================================================

# ── 阶段 1：前端构建 ──
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
RUN npm config set registry https://registry.npmmirror.com
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --production=false
COPY frontend/ ./
RUN npm run build

# ── 阶段 2：后端运行时 ──
FROM python:3.10-slim-bookworm AS backend
WORKDIR /app

# 系统依赖（阿里云 apt 镜像）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl libmagic1 && \
    apt-get upgrade -y --no-install-recommends && \
    rm -rf /var/lib/apt/lists/*

# 安装 uv（通过 PyPI 镜像安装，避免 ghcr.io 拉取失败）
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com uv

# Python 依赖（阿里云 PyPI 镜像 + CPU-only PyTorch）— 利用 Docker cache
COPY pyproject.toml uv.lock ./
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV UV_HTTP_TIMEOUT=120
RUN uv sync --frozen --no-dev

# 后端代码（频繁变更，放最后以最大化 cache 命中）
COPY backend/ ./backend/

# 前端构建产物
COPY --from=frontend-builder /app/frontend/dist ./static/

# 数据目录 + 权限
RUN mkdir -p /app/backend/data

# 非 root 用户（CIS Benchmark 安全要求）
RUN useradd --create-home --shell /bin/false appuser && \
    chown -R appuser:appuser /app

# Entrypoint（以 root 修复 bind mount 权限，然后切换到 appuser）
COPY deploy/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# 环境变量
ENV PYTHONPATH=/app/backend
ENV REDIS_URL=redis://redis:6379/0

EXPOSE 8000

ENTRYPOINT ["/entrypoint.sh"]

# 双 worker 利用 2c4g 双核（SQLite WAL 模式支持并发读）
CMD ["uv", "run", "uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
