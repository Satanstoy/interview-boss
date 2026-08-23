#!/usr/bin/env bash
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
calls="$tmp_dir/docker.calls"

cat > "$fake_bin/docker" <<'EOF'
#!/usr/bin/env bash
printf '%s\n' "$*" >> "$FAKE_DOCKER_CALLS"
case "$*" in
  *"buildx inspect interview-boss"*) printf 'Driver: docker-container\n'; exit 0 ;;
  *"buildx create"*) exit 0 ;;
  *" build "*) exit 0 ;;
  *" run "*) exit 23 ;;
  *" down --volumes --remove-orphans"*) exit 0 ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$fake_bin/docker"

set +e
PATH="$fake_bin:$PATH" \
  FAKE_DOCKER_CALLS="$calls" \
  DEPLOY_TARGET_FREE_MB=1 \
  DEPLOY_HARD_MIN_FREE_MB=1 \
  DEPLOY_MIRROR_HEALTHCHECK_ON_BUILD=0 \
  "$DEPLOY_SCRIPT" test --collect-only >/dev/null 2>&1
rc=$?
set -e

[[ "$rc" -eq 23 ]] || fail "test command did not preserve pytest failure status (rc=$rc)"
grep -Eq 'compose --project-name interview-boss-test-[0-9]+-[0-9]+ .* down --volumes --remove-orphans$' "$calls" \
  || fail "failed test did not run scoped Compose cleanup"
if grep -Eq 'interview-boss-test-.* --rmi|docker image rm interview-boss-test' "$calls"; then
  fail "test cleanup attempted to delete the reusable test image"
fi

echo "PASS: failed test preserves failure status and cleans only its temporary Compose project"
