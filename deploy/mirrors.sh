#!/bin/bash
# 智能镜像源选择系统 v2
# 用法: source deploy/mirrors.sh && select_mirrors
#
# 功能:
#   1. 维护 5 类镜像源候选池（Docker Hub / npm / PyPI / Debian apt / Alpine apk）
#   2. 构建前并行测速，选最优源（结果缓存 24h）
#   3. 更新 daemon.json + buildkitd.toml 的 Docker Hub 镜像
#   4. 实际 pull 验证选出的源可用
#   5. 导出 NPM_MIRROR / PYPI_MIRROR / APT_MIRROR / APK_MIRROR 环境变量

set -euo pipefail

# log/warn/err 函数（如果未从 docker-deploy.sh 继承，则定义 fallback）
if ! declare -f log &>/dev/null; then
  GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
  log()  { echo -e "${GREEN}[INFO]${NC} $1"; }
  warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
  err()  { echo -e "${RED}[ERROR]${NC} $1"; }
fi

# ── 配置 ──

MIRROR_CACHE_VERSION="${MIRROR_CACHE_VERSION:-v2}"
MIRROR_CACHE_DIR="${MIRROR_CACHE_DIR:-/tmp/interview-boss-mirrors-${MIRROR_CACHE_VERSION}}"
MIRROR_CACHE_TTL="${MIRROR_CACHE_TTL:-86400}"  # 24h

# ── 镜像源候选池 ──

DOCKER_HUB_MIRRORS=(
  "https://docker.m.daocloud.io"
  "https://docker.1ms.run"
  "https://docker.xuanyuan.me"
  "https://dockerpull.org"
  "https://dockerhub.icu"
  "https://docker.rainbond.cc"
)

NPM_MIRRORS=(
  "https://registry.npmmirror.com"
  "https://registry.npmmirror.cn"
  "https://mirrors.cloud.tencent.com/npm/"
  "https://mirrors.huaweicloud.com/repository/npm/"
)

PYPI_MIRRORS=(
  "https://mirrors.cloud.tencent.com/pypi/simple/"
  "https://mirrors.aliyun.com/pypi/simple/"
  "https://pypi.tuna.tsinghua.edu.cn/simple/"
  "https://mirrors.huaweicloud.com/repository/pypi/simple/"
  "https://pypi.mirrors.ustc.edu.cn/simple/"
)

APT_MIRRORS=(
  "mirrors.aliyun.com"
  "mirrors.tuna.tsinghua.edu.cn"
  "mirrors.cloud.tencent.com"
  "mirrors.huaweicloud.com"
  "mirrors.ustc.edu.cn"
)

APK_MIRRORS=(
  "mirrors.aliyun.com"
  "mirrors.tuna.tsinghua.edu.cn"
  "mirrors.cloud.tencent.com"
  "mirrors.huaweicloud.com"
  "mirrors.ustc.edu.cn"
)

# ── 缓存函数 ──

# 从缓存读取测速结果
# 参数: $1=缓存 key
# 输出: 缓存的值（过期或不存在返回空）
cache_get() {
  local key="$1"
  local cache_file="$MIRROR_CACHE_DIR/$key"
  if [ -f "$cache_file" ]; then
    local age
    age=$(( $(date +%s) - $(stat -c %Y "$cache_file" 2>/dev/null || echo 0) ))
    if [ "$age" -lt "$MIRROR_CACHE_TTL" ]; then
      cat "$cache_file"
      return 0
    fi
    rm -f "$cache_file"
  fi
  return 1
}

# 写入缓存
# 参数: $1=缓存 key  $2=值
cache_set() {
  local key="$1"
  local value="$2"
  mkdir -p "$MIRROR_CACHE_DIR"
  echo "$value" > "$MIRROR_CACHE_DIR/$key"
}

cache_delete() {
  local key="$1"
  rm -f "$MIRROR_CACHE_DIR/$key" 2>/dev/null || true
}

# ── 测速函数 ──

# 测试单个镜像源的响应时间
# 参数: $1=URL  $2=超时秒数（默认5）
# 输出: 延迟秒数（浮点），失败返回 999
test_mirror_speed() {
  local url="$1"
  local timeout="${2:-5}"
  local time_total

  time_total=$(curl -sS -o /dev/null \
    -w "%{time_total}" \
    --connect-timeout 3 \
    --max-time "$timeout" \
    -H "Accept: */*" \
    "$url" 2>/dev/null) || time_total="999"

  # 验证是数字
  if [[ "$time_total" =~ ^[0-9]+\.?[0-9]*$ ]]; then
    echo "$time_total"
  else
    echo "999"
  fi
}

