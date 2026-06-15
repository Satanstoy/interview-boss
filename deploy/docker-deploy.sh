#!/bin/bash
# InterviewBoss Docker 部署脚本（多项目安全版）
# 用法：./docker-deploy.sh [build|up|down|restart|status|logs|update|frontend|worker-up|worker-down|worker-restart|worker-logs|test|backup|cleanup|diagnose]
# 不使用全局 prune（docker system prune / container prune / network prune / image prune），
# 只清理本项目资源和 BuildKit 缓存，不影响其他 Docker 项目。

set -euo pipefail

PROJECT_DIR="/home/ubuntu/sj/interview-boss"
cd "$PROJECT_DIR"

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
export BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}"

# 磁盘保护阈值（单位：MB）。构建前至少保留 4GB；构建后尽量恢复到 5GB。
# 多项目安全：只用 docker builder prune 收缩缓存，不用全局 prune。
DEPLOY_MIN_FREE_MB="${DEPLOY_MIN_FREE_MB:-4096}"
DEPLOY_TARGET_FREE_MB="${DEPLOY_TARGET_FREE_MB:-5120}"
BUILDKIT_RESERVED_SPACE="${BUILDKIT_RESERVED_SPACE:-2GB}"

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

# ── 回滚支持 ──
OLD_BACKEND_IMAGE=""

save_old_image() {
  OLD_BACKEND_IMAGE=$(docker images --format '{{.ID}}' interview-boss-app:local 2>/dev/null | head -1)
}

rollback_backend() {
  if [ -n "$OLD_BACKEND_IMAGE" ]; then
    warn "Rolling back backend to previous image..."
    docker tag "$OLD_BACKEND_IMAGE" interview-boss-app:rollback 2>/dev/null || true
    docker compose up -d --no-deps --wait --wait-timeout 30 backend 2>/dev/null || true
    err "Rollback attempted. Check status with: $0 status"
  else
    err "No previous image available for rollback"
  fi
}

# ── 磁盘保护 ──
root_free_mb() {
  df -Pm / | awk 'NR == 2 {print $4}'
}

show_disk_usage() {
  local free_mb
  free_mb=$(root_free_mb)
  log "根分区可用空间: ${free_mb}MB"
  docker system df 2>/dev/null || true
}

prune_build_cache() {
  warn "清理 BuildKit 构建缓存，保留约 ${BUILDKIT_RESERVED_SPACE}..."
  docker builder prune -f --reserved-space "${BUILDKIT_RESERVED_SPACE}" >/dev/null 2>&1 || \
    docker builder prune -f --keep-storage "${BUILDKIT_RESERVED_SPACE}" >/dev/null 2>&1 || true
}

# 安全清理：BuildKit cache、dangling images、项目 stopped/orphan 资源。
# 默认不清理宿主机 node_modules/.venv，除非 DEPLOY_PRUNE_HOST_ARTIFACTS=1 或传入 --aggressive。
prune_unused_docker() {
  local aggressive="${1:-}"
  warn "安全清理本项目未使用资源（多项目安全，不使用全局 prune）..."

  # 1. 本项目 stopped/created 容器（不影响运行中服务）
  local stopped_containers
  stopped_containers=$(docker ps -a -q \
    --filter "label=com.docker.compose.project=interview-boss" \
    --filter "status=exited" \
    --filter "status=created" 2>/dev/null || true)
  if [ -n "$stopped_containers" ]; then
    docker rm -f $stopped_containers >/dev/null 2>&1 || true
  fi

  # 2. dangling images（不指定项目名，安全操作）
  docker image prune -f 2>/dev/null || true

  # 3. BuildKit 缓存（只在磁盘低时清理，避免破坏 uv/apt 下载缓存）
  local free_mb
  free_mb=$(root_free_mb)
  if [ "$free_mb" -lt "$DEPLOY_TARGET_FREE_MB" ]; then
    prune_build_cache
  else
    log "磁盘 ${free_mb}MB 充足，跳过 BuildKit 缓存清理（保留下载缓存加速下次构建）"
  fi

  # 4. 宿主机大文件目录（只报告，除非显式启用）
  if [ "${aggressive}" = "--aggressive" ] || [ "${DEPLOY_PRUNE_HOST_ARTIFACTS:-0}" = "1" ]; then
    warn "aggressive 模式：清理宿主机 node_modules 和 .venv..."
    local pdir="$PROJECT_DIR"
    [ -d "$pdir/frontend/node_modules" ] && rm -rf "$pdir/frontend/node_modules"
    [ -d "$pdir/backend/.venv" ] && rm -rf "$pdir/backend/.venv"
  else
    local pdir="$PROJECT_DIR"
    local nm_size venv_size
    nm_size=$(du -sh "$pdir/frontend/node_modules" 2>/dev/null | cut -f1 || echo "N/A")
    venv_size=$(du -sh "$pdir/backend/.venv" 2>/dev/null | cut -f1 || echo "N/A")
    log "宿主机目录（只报告，不清理；用 --aggressive 或 DEPLOY_PRUNE_HOST_ARTIFACTS=1 启用）："
    log "  frontend/node_modules: $nm_size"
    log "  backend/.venv:         $venv_size"
  fi
}

