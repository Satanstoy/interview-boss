#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="${FRONTEND_DEPS_PROJECT_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
FRONTEND_DIR="$PROJECT_DIR/frontend"
CACHE_DIR="${FRONTEND_DEPS_CACHE_DIR:-/data/home/ubuntu/cache/interview-boss/frontend-deps}"
NPM_CACHE_DIR="${NPM_CONFIG_CACHE:-/data/home/ubuntu/npm}"
MIN_ROOT_FREE_MB="${FRONTEND_DEPS_MIN_ROOT_FREE_MB:-1024}"
MIN_CACHE_FREE_MB="${FRONTEND_DEPS_MIN_CACHE_FREE_MB:-1024}"
MAX_VERSIONS="${FRONTEND_DEPS_MAX_VERSIONS:-1}"

fail() {
  echo "[frontend-deps] ERROR: $*" >&2
  exit 1
}

require_file() {
  [ -f "$1" ] || fail "缺少文件: $1"
}

cleanup_directory() {
  local directory="$1"
  [ -d "$directory" ] || return 0
  find "$directory" -depth -mindepth 1 -delete
  rmdir "$directory"
}

require_file "$FRONTEND_DIR/package.json"
require_file "$FRONTEND_DIR/package-lock.json"
command -v sha256sum >/dev/null 2>&1 || fail "需要 sha256sum"
command -v npm >/dev/null 2>&1 || fail "需要 npm"
command -v flock >/dev/null 2>&1 || fail "需要 flock"

free_mb() {
  df -Pm "$1" | awk 'NR == 2 { print $4 }'
}

root_free_mb=$(free_mb "$PROJECT_DIR")
[ "${root_free_mb:-0}" -ge "$MIN_ROOT_FREE_MB" ] || \
  fail "根分区剩余 ${root_free_mb:-0}MB，低于前端依赖安装下限 ${MIN_ROOT_FREE_MB}MB"

command -v findmnt >/dev/null 2>&1 || fail "需要 findmnt 来确认 /data 挂载"
cache_source=$(findmnt -no SOURCE --target "$CACHE_DIR" 2>/dev/null || true)
case "$cache_source" in
  ''|/|/dev/vda*)
    fail "共享前端依赖缓存必须位于独立数据盘: $CACHE_DIR"
    ;;
esac

mkdir -p "$CACHE_DIR"

cache_parent=$(dirname "$CACHE_DIR")
cache_free_mb=$(free_mb "$cache_parent")
[ "${cache_free_mb:-0}" -ge "$MIN_CACHE_FREE_MB" ] || \
  fail "共享缓存所在分区剩余 ${cache_free_mb:-0}MB，低于安装下限 ${MIN_CACHE_FREE_MB}MB"

[[ "$MAX_VERSIONS" =~ ^[1-9][0-9]*$ ]] || fail "FRONTEND_DEPS_MAX_VERSIONS 必须是正整数: $MAX_VERSIONS"

dependency_key=$(cd "$FRONTEND_DIR" && sha256sum package.json package-lock.json | sha256sum | cut -c1-24)
install_root="$CACHE_DIR/$dependency_key"
node_modules_dir="$install_root/node_modules"
marker="$install_root/.interview-boss-dependency-key"
lock_file="$CACHE_DIR/.install.lock"

exec 9>"$lock_file"
flock 9

if [ -e "$install_root" ] && [ ! -f "$marker" ]; then
  fail "共享依赖目录不是由本脚本创建，拒绝覆盖: $install_root"
fi

if [ -e "$install_root" ]; then
  [ -f "$marker" ] || fail "共享依赖目录状态异常，拒绝覆盖: $install_root"
  [ -x "$node_modules_dir/.bin/playwright" ] || fail "共享依赖目录不完整，拒绝覆盖: $install_root"
fi

if [ ! -f "$marker" ]; then
  temporary_root=$(mktemp -d "$CACHE_DIR/.install-${dependency_key}.XXXXXX")
  install_failed=1
  trap 'if [ "${install_failed:-1}" -ne 0 ]; then cleanup_directory "$temporary_root" 2>/dev/null || true; fi' EXIT

  cp "$FRONTEND_DIR/package.json" "$temporary_root/package.json"
  cp "$FRONTEND_DIR/package-lock.json" "$temporary_root/package-lock.json"
  (
    cd "$temporary_root"
    npm ci \
      --cache "$NPM_CACHE_DIR" \
      --prefer-offline \
      --no-audit \
      --no-fund
  )

  printf '%s\n' "$dependency_key" > "$temporary_root/.interview-boss-dependency-key"
  mv "$temporary_root" "$install_root"
  install_failed=0
  trap - EXIT
fi

actual_key=$(cat "$marker")
[ "$actual_key" = "$dependency_key" ] || fail "共享依赖 lockfile 不匹配: $install_root"
[ -x "$node_modules_dir/.bin/playwright" ] || fail "共享依赖缺少本地 Playwright: $node_modules_dir"

worktree_node_modules="$FRONTEND_DIR/node_modules"
if [ -L "$worktree_node_modules" ]; then
  current_target=$(readlink -f "$worktree_node_modules")
  [ "$current_target" = "$node_modules_dir" ] || {
    unlink "$worktree_node_modules"
    ln -s "$node_modules_dir" "$worktree_node_modules"
  }
elif [ -e "$worktree_node_modules" ]; then
  fail "当前 worktree 已有实际 node_modules，拒绝覆盖: $worktree_node_modules"
else
  ln -s "$node_modules_dir" "$worktree_node_modules"
fi

# 保留其他工作树引用的缓存；未使用版本按 MAX_VERSIONS 收敛，避免依赖升级/切换
# 分支都在 /data 上累积一整份 node_modules；Playwright 浏览器缓存位于独立
# PLAYWRIGHT_BROWSERS_PATH，不由这里清理，因此不会触发浏览器重复下载。
kept_versions=1
cache_entry_in_use() {
  local entry="$1" record worktree dependency_target
  while IFS= read -r -d '' record; do
    [[ "$record" == worktree\ * ]] || continue
    worktree="${record#worktree }"
    [ -L "$worktree/frontend/node_modules" ] || continue
    dependency_target=$(readlink -f "$worktree/frontend/node_modules")
    [ "$dependency_target" = "$entry/node_modules" ] && return 0
  done < <(git -C "$PROJECT_DIR" worktree list --porcelain -z 2>/dev/null || true)
  return 1
}
while IFS= read -r entry; do
  cache_entry="${entry#* }"
  [ "$cache_entry" = "$install_root" ] && continue
  cache_entry_in_use "$cache_entry" && continue
  if [ "$kept_versions" -lt "$MAX_VERSIONS" ]; then
    kept_versions=$((kept_versions + 1))
    continue
  fi
  [ -f "$cache_entry/.interview-boss-dependency-key" ] || continue
  cleanup_directory "$cache_entry"
done < <(
  find "$CACHE_DIR" -mindepth 1 -maxdepth 1 -type d \
    -regextype posix-extended -regex '.*/[0-9a-f]{24}' \
    -printf '%T@ %p\n' | sort -nr
)

echo "[frontend-deps] ready: $dependency_key"
