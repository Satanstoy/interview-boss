#!/usr/bin/env bash
# BuildKit 缓存守卫的行为测试。
#
# 背景：2026-09-28 一次正式 update 构建后因空间不足被拒，根因是磁盘保护
# "失败即跳过、跳过即成功" —— prune_build_cache 读到空值就 return 0，
# 调用方无从区分"清理成功"与"根本没清"。
#
# 本测试用 PATH 打桩假 docker/df，真跑子命令，验证三条不变量：
#   1. 缓存超 cap → 触发不带年龄过滤的 prune，并读回校验
#   2. 读不到 cache/driver → 返回非 0（不得静默成功）
#   3. 清理后仍不达标 → 发 ALERT 且拒绝
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_SCRIPT="$PROJECT_DIR/deploy/docker-deploy.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
fake_bin="$tmp_dir/bin"
mkdir -p "$fake_bin"

cat > "$fake_bin/docker" <<'FAKE'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_DOCKER_CALLS"

case "$*" in
  "buildx ls")
    printf 'NAME/NODE   DRIVER/ENDPOINT   STATUS   BUILDKIT   PLATFORMS\n'
    printf 'interview-boss\tdocker-container\n'
    printf ' \\_ interview-boss0\t\\_ unix:///var/run/docker.sock\trunning\tv0.32.2\n'
    exit "${FAKE_LS_RC:-0}"
    ;;
  "buildx du --builder interview-boss")
    if [[ "${FAKE_DU_RC:-0}" != "0" ]]; then exit "$FAKE_DU_RC"; fi
    state="$(cat "$FAKE_DU_STATE" 2>/dev/null || echo 3000MB)"
    printf 'abc\tfalse\t100MB\t1 minute ago\n'
    printf 'Reclaimable:\t50MB\n'
    printf 'Total:\t\t%s\n' "$state"
    exit 0
    ;;
  *"buildx inspect interview-boss --bootstrap"*)
    exit "${FAKE_BOOTSTRAP_RC:-0}"
    ;;
  *"buildx inspect interview-boss"*)
    if [[ "${FAKE_INSPECT_RC:-0}" != "0" ]]; then exit "$FAKE_INSPECT_RC"; fi
    printf 'Driver: docker-container\n'
    exit 0
    ;;
  *"buildx prune --builder interview-boss"*)
    # 真的收敛：把状态写成 cap 以下（模拟 BuildKit 行为）
    printf '%s\n' "${FAKE_PRUNE_RESULT:-1000MB}" > "$FAKE_DU_STATE"
    exit "${FAKE_PRUNE_RC:-0}"
    ;;
  "image ls --filter dangling=true --format {{.ID}}")
    printf '%s\n' ${FAKE_DANGLING_IDS:-}
    exit 0
    ;;
  *"image inspect -f {{index .Config.Labels \"com.docker.compose.project\"}}"*)
    printf '%s\n' "${FAKE_PROJECT:-interview-boss}"
    exit 0
    ;;
  *"image inspect -f {{index .Config.Labels \"com.docker.compose.service\"}}"*)
    printf '%s\n' "${FAKE_SERVICE:-backend}"
    exit 0
    ;;
  *"image inspect -f {{.Id}}"*)
    # 受保护标签与悬空候选返回同一镜像 ID（模拟 :previous 落到 dangling 列表）
    printf 'sha256:%s\n' "${FAKE_PROTECTED_ID:-aaaa11112222}"
    exit 0
    ;;
  *) exit 0 ;;
esac
FAKE
chmod +x "$fake_bin/docker"

cat > "$fake_bin/df" <<'FAKE'
#!/usr/bin/env bash
printf 'Filesystem     1M-blocks  Used Available Capacity Mounted on\n'
printf '/dev/vda2          40960 35000      %s      90%% /\n' "${FAKE_FREE_MB:-6000}"
FAKE
chmod +x "$fake_bin/df"

run_self_check() {
  local calls="$tmp_dir/calls.$1"
  : > "$calls"
  set +e
  PATH="$fake_bin:$PATH" \
    FAKE_DOCKER_CALLS="$calls" \
    FAKE_DU_STATE="$2" \
    FAKE_FREE_MB="$3" \
    FAKE_DU_RC="${4:-0}" \
    FAKE_DANGLING_IDS="${5:-}" \
    FAKE_PRUNE_RESULT="${6:-1000MB}" \
    "$DEPLOY_SCRIPT" storage-self-check >"$tmp_dir/out.$1" 2>&1
  local rc=$?
  set -e
  echo "$rc"
}

# ── 场景 1：缓存超 cap → 收敛 + 校验通过 ────────────────────────────
printf '3000MB\n' > "$tmp_dir/state1"
rc="$(run_self_check 1 "$tmp_dir/state1" 6000)"
[[ "$rc" -eq 0 ]] || { cat "$tmp_dir/out.1"; fail "超 cap 时应清理并成功 (rc=$rc)"; }
grep -q 'buildx prune --builder interview-boss' "$tmp_dir/calls.1" \
  || { cat "$tmp_dir/out.1"; fail "缓存超 cap 却未执行 buildx prune"; }
