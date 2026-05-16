# ============================================================
# InterviewBoss Docker 镜像（多阶段构建）
# ============================================================

# ── 阶段 1：前端构建 ──
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --production=false
COPY frontend/ ./
RUN npm run build

# ── 阶段 2：后端运行时 ──
FROM python:3.10-slim AS backend
WORKDIR /app

# 系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    rm -rf /var/lib/apt/lists/*

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Python 依赖（利用缓存层）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# 后端代码
COPY backend/ ./backend/

# 前端构建产物
COPY --from=frontend-builder /app/frontend/dist ./static/

# 数据目录
RUN mkdir -p /app/backend/data

# 环境变量
ENV PYTHONPATH=/app/backend
ENV REDIS_URL=redis://redis:6379/0

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.asgi:app", "--host", "0.0.0.0", "--port", "8000"]
