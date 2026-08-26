#!/bin/bash
# InterviewBoss Docker 部署脚本（多项目安全版）
# 用法：./docker-deploy.sh [build|up|down|restart|status|logs|update|frontend|worker-up|worker-down|worker-restart|worker-logs|eval-worker-install|eval-worker-status|test|check|backup|restore|cleanup|storage-check|storage-maintenance|diagnose|mirrors]
# 不使用全局 prune（docker system prune / container prune / network prune / image prune），
# 只清理本项目资源和 BuildKit 缓存，不影响其他 Docker 项目。

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

# 镜像源测速选源（source，不执行）
source "$PROJECT_DIR/deploy/mirrors.sh"
source "$PROJECT_DIR/deploy/storage-retention.sh"

export DOCKER_BUILDKIT=1
export COMPOSE_DOCKER_CLI_BUILD=1
export BUILDKIT_PROGRESS="${BUILDKIT_PROGRESS:-plain}"

# 磁盘保护阈值（单位：MB）。构建前硬性保留 6GB；构建后尽量恢复到 8GB。
# 构建后低于硬阈值时返回失败，避免以“空间不足但仍成功”的状态继续部署。
DEPLOY_HARD_MIN_FREE_MB="${DEPLOY_HARD_MIN_FREE_MB:-6144}"
DEPLOY_TARGET_FREE_MB="${DEPLOY_TARGET_FREE_MB:-8192}"
BUILDKIT_MAX_USED_SPACE="${BUILDKIT_MAX_USED_SPACE:-1536MB}"
BUILDKIT_CACHE_MAX_AGE="${BUILDKIT_CACHE_MAX_AGE:-168h}"
BUILDKIT_BUILDER="${BUILDKIT_BUILDER:-interview-boss}"
BUILDKIT_BUILDER_DRIVER="${BUILDKIT_BUILDER_DRIVER:-docker-container}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
BACKUP_MIN_KEEP_FILES="${BACKUP_MIN_KEEP_FILES:-3}"
APP_RUNTIME_UID="${APP_RUNTIME_UID:-1000}"
APP_RUNTIME_GID="${APP_RUNTIME_GID:-1000}"

# 镜像源策略：
# - 默认复用缓存/稳定默认源，保持 Docker layer cache key 稳定。
# - 每次 build 只做短健康检查；失败才刷新 package manager 镜像源。
# - 全量测速 + Docker daemon registry mirror 更新只在 mirrors 命令或显式开关下执行。
DEPLOY_MIRROR_HEALTHCHECK_ON_BUILD="${DEPLOY_MIRROR_HEALTHCHECK_ON_BUILD:-1}"
DEPLOY_MIRROR_HEALTHCHECK_TIMEOUT="${DEPLOY_MIRROR_HEALTHCHECK_TIMEOUT:-2}"
DEPLOY_SELECT_MIRRORS_ON_BUILD="${DEPLOY_SELECT_MIRRORS_ON_BUILD:-0}"
DEPLOY_DOCKER_DNS="${DEPLOY_DOCKER_DNS:-223.5.5.5,119.29.29.29}"

# 颜色
GREEN='[0;32m'
YELLOW='[1;33m'
RED='[0;31m'
NC='[0m'

log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err() { echo -e "${RED}[ERROR]${NC} $1"; }

ensure_runtime_secrets() {
  local redis_secret_file="$PROJECT_DIR/backend/.redis-password"
  local env_file="$PROJECT_DIR/backend/.env"
  local generated_secret

  if [ ! -s "$redis_secret_file" ] || [ "$(wc -c < "$redis_secret_file")" -lt 33 ]; then
    umask 077
    if command -v openssl >/dev/null 2>&1; then
      generated_secret=$(openssl rand -hex 32)
    else
      generated_secret=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
    fi
    printf '%s\n' "$generated_secret" > "$redis_secret_file"
    log "已生成 Redis 运行时认证密钥（仅保存于 backend/.redis-password）"
  fi
  chmod 600 "$redis_secret_file"

  local oauth_secret=""
  local jwt_secret=""
  if [ -f "$env_file" ]; then
    oauth_secret=$(awk -F= '$1 == "OAUTH_SECRET_KEY" { value=$2; sub(/^[[:space:]]+/, "", value); gsub(/^"|"$/, "", value); print value; exit }' "$env_file")
    jwt_secret=$(awk -F= '$1 == "JWT_SECRET" { value=$2; sub(/^[[:space:]]+/, "", value); gsub(/^"|"$/, "", value); print value; exit }' "$env_file")
    chmod 600 "$env_file"
  fi
  if [ -f "$env_file" ] && [ -z "$oauth_secret" ]; then
    umask 077
    if command -v openssl >/dev/null 2>&1; then
      generated_secret=$(openssl rand -hex 32)
    else
      generated_secret=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
    fi
    printf '\nOAUTH_SECRET_KEY=%s\n' "$generated_secret" >> "$env_file"
    chmod 600 "$env_file"
    log "已生成 OAuth 签名密钥并写入 backend/.env"
  fi
  if [ -f "$env_file" ] && [ -z "$jwt_secret" ]; then
    umask 077
    if command -v openssl >/dev/null 2>&1; then
      generated_secret=$(openssl rand -hex 32)
    else
      generated_secret=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
    fi
    printf '\nJWT_SECRET=%s\n' "$generated_secret" >> "$env_file"
    chmod 600 "$env_file"
    log "已生成 JWT 签名密钥并写入 backend/.env（仅首次部署）"
  fi
}

ensure_runtime_data_dir() {
  local data_dir="$PROJECT_DIR/backend/data"
  local current_owner write_probe

  mkdir -p "$data_dir"
  current_owner=$(stat -c '%u:%g' "$data_dir" 2>/dev/null || true)
  if [ "$current_owner" != "${APP_RUNTIME_UID}:${APP_RUNTIME_GID}" ] || [ ! -w "$data_dir" ]; then
    if [ "$(id -u)" -eq 0 ]; then
      chown -R "${APP_RUNTIME_UID}:${APP_RUNTIME_GID}" "$data_dir"
    elif command -v sudo >/dev/null 2>&1; then
      sudo chown -R "${APP_RUNTIME_UID}:${APP_RUNTIME_GID}" "$data_dir"
    else
      err "运行时数据目录不可由 appuser 写入: $data_dir（需要 UID:GID ${APP_RUNTIME_UID}:${APP_RUNTIME_GID}）"
      return 1
    fi
  fi

  write_probe="$data_dir/.write-test.$$"
  if ! touch "$write_probe" 2>/dev/null; then
    err "运行时数据目录写入检查失败: $data_dir（appuser 需要可写）"
    return 1
  fi
  rm -f "$write_probe"
  log "运行时数据目录权限通过: $data_dir (${APP_RUNTIME_UID}:${APP_RUNTIME_GID})"
}