# 并行测速多个源，返回按延迟排序的结果
# 参数: $1=测试路径后缀  $2=超时秒数  $3...=镜像URL列表
# 输出: 每行 "延迟 URL"，按延迟升序
test_mirrors_parallel() {
  local test_suffix="$1"
  local timeout="$2"
  shift 2
  local mirrors=("$@")

  local tmpdir
  tmpdir=$(mktemp -d)
  local pids=()

  for i in "${!mirrors[@]}"; do
    local url="${mirrors[$i]}"
    local test_url="${url%/}${test_suffix}"
    (
      local t
      t=$(test_mirror_speed "$test_url" "$timeout")
      echo "$t $url" > "$tmpdir/result_$i"
    ) &>/dev/null &
    pids+=($!)
  done

  # 等待所有测速完成（带整体超时）
  local overall_timeout=$((timeout + 5))
  local elapsed=0
  while kill -0 "${pids[@]}" 2>/dev/null; do
    sleep 0.2
    elapsed=$((elapsed + 1))
    if [ "$elapsed" -gt $((overall_timeout * 5)) ]; then
      kill "${pids[@]}" 2>/dev/null || true
      break
    fi
  done
  wait 2>/dev/null || true

  # 收集结果并排序
  local results=()
  for f in "$tmpdir"/result_*; do
    [ -f "$f" ] && results+=("$(cat "$f")")
  done
  rm -rf "$tmpdir"

  printf '%s\n' "${results[@]}" | sort -n
}

# 从候选池中选出最快的镜像源（带缓存）
# 参数: $1=缓存 key  $2=测试路径后缀  $3=超时秒数  $4...=镜像URL列表
# 输出: 最快的镜像URL（stdout）
pick_fastest() {
  local cache_key="$1"
  local test_suffix="$2"
  local timeout="$3"
  shift 3
  local mirrors=("$@")

  # 尝试从缓存读取
  local cached
  if cached=$(cache_get "$cache_key"); then
    echo "$cached"
    return 0
  fi

  local sorted
  sorted=$(test_mirrors_parallel "$test_suffix" "$timeout" "${mirrors[@]}")

  # 过滤掉超时/失败的（延迟 >= 999），取第一个
  local best
  best=$(echo "$sorted" | awk '$1 < 999 {print $2; exit}')

  if [ -z "$best" ]; then
    best="${mirrors[0]}"
  fi

  # 写入缓存
  cache_set "$cache_key" "$best"
  echo "$best"
}

# 读取缓存中的 package manager 镜像源；缓存缺失时使用稳定默认值。
# 这个函数不测速、不写 Docker daemon，适合每次 build 前调用以保持 layer cache key 稳定。
load_cached_package_mirrors() {
  NPM_MIRROR=$(cache_get "npm" 2>/dev/null || echo "${NPM_MIRRORS[0]}")
  PYPI_MIRROR=$(cache_get "pypi" 2>/dev/null || echo "${PYPI_MIRRORS[0]}")
  APT_MIRROR=$(cache_get "apt" 2>/dev/null || echo "${APT_MIRRORS[0]}")
  APK_MIRROR=$(cache_get "apk" 2>/dev/null || echo "${APK_MIRRORS[0]}")
  export NPM_MIRROR PYPI_MIRROR APT_MIRROR APK_MIRROR
}

# 快速健康检查当前 package manager 镜像源。
# 只检查 Dockerfile 真正会用到的 npm / PyPI / apt，避免每次 build 做完整测速。
check_package_mirrors_healthy() {
  local timeout="${1:-2}"
  local failed=0
  local npm_url="${NPM_MIRROR%/}/"
  local pypi_url="${PYPI_MIRROR%/}/pip/"
  local apt_url="http://${APT_MIRROR}/debian/dists/bookworm/Release"
  local t

  t=$(test_mirror_speed "$npm_url" "$timeout")
  if awk "BEGIN {exit !($t >= 999)}"; then
    warn "npm 镜像源健康检查失败: $NPM_MIRROR"
    failed=1
  fi

  t=$(test_mirror_speed "$pypi_url" "$timeout")
  if awk "BEGIN {exit !($t >= 999)}"; then
    warn "PyPI 镜像源健康检查失败: $PYPI_MIRROR"
    failed=1
  fi

  t=$(test_mirror_speed "$apt_url" "$timeout")
  if awk "BEGIN {exit !($t >= 999)}"; then
    warn "Debian apt 镜像源健康检查失败: $APT_MIRROR"
    failed=1
  fi

  [ "$failed" -eq 0 ]
}

