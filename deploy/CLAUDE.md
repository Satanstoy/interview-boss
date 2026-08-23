# Deploy — 部署脚本

> 位置：`deploy/` | 上游：根目录 `docker-compose.yml` | 下游：Docker 容器
> 职责：Docker 部署脚本和容器配置。

## 文件

| 文件 | 用途 |
|------|------|
| `docker-deploy.sh` | **生产部署脚本**（build / update / frontend / worker-up / worker-down / worker-restart / status / logs / test / backup / restore / cleanup / diagnose / migrate） |
| `storage-retention.sh` | 统一数据库/迁移快照保留策略（默认 7 天，至少保留最近 3 份） |
| `systemd/interview-boss-storage-maintenance.*` | 每日执行备份、测试资源和 BuildKit 缓存维护 |
| `entrypoint.sh` | Docker 容器入口点 |
| `nginx-hardened.conf` | 旧版/参考 Nginx 安全加固配置；当前 Docker 镜像实际复制 `nginx/nginx.conf` |
| `mirrors.sh` | 智能镜像源选择系统 v2：维护 5 类镜像源候选池（Docker Hub / npm / PyPI / Debian apt / Alpine apk），构建前并行测速选最优源（结果缓存 24h），更新 daemon.json + buildkitd.toml 的 Docker Hub 镜像，导出 `NPM_MIRROR` / `PYPI_MIRROR` / `APT_MIRROR` / `APK_MIRROR` 环境变量 |

## 规则

- 部署命令：`./deploy/docker-deploy.sh update`
- 后端测试：`./deploy/docker-deploy.sh test -q`（使用带版本 tag 的独立 Compose project）。测试结束只删除测试容器、临时卷和 orphan，不删除当前测试镜像；旧测试镜像由定时维护按 `interview-boss-test:*` 精确清理。`test` 服务 data 卷为独立命名卷 `test-data`，挂在 `/app/backend/data`，与生产 `./backend/data` 隔离，测试不得读写生产数据
- HuggingFace 缓存主机路径经 `HF_CACHE_DIR` 参数化：`${HF_CACHE_DIR:-/home/ubuntu/.cache/huggingface}`。docker-deploy.sh 本身不设置该变量，compose 在解析时从调用进程环境读取（`HF_CACHE_DIR=/path ./deploy/docker-deploy.sh update/test` 可覆盖）；不设置时默认挂载 `/home/ubuntu/.cache/huggingface`，与旧版行为完全一致