grep -q -- '--max-used-space' "$tmp_dir/calls.1" || fail "prune 未带 --max-used-space"
if grep -q -- '--filter until=' "$tmp_dir/calls.1"; then
  fail "prune 不应带年龄过滤（fresh 缓存永远清不动）"
fi
grep -q '收敛' "$tmp_dir/out.1" || { cat "$tmp_dir/out.1"; fail "未输出收敛结果"; }
[[ "$(cat "$tmp_dir/state1")" == "1000MB" ]] || fail "prune 未被真正调用"

# ── 场景 2：读不到缓存用量 → 不得静默成功 ──────────────────────────
printf '3000MB\n' > "$tmp_dir/state2"
rc="$(run_self_check 2 "$tmp_dir/state2" 6000 1)"
[[ "$rc" -ne 0 ]] || { cat "$tmp_dir/out.2"; fail "读不到 cache 时必须失败，不能静默通过"; }
grep -qE '无法读取|拒绝' "$tmp_dir/out.2" || { cat "$tmp_dir/out.2"; fail "未给出可读的失败原因"; }

# ── 场景 3：清理后仍低于硬阈值 → ALERT + 拒绝 ──────────────────────
printf '100MB\n' > "$tmp_dir/state3"
rc="$(run_self_check 3 "$tmp_dir/state3" 1000)"
[[ "$rc" -ne 0 ]] || { cat "$tmp_dir/out.3"; fail "低于硬阈值时必须拒绝 (rc=$rc)"; }
grep -q 'ALERT' "$tmp_dir/out.3" || { cat "$tmp_dir/out.3"; fail "低于硬阈值时未发告警"; }

# ── 场景 4：:previous 回滚镜像即使出现在 dangling 列表也不得删除 ─────
# 2026-09-28：容器切到新镜像后，:previous 会短暂落进 dangling=true，旧逻辑只按
# "是否被容器引用"判断，于是连标签一起删掉，回滚后路被切断。
printf '100MB\n' > "$tmp_dir/state4"
rc="$(run_self_check 4 "$tmp_dir/state4" 6000 0 aaaa11112222)"
[[ "$rc" -eq 0 ]] || { cat "$tmp_dir/out.4"; fail "受保护镜像场景不应导致自检失败 (rc=$rc)"; }
if grep -q 'image rm aaaa11112222' "$tmp_dir/calls.4"; then
  cat "$tmp_dir/out.4"
  fail "受保护回滚镜像被删除了"
fi
grep -q '保留受保护镜像' "$tmp_dir/out.4" || { cat "$tmp_dir/out.4"; fail "未记录受保护镜像的保留决定"; }

# ── 场景 5：构建路径必须过守卫（曾漏改调用点导致 command not found）────
printf '3000MB\n' > "$tmp_dir/state5"
: > "$tmp_dir/calls.5"
set +e
PATH="$fake_bin:$PATH" \
  FAKE_DOCKER_CALLS="$tmp_dir/calls.5" \
  FAKE_DU_STATE="$tmp_dir/state5" \
  FAKE_FREE_MB=6000 \
  DEPLOY_MIRROR_HEALTHCHECK_ON_BUILD=0 \
  DEPLOY_SELECT_MIRRORS_ON_BUILD=0 \
  "$DEPLOY_SCRIPT" build >"$tmp_dir/out.5" 2>&1
rc5=$?
set -e
if grep -q 'command not found' "$tmp_dir/out.5"; then
  cat "$tmp_dir/out.5"; fail "构建路径引用了不存在的函数"
fi
[[ "$rc5" -eq 0 ]] || { cat "$tmp_dir/out.5"; fail "构建路径应成功 (rc=$rc5)"; }
grep -q 'compose build' "$tmp_dir/calls.5" || { cat "$tmp_dir/out.5"; fail "构建路径未执行 compose build"; }
grep -q 'buildx prune --builder interview-boss' "$tmp_dir/calls.5" \
  || { cat "$tmp_dir/out.5"; fail "构建前缓存超 cap 却未收敛"; }
grep -q '收敛' "$tmp_dir/out.5" || { cat "$tmp_dir/out.5"; fail "构建路径未输出收敛结果"; }

# ── 场景 6：prune 残留略超 cap 但在容差内 → 应通过 ─────────────────
# 真机实测：--max-used-space 1536MB 收敛到 1547MB，绝不能因此判"保护失败"
printf '3000MB\n' > "$tmp_dir/state6"
rc="$(run_self_check 6 "$tmp_dir/state6" 6000 0 "" 1580MB)"
[[ "$rc" -eq 0 ]] || { cat "$tmp_dir/out.6"; fail "容差内的残留不应判失败 (rc=$rc)"; }

# ── 场景 7：prune 后仍远超 cap+容差 → 必须失败 ─────────────────────
printf '3000MB\n' > "$tmp_dir/state7"
rc="$(run_self_check 7 "$tmp_dir/state7" 6000 0 "" 2500MB)"
[[ "$rc" -ne 0 ]] || { cat "$tmp_dir/out.7"; fail "远超容差时必须判失败 (rc=$rc)"; }

echo "PASS: build cache guard enforces cap, verifies result, never silently skips"
