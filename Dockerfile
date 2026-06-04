# ============================================================
# InterviewBoss Docker 镜像（3 阶段构建，国内镜像加速）
# 优化重点：消除 chown -R 的 overlayfs copy-up（省 ~1.2GB）
# ============================================================

# ── 阶段 1：前端构建 ──
FROM node:20-alpine AS frontend-builder
WORKDIR /app/frontend
RUN npm config set registry https://registry.npmmirror.com
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --production=false
COPY frontend/ ./
RUN npm run build

# ── 阶段 2：Python 依赖安装（构建阶段，不进入最终镜像）──
FROM python:3.10-slim-bookworm AS deps-builder
WORKDIR /app
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl libmagic1 && \
    rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com uv
COPY pyproject.toml uv.lock ./
ENV UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/
ENV UV_HTTP_TIMEOUT=120
ENV UV_LINK_MODE=copy
# --mount=type=cache: 保留 uv 下载缓存，依赖不变时零网络请求
# --no-install-project: 只装第三方依赖，不装项目本身（项目代码变化不触发重装）
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project && \
    # 清理 __pycache__，只保留 .venv
    find /app/.venv -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null; \
    find /app/.venv -name '*.pyc' -delete 2>/dev/null; \
    true

# ── 阶段 3：运行时镜像（最小化）──
FROM python:3.10-slim-bookworm AS runtime
WORKDIR /app

# 系统依赖
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends curl libmagic1 && \
    rm -rf /var/lib/apt/lists/*

# 安装 uv（CMD 需要 uv run）
RUN pip install --no-cache-dir -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com uv

# 非 root 用户（在 COPY 之前创建，这样 --chown 才能生效）
RUN useradd --create-home --shell /bin/false appuser && \
    mkdir -p /app/backend/data && \
    chown -R appuser:appuser /app

# 从 builder 复制 Python 依赖（--chown 避免后续 chown -R 的 overlayfs copy-up）
COPY --from=deps-builder --chown=appuser /app/.venv /app/.venv

# 后端代码
COPY --chown=appuser backend/ ./backend/

# 前端构建产物
COPY --from=frontend-builder --chown=appuser /app/frontend/dist ./static/

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