# ── 检查 Docker 权限 ──
check_docker() {
  if ! docker info >/dev/null 2>&1; then
    err "Docker 权限不足或未启动"
    echo "  执行: sudo usermod -aG docker $(whoami) && 重新登录"
    exit 1
  fi
}

ensure_docker_dns_config() {
  local daemon_json="/etc/docker/daemon.json"
  if ! command -v jq >/dev/null 2>&1; then
    warn "jq 未安装，跳过 Docker DNS 持久化配置"
    return 0
  fi

  local current_json tmp_json dns_json
  current_json=$(mktemp)
  tmp_json=$(mktemp)

  if [ -f "$daemon_json" ]; then
    cp "$daemon_json" "$current_json"
  else
    echo "{}" > "$current_json"
  fi

  dns_json=$(printf '%s' "$DEPLOY_DOCKER_DNS" | tr ',' '\n' | sed '/^[[:space:]]*$/d' | jq -R . | jq -s .)
  jq --argjson dns "$dns_json" '.dns = $dns' "$current_json" > "$tmp_json"

  if diff -q "$current_json" "$tmp_json" >/dev/null 2>&1; then
    log "Docker DNS 配置无需变更"
  else
    sudo cp "$tmp_json" "$daemon_json"
    log "Docker DNS 已更新为: $DEPLOY_DOCKER_DNS，重载 Docker daemon..."
    sudo systemctl reload docker 2>/dev/null || sudo systemctl restart docker 2>/dev/null || warn "Docker daemon 重载失败，可能需要手动重启"
  fi

  rm -f "$current_json" "$tmp_json"
}

# ── 回滚支持 ──
OLD_BACKEND_IMAGE=""
EPHEMERAL_TEST_PROJECT=""
EPHEMERAL_TEST_TAG=""

current_test_tag() {
  printf '%s\n' "${INTERVIEW_BOSS_TEST_TAG:-$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo local)}"
}

cleanup_ephemeral_test() {
  local project="$EPHEMERAL_TEST_PROJECT"
  [ -n "$project" ] || return 0

  INTERVIEW_BOSS_TEST_TAG="${EPHEMERAL_TEST_TAG:-local}" \
    docker compose --project-name "$project" --profile test \
    down --volumes --remove-orphans >/dev/null 2>&1 || \
    warn "临时测试 Compose project 清理不完整: $project"
  EPHEMERAL_TEST_PROJECT=""
}

