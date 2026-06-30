#!/bin/bash
# 智能镜像源选择系统
# 用法: source deploy/mirrors.sh && select_mirrors
#
# 功能:
#   1. 维护 4 类镜像源候选池（Docker Hub / npm / PyPI / Debian apt）
#   2. 构建前并行测速，选最优源
#   3. 更新 daemon.json 的 Docker Hub 镜像（去掉被拦截的源）
#   4. 导出 NPM_MIRROR / PYPI_MIRROR / APT_MIRROR 环境变量供 docker-compose 使用

set -euo pipefail

# log/warn 函数（如果未从 docker-deploy.sh 继承，则定义 fallback）
if ! declare -f log &>/dev/null; then
  GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
  log()  { echo -e "${GREEN}[INFO]${NC} $1"; }
  warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
fi

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
  "https://mirrors.aliyun.com/pypi/simple/"
  "https://pypi.tuna.tsinghua.edu.cn/simple/"
  "https://mirrors.cloud.tencent.com/pypi/simple/"
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
    # 拼接测试 URL：去掉末尾 /，加上测试后缀
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

  # 按延迟排序输出
  printf '%s\n' "${results[@]}" | sort -n
}

# 从候选池中选出最快的镜像源
# 参数: $1=测试路径后缀  $2=超时秒数  $3...=镜像URL列表
# 输出: 最快的镜像URL（stdout），失败返回空
pick_fastest() {
  local test_suffix="$1"
  local timeout="$2"
  shift 2
  local mirrors=("$@")

  local sorted
  sorted=$(test_mirrors_parallel "$test_suffix" "$timeout" "${mirrors[@]}")

  # 过滤掉超时/失败的（延迟 >= 999），取第一个
  local best
  best=$(echo "$sorted" | awk '$1 < 999 {print $2; exit}')

  if [ -n "$best" ]; then
    echo "$best"
  else
    # 所有源都失败，返回第一个候选作为 fallback
    echo "${mirrors[0]}"
  fi
}

# ── daemon.json 更新 ──

# 更新 Docker daemon.json 的 registry-mirrors
# 参数: $1=最佳镜像源URL
update_daemon_json_mirrors() {
  local best_mirror="$1"
  local daemon_json="/etc/docker/daemon.json"

  if [ ! -f "$daemon_json" ]; then
    warn "daemon.json 不存在，跳过更新"
    return 0
  fi

  # 检查是否有 jq
  if ! command -v jq &>/dev/null; then
    warn "jq 未安装，跳过 daemon.json 更新"
    return 0
  fi

  # 构建新的 mirrors 列表：最佳源放第一位，其余保留（去掉重复和已知被拦截的源）
  local current_mirrors
  current_mirrors=$(jq -r '."registry-mirrors" // [] | .[]' "$daemon_json" 2>/dev/null || echo "")

  # 已知被 Cloudflare 拦截的源
  local blocked_sources=("docker.xuanyuan.me")

  local new_mirrors=("$best_mirror")
  while IFS= read -r mirror; do
    [ -z "$mirror" ] && continue
    # 跳过已添加的最佳源
    [ "$mirror" = "$best_mirror" ] && continue
    # 跳过已知被拦截的源
    local blocked=false
    for blocked_src in "${blocked_sources[@]}"; do
      if [[ "$mirror" == *"$blocked_src"* ]]; then
        blocked=true
        break
      fi
    done
    $blocked && continue
    new_mirrors+=("$mirror")
  done <<< "$current_mirrors"

  # 写入 daemon.json
  local mirrors_json
  mirrors_json=$(printf '%s\n' "${new_mirrors[@]}" | jq -R . | jq -s .)

  local tmp_json
  tmp_json=$(mktemp)
  jq --argjson mirrors "$mirrors_json" '."registry-mirrors" = $mirrors' "$daemon_json" > "$tmp_json"

  # 比较是否有变化
  if ! diff -q "$daemon_json" "$tmp_json" >/dev/null 2>&1; then
    sudo cp "$tmp_json" "$daemon_json"
    log "daemon.json 已更新，重载 Docker daemon..."
    sudo systemctl reload docker 2>/dev/null || sudo systemctl restart docker 2>/dev/null || warn "Docker daemon 重载失败，可能需要手动重启"
  else
    log "daemon.json 无需变更"
  fi
  rm -f "$tmp_json"
}

# ── 主入口 ──

# 测速选择所有镜像源并导出环境变量
# 使用: select_mirrors
# 副作用: 导出 NPM_MIRROR, PYPI_MIRROR, APT_MIRROR 环境变量
#         更新 /etc/docker/daemon.json（需要 sudo 权限）
select_mirrors() {
  log "测速选择最优镜像源..."

  # Docker Hub 镜像源 → 更新 daemon.json
  local best_docker_hub
  best_docker_hub=$(pick_fastest "/v2/" 5 "${DOCKER_HUB_MIRRORS[@]}")
  if [ -n "$best_docker_hub" ]; then
    update_daemon_json_mirrors "$best_docker_hub"
    log "Docker Hub 镜像源: $best_docker_hub"
  fi

  # npm 镜像源
  NPM_MIRROR=$(pick_fastest "/" 5 "${NPM_MIRRORS[@]}")
  export NPM_MIRROR
  log "npm 镜像源: $NPM_MIRROR"

  # PyPI 镜像源（测试 /simple/ 路径）
  PYPI_MIRROR=$(pick_fastest "/simple/" 5 "${PYPI_MIRRORS[@]}")
  export PYPI_MIRROR
  log "PyPI 镜像源: $PYPI_MIRROR"

  # Debian apt 镜像源（测试 HTTP 根路径）
  APT_MIRROR=$(pick_fastest "/" 5 "${APT_MIRRORS[@]}")
  export APT_MIRROR
  log "Debian apt 镜像源: $APT_MIRROR"

  log "镜像源测速完成"
}