ensure_disk_before_build() {
  local free_mb
  free_mb=$(root_free_mb)
  if [ "$free_mb" -ge "$DEPLOY_MIN_FREE_MB" ]; then
    log "磁盘检查通过: ${free_mb}MB 可用"
    return 0
  fi

  warn "根分区可用空间 ${free_mb}MB，低于构建前阈值 ${DEPLOY_MIN_FREE_MB}MB，尝试清理构建缓存..."
  prune_unused_docker

  free_mb=$(root_free_mb)
  if [ "$free_mb" -lt "$DEPLOY_MIN_FREE_MB" ]; then
    err "根分区可用空间仍只有 ${free_mb}MB，低于 ${DEPLOY_MIN_FREE_MB}MB，拒绝部署以避免磁盘爆满"
    show_disk_usage
    exit 1
  fi
  log "清理后磁盘检查通过: ${free_mb}MB 可用"
}

cleanup_after_build() {
  local free_mb
  free_mb=$(root_free_mb)
  # 只在磁盘低于目标阈值时才收缩 BuildKit cache，避免删掉 uv/apt 下载缓存
  if [ "$free_mb" -lt "$DEPLOY_TARGET_FREE_MB" ]; then
    warn "构建后可用空间 ${free_mb}MB，低于目标 ${DEPLOY_TARGET_FREE_MB}MB，收缩 BuildKit 缓存..."
    prune_build_cache
    free_mb=$(root_free_mb)
  fi
  if [ "$free_mb" -lt "$DEPLOY_TARGET_FREE_MB" ]; then
    warn "构建后根分区可用空间 ${free_mb}MB，低于目标 ${DEPLOY_TARGET_FREE_MB}MB"
    warn "建议运行 './docker-deploy.sh cleanup' 或 'cleanup --aggressive' 手动清理"
  fi
  show_disk_usage
}

guarded_compose_build() {
  local rc
  ensure_disk_before_build
  set +e
  docker compose build "$@"
  rc=$?
  set -e
  cleanup_after_build
  if [ "$rc" -ne 0 ]; then
    err "Docker 构建失败，已执行构建后清理；退出码: $rc"
    exit "$rc"
  fi
}

# ── 构建镜像 ──
do_build() {
  log "构建 app/nginx 镜像（启用 BuildKit 本地缓存）..."
  guarded_compose_build backend nginx
  log "镜像构建完成（backend/worker 共用 app 镜像，nginx 内置前端 dist）"
}

# ── 启动核心服务 ──
do_up() {
  log "启动核心服务（redis/backend/nginx，不默认启动 worker）..."
  docker compose up -d --wait --wait-timeout 60 redis backend nginx
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
  docker compose restart --wait --wait-timeout 30 redis backend nginx
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

  # 1. Pre-flight
  ensure_disk_before_build
  save_old_image

  # 2. 数据库备份
  local backup_dir="$PROJECT_DIR/backups"
  local timestamp
  timestamp=$(date +%Y%m%d_%H%M%S)
  mkdir -p "$backup_dir"
  log "更新前备份数据库..."
  cp "$PROJECT_DIR/backend/data/interview-boss.db" "$backup_dir/interview-boss_${timestamp}.db" 2>/dev/null || warn "数据库文件不存在（首次部署？）"

  # 3. 构建
  do_build

  # 4. 启动服务（等待健康检查）
  log "启动更新后的服务（等待健康检查）..."
  if ! docker compose up -d --no-deps --wait --wait-timeout 60 redis backend nginx; then
    err "服务在 60s 内未通过健康检查"
    do_status
    rollback_backend
    exit 1
  fi

  # 5. 清理旧悬空镜像
  docker image prune -f 2>/dev/null || true

  # 6. 验证
  do_status
  log "更新完成（备份: $backup_dir/interview-boss_${timestamp}.db）"
}