save_old_image() {
  OLD_BACKEND_IMAGE=$(docker images --format '{{.ID}}' interview-boss-app:local 2>/dev/null | head -1)
  if [ -n "$OLD_BACKEND_IMAGE" ]; then
    if ! docker tag "$OLD_BACKEND_IMAGE" interview-boss-app:previous >/dev/null 2>&1; then
      warn "无法保留上一版本生产镜像标签 interview-boss-app:previous"
    fi
  fi

  local image old_image previous_tag
  for image in interview-boss-nginx:local interview-boss-oauth-gateway:latest; do
    old_image=$(docker images --format '{{.ID}}' "$image" 2>/dev/null | head -1)
    [ -n "$old_image" ] || continue
    previous_tag="${image%%:*}:previous"
    if ! docker tag "$old_image" "$previous_tag" >/dev/null 2>&1; then
      warn "无法保留上一版本生产镜像标签 $previous_tag"
    fi
  done
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

ensure_buildkit_builder() {
  local driver
  if docker buildx inspect "$BUILDKIT_BUILDER" >/dev/null 2>&1; then
    driver=$(docker buildx inspect "$BUILDKIT_BUILDER" 2>/dev/null | awk -F': ' '/^Driver:/ {gsub(/^ +| +$/, "", $2); print $2; exit}')
    if [ "$driver" != "$BUILDKIT_BUILDER_DRIVER" ]; then
      err "BuildKit builder $BUILDKIT_BUILDER 的 driver=$driver，不符合隔离要求（需要 $BUILDKIT_BUILDER_DRIVER）"
      return 1
    fi
    return 0
  fi

  warn "创建 InterviewBoss 专用 BuildKit builder: $BUILDKIT_BUILDER"
  if ! docker buildx create \
    --name "$BUILDKIT_BUILDER" \
    --driver "$BUILDKIT_BUILDER_DRIVER" \
    --driver-opt network=host >/dev/null; then
    err "无法创建 InterviewBoss 专用 BuildKit builder"
    return 1
  fi
}

prune_build_cache() {
  local mode="${1:-light}"
  local filter_args=(--filter "until=${BUILDKIT_CACHE_MAX_AGE}")
  local builder_driver
  if ! docker buildx inspect "$BUILDKIT_BUILDER" >/dev/null 2>&1; then
    log "InterviewBoss 专用 BuildKit builder 尚未创建，跳过其缓存清理"
    return 0
  fi
  builder_driver=$(docker buildx inspect "$BUILDKIT_BUILDER" 2>/dev/null | awk -F': ' '/^Driver:/ {gsub(/^ +| +$/, "", $2); print $2; exit}')
  if [ "$builder_driver" != "$BUILDKIT_BUILDER_DRIVER" ]; then
    err "拒绝清理非隔离 BuildKit builder: $BUILDKIT_BUILDER (driver=$builder_driver)"
    return 1
  fi
  if ! docker buildx inspect "$BUILDKIT_BUILDER" --bootstrap >/dev/null 2>&1; then
    warn "InterviewBoss BuildKit builder 无法启动，跳过本轮缓存清理"
    return 1
  fi

  if [[ "$mode" == "aggressive" ]]; then
    local free_mb
    free_mb=$(root_free_mb)
    if [ "$free_mb" -lt "$DEPLOY_HARD_MIN_FREE_MB" ]; then
      filter_args=()
      warn "根分区低于硬阈值，允许应急清理近期 BuildKit 缓存"
    else
      warn "空间未低于硬阈值，aggressive 请求降级为 7 天过期缓存清理"
      mode="light"
    fi
  fi

  warn "清理 BuildKit 构建缓存（模式=${mode}，最大 ${BUILDKIT_MAX_USED_SPACE}）..."
  if docker buildx prune --builder "$BUILDKIT_BUILDER" -f \
    "${filter_args[@]}" \
    --max-used-space "${BUILDKIT_MAX_USED_SPACE}" \
    --min-free-space "${DEPLOY_TARGET_FREE_MB}MB"; then
    return 0
  fi

  warn "docker buildx prune 参数不可用，使用兼容回退模式..."
  local fallback_args=(--reserved-space "${BUILDKIT_MAX_USED_SPACE}")
  if [[ "$mode" != "aggressive" ]]; then
    fallback_args+=(--filter "until=${BUILDKIT_CACHE_MAX_AGE}")
  fi
  docker builder prune --builder "$BUILDKIT_BUILDER" -f "${fallback_args[@]}"
}

# 清理测试专用镜像和卷。测试服务使用显式命名，生产服务不依赖它们。
prune_test_resources() {
  local volume project volume_kind links image image_id current_image linked_containers compose_service
  current_image="interview-boss-test:$(current_test_tag)"

  for volume in $(docker volume ls -q 2>/dev/null); do
    project=$(docker volume inspect -f '{{index .Labels "com.docker.compose.project"}}' "$volume" 2>/dev/null || true)
    volume_kind=$(docker volume inspect -f '{{index .Labels "com.docker.compose.volume"}}' "$volume" 2>/dev/null || true)
    if [[ "$volume_kind" != "test-data" ]]; then
      continue
    fi
    if [[ "$project" != "interview-boss" && "$project" != interview-boss-test-* && "$project" != interview-boss-check-* ]]; then
      continue
    fi
    links=$(docker volume inspect -f '{{len .Containers}}' "$volume" 2>/dev/null || echo 1)
    if [[ "$links" == "0" ]]; then
      if [[ "${STORAGE_RETENTION_DRY_RUN:-0}" == "1" ]]; then
        log "would remove unused test volume: $volume"
      elif docker volume rm "$volume" >/dev/null 2>&1; then
        log "已清理未使用测试卷: $volume"
      else
        warn "测试卷清理失败（保留，可能仍被引用）: $volume"
      fi
    fi
  done

  while IFS= read -r image; do
    [ -n "$image" ] || continue
    image_id=$(docker image inspect -f '{{.Id}}' "$image" 2>/dev/null || true)
    [ -n "$image_id" ] || continue
    if [[ "$image" == "$current_image" ]]; then
      continue
    fi
    linked_containers=$(docker ps -a --filter "ancestor=$image_id" -q 2>/dev/null || true)
    if [ -z "$linked_containers" ]; then
      if [[ "${STORAGE_RETENTION_DRY_RUN:-0}" == "1" ]]; then
        log "would remove unused old test image: $image"
      elif docker image rm "$image" >/dev/null 2>&1; then
        log "已清理未使用测试镜像: $image"
      else
        warn "旧测试镜像清理失败（保留）: $image"
      fi
    fi
  done < <(docker image ls --format '{{.Repository}}:{{.Tag}}' 'interview-boss-test:*' 2>/dev/null)

  # 同一测试 tag 被重复构建时，旧 image 可能变成 <none>:<none>。
  # 无标签镜像没有名称可匹配，只有同时具备 Compose project/service 标签时才处理，
  # 并且仍跳过有容器引用的 image，避免触碰其他 Docker project。
  while IFS= read -r image_id; do
    [ -n "$image_id" ] || continue
    project=$(docker image inspect -f '{{index .Config.Labels "com.docker.compose.project"}}' "$image_id" 2>/dev/null || true)
    compose_service=$(docker image inspect -f '{{index .Config.Labels "com.docker.compose.service"}}' "$image_id" 2>/dev/null || true)
    case "$project:$compose_service" in
      interview-boss:test|interview-boss:backend|interview-boss:nginx|interview-boss:oauth-gateway|\
      interview-boss-test-*:test|interview-boss-check-*:test)
        ;;
      *)
        continue
        ;;
    esac
    linked_containers=$(docker ps -a --filter "ancestor=$image_id" -q 2>/dev/null || true)
    [ -z "$linked_containers" ] || continue
    if [[ "${STORAGE_RETENTION_DRY_RUN:-0}" == "1" ]]; then
      log "would remove unused scoped dangling image: $image_id ($project/$compose_service)"
    elif docker image rm "$image_id" >/dev/null 2>&1; then
      log "已清理未使用的本项目悬空镜像: $image_id ($project/$compose_service)"
    else
      warn "本项目悬空镜像清理失败（保留）: $image_id"
    fi
  done < <(docker image ls --filter dangling=true --format '{{.ID}}' 2>/dev/null | sort -u)
}

# 清理 InterviewBoss 生产镜像的旧标签。当前和 previous 标签始终保留，
# 只处理明确的本项目镜像名，不触碰 Redis 或其他 Compose project 的镜像。
prune_production_images() {
  local image image_id linked_containers
  while IFS= read -r image; do
    [ -n "$image" ] || continue
    case "$image" in
      interview-boss-app:local|interview-boss-app:previous|\
      interview-boss-nginx:local|interview-boss-nginx:previous|\
      interview-boss-oauth-gateway:latest|interview-boss-oauth-gateway:previous)
        continue
        ;;
    esac
    image_id=$(docker image inspect -f '{{.Id}}' "$image" 2>/dev/null || true)
    [ -n "$image_id" ] || continue
    linked_containers=$(docker ps -a --filter "ancestor=$image_id" -q 2>/dev/null || true)
    if [ -n "$linked_containers" ]; then
      continue
    fi
    if [[ "${STORAGE_RETENTION_DRY_RUN:-0}" == "1" ]]; then
      log "would remove unused old production image: $image"
    elif docker image rm "$image" >/dev/null 2>&1; then
      log "已清理未使用旧生产镜像标签: $image"
    else
      warn "旧生产镜像清理失败（保留）: $image"
    fi
  done < <(
    {
      docker image ls --format '{{.Repository}}:{{.Tag}}' 'interview-boss-app:*' 2>/dev/null
      docker image ls --format '{{.Repository}}:{{.Tag}}' 'interview-boss-nginx:*' 2>/dev/null
      docker image ls --format '{{.Repository}}:{{.Tag}}' 'interview-boss-oauth-gateway:*' 2>/dev/null
      docker image ls --format '{{.Repository}}:{{.Tag}}' 'interview-boss-taxonomy:*' 2>/dev/null
    } | sort -u
  )
}

