# Deploy — 部署脚本

> 位置：`deploy/` | 上游：根目录 `docker-compose.yml` | 下游：Docker 容器
> 职责：Docker 部署脚本和 systemd 服务配置。

## 文件

| 文件 | 用途 |
|------|------|
| `docker-deploy.sh` | **生产部署脚本**（build / update / worker-up / worker-down / status / logs / backup） |
| `deploy.sh` | systemd 模式部署（**不用于生产**） |
| `entrypoint.sh` | Docker 容器入口点 |
| `interview-boss-worker.service` | systemd 服务文件（配合 deploy.sh 使用） |
| `nginx-hardened.conf` | Nginx 安全加固配置 |

## 规则

- 生产环境必须用 `docker-deploy.sh`，禁止用 `deploy.sh` 的 systemd 模式
- 部署命令：`./deploy/docker-deploy.sh update`

- Worker 默认不随核心服务启动；需要后台任务时执行 `./deploy/docker-deploy.sh worker-up`，任务完成后可执行 `worker-down` 释放资源
- Docker 构建使用 BuildKit、inline cache 和 npm/uv cache mounts；不要用 `docker builder prune`，除非要强制全量重建
- Nginx 镜像内置前端 dist，生产不再挂载宿主机 `frontend/dist`
