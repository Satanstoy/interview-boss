#!/bin/bash
# InterviewBoss Docker 部署脚本
# 用法：./docker-deploy.sh [build|up|down|restart|status|logs|update|worker-up|worker-down|worker-restart|worker-logs|backup|cleanup]

set -euo pipefail

PROJECT_DIR="/home/ubuntu/sj/interview-boss"
cd "$PROJECT_DIR"

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
export BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}"

# 颜色
GREEN='[0;32m'
YELLOW='[1;33m'
RED='[0;31m'
NC='[0m'

log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err() { echo -e "${RED}[ERROR]${NC} $1"; }

# ── 检查 Docker 权限 ──
check_docker() {
  if ! docker info >/dev/null 2>&1; then
    err "Docker 权限不足或未启动"
    echo "  执行: sudo usermod -aG docker $(whoami) && 重新登录"
    exit 1
  fi
}

# ── 构建镜像 ──
do_build() {
  log "构建 app/nginx 镜像（启用 BuildKit 本地缓存）..."
  docker compose build backend nginx
  # 自动清理构建产生的悬空镜像，保留 BuildKit cache 目录
  docker image prune -f >/dev/null 2>&1 || true
  log "镜像构建完成（backend/worker 共用 app 镜像，nginx 内置前端 dist）"
}

# ── 启动核心服务 ──
do_up() {
  log "启动核心服务（redis/backend/nginx，不默认启动 worker）..."
  docker compose up -d redis backend nginx
  sleep 3
  do_status
}

# ── 停止服务 ──
do_down() {
  log "停止 Docker 服务..."
  docker compose --profile worker down
  log "服务已停止"
}

# ── 重启核心服务 ──
do_restart() {
  log "重启核心服务..."
  docker compose restart redis backend nginx
  sleep 3
  do_status
}

# ── 查看状态 ──
do_status() {
  log "服务状态："
  docker compose --profile worker ps
  echo ""
  log "资源使用："
  docker stats --no-stream --format "table {{.Name}}	{{.CPUPerc}}	{{.MemUsage}}" 2>/dev/null || true
}

# ── 查看日志 ──
do_logs() {
  local service="${1:-}"
  if [ -n "$service" ]; then
    docker compose --profile worker logs -f --tail=50 "$service"
  else
    docker compose --profile worker logs -f --tail=50
  fi
}

# ── 更新部署（代码变更后）──
do_update() {
  log "更新核心服务（不中断 Redis，不默认启动 worker）..."
  do_build
  docker compose up -d --no-deps redis backend nginx
  sleep 5
  do_status
  log "更新完成"
}

# ── Worker 按需挂载 ──
do_worker_up() {
  log "启动 Worker（按需后台任务）..."
  docker compose --profile worker up -d --build worker
  sleep 2
  do_status
}

do_worker_down() {
  log "停止 Worker..."
  docker compose --profile worker stop worker 2>/dev/null || true
  docker compose --profile worker rm -f worker 2>/dev/null || true
  do_status
}

do_worker_restart() {
  log "重建并重启 Worker..."
  docker compose build backend
  docker compose --profile worker up -d --no-deps worker
  sleep 2
  do_status
}

# ── 备份数据 ──
do_backup() {
  local backup_dir="$PROJECT_DIR/backups"
  local timestamp=$(date +%Y%m%d_%H%M%S)
  mkdir -p "$backup_dir"

  log "备份 SQLite 数据库..."
  cp "$PROJECT_DIR/backend/data/interview-boss.db"      "$backup_dir/interview-boss_${timestamp}.db"

  log "备份 Redis 数据..."
  docker compose exec redis redis-cli BGSAVE >/dev/null 2>&1 || true
  sleep 1
  docker cp "$(docker compose ps -q redis):/data/dump.rdb"      "$backup_dir/redis_${timestamp}.rdb" 2>/dev/null || warn "Redis 备份跳过"

  log "备份完成: $backup_dir/"
  ls -lh "$backup_dir/"*_"${timestamp}"* 2>/dev/null
}

# ── 清理旧镜像 ──
do_cleanup() {
  log "清理未使用的 Docker 资源（保留 .docker-cache 构建缓存目录）..."
  docker system prune -f
  log "清理完成"
}

# ── 停止宿主机服务（首次迁移用）──
do_migrate() {
  log "停止宿主机服务..."
  sudo systemctl stop interview-boss 2>/dev/null || true
  sudo systemctl stop interview-boss-worker 2>/dev/null || true
  sudo systemctl stop nginx 2>/dev/null || true
  sudo systemctl disable interview-boss 2>/dev/null || true
  sudo systemctl disable interview-boss-worker 2>/dev/null || true
  log "宿主机服务已停止，端口 80 已释放"
}

# ── 主逻辑 ──
MODE="${1:-all}"

case "$MODE" in
  build)           check_docker; do_build ;;
  up)              check_docker; do_up ;;
  down)            check_docker; do_down ;;
  restart)         check_docker; do_restart ;;
  status)          check_docker; do_status ;;
  logs)            check_docker; do_logs "${2:-}" ;;
  update)          check_docker; do_update ;;
  worker-up)       check_docker; do_worker_up ;;
  worker-down)     check_docker; do_worker_down ;;
  worker-restart)  check_docker; do_worker_restart ;;
  worker-logs)     check_docker; do_logs worker ;;
  backup)          check_docker; do_backup ;;
  cleanup)         check_docker; do_cleanup ;;
  migrate)         do_migrate ;;
  all)
    check_docker
    do_build
    do_up
    ;;
  *)
    echo "InterviewBoss Docker 部署脚本"
    echo ""
    echo "用法: ./docker-deploy.sh <命令>"
    echo ""
    echo "命令:"
    echo "  build           构建 app/nginx 镜像"
    echo "  up              启动核心服务（redis/backend/nginx）"
    echo "  down            停止所有服务（包含 worker profile）"
    echo "  restart         重启核心服务"
    echo "  status          查看服务状态和资源使用"
    echo "  logs            查看日志（可指定服务名: logs backend）"
    echo "  update          更新核心服务（不中断 Redis，不默认启动 worker）"
    echo "  worker-up       按需启动 Worker"
    echo "  worker-down     停止并移除 Worker 容器"
    echo "  worker-restart  重建 app 镜像并重启 Worker"
    echo "  worker-logs     查看 Worker 日志"
    echo "  backup          备份数据库和 Redis 数据"
    echo "  cleanup         清理未使用的 Docker 资源"
    echo "  migrate         停止宿主机服务（首次迁移用）"
    echo "  all             构建 + 启动核心服务（首次部署）"
    echo ""
    echo "示例:"
    echo "  ./docker-deploy.sh all"
    echo "  ./docker-deploy.sh update"
    echo "  ./docker-deploy.sh worker-up"
    echo "  ./docker-deploy.sh logs backend"
    ;;
esac