# 安全清理：BuildKit cache、测试资源、项目 stopped/orphan 资源。
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
    if [[ "${STORAGE_RETENTION_DRY_RUN:-0}" == "1" ]]; then
      log "would remove stopped InterviewBoss containers: $(printf '%s' "$stopped_containers" | tr '\n' ' ')"
    elif ! printf '%s\n' "$stopped_containers" | xargs -r docker rm -f >/dev/null 2>&1; then
      warn "InterviewBoss stopped container 清理失败（保留未删除资源）"
    fi
  fi

  # 2. 生产/测试镜像和卷有明确名称或 label，不做全局 image prune。
  prune_production_images
  prune_test_resources

  # 3. 正常空间不做重型缓存清理；低于目标时只清理过期缓存。
  if [[ "${STORAGE_RETENTION_DRY_RUN:-0}" == "1" ]]; then
    log "dry-run：跳过 BuildKit 实际清理"
  elif [[ "${SKIP_BUILDKIT_CLEANUP:-0}" == "1" ]]; then
    log "调用方负责 BuildKit 缓存维护，跳过重复清理"
  else
    local free_mb
    free_mb=$(root_free_mb)
    if [ "$free_mb" -lt "$DEPLOY_TARGET_FREE_MB" ]; then
      prune_build_cache light
    else
      log "磁盘 ${free_mb}MB 高于目标 ${DEPLOY_TARGET_FREE_MB}MB，保留热 BuildKit 缓存"
    fi
  fi

  # 4. 宿主机大文件目录（只报告，除非显式启用）
  local host_free_mb
  host_free_mb=$(root_free_mb)
  if { [ "${aggressive}" = "--aggressive" ] || [ "${DEPLOY_PRUNE_HOST_ARTIFACTS:-0}" = "1" ]; } \
    && [ "$host_free_mb" -lt "$DEPLOY_TARGET_FREE_MB" ]; then
    warn "磁盘低于目标，清理宿主机 node_modules 和 .venv..."
    local pdir="$PROJECT_DIR"
    if [ -d "$pdir/frontend/node_modules" ] && ! rm -rf -- "$pdir/frontend/node_modules"; then
      warn "清理 frontend/node_modules 失败"
    fi
    if [ -d "$pdir/backend/.venv" ] && ! rm -rf -- "$pdir/backend/.venv"; then
      warn "清理 backend/.venv 失败"
    fi
  elif [ "${aggressive}" = "--aggressive" ] || [ "${DEPLOY_PRUNE_HOST_ARTIFACTS:-0}" = "1" ]; then
    log "磁盘 ${host_free_mb}MB 未低于目标，保留 node_modules 和 .venv"
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
  if [ "$free_mb" -lt "$DEPLOY_HARD_MIN_FREE_MB" ]; then
    err "根分区可用空间 ${free_mb}MB，低于硬阈值 ${DEPLOY_HARD_MIN_FREE_MB}MB，直接拒绝构建"
    show_disk_usage
    exit 1
  fi
  if [ "$free_mb" -ge "$DEPLOY_TARGET_FREE_MB" ]; then
    log "磁盘检查通过: ${free_mb}MB 可用"
    return 0
  fi

  warn "根分区可用空间 ${free_mb}MB，低于目标 ${DEPLOY_TARGET_FREE_MB}MB，执行轻量定向清理..."
  prune_unused_docker

  free_mb=$(root_free_mb)
  if [ "$free_mb" -lt "$DEPLOY_HARD_MIN_FREE_MB" ]; then
    err "清理后根分区可用空间仍只有 ${free_mb}MB，低于硬阈值 ${DEPLOY_HARD_MIN_FREE_MB}MB，拒绝构建"
    show_disk_usage
    exit 1
  fi
  log "清理后磁盘检查通过: ${free_mb}MB 可用"
}

cleanup_after_build() {
  local free_mb cleanup_rc=0
  free_mb=$(root_free_mb)
  # 正常空间只检查；低于目标时才执行轻量定向清理，避免每次 build 重型 prune。
  if [ "$free_mb" -lt "$DEPLOY_TARGET_FREE_MB" ]; then
    warn "构建后可用空间 ${free_mb}MB，低于目标 ${DEPLOY_TARGET_FREE_MB}MB，收缩过期 BuildKit 缓存..."
    if ! prune_build_cache light; then
      err "BuildKit 缓存清理失败，拒绝继续部署"
      cleanup_rc=1
    fi
    free_mb=$(root_free_mb)
  else
    log "构建后可用空间 ${free_mb}MB，高于目标，保留热缓存"
  fi

  if [ "$free_mb" -lt "$DEPLOY_HARD_MIN_FREE_MB" ]; then
    warn "轻量清理后仍低于硬阈值，执行一次应急 BuildKit 清理..."
    if ! prune_build_cache aggressive; then
      err "应急 BuildKit 缓存清理失败，拒绝继续部署"
      cleanup_rc=1
    fi
    free_mb=$(root_free_mb)
  fi
  if [ "$free_mb" -lt "$DEPLOY_HARD_MIN_FREE_MB" ]; then
    err "构建后根分区可用空间 ${free_mb}MB，低于硬阈值 ${DEPLOY_HARD_MIN_FREE_MB}MB，拒绝继续部署"
    cleanup_rc=1
  elif [ "$free_mb" -lt "$DEPLOY_TARGET_FREE_MB" ]; then
    warn "构建后根分区可用空间 ${free_mb}MB，低于目标 ${DEPLOY_TARGET_FREE_MB}MB；下一次构建将按硬阈值检查"
  fi
  show_disk_usage
  return "$cleanup_rc"
}

# 镜像源准备：默认轻量健康检查，失败才刷新 package 镜像源。
maybe_select_mirrors() {
  if [ "$DEPLOY_SELECT_MIRRORS_ON_BUILD" = "1" ]; then
    warn "DEPLOY_SELECT_MIRRORS_ON_BUILD=1，构建前执行完整镜像源测速..."
    select_mirrors
    return
  fi

  load_cached_package_mirrors

  if [ "$DEPLOY_MIRROR_HEALTHCHECK_ON_BUILD" != "1" ]; then
    log "使用缓存镜像源（跳过健康检查）: npm=$NPM_MIRROR, PyPI=$PYPI_MIRROR, apt=$APT_MIRROR"
    return
  fi

  if check_package_mirrors_healthy "$DEPLOY_MIRROR_HEALTHCHECK_TIMEOUT"; then
    log "镜像源健康检查通过: npm=$NPM_MIRROR, PyPI=$PYPI_MIRROR, apt=$APT_MIRROR"
    return
  fi

  warn "缓存镜像源不可用，刷新 package manager 镜像源（不修改 Docker daemon）..."
  refresh_package_mirrors
}

