#!/bin/bash
# InterviewBoss Docker 部署脚本
# 用法：./docker-deploy.sh [build|up|down|restart|status|logs|update|backup]

set -euo pipefail

PROJECT_DIR="/home/ubuntu/sj/interview-boss"
cd "$PROJECT_DIR"

# 颜色
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

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
  log "构建 Docker 镜像..."
  docker compose build 2>&1
  # 自动清理构建产生的悬空镜像，防止磁盘空间耗尽
  docker image prune -f >/dev/null 2>&1 || true
  log "镜像构建完成（已清理悬空镜像）"
}

# ── 启动服务 ──
do_up() {
  log "启动 Docker 服务..."
  docker compose down 2>/dev/null || true
  docker compose up -d
  sleep 3
  do_status
}

# ── 停止服务 ──
do_down() {
  log "停止 Docker 服务..."
  docker compose down
  log "服务已停止"
}

# ── 重启服务 ──
do_restart() {
  log "重启 Docker 服务..."
  docker compose restart
  sleep 3
  do_status
}

# ── 查看状态 ──
do_status() {
  log "服务状态："
  docker compose ps
  echo ""
  log "资源使用："
  docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>/dev/null || true
}

# ── 查看日志 ──
do_logs() {
  local service="${1:-}"
  if [ -n "$service" ]; then
    docker compose logs -f --tail=50 "$service"
  else
    docker compose logs -f --tail=50
  fi
}

# ── 更新部署（代码变更后）──
do_update() {
  log "更新部署..."
  docker compose down 2>/dev/null || true
  docker compose build backend worker nginx
  docker compose up -d
  sleep 5
  do_status
  log "更新完成"
}

# ── 备份数据 ──
do_backup() {
  local backup_dir="$PROJECT_DIR/backups"
  local timestamp=$(date +%Y%m%d_%H%M%S)
  mkdir -p "$backup_dir"

  log "备份 SQLite 数据库..."
  cp "$PROJECT_DIR/backend/data/interview-boss.db" \
     "$backup_dir/interview-boss_${timestamp}.db"

  log "备份 Redis 数据..."
  docker compose exec redis redis-cli BGSAVE >/dev/null 2>&1 || true
  sleep 1
  docker cp "$(docker compose ps -q redis):/data/dump.rdb" \
     "$backup_dir/redis_${timestamp}.rdb" 2>/dev/null || warn "Redis 备份跳过"

  log "备份完成: $backup_dir/"
  ls -lh "$backup_dir/"*_"${timestamp}"* 2>/dev/null
}

# ── 清理旧镜像 ──
do_cleanup() {
  log "清理未使用的 Docker 资源..."
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
  build)    check_docker; do_build ;;
  up)       check_docker; do_up ;;
  down)     check_docker; do_down ;;
  restart)  check_docker; do_restart ;;
  status)   check_docker; do_status ;;
  logs)     check_docker; do_logs "${2:-}" ;;
  update)   check_docker; do_update ;;
  backup)   check_docker; do_backup ;;
  cleanup)  check_docker; do_cleanup ;;
  migrate)  do_migrate ;;
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
    echo "  build     构建 Docker 镜像"
    echo "  up        启动所有服务"
    echo "  down      停止所有服务"
    echo "  restart   重启所有服务"
    echo "  status    查看服务状态和资源使用"
    echo "  logs      查看日志（可指定服务名: logs backend）"
    echo "  update    更新部署（代码变更后）"
    echo "  backup    备份数据库和 Redis 数据"
    echo "  cleanup   清理未使用的 Docker 资源"
    echo "  migrate   停止宿主机服务（首次迁移用）"
    echo "  all       构建 + 启动（首次部署）"
    echo ""
    echo "示例:"
    echo "  ./docker-deploy.sh all          # 首次部署"
    echo "  ./docker-deploy.sh update       # 代码更新后重新部署"
    echo "  ./docker-deploy.sh logs backend # 查看后端日志"
    echo "  ./docker-deploy.sh backup       # 备份数据"
    ;;
esac
