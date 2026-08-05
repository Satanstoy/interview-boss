#!/bin/bash
set -uo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODE="${1:-all}"
blocking_failed=0
declare -a RESULTS=()

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

run_backend() {
  require_blocking_cmd docker || return
  check_docker_access || return

  run_blocking "backend test image" \
    docker compose --profile test build test

  run_blocking "backend collect" \
    docker compose --profile test run --rm test uv run pytest --collect-only -q

  # PYTHONPYCACHEPREFIX: test 容器源码挂载为 :ro，把 pyc 写到 /tmp 避免 read-only 报错
  run_blocking "backend compile" \
    docker compose --profile test run --rm -e PYTHONPYCACHEPREFIX=/tmp/pycache test uv run python -m compileall -q backend/app

  run_blocking "backend structure tests" \
    docker compose --profile test run --rm test uv run pytest \
      backend/tests/bank/test_master_bank_syntax.py \
      backend/tests/infra/test_docker_config.py \
      backend/tests/services/test_router_refactor.py \
      -q
}

run_frontend() {
  require_blocking_cmd npm || return

  run_blocking "frontend build" \
    bash -lc "cd '$PROJECT_DIR/frontend' && npm run build"

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
  if ! command -v uv >/dev/null 2>&1; then
    record "SKIP" "backend audit" "uv command not found; run uv tool run pip-audit manually"
    return
  fi

  run_nonblocking "backend audit" \
    bash -lc "cd '$PROJECT_DIR' && uv tool run pip-audit -r <(uv export --frozen --no-dev --format requirements-txt --no-hashes) --no-deps --disable-pip --progress-spinner off"
}

run_audit() {
  echo "AUDIT: reported only, non-blocking in this phase"
  run_frontend_audit
  run_backend_audit
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
  *)
    record "FAIL" "check mode" "unknown mode: ${MODE}"
    blocking_failed=1
    ;;
esac

print_summary
exit "$blocking_failed"