preflight_update_contract() {
  local dockerfile="$PROJECT_DIR/Dockerfile"
  local compose_file="$PROJECT_DIR/docker-compose.yml"
  local prod_deps_stage

  if ! grep -q -- "uv export --frozen --no-dev --no-hashes --format requirements-txt" "$dockerfile"; then
    err "部署预检失败：生产依赖必须先 uv export --frozen --no-dev --no-hashes --format requirements-txt，再交给 pip 镜像安装"
    exit 1
  fi

  prod_deps_stage=$(awk '
    /^FROM python-base AS deps-builder$/ {in_stage=1}
    /^FROM python-base AS deps-builder-dev$/ {in_stage=0}
    in_stage {print}
  ' "$dockerfile")
  if printf '%s\n' "$prod_deps_stage" | grep -q -- "uv sync --frozen --no-dev --no-install-project"; then
    err "部署预检失败：生产依赖阶段禁止回退到 uv sync --frozen --no-dev --no-install-project；uv.lock 里的 files.pythonhosted.org 直链会绕过 PyPI 镜像并造成 update 卡住"
    exit 1
  fi

  if ! grep -q -- "network: host" "$compose_file"; then
    err "部署预检失败：compose build 必须保留 network: host，避免 BuildKit DNS fallback 到不可控外部 DNS"
    exit 1
  fi

  if grep -q -- "files.pythonhosted.org" "$dockerfile"; then
    err "部署预检失败：Dockerfile 不应直接引用 files.pythonhosted.org，依赖下载必须走当前 PyPI 镜像源"
    exit 1
  fi

  log "部署预检通过：生产依赖走 pip 镜像，BuildKit 使用 host network"
}

guarded_compose_build() {
  local rc cleanup_rc
  preflight_update_contract
  ensure_disk_before_build
  if ! ensure_buildkit_builder; then
    exit 1
  fi
  maybe_select_mirrors
  set +e
  docker compose build --builder "$BUILDKIT_BUILDER" "$@"
  rc=$?
  cleanup_after_build
  cleanup_rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    err "Docker 构建失败，已执行构建后清理；退出码: $rc"
    exit "$rc"
  fi
  if [ "$cleanup_rc" -ne 0 ]; then
    err "Docker 构建完成但磁盘保护未通过，拒绝继续部署"
    exit "$cleanup_rc"
  fi
}

guarded_compose_build_project() {
  local project_name="$1"
  shift
  local rc cleanup_rc
  preflight_update_contract
  ensure_disk_before_build
  if ! ensure_buildkit_builder; then
    return 1
  fi
  maybe_select_mirrors
  set +e
  INTERVIEW_BOSS_TEST_TAG="${EPHEMERAL_TEST_TAG:-local}" \
    docker compose --project-name "$project_name" build --builder "$BUILDKIT_BUILDER" "$@"
  rc=$?
  cleanup_after_build
  cleanup_rc=$?
  set -e
  if [ "$rc" -ne 0 ]; then
    err "Docker 构建失败，已执行构建后清理；退出码: $rc"
    return "$rc"
  fi
  if [ "$cleanup_rc" -ne 0 ]; then
    err "Docker 构建完成但磁盘保护未通过，拒绝继续测试"
    return "$cleanup_rc"
  fi
}

# ── 构建镜像 ──
do_build() {
  log "构建 app/nginx/oauth-gateway 镜像（启用 BuildKit 本地缓存）..."
  guarded_compose_build backend nginx oauth-gateway
  log "镜像构建完成（backend/worker 共用 app 镜像，nginx 内置前端 dist，OAuth gateway 独立构建）"
}

# ── 启动核心服务 ──
do_up() {
  log "启动核心服务（redis queue/cache、backend/nginx/oauth-gateway，不默认启动 worker）..."
  ensure_runtime_data_dir
  docker compose up -d --wait --wait-timeout 60 redis redis-cache backend nginx oauth-gateway
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
  docker compose restart --wait --wait-timeout 30 redis redis-cache backend nginx oauth-gateway
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
  ensure_runtime_data_dir
  ensure_disk_before_build
  save_old_image

  # 2. 数据库备份
  local backup_dir="$PROJECT_DIR/backups"
  local timestamp
  timestamp=$(date +%Y%m%d_%H%M%S)
  storage_require_data_mount || {
    err "更新前备份目录依赖 /data，未确认真实挂载，拒绝更新"
    exit 1
  }
  mkdir -p "$backup_dir"
  log "更新前备份数据库..."
  if [ -f "$PROJECT_DIR/backend/data/interview-boss.db" ]; then
    if ! backup_sqlite_wal "$PROJECT_DIR/backend/data/interview-boss.db" "$backup_dir/interview-boss_${timestamp}.db"; then
      err "数据库在线备份失败，拒绝继续更新"
      exit 1
    fi
  else
    warn "数据库文件不存在（首次部署？）"
  fi

  # 3. 构建
  do_build

  # 4. 启动服务（等待健康检查）
  log "启动更新后的服务（等待健康检查）..."
  if ! docker compose up -d --no-deps --wait --wait-timeout 60 redis redis-cache backend nginx oauth-gateway; then
    err "服务在 60s 内未通过健康检查"
    do_status
    rollback_backend
    exit 1
  fi

  # 5. 清理过期备份
  storage_cleanup_backups "$PROJECT_DIR"

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
  docker compose exec nginx sh -lc 'chmod -R a+rX /usr/share/nginx/html'
  log "前端已更新，无需重建镜像或重启容器"
}

# ── Worker 按需挂载 ──
do_worker_up() {
  log "启动 Worker（按需后台任务）..."
  ensure_runtime_data_dir
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

# ── Eval Worker systemd timer ──
do_eval_worker_install() {
  local unit_dir="/etc/systemd/system"
  log "安装 Eval Worker systemd service/timer..."
  sudo install -m 0644 \
    "$PROJECT_DIR/deploy/systemd/interview-boss-eval-worker.service" \
    "$unit_dir/interview-boss-eval-worker.service"
  sudo install -m 0644 \
    "$PROJECT_DIR/deploy/systemd/interview-boss-eval-worker.timer" \
    "$unit_dir/interview-boss-eval-worker.timer"
  sudo systemctl daemon-reload
  sudo systemctl enable --now interview-boss-eval-worker.timer
  log "Eval Worker timer 已安装并启用"
}

do_eval_worker_status() {
  local db_path="$PROJECT_DIR/backend/data/interview-boss.db"
  log "Eval Worker systemd 状态："
  systemctl is-enabled interview-boss-eval-worker.timer 2>/dev/null || true
  systemctl is-active interview-boss-eval-worker.timer 2>/dev/null || true
  echo ""
  log "Eval Worker 容器状态："
  docker compose --profile eval ps eval-worker || true
  echo ""
  log "Eval Run 队列诊断："
  if [ -f "$db_path" ]; then
    DB_PATH="$db_path" python3 - <<'PY'
import os
import sqlite3

path = os.environ["DB_PATH"]
with sqlite3.connect(path) as conn:
    conn.row_factory = sqlite3.Row
    counts = {
        row["status"]: row["count"]
        for row in conn.execute(
            "SELECT status, COUNT(*) AS count FROM eval_runs GROUP BY status"
        )
    }
    try:
        heartbeat = conn.execute(
            "SELECT status, last_seen_at, last_error "
            "FROM worker_heartbeats WHERE worker_name = 'eval-worker'"
        ).fetchone()
    except sqlite3.OperationalError:
        heartbeat = None
    active = sum(counts.get(status, 0) for status in ("created", "queued", "running"))
    if active == 0:
        state = "queue_empty"
    elif heartbeat is None or heartbeat["status"] != "online":
        state = "worker_offline"
    else:
        state = "worker_online"
    stale = conn.execute(
        "SELECT COUNT(*) FROM eval_runs "
        "WHERE status IN ('created', 'queued') "
        "AND created_at < datetime('now', '-10 minutes')"
    ).fetchone()[0]
    if active and stale:
        state = "queued_stuck"
    print({"queue_state": state, "stale_queued_count": stale, "counts": counts, "heartbeat": dict(heartbeat) if heartbeat else None})
PY
  else
    warn "数据库不存在: $db_path"
  fi
}

# ── 备份数据 ──
# SQLite WAL 模式在线备份：裸 cp 会漏掉 -wal 中未 checkpoint 的已提交事务且可能撕裂文件，
# 必须用 sqlite 在线备份 API（.backup / python backup）。
backup_sqlite_wal() {
  local src="$1" dest="$2"
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$src" ".backup '$dest'"
  elif command -v python3 >/dev/null 2>&1; then
    python3 - "$src" "$dest" <<'PY'
import sqlite3, sys
src, dest = sys.argv[1], sys.argv[2]
s = sqlite3.connect(src)
d = sqlite3.connect(dest)
try:
    s.backup(d)
finally:
    d.close(); s.close()
PY
  else
    err "备份失败：需要 sqlite3 或 python3 才能在线备份 WAL 数据库"
    return 1
  fi
}

do_backup() {
  local backup_dir="$PROJECT_DIR/backups"
  local timestamp=$(date +%Y%m%d_%H%M%S)
  storage_require_data_mount || {
    err "备份目录依赖 /data，未确认真实挂载，拒绝写入"
    return 1
  }
  mkdir -p "$backup_dir"

  log "备份 SQLite 数据库（WAL 在线备份）..."
  backup_sqlite_wal "$PROJECT_DIR/backend/data/interview-boss.db" "$backup_dir/interview-boss_${timestamp}.db"

  log "备份 Redis queue 数据（cache 为无持久化缓存，不备份）..."
  if [ -s "$PROJECT_DIR/backend/.redis-password" ]; then
    docker compose exec -T redis sh -c 'REDISCLI_AUTH="$(cat /run/secrets/redis_password)" redis-cli BGSAVE' >/dev/null 2>&1 || true
  else
    warn "Redis 密钥不存在，跳过 Redis BGSAVE"
  fi
  sleep 1
  docker cp "$(docker compose ps -q redis):/data/dump.rdb"      "$backup_dir/redis_${timestamp}.rdb" 2>/dev/null || warn "Redis 备份跳过"

  log "备份完成: $backup_dir/"
  storage_cleanup_backups "$PROJECT_DIR"
  ls -lh "$backup_dir/"*_"${timestamp}"* 2>/dev/null
}

# ── 恢复数据库 ──
# 从备份文件恢复 SQLite 数据库。与备份同规则命名（backups/interview-boss_<时间戳>.db）。
# 流程：先自动备份当前库再保险一次 → 停止 backend → 覆盖 DB 并清理 -wal/-shm → 启动 → 健康检查。
find_latest_backup() {
  local backup_dir="$PROJECT_DIR/backups"
  # 仅匹配 interview-boss_<时间戳>.db 格式，排除 redis 等其他备份
  ls -1t "$backup_dir"/interview-boss_*.db 2>/dev/null | head -1
}

do_restore() {
  local backup_path="${1:-}"
  local backup_dir="$PROJECT_DIR/backups"
  local db_path="$PROJECT_DIR/backend/data/interview-boss.db"
  local timestamp=$(date +%Y%m%d_%H%M%S)
  local safety_backup=""

  storage_require_data_mount || {
    err "恢复前安全备份依赖 /data，未确认真实挂载，拒绝恢复"
    return 1
  }

  if [ -n "$backup_path" ]; then
    backup_path="$(cd "$(dirname "$backup_path")" && pwd)/$(basename "$backup_path")"
    if [ ! -f "$backup_path" ]; then
      err "指定的备份文件不存在: $backup_path"
      exit 1
    fi
  else
    backup_path="$(find_latest_backup)"
    if [ -z "$backup_path" ]; then
      err "未找到可用备份（$backup_dir/interview-boss_*.db），请先运行 backup 命令"
      exit 1
    fi
  fi

  # 校验备份文件确实是有效 SQLite 数据库
  if ! head -c 16 "$backup_path" 2>/dev/null | strings | grep -q "SQLite"; then
    err "备份文件不是有效的 SQLite 数据库: $backup_path"
    exit 1
  fi

  warn "即将从备份恢复数据库: $backup_path"
  warn "  → 将覆盖当前数据库: $db_path"
  warn "  恢复前会先自动备份当前数据库（再次保险）。"

  # 自动再保险：恢复前备份当前库，避免恢复失败时丢失现有数据
  mkdir -p "$backup_dir"
  if [ -f "$db_path" ]; then
    safety_backup="$backup_dir/interview-boss_pre-restore_${timestamp}.db"
    log "恢复前自动备份当前数据库 -> $safety_backup"
    backup_sqlite_wal "$db_path" "$safety_backup" \
      || { err "恢复前备份当前数据库失败，已中止恢复"; exit 1; }
  else
    warn "当前数据库文件不存在（首次部署？），跳过恢复前备份"
  fi

  check_docker

  # 1. 停止 backend 容器（避免运行中写入/覆盖数据库）
  log "停止 backend 容器..."
  docker compose stop --timeout 30 backend 2>/dev/null || true

  # 2. 覆盖数据库并清理 WAL 相关文件
  log "覆盖数据库并清理 -wal/-shm 残留..."
  rm -f "$db_path-wal" "$db_path-shm"
  cp "$backup_path" "$db_path"

  # 3. 启动 backend（等待健康检查），确保依赖的基础设施也在运行
  log "启动 backend（等待健康检查）..."
  if ! docker compose up -d --no-deps --wait --wait-timeout 60 redis redis-cache backend nginx oauth-gateway; then
    err "backend 在 60s 内未通过健康检查"
    docker compose ps
    warn "恢复操作未完全成功；请检查容器状态。可用以下命令回滚到恢复前的库："
    [ -n "$safety_backup" ] && warn "  cp '$safety_backup' '$db_path' && $0 restart"
    exit 1
  fi

  log "数据库恢复完成: $(basename "$backup_path")"
  storage_cleanup_backups "$PROJECT_DIR"
  if [ -n "$safety_backup" ]; then
    log "恢复前备份保留在: $safety_backup（确认无误后可删除）"
  fi
  do_status
}

# 恢复演练（不触碰生产库）：把备份恢复到临时副本并做完整性/一致性校验。
# audit 2026-08-24 P3：备份此前从未被验证可恢复。全量切换仍走 do_restore。
do_restore_verify() {
  local backup_path="${1:-}"
  local backup_dir="$PROJECT_DIR/backups"
  if [ -z "$backup_path" ]; then
    backup_path="$(find_latest_backup)"
    if [ -z "$backup_path" ]; then
      err "未找到可用备份（$backup_dir/interview-boss_*.db），请先运行 backup 命令"
      exit 1
    fi
    log "使用最新备份: $backup_path"
  fi
  [ -f "$backup_path" ] || { err "备份文件不存在: $backup_path"; exit 1; }

  local tmp="/tmp/interview-boss-restore-drill-$(date +%Y%m%d_%H%M%S).db"
  cp "$backup_path" "$tmp"

  command -v python3 >/dev/null 2>&1 || { err "宿主机缺少 python3/sqlite3，无法演练"; rm -f "$tmp"; exit 1; }
  log "[1/3] integrity_check ..."
  local out
  out=$(python3 - "$tmp" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1])
integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
if integrity != "ok":
    print(f"INTEGRITY_FAIL:{integrity}")
    sys.exit(0)
fk = len(conn.execute("PRAGMA foreign_key_check").fetchall())
counts = {
    "users": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
    "question_bank": conn.execute("SELECT COUNT(*) FROM question_bank WHERE deleted_at IS NULL").fetchone()[0],
    "interview": conn.execute("SELECT COUNT(*) FROM interview WHERE deleted_at IS NULL").fetchone()[0],
}
print(f"OK fk_violations={fk} users={counts['users']} question_bank_active={counts['question_bank']} interview_active={counts['interview']}")
PY
)
  echo "  $out"
  case "$out" in
    OK*)
      local fk=$(echo "$out" | sed -E 's/.*fk_violations=([0-9]+).*/\1/')
      [ "$fk" -ne 0 ] && warn "发现 $fk 行 FK 违规（不阻断演练，但应排查）"
      local users=$(echo "$out" | sed -E 's/.*users=([0-9]+).*/\1/')
      [ "$users" -eq 0 ] && { err "users 表为空，备份疑似损坏"; rm -f "$tmp"; exit 1; }
      ;;
    *)
      err "integrity_check 失败: $out"; rm -f "$tmp"; exit 1 ;;
  esac

  rm -f "$tmp"
  log "恢复演练 PASS：$(basename "$backup_path") 可正常恢复（临时副本已清理）"
}