select_package_mirrors() {
  NPM_MIRROR=$(pick_fastest "npm" "/" 5 "${NPM_MIRRORS[@]}")
  export NPM_MIRROR
  log "npm 镜像源: $NPM_MIRROR"

  PYPI_MIRROR=$(pick_fastest "pypi" "/simple/" 5 "${PYPI_MIRRORS[@]}")
  export PYPI_MIRROR
  log "PyPI 镜像源: $PYPI_MIRROR"

  APT_MIRROR=$(pick_fastest "apt" "/debian/dists/bookworm/Release" 5 "${APT_MIRRORS[@]}")
  export APT_MIRROR
  log "Debian apt 镜像源: $APT_MIRROR"

  APK_MIRROR=$(pick_fastest "apk" "/" 5 "${APK_MIRRORS[@]}")
  export APK_MIRROR
  log "Alpine apk 镜像源: $APK_MIRROR"
}

refresh_package_mirrors() {
  cache_delete "npm"
  cache_delete "pypi"
  cache_delete "apt"
  cache_delete "apk"
  select_package_mirrors
}

# 验证镜像源是否真的能拉到镜像
# 参数: $1=镜像源 URL  $2=测试镜像名（可选，默认 library/alpine:latest）
# 返回: 0=可用  1=不可用
verify_mirror_pull() {
  local mirror_url="$1"
  local test_image="${2:-library/alpine:latest}"
  local mirror_host
  mirror_host=$(echo "$mirror_url" | sed 's|https://||;s|/.*||')

  # 用 curl 检查 manifest 是否可获取（不需要真的 docker pull）
  local manifest_url="${mirror_url%/}/v2/${test_image}/manifests/latest"
  local http_code
  http_code=$(curl -sS -o /dev/null -w "%{http_code}" \
    --connect-timeout 5 --max-time 10 \
    -H "Accept: application/vnd.docker.distribution.manifest.v2+json" \
    "$manifest_url" 2>/dev/null) || http_code="000"

  # 200=直接可用, 401/403=需要认证(Docker daemon 自动处理), 3xx=重定向
  if [[ "$http_code" =~ ^(200|301|302|307|308|401|403)$ ]]; then
    return 0
  else
    return 1
  fi
}

# ── 配置文件更新 ──

# 已知被 Cloudflare 拦截或失效的源
get_blocked_sources() {
  echo "docker.xuanyuan.me"
}

# 备份配置文件（如果还没备份过）
backup_config() {
  local file="$1"
  if [ -f "$file" ] && [ ! -f "${file}.bak" ]; then
    sudo cp "$file" "${file}.bak"
    log "已备份 ${file} → ${file}.bak"
  fi
}

# 更新 Docker daemon.json 的 registry-mirrors
# 参数: $1=最佳镜像源URL
update_daemon_json_mirrors() {
  local best_mirror="$1"
  local daemon_json="/etc/docker/daemon.json"

  if [ ! -f "$daemon_json" ]; then
    warn "daemon.json 不存在，跳过更新"
    return 0
  fi

  if ! command -v jq &>/dev/null; then
    warn "jq 未安装，跳过 daemon.json 更新"
    return 0
  fi

  # 备份
  backup_config "$daemon_json"

  # 构建新的 mirrors 列表：最佳源放第一，去掉重复/被拦截源，末尾加官方回源
  local current_mirrors
  current_mirrors=$(jq -r '."registry-mirrors" // [] | .[]' "$daemon_json" 2>/dev/null || echo "")

  local blocked_sources
  blocked_sources=$(get_blocked_sources)

  local new_mirrors=("$best_mirror")
  while IFS= read -r mirror; do
    [ -z "$mirror" ] && continue
    [ "$mirror" = "$best_mirror" ] && continue
    # 跳过已知被拦截的源
    local blocked=false
    while IFS= read -r blocked_src; do
      if [[ "$mirror" == *"$blocked_src"* ]]; then
        blocked=true
        break
      fi
    done <<< "$blocked_sources"
    $blocked && continue
    new_mirrors+=("$mirror")
  done <<< "$current_mirrors"

  # 末尾加官方回源（如果列表里没有）
  local has_official=false
  for m in "${new_mirrors[@]}"; do
    [[ "$m" == *"registry-1.docker.io"* ]] && has_official=true
  done
  if ! $has_official; then
    new_mirrors+=("https://registry-1.docker.io")
  fi

  # 写入
  local mirrors_json
  mirrors_json=$(printf '%s\n' "${new_mirrors[@]}" | jq -R . | jq -s .)

  local tmp_json
  tmp_json=$(mktemp)
  jq --argjson mirrors "$mirrors_json" '."registry-mirrors" = $mirrors' "$daemon_json" > "$tmp_json"

  if ! diff -q "$daemon_json" "$tmp_json" >/dev/null 2>&1; then
    sudo cp "$tmp_json" "$daemon_json"
    log "daemon.json 已更新，重载 Docker daemon..."
    sudo systemctl reload docker 2>/dev/null || sudo systemctl restart docker 2>/dev/null || warn "Docker daemon 重载失败，可能需要手动重启"
  else
    log "daemon.json 无需变更"
  fi
  rm -f "$tmp_json"
}

