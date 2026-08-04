# Deploy — 部署脚本

> 位置：`deploy/` | 上游：根目录 `docker-compose.yml` | 下游：Docker 容器
> 职责：Docker 部署脚本和容器配置。

## 文件

| 文件 | 用途 |
|------|------|
| `docker-deploy.sh` | **生产部署脚本**（build / update / frontend / worker-up / worker-down / worker-restart / status / logs / test / backup / cleanup / diagnose / migrate） |
| `entrypoint.sh` | Docker 容器入口点 |
| `nginx-hardened.conf` | 旧版/参考 Nginx 安全加固配置；当前 Docker 镜像实际复制 `nginx/nginx.conf` |

## 规则

- 部署命令：`./deploy/docker-deploy.sh update`
- 后端测试：`./deploy/docker-deploy.sh test -q`（构建并使用 `test-runtime`，不是生产 `backend` 容器）

- Worker 默认不随核心服务启动；需要后台任务时执行 `./deploy/docker-deploy.sh worker-up`，任务完成后可执行 `worker-down` 释放资源
- Docker 构建使用 BuildKit、inline cache 和 npm/uv cache mounts；部署脚本会自动执行磁盘保护和 BuildKit cache 收缩，不要绕过脚本长期直接运行 `docker compose build`
- 镜像源策略：普通 `build/update/test/worker-up` 默认复用版本化缓存/稳定默认源，只做短健康检查；健康检查失败才刷新 npm/PyPI/apt 源，避免每次部署改 build args 造成依赖层缓存失效，也避免旧脚本缓存的坏源污染后续 update。镜像源整体失效或首次配置机器时执行 `./deploy/docker-deploy.sh mirrors`，该命令会清缓存、完整测速并更新 Docker Hub registry mirror。
- 部署预检：普通构建会先运行 `preflight_update_contract`，确认生产依赖仍是 `uv export + pip install -i $PYPI_MIRROR`，compose build 仍保留 `network: host`。不要把生产依赖阶段改回 `uv sync --frozen --no-dev --no-install-project`，否则 `uv.lock` 里的 `files.pythonhosted.org` 直链会绕过 PyPI 镜像并造成 update 卡住。
- BuildKit DNS 策略：compose build 必须使用 `network: host`，避免 Docker 从 systemd-resolved stub resolv.conf fallback 到不可控外部 DNS。`mirrors` 命令会持久化 Docker daemon DNS，默认 `DEPLOY_DOCKER_DNS=223.5.5.5,119.29.29.29`。
- Nginx 镜像内置前端 dist，生产不再挂载宿主机 `frontend/dist`
- 当前生产 Nginx 配置在 `nginx/nginx.conf`：静态文件根目录 `/usr/share/nginx/html`，`/api/` 和 `/mcp` 反代到 `backend:8000`，SSE/MCP 路径关闭 proxy buffering/cache/gzip
- Nginx 静态资源权限必须可被 worker 读取：Dockerfile 的 nginx-runtime 阶段在复制 dist 后执行 `chmod -R a+rX /usr/share/nginx/html`；`frontend` 快速部署也必须在 `docker cp` 后执行同样 chmod，避免宿主机 `0600` 图片进入容器后变成 403
- `./deploy/docker-deploy.sh frontend` 用于 Docker 已运行时快速发布前端；脚本在 `docker cp frontend/dist/.` 后必须修正 `/usr/share/nginx/html` 权限为 `a+rX`，避免 Nginx 因宿主构建产物权限导致 403
- 磁盘保护阈值：构建前根分区至少 `DEPLOY_MIN_FREE_MB=2048` MB；构建后低于 `DEPLOY_TARGET_FREE_MB=5120` MB 时自动执行 `docker builder prune`，默认 `BUILDKIT_RESERVED_SPACE=2GB`
- `cleanup_after_build` 绝不在构建成功后执行 `docker compose down --rmi local`；低于目标时只 prune build cache 并提示手动 cleanup
- `prune_unused_docker` 为安全清理：BuildKit cache、dangling images、项目 stopped/orphan 资源；宿主机 `node_modules`/`.venv` 只报告，除非 `DEPLOY_PRUNE_HOST_ARTIFACTS=1` 或 `cleanup --aggressive`
- `diagnose`：输出根分区、docker system df、frontend/node_modules、.venv、frontend/dist 大小等诊断信息
- `cleanup --dry-run`：等价于 diagnose，只输出不清理
- 可调开关：`DEPLOY_MIRROR_HEALTHCHECK_ON_BUILD=1`、`DEPLOY_MIRROR_HEALTHCHECK_TIMEOUT=2`、`DEPLOY_SELECT_MIRRORS_ON_BUILD=0`、`MIRROR_CACHE_VERSION=v2`。不要把 `DEPLOY_SELECT_MIRRORS_ON_BUILD=1` 作为日常默认值，否则每次 update 都可能测速、改 daemon 或改变 build args。
