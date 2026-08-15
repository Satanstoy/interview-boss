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

  # 全量关键子集 pytest(audit WARN 不拦截): 让完整失败面进入门禁报告。
  # 已知既有失败(非本次引入)不会让门禁恒红; 收敛后可将此段改为 blocking。
  run_nonblocking "backend full tests" \
    docker compose --profile test run --rm -e PYTHONPYCACHEPREFIX=/tmp/pycache test uv run pytest \
      backend/tests/bank backend/tests/chat backend/tests/pipeline \
      backend/tests/services backend/tests/security backend/tests/infra \
      -q --tb=no
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
  # 与 run_backend 保持一致走 test-runtime 容器，避免依赖宿主机 uv/PATH。
  if ! docker info >/dev/null 2>&1; then
    record "SKIP" "backend audit" "Docker unavailable; run uvx pip-audit manually"
    return
  fi

  run_nonblocking "backend audit" \
    docker compose --profile test run --rm test sh -lc \
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

  run_nonblocking "backend ruff" \
    docker compose --profile test run --rm test uv run ruff check backend/app

  run_nonblocking "backend mypy" \
    docker compose --profile test run --rm test uv run mypy backend/app
}

run_static_frontend() {
  if ! command -v npm >/dev/null 2>&1; then
    record "SKIP" "frontend static" "npm command not found"
    return
  fi

  run_nonblocking "frontend eslint" \
    bash -lc "cd '$PROJECT_DIR/frontend' && npm run lint"
}

run_audit() {
  echo "AUDIT: reported only, non-blocking in this phase"
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