# 更新 BuildKit 配置 (/etc/buildkitd.toml)
# 参数: $1=最佳镜像源URL列表（逗号分隔）
update_buildkit_config() {
  local mirrors_csv="$1"
  local buildkitd_toml="/etc/buildkitd.toml"

  # 在 DOCKER_BUILDKIT=1 模式下（daemon 内置 BuildKit），daemon.json 的 registry-mirrors
  # 已经对构建生效。/etc/buildkitd.toml 只在 docker-container driver（独立 BuildKit）才需要。
  # 检查是否存在 buildx builder 使用 docker-container driver
  local buildx_output
  buildx_output=$(docker buildx inspect 2>/dev/null || true)
  if ! echo "$buildx_output" | grep -q "docker-container"; then
    log "BuildKit 使用 daemon 内置模式，已通过 daemon.json 配置镜像加速"
    return 0
  fi

  # 备份
  backup_config "$buildkitd_toml"

  # 生成 mirrors 数组
  local mirrors_toml=""
  IFS=',' read -ra mirror_arr <<< "$mirrors_csv"
  for m in "${mirror_arr[@]}"; do
    mirrors_toml+="  \"${m}\",\n"
  done

  local tmp_toml
  tmp_toml=$(mktemp)
  cat > "$tmp_toml" << EOF
# BuildKit 镜像加速配置（由 deploy/mirrors.sh 自动生成）
# 官方文档: https://docs.docker.com/build/buildkit/configure/

debug = false

[registry."docker.io"]
  mirrors = [
$(echo -e "$mirrors_toml" | sed '$ s/,$//')
  ]
EOF

  # 比较是否有变化
  if [ -f "$buildkitd_toml" ] && diff -q "$buildkitd_toml" "$tmp_toml" >/dev/null 2>&1; then
    log "buildkitd.toml 无需变更"
    rm -f "$tmp_toml"
  else
    sudo cp "$tmp_toml" "$buildkitd_toml"
    log "buildkitd.toml 已更新"
    rm -f "$tmp_toml"
  fi
}

# ── 主入口 ──

# 测速选择所有镜像源并导出环境变量
# 使用: select_mirrors
# 副作用: 导出 NPM_MIRROR, PYPI_MIRROR, APT_MIRROR, APK_MIRROR 环境变量
#         更新 /etc/docker/daemon.json + /etc/buildkitd.toml
select_mirrors() {
  log "测速选择最优镜像源..."

  # Docker Hub 镜像源
  local best_docker_hub
  best_docker_hub=$(pick_fastest "docker-hub" "/v2/" 5 "${DOCKER_HUB_MIRRORS[@]}")

  # 验证选出的源真的能用
  if ! verify_mirror_pull "$best_docker_hub"; then
    warn "最快源 $best_docker_hub pull 验证失败，尝试备选..."
    # 从候选池中找下一个能用的
    for candidate in "${DOCKER_HUB_MIRRORS[@]}"; do
      [ "$candidate" = "$best_docker_hub" ] && continue
      if verify_mirror_pull "$candidate"; then
        best_docker_hub="$candidate"
        cache_set "docker-hub" "$best_docker_hub"
        break
      fi
    done
  fi

  # 更新 daemon.json + buildkitd.toml
  update_daemon_json_mirrors "$best_docker_hub"
  update_buildkit_config "$best_docker_hub"
  log "Docker Hub 镜像源: $best_docker_hub"

  # package manager 镜像源
  select_package_mirrors

  log "镜像源测速完成"
}

# 清除测速缓存
# 使用: clear_mirror_cache
clear_mirror_cache() {
  if [ -d "$MIRROR_CACHE_DIR" ]; then
    rm -rf "$MIRROR_CACHE_DIR"
    log "镜像源缓存已清除"
  fi
}

# 恢复配置文件备份
# 使用: restore_mirror_configs
restore_mirror_configs() {
  local restored=0
  for f in /etc/docker/daemon.json /etc/buildkitd.toml; do
    if [ -f "${f}.bak" ]; then
      sudo cp "${f}.bak" "$f"
      log "已恢复 ${f}"
      restored=$((restored + 1))
    fi
  done
  if [ "$restored" -eq 0 ]; then
    warn "没有找到备份文件"
  fi
}
