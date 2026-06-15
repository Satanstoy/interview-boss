# Deploy — 部署脚本

> 位置：`deploy/` | 上游：根目录 `docker-compose.yml` | 下游：Docker 容器
> 职责：Docker 部署脚本和容器配置。

## 文件

| 文件 | 用途 |
|------|------|
| `docker-deploy.sh` | **生产部署脚本**（build / update / worker-up / worker-down / status / logs / backup / cleanup / diagnose） |
| `entrypoint.sh` | Docker 容器入口点 |
| `nginx-hardened.conf` | Nginx 安全加固配置 |

## 规则

- 部署命令：`./deploy/docker-deploy.sh update`

- Worker 默认不随核心服务启动；需要后台任务时执行 `./deploy/docker-deploy.sh worker-up`，任务完成后可执行 `worker-down` 释放资源
- Docker 构建使用 BuildKit、inline cache 和 npm/uv cache mounts；部署脚本会自动执行磁盘保护和 BuildKit cache 收缩，不要绕过脚本长期直接运行 `docker compose build`
- Nginx 镜像内置前端 dist，生产不再挂载宿主机 `frontend/dist`
- 磁盘保护阈值：构建前根分区至少 `DEPLOY_MIN_FREE_MB=4096` MB；构建后低于 `DEPLOY_TARGET_FREE_MB=5120` MB 时自动执行 `docker builder prune`，默认 `BUILDKIT_RESERVED_SPACE=2GB`
- `cleanup_after_build` 绝不在构建成功后执行 `docker compose down --rmi local`；低于目标时只 prune build cache 并提示手动 cleanup
- `prune_unused_docker` 为安全清理：BuildKit cache、dangling images、项目 stopped/orphan 资源；宿主机 `node_modules`/`.venv` 只报告，除非 `DEPLOY_PRUNE_HOST_ARTIFACTS=1` 或 `cleanup --aggressive`
- `diagnose`：输出根分区、docker system df、frontend/node_modules、.venv、frontend/dist 大小等诊断信息
- `cleanup --dry-run`：等价于 diagnose，只输出不清理