- Worker 默认不随核心服务启动；需要后台任务时执行 `./deploy/docker-deploy.sh worker-up`，任务完成后可执行 `worker-down` 释放资源
- Docker 构建使用 InterviewBoss 专用 BuildKit builder、inline cache 和 npm/uv cache mounts；部署脚本会自动执行磁盘保护和专用 builder cache 收缩，不要绕过脚本长期直接运行 `docker compose build`
- 存储维护：安装 `deploy/systemd/interview-boss-storage-maintenance.service` 和 `.timer` 后，每日执行 `./deploy/docker-deploy.sh storage-maintenance`；也可以手动执行 `storage-check`、`cleanup --dry-run` 或该命令
- 镜像源策略：普通 `build/update/test/worker-up` 默认复用版本化缓存/稳定默认源，只做短健康检查；健康检查失败才刷新 npm/PyPI/apt 源，避免每次部署改 build args 造成依赖层缓存失效，也避免旧脚本缓存的坏源污染后续 update。镜像源整体失效或首次配置机器时执行 `./deploy/docker-deploy.sh mirrors`，该命令会清缓存、完整测速并更新 Docker Hub registry mirror。
- 部署预检：普通构建会先运行 `preflight_update_contract`，确认生产依赖仍是 `uv export + pip install -i $PYPI_MIRROR`，compose build 仍保留 `network: host`。不要把生产依赖阶段改回 `uv sync --frozen --no-dev --no-install-project`，否则 `uv.lock` 里的 `files.pythonhosted.org` 直链会绕过 PyPI 镜像并造成 update 卡住。
- BuildKit DNS 策略：compose build 必须使用 `network: host`，避免 Docker 从 systemd-resolved stub resolv.conf fallback 到不可控外部 DNS。`mirrors` 命令会持久化 Docker daemon DNS，默认 `DEPLOY_DOCKER_DNS=223.5.5.5,119.29.29.29`。
- Nginx 镜像内置前端 dist，生产不再挂载宿主机 `frontend/dist`
- 当前生产 Nginx 配置在 `nginx/nginx.conf`：静态文件根目录 `/usr/share/nginx/html`，`/api/` 和 `/mcp` 反代到 `backend:8000`，SSE/MCP 路径关闭 proxy buffering/cache/gzip
- Nginx 静态资源权限必须可被 worker 读取：Dockerfile 的 nginx-runtime 阶段在复制 dist 后执行 `chmod -R a+rX /usr/share/nginx/html`；`frontend` 快速部署也必须在 `docker cp` 后执行同样 chmod，避免宿主机 `0600` 图片进入容器后变成 403
- `./deploy/docker-deploy.sh frontend` 用于 Docker 已运行时快速发布前端；脚本在 `docker cp frontend/dist/.` 后必须修正 `/usr/share/nginx/html` 权限为 `a+rX`，避免 Nginx 因宿主构建产物权限导致 403
- 磁盘保护阈值：构建前硬性下限 `DEPLOY_HARD_MIN_FREE_MB=6144` MB；目标空间 `DEPLOY_TARGET_FREE_MB=8192` MB；BuildKit 最大缓存 `BUILDKIT_MAX_USED_SPACE=1536MB`；缓存年龄上限 `BUILDKIT_CACHE_MAX_AGE=168h`（7 天）
- 构建前高于目标时保留热缓存；低于目标但不低于硬阈值时只做轻量定向清理；低于硬阈值直接拒绝构建。构建后同样检查，清理失败或仍低于硬阈值会返回非零状态，阻止继续部署
- BuildKit 清理显式使用 `BUILDKIT_BUILDER=interview-boss` 专用 builder；定时维护只清理该 builder，避免回收其他 Docker project 的构建缓存。只有磁盘低于硬阈值时才允许无 `until` 的应急清理
- `prune_unused_docker` 只清理带明确 project/label 的测试资源和 InterviewBoss stopped/orphan 容器，不使用全局 image prune；宿主机 `node_modules`/`.venv` 只报告，除非 `DEPLOY_PRUNE_HOST_ARTIFACTS=1` 或 `cleanup --aggressive`
- `diagnose`：输出根分区、docker system df、frontend/node_modules、.venv、frontend/dist 大小等诊断信息
- `cleanup --dry-run`：输出备份、测试卷/镜像和主机目录的清理计划，不执行删除或 BuildKit prune
- 数据库备份：`./deploy/docker-deploy.sh backup` 会将 SQLite 库以 WAL 在线备份方式存到 `backups/interview-boss_<时间戳>.db`，命名规则见 `backup_sqlite_wal` / `do_backup`；`BACKUP_RETENTION_DAYS` 默认 7 天，`BACKUP_MIN_KEEP_FILES` 默认保留最近 3 份。`/data/projects/archive/interview-boss-backup-*` 的完整历史副本也按同一策略清理，但被 `/opt/interview-boss-backup-*` 软链接引用的副本会保留；Redis RDB 不享受最少 3 份保护，只按 7 天清理
- Evaluation 历史产物：`backend/data/evaluations` 由同一存储维护流程按 7 天 / 至少 3 份策略定向清理，只处理该目录顶层文件，不递归删除其他项目或数据库内容
- 数据库恢复：`./deploy/docker-deploy.sh restore [<备份路径>]`（缺省自动用 `backups/` 最新 `interview-boss_*.db`）。恢复流程：先校验备份为有效 SQLite 库 → **恢复前自动再备份当前库**（`backups/interview-boss_pre-restore_<时间戳>.db`）→ 停止 `backend` → 覆盖 `backend/data/interview-boss.db` 并清理 `-wal`/`-shm` → 启动 backend 并等待健康检查。恢复会覆盖生产库，属破坏性操作，仅用于恢复演练/真实故障恢复
- 可调开关：`DEPLOY_MIRROR_HEALTHCHECK_ON_BUILD=1`、`DEPLOY_MIRROR_HEALTHCHECK_TIMEOUT=2`、`DEPLOY_SELECT_MIRRORS_ON_BUILD=0`、`MIRROR_CACHE_VERSION=v2`。不要把 `DEPLOY_SELECT_MIRRORS_ON_BUILD=1` 作为日常默认值，否则每次 update 都可能测速、改 daemon 或改变 build args。