# ── 运行测试 ──
do_test() {
  EPHEMERAL_TEST_PROJECT="interview-boss-test-${BASHPID}-$(date +%s)"
  EPHEMERAL_TEST_TAG="$(current_test_tag)"
  trap cleanup_ephemeral_test EXIT
  trap 'cleanup_ephemeral_test; exit 130' INT TERM

  log "构建测试镜像（tag=interview-boss-test:$EPHEMERAL_TEST_TAG, project=$EPHEMERAL_TEST_PROJECT）..."
  guarded_compose_build_project "$EPHEMERAL_TEST_PROJECT" test
  log "运行 pytest..."
  INTERVIEW_BOSS_TEST_TAG="$EPHEMERAL_TEST_TAG" \
    docker compose --project-name "$EPHEMERAL_TEST_PROJECT" --profile test \
    run --rm test uv run pytest backend/tests/ "$@"
  cleanup_ephemeral_test
  trap - EXIT INT TERM
}

# ── 运行日常质量门禁 ──
do_check() {
  "$PROJECT_DIR/scripts/check.sh" "$@"
}

# ── 检查磁盘和 /data 挂载 ──
do_storage_check() {
  local free_mb
  free_mb=$(root_free_mb)
  log "根分区可用空间: ${free_mb}MB"
  df -hT / /data 2>/dev/null || df -hT /

  if storage_data_mount_available; then
    log "/data 真实挂载信息："
    findmnt -M /data -o TARGET,SOURCE,FSTYPE,OPTIONS
    return 0
  fi

  warn "/data 未检测到真实挂载；禁止向 /data-backed 缓存/备份路径写入"
  return 1
}

