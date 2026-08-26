#!/bin/bash
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-all}"
blocking_failed=0
declare -a RESULTS=()
TEST_COMPOSE_PROJECT=""
TEST_IMAGE_READY=0
TEST_IMAGE_TAG="${INTERVIEW_BOSS_TEST_TAG:-$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo local)}"
TEST_BUILDKIT_BUILDER="${BUILDKIT_BUILDER:-interview-boss}"
TEST_BUILDKIT_DRIVER="${BUILDKIT_BUILDER_DRIVER:-docker-container}"
TEST_HARD_MIN_FREE_MB="${DEPLOY_HARD_MIN_FREE_MB:-6144}"

prepare_test_project() {
  if [ -z "$TEST_COMPOSE_PROJECT" ]; then
    TEST_COMPOSE_PROJECT="interview-boss-check-${BASHPID}-$(date +%s)"
  fi
}

compose_test() {
  prepare_test_project
  INTERVIEW_BOSS_TEST_TAG="$TEST_IMAGE_TAG" \
    docker compose --project-name "$TEST_COMPOSE_PROJECT" --profile test "$@"
}

ensure_test_builder() {
  local driver
  if docker buildx inspect "$TEST_BUILDKIT_BUILDER" >/dev/null 2>&1; then
    driver=$(docker buildx inspect "$TEST_BUILDKIT_BUILDER" 2>/dev/null | awk -F': ' '/^Driver:/ {gsub(/^ +| +$/, "", $2); print $2; exit}')
    if [ "$driver" != "$TEST_BUILDKIT_DRIVER" ]; then
      record "FAIL" "InterviewBoss BuildKit builder" "driver=$driver, expected $TEST_BUILDKIT_DRIVER"
      blocking_failed=1
      return 1
    fi
    return 0
  fi

  if ! docker buildx create \
    --name "$TEST_BUILDKIT_BUILDER" \
    --driver "$TEST_BUILDKIT_DRIVER" \
    --driver-opt network=host >/dev/null; then
    record "FAIL" "InterviewBoss BuildKit builder" "could not create $TEST_BUILDKIT_BUILDER"
    blocking_failed=1
    return 1
  fi
}

test_root_free_mb() {
  df -Pm / | awk 'NR == 2 {print $4}'
}

check_test_build_space() {
  local free_mb
  free_mb=$(test_root_free_mb)
  if [ "$free_mb" -lt "$TEST_HARD_MIN_FREE_MB" ]; then
    record "FAIL" "backend test image" "root free ${free_mb}MB below hard threshold ${TEST_HARD_MIN_FREE_MB}MB"
    blocking_failed=1
    return 1
  fi
  return 0
}

cleanup_test_project() {
  local project="$TEST_COMPOSE_PROJECT"
  [ -n "$project" ] || return 0

  if ! INTERVIEW_BOSS_TEST_TAG="$TEST_IMAGE_TAG" \
      docker compose --project-name "$project" --profile test \
      down --volumes --remove-orphans >/dev/null 2>&1; then
    printf 'WARNING: test Compose project cleanup failed: %s\n' "$project" >&2
    blocking_failed=1
  fi
  TEST_COMPOSE_PROJECT=""
}

on_exit() {
  local rc=$?
  cleanup_test_project || true
  if [ "$rc" -eq 0 ] && [ "$blocking_failed" -ne 0 ]; then
    rc=1
  fi
  exit "$rc"
}

trap on_exit EXIT
trap 'cleanup_test_project || true; exit 130' INT TERM

record() {
  local status="$1"
  local name="$2"
  local message="${3:-}"
  RESULTS+=("${status}|${name}|${message}")
  if [ -n "$message" ]; then
    printf "%s %s: %s\n" "$status" "$name" "$message"
  else
    printf "%s %s\n" "$status" "$name"
  fi
}

require_blocking_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    record "FAIL" "tool ${cmd}" "command not found"
    blocking_failed=1
    return 1
  fi
  return 0
}

run_blocking() {
  local name="$1"
  shift
  if "$@"; then
    record "PASS" "$name"
  else
    local rc=$?
    record "FAIL" "$name" "exit ${rc}"
    blocking_failed=1
  fi
}

run_nonblocking() {
  local name="$1"
  shift
  if "$@"; then
    record "PASS" "$name"
  else
    local rc=$?
    record "WARN" "$name" "reported issues or could not complete, exit ${rc}"
  fi
}

check_docker_access() {
  if ! docker info >/dev/null 2>&1; then
    record "FAIL" "tool docker" "Docker unavailable or permission denied"
    blocking_failed=1
    return 1
  fi
  return 0
}

ensure_test_image() {
  if [ "$TEST_IMAGE_READY" -eq 1 ]; then
    return 0
  fi

  check_test_build_space || return 1
  ensure_test_builder || return 1

  if compose_test build --builder "$TEST_BUILDKIT_BUILDER" test; then
    record "PASS" "backend test image"
    TEST_IMAGE_READY=1
    return 0
  else
    local rc=$?
    record "FAIL" "backend test image" "exit ${rc}"
    blocking_failed=1
    return 1
  fi
}