# ── 前端快速更新（跳过 Docker 构建，直接替换 nginx 内的 dist） ──
do_frontend() {
  log "快速更新前端（仅构建 + 拷贝到 nginx 容器）..."
  cd "$PROJECT_DIR/frontend"
  if ! npm run build; then
    err "前端构建失败"
    cd "$PROJECT_DIR"
    exit 1
  fi
  cd "$PROJECT_DIR"
  docker cp frontend/dist/. interview-boss-nginx-1:/usr/share/nginx/html/
  log "前端已更新，无需重建镜像或重启容器"
}

# ── Worker 按需挂载 ──
do_worker_up() {
  log "启动 Worker（按需后台任务）..."
  guarded_compose_build backend
  docker compose --profile worker up -d --no-deps --wait --wait-timeout 30 worker
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
  guarded_compose_build backend
  docker compose --profile worker up -d --no-deps --wait --wait-timeout 30 worker
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

# ── 运行测试 ──
do_test() {
  log "构建测试镜像..."
  guarded_compose_build test
  log "运行 pytest..."
  docker compose --profile test run --rm test uv run pytest backend/tests/ "$@"
}

# ── 诊断磁盘使用 ──
do_diagnose() {
  log "========== 磁盘诊断 =========="
  echo ""
  log "根分区："
  df -h /
  echo ""
  log "Docker 系统资源："
  docker system df 2>/dev/null || true
  echo ""
  log "宿主机大文件目录："
  local pdir="$PROJECT_DIR"
  du -sh "$pdir/frontend/node_modules" 2>/dev/null && true
  du -sh "$pdir/backend/.venv"         2>/dev/null && true
  du -sh "$pdir/frontend/dist"         2>/dev/null && true
  log "  （以上目录由宿主机管理，非 Docker volume）"
  echo ""
  log "Docker BuildKit 缓存："
  docker builder du 2>/dev/null || true
  echo ""
  log "阈值设置（当前值 / 默认值）："
  log "  DEPLOY_MIN_FREE_MB:     $DEPLOY_MIN_FREE_MB / 4096"
  log "  DEPLOY_TARGET_FREE_MB:  $DEPLOY_TARGET_FREE_MB / 5120"
  log "  BUILDKIT_RESERVED_SPACE: $BUILDKIT_RESERVED_SPACE / 2GB"
  echo ""
  log "========== 诊断完成 =========="
}

# ── 清理旧镜像 ──
do_cleanup() {
  local dry_run=false
  local aggressive=""
  for arg in "$@"; do
    case "$arg" in
      --dry-run) dry_run=true ;;
      --aggressive) aggressive="--aggressive" ;;
    esac
  done

  if [ "$dry_run" = true ]; then
    log "dry-run 模式：仅输出诊断信息，不执行清理"
    do_diagnose
    return
  fi

  log "清理本项目资源（多项目安全）..."
  prune_unused_docker "$aggressive"
  show_disk_usage
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
  frontend)        check_docker; do_frontend ;;
  worker-up)       check_docker; do_worker_up ;;
  worker-down)     check_docker; do_worker_down ;;
  worker-restart)  check_docker; do_worker_restart ;;
  worker-logs)     check_docker; do_logs worker ;;
  test)            check_docker; do_test "${@:2}" ;;
  backup)          check_docker; do_backup ;;
  cleanup)         check_docker; do_cleanup "${@:2}" ;;
  diagnose)        do_diagnose ;;
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
    echo "  update          更新核心服务（自动备份 DB、健康检查等待、失败回滚）"
    echo "  frontend        快速更新前端（npm build + docker cp，跳过镜像构建）"
    echo "  worker-up       按需启动 Worker"
    echo "  worker-down     停止并移除 Worker 容器"
    echo "  worker-restart  重建 app 镜像并重启 Worker"
    echo "  worker-logs     查看 Worker 日志"
    echo "  test            运行 pytest 测试（可传入 pytest 参数）"
    echo "  backup          备份数据库和 Redis 数据"
    echo "  cleanup [--dry-run] [--aggressive]  清理本项目资源（不影响其他项目）"
    echo "  diagnose        输出磁盘/资源诊断信息（不修改任何资源）"
    echo "  migrate         停止宿主机服务（首次迁移用）"
    echo "  all             构建 + 启动核心服务（首次部署）"
    echo ""
    echo "示例:"
    echo "  ./docker-deploy.sh all"
    echo "  ./docker-deploy.sh update"
    echo "  ./docker-deploy.sh worker-up"
    echo "  ./docker-deploy.sh test"
    echo "  ./docker-deploy.sh test -k test_login"
    echo "  ./docker-deploy.sh logs backend"
    ;;
esac