# ── 诊断磁盘使用 ──
do_diagnose() {
  log "========== 磁盘诊断 =========="
  echo ""
  do_storage_check || true
  echo ""
  log "Docker 系统资源："
  docker system df 2>/dev/null || true
  echo ""
  log "宿主机大文件目录："
  local pdir="$PROJECT_DIR"
  du -sh "$pdir/frontend/node_modules" 2>/dev/null && true
  du -sh "$pdir/backend/.venv"         2>/dev/null && true
  du -sh "$pdir/frontend/dist"         2>/dev/null && true
  du -sh "$pdir/backups"               2>/dev/null && true
  du -sh "${PROJECT_ARCHIVE_DIR:-/data/projects/archive}" 2>/dev/null && true
  du -sh "$pdir/backend/data/backups"  2>/dev/null && true
  du -sh "$pdir/backend/data/evaluations" 2>/dev/null && true
  log "  （以上目录由宿主机管理，非 Docker volume）"
  echo ""
  log "Docker BuildKit 缓存："
  if docker buildx inspect "$BUILDKIT_BUILDER" >/dev/null 2>&1; then
    docker buildx du --builder "$BUILDKIT_BUILDER" 2>/dev/null || true
  else
    log "  InterviewBoss 专用 builder 尚未创建"
  fi
  echo ""
  log "阈值设置（当前值 / 默认值）："
  log "  DEPLOY_HARD_MIN_FREE_MB:  $DEPLOY_HARD_MIN_FREE_MB / 6144"
  log "  DEPLOY_TARGET_FREE_MB:    $DEPLOY_TARGET_FREE_MB / 8192"
  log "  BUILDKIT_MAX_USED_SPACE:  $BUILDKIT_MAX_USED_SPACE / 1536MB"
  log "  BUILDKIT_CACHE_MAX_AGE:   $BUILDKIT_CACHE_MAX_AGE / 168h"
  log "  BUILDKIT_BUILDER:          $BUILDKIT_BUILDER ($BUILDKIT_BUILDER_DRIVER)"
  log "  BACKUP_RETENTION_DAYS:    $BACKUP_RETENTION_DAYS / 7"
  log "  BACKUP_MIN_KEEP_FILES:    $BACKUP_MIN_KEEP_FILES / 3"
  echo ""
  log "========== 诊断完成 =========="
}