run_backend() {
  require_blocking_cmd docker || return
  check_docker_access || return

  ensure_test_image || return

  run_blocking "backend collect" \
    compose_test run --rm test uv run pytest --collect-only -q

  # PYTHONPYCACHEPREFIX: test 容器源码挂载为 :ro，把 pyc 写到 /tmp 避免 read-only 报错
  run_blocking "backend compile" \
    compose_test run --rm -e PYTHONPYCACHEPREFIX=/tmp/pycache test uv run python -m compileall -q backend/app

  run_blocking "backend structure tests" \
    compose_test run --rm test uv run pytest \
      backend/tests/bank/test_master_bank_syntax.py \
      backend/tests/infra/test_docker_config.py \
      backend/tests/services/test_router_refactor.py \
      -q

  # 全量关键子集已恢复为 0 failed，重新作为发布 blocking gate。
  run_blocking "backend full tests" \
    compose_test run --rm -e PYTHONPYCACHEPREFIX=/tmp/pycache test uv run pytest \
      backend/tests/bank backend/tests/chat backend/tests/pipeline \
      backend/tests/services backend/tests/security backend/tests/infra \
      -q --tb=no

  local schema_source_commit
  schema_source_commit=$(git -C "$PROJECT_DIR" log -1 --format=%h -- backend/app/db/migrations 2>/dev/null || echo unknown)
  run_blocking "schema docs freshness" \
    compose_test run --rm \
    -e ADMIN_PASSWORD=schema-check-placeholder \
    -e SCHEMA_SOURCE_MIGRATION_COMMIT="$schema_source_commit" \
    test uv run python /app/scripts/generate_schema_docs.py --check
}

run_frontend() {
  require_blocking_cmd npm || return

  run_blocking "frontend build" \
    bash -lc "cd '$PROJECT_DIR/frontend' && npm run build"

  run_blocking "frontend eslint" \
    bash -lc "cd '$PROJECT_DIR/frontend' && npm run lint"

  run_blocking "frontend type-check" \
    bash -lc "cd '$PROJECT_DIR/frontend' && npm run type-check"

  run_blocking "frontend tests" \
    bash -lc "cd '$PROJECT_DIR/frontend' && npm run test"
}

run_frontend_audit() {
  if ! command -v npm >/dev/null 2>&1; then
    record "SKIP" "frontend audit" "npm command not found"
    return
  fi

  run_nonblocking "frontend audit" \
    bash -lc "cd '$PROJECT_DIR/frontend' && npm run audit:prod"
}

run_backend_audit() {
  # 与 run_backend 保持一致走 test-runtime 容器，避免依赖宿主机 uv/PATH。
  if ! docker info >/dev/null 2>&1; then
    record "SKIP" "backend audit" "Docker unavailable; run uvx pip-audit manually"
    return
  fi

  ensure_test_image || return

  run_nonblocking "backend audit" \
    compose_test run --rm test sh -lc \
      "cd /app && uv export --frozen --no-dev --format requirements-txt --no-hashes -o /tmp/requirements-audit.txt && uv run pip-audit -r /tmp/requirements-audit.txt --no-deps --disable-pip --progress-spinner off"
}

# line-guard: blocking gate - delegates to scripts/line_guard.sh (allowlist-based)
run_line_guard() {
  if ! [ -x "$PROJECT_DIR/scripts/line_guard.sh" ]; then
    record "FAIL" "line-guard" "scripts/line_guard.sh missing or not executable"
    blocking_failed=1
    return
  fi
  if bash "$PROJECT_DIR/scripts/line_guard.sh"; then
    record "PASS" "line-guard" "all source files within line limits"
  else
    record "FAIL" "line-guard" "a source file exceeds its line cap - see output above"
    blocking_failed=1
  fi
}

run_secret_scan() {
  if ! command -v python3 >/dev/null 2>&1; then
    record "FAIL" "secret scan" "python3 command not found"
    blocking_failed=1
    return
  fi

  run_blocking "secret scan" \
    python3 "$PROJECT_DIR/backend/scripts/check_secrets.py"
}

run_static_backend() {
  if ! docker info >/dev/null 2>&1; then
    record "SKIP" "backend static" "Docker unavailable"
    return
  fi

  ensure_test_image || return

  # ruff(E4/E7/E9/F) 自 2026-08-24 起基线清零,升级为 blocking;新增违例即 FAIL。
  run_blocking "backend ruff" \
    compose_test run --rm test uv run ruff check backend/app

  run_blocking "backend mypy baseline" \
    compose_test run --rm test bash /app/scripts/check_mypy_baseline.sh

}

run_static_frontend() {
  if ! command -v npm >/dev/null 2>&1; then
    record "SKIP" "frontend static" "npm command not found"
    return
  fi

  run_blocking "frontend eslint" \
    bash -lc "cd '$PROJECT_DIR/frontend' && npm run lint"
}

run_audit() {
  echo "AUDIT: dependency audit is WARN-only; static quality gates are blocking"
  run_frontend_audit
  run_backend_audit
  run_static_backend
  run_static_frontend
}

print_summary() {
  echo ""
  echo "InterviewBoss daily check"
  echo ""

  local entry status name message
  for entry in "${RESULTS[@]}"; do
    IFS='|' read -r status name message <<< "$entry"
    if [ -n "$message" ]; then
      printf "%s %s: %s\n" "$status" "$name" "$message"
    else
      printf "%s %s\n" "$status" "$name"
    fi
  done

  echo ""
  if [ "$blocking_failed" -eq 0 ]; then
    echo "Blocking checks: PASS"
  else
    echo "Blocking checks: FAIL"
  fi
  echo "Audit checks: WARN only"
}

cd "$PROJECT_DIR" || exit 1

case "$MODE" in
  all)
    run_secret_scan
    run_line_guard
    run_backend
    run_frontend
    run_audit
    ;;
  backend)
    run_backend
    ;;
  frontend)
    run_frontend
    ;;
  audit)
    run_audit
    ;;
  lineguard)
    run_line_guard
    ;;
  *)
    record "FAIL" "check mode" "unknown mode: ${MODE}"
    blocking_failed=1
    ;;
esac

print_summary
exit "$blocking_failed"