# ── 定时存储维护 ──
do_maintenance() {
  local mount_rc=0
  local free_mb
  log "执行 InterviewBoss 存储维护（备份、测试资源、BuildKit 缓存）..."
  do_storage_check || mount_rc=1
  storage_cleanup_backups "$PROJECT_DIR"
  free_mb=$(root_free_mb)
  if [ "$free_mb" -lt "$DEPLOY_HARD_MIN_FREE_MB" ]; then
    warn "维护开始时已低于硬阈值，允许回收可重建的 node_modules/.venv"
    SKIP_BUILDKIT_CLEANUP=1 prune_unused_docker --aggressive
  else
    SKIP_BUILDKIT_CLEANUP=1 prune_unused_docker
  fi
  if ! prune_build_cache light; then
    err "定时 BuildKit 过期缓存维护失败"
    return 1
  fi
  free_mb=$(root_free_mb)
  if [ "$free_mb" -lt "$DEPLOY_HARD_MIN_FREE_MB" ]; then
    if ! prune_build_cache aggressive; then
      err "定时应急 BuildKit 缓存维护失败"
      return 1
    fi
  fi
  show_disk_usage

  free_mb=$(root_free_mb)
  if [ "$free_mb" -lt "$DEPLOY_HARD_MIN_FREE_MB" ]; then
    err "维护后根分区仍只有 ${free_mb}MB，低于硬阈值 ${DEPLOY_HARD_MIN_FREE_MB}MB"
    return 1
  fi
  if [ "$mount_rc" -ne 0 ]; then
    err "/data 未挂载，维护已跳过 /data-backed 备份清理"
    return 1
  fi
  log "存储维护完成: ${free_mb}MB 可用"
}

# ── 手动清理旧资源 ──
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
    log "dry-run 模式：输出清理计划，不执行删除或 BuildKit prune"
    STORAGE_RETENTION_DRY_RUN=1 storage_cleanup_backups "$PROJECT_DIR"
    STORAGE_RETENTION_DRY_RUN=1 prune_unused_docker "$aggressive"
    do_diagnose
    return
  fi

  log "清理本项目资源（多项目安全）..."
  storage_cleanup_backups "$PROJECT_DIR"
  prune_unused_docker "$aggressive"
  if ! prune_build_cache light; then
    err "定向 BuildKit 过期缓存清理失败"
    return 1
  fi
  show_disk_usage
  log "清理完成"
}

# ── 镜像源刷新（显式维护命令）──
do_mirrors() {
  log "清除镜像源缓存并重新测速（包含 Docker Hub registry mirror 配置）..."
  clear_mirror_cache
  ensure_docker_dns_config
  DEPLOY_SELECT_MIRRORS_ON_BUILD=1 select_mirrors
  log "镜像源刷新完成；后续 build/update 将复用缓存源，除非健康检查失败"
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
  diagnose|mirrors|migrate|cleanup|maintenance|storage-check|storage-maintenance|help|--help|-h) ;;
  *) ensure_runtime_secrets ;;
esac

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
  eval-worker-install) check_docker; do_eval_worker_install ;;
  eval-worker-status)  check_docker; do_eval_worker_status ;;
  test)            check_docker; do_test "${@:2}" ;;
  check)           check_docker; do_check "${@:2}" ;;
  backup)          check_docker; do_backup ;;
  restore)
    if [ "${2:-}" = "--verify" ]; then
      do_restore_verify "${3:-}"
    else
      check_docker; do_restore "${2:-}"
    fi ;;

  cleanup)         check_docker; do_cleanup "${@:2}" ;;
  maintenance)     check_docker; do_maintenance ;;
  storage-check)   do_storage_check ;;
  storage-maintenance) check_docker; do_maintenance ;;
  diagnose)        do_diagnose ;;
  mirrors)         check_docker; do_mirrors ;;
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
  echo "  eval-worker-install 安装并启用 Eval Worker systemd timer"
  echo "  eval-worker-status  查看 timer、容器、队列与 heartbeat 状态"
    echo "  test            运行 pytest 测试（可传入 pytest 参数）"
    echo "  check [backend|frontend|audit]  运行日常质量门禁（audit 只报告不拦截）"
    echo "  backup          备份数据库和 Redis 数据"
    echo "  restore [备份路径]  从备份恢复数据库（缺省用最新备份；恢复前自动再备份当前库）"
  echo "  restore --verify [备份路径]  恢复演练：临时副本校验，不触碰生产库"
    echo "  cleanup [--dry-run] [--aggressive]  清理本项目资源（不影响其他项目）"
    echo "  storage-check   只检查根盘空间和 /data 是否真实挂载"
    echo "  storage-maintenance  执行定时清理：备份、测试资源和 BuildKit 缓存"
    echo "  maintenance     storage-maintenance 的兼容别名"
    echo "  diagnose        输出磁盘/资源诊断信息（不修改任何资源）"
    echo "  mirrors         强制刷新镜像源缓存和 Docker Hub registry mirror"
    echo "  migrate         停止宿主机服务（首次迁移用）"
    echo "  all             构建 + 启动核心服务（首次部署）"
    echo ""
    echo "示例:"
    echo "  ./docker-deploy.sh all"
    echo "  ./docker-deploy.sh update"
    echo "  ./docker-deploy.sh worker-up"
    echo "  ./docker-deploy.sh test"
    echo "  ./docker-deploy.sh test -k test_login"
    echo "  ./docker-deploy.sh check"
    echo "  ./docker-deploy.sh check backend"
    echo "  ./docker-deploy.sh logs backend"
    echo "  ./docker-deploy.sh mirrors"
    ;;
esac
