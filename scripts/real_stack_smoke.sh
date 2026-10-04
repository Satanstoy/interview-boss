#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.real-e2e.yml"
PROJECT="interview-boss-real-e2e-${BASHPID}-$(date +%s)"
PORT="${REAL_STACK_PORT:-18081}"
BASE_URL="http://127.0.0.1:${PORT}"
REAL_STACK_BUILDER="${BUILDKIT_BUILDER:-interview-boss}"
TEMP_ARTIFACTS="$(mktemp -d "${TMPDIR:-/tmp}/interview-boss-real-stack.XXXXXX")"
FINAL_ARTIFACT_ROOT="$PROJECT_DIR/test-results/real-stack"
RUN_STATUS=0

compose() {
  REAL_STACK_PORT="$PORT" docker compose --project-name "$PROJECT" -f "$COMPOSE_FILE" "$@"
}

ensure_real_stack_builder() {
  local driver
  if docker buildx inspect "$REAL_STACK_BUILDER" >/dev/null 2>&1; then
    # Read the full inspect output: exiting awk as soon as it sees Driver can
    # close the pipe early, making docker buildx exit with SIGPIPE under pipefail.
    driver=$(docker buildx inspect "$REAL_STACK_BUILDER" 2>/dev/null | awk -F': ' '/^Driver:/ && !found {gsub(/^ +| +$/, "", $2); driver=$2; found=1} END {if (found) print driver}')
    [ "$driver" = "docker-container" ] || {
      printf 'Real-stack BuildKit builder has driver=%s, expected docker-container\n' "$driver" >&2
      return 1
    }
    return 0
  fi

  docker buildx create \
    --name "$REAL_STACK_BUILDER" \
    --driver docker-container \
    --driver-opt network=host >/dev/null
}

copy_failure_artifacts() {
  mkdir -p "$FINAL_ARTIFACT_ROOT/$PROJECT"
  cp -R "$TEMP_ARTIFACTS/." "$FINAL_ARTIFACT_ROOT/$PROJECT/"
  printf 'Real-stack failure artifacts: %s\n' "$FINAL_ARTIFACT_ROOT/$PROJECT" >&2
}

copy_success_artifacts() {
  local artifact_dir="$FINAL_ARTIFACT_ROOT/$PROJECT"
  local copied=0
  local name
  for name in \
    ac028-browser-result.png \
    ac028-browser-result.json \
    ac001-ac002-browser-result.json \
    ac022-browser-result.json \
    ac022-db-trace.json \
    ac029-browser-result.json \
    ac029-db-trace.json; do
    if [ -f "$TEMP_ARTIFACTS/$name" ]; then
      mkdir -p "$artifact_dir"
      cp "$TEMP_ARTIFACTS/$name" "$artifact_dir/"
      copied=1
    fi
  done
  if [ "$copied" -eq 1 ]; then
    printf 'Real-stack result artifacts: %s\n' "$artifact_dir"
  fi
}

cleanup() {
  RUN_STATUS=$?
  set +e

  compose ps >"$TEMP_ARTIFACTS/compose-ps.txt" 2>&1
  compose logs --no-color >"$TEMP_ARTIFACTS/compose.log" 2>&1
  compose exec -T backend python -c \
    'import sqlite3; c=sqlite3.connect("/app/backend/data/interview-boss.db"); print(c.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone())' \
    >"$TEMP_ARTIFACTS/schema-version.txt" 2>&1

  if [ "$RUN_STATUS" -ne 0 ] && [ "${REAL_STACK_CAPTURE_FAILURE_DB:-0}" = "1" ]; then
    backend_container=$(compose ps -q backend)
    compose exec -T backend python - <<'PY' >/dev/null 2>&1
import sqlite3
source = sqlite3.connect("/app/backend/data/interview-boss.db")
snapshot = sqlite3.connect("/tmp/real-stack-failure.sqlite3")
source.backup(snapshot)
snapshot.close()
source.close()
PY
    docker cp "$backend_container:/tmp/real-stack-failure.sqlite3" \
      "$TEMP_ARTIFACTS/real-stack-failure.sqlite3" >/dev/null 2>&1
  fi

  copy_success_artifacts
  if [ "$RUN_STATUS" -ne 0 ]; then
    copy_failure_artifacts
  fi
  compose down --volumes --remove-orphans >/dev/null 2>&1
  rm -rf "$TEMP_ARTIFACTS"
  exit "$RUN_STATUS"
}

trap cleanup EXIT
trap 'exit 130' INT TERM

cd "$PROJECT_DIR"
command -v docker >/dev/null 2>&1
command -v curl >/dev/null 2>&1
command -v npm >/dev/null 2>&1
[ -x "$PROJECT_DIR/frontend/node_modules/.bin/playwright" ] || {
  printf 'Frontend Playwright dependencies are missing. Install them before starting the disposable stack.\n' >&2
  exit 1
}

run_frontend_playwright() {
  PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/data/home/ubuntu/cache/ms-playwright}" \
    "$PROJECT_DIR/frontend/node_modules/.bin/playwright" test \
    --config "$PROJECT_DIR/frontend/playwright.config.js" "$@"
}

compose config --quiet
if [ "${REAL_STACK_REUSE_BUILT_IMAGES:-0}" = "1" ]; then
  for image in \
    interview-boss-app:real-e2e \
    interview-boss-nginx:real-e2e \
    interview-boss-oauth-gateway:real-e2e \
    interview-boss-llm-stub:real-e2e; do
    docker image inspect "$image" >/dev/null 2>&1 || {
      printf 'Requested image reuse, but image is missing: %s\n' "$image" >&2
      exit 1
    }
  done
  compose up --no-build -d --wait --wait-timeout 180
else
  ensure_real_stack_builder
  compose build --builder "$REAL_STACK_BUILDER" backend worker nginx oauth-gateway llm-stub
  compose up -d --wait --wait-timeout 180
fi

curl --fail --silent --show-error --retry 30 --retry-delay 2 --retry-connrefused "$BASE_URL/" >/dev/null
curl --fail --silent --show-error --retry 30 --retry-delay 2 --retry-connrefused "$BASE_URL/api/health" >/dev/null

# AC-001/002: real API + SQLite + browser pagination and authorized target lookup.
compose exec -T backend python /app/backend/e2e/seed_ac001_ac002.py \
  >"$TEMP_ARTIFACTS/ac001-ac002-seed.json"
cd "$PROJECT_DIR/frontend"
REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL="$BASE_URL" \
  AC001_AC002_BROWSER_TRACE="$TEMP_ARTIFACTS/ac001-ac002-browser-result.json" \
  run_frontend_playwright tests/e2e/interview-pagination-real-stack.spec.js \
  --timeout "${AC001_AC002_REAL_STACK_TEST_TIMEOUT:-180000}"
if [ "${REAL_STACK_ONLY_AC001_AC002:-0}" = "1" ]; then
  exit 0
fi

# AC-022: send unsupported, empty, oversized, corrected, replayed, and changed
# multipart bodies through the real browser/API before checking disposable SQLite.
cd "$PROJECT_DIR/frontend"
REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL="$BASE_URL" \
  AC022_BROWSER_TRACE="$TEMP_ARTIFACTS/ac022-browser-result.json" \
  run_frontend_playwright tests/e2e/upload-file-validation-real-stack.spec.js \
  --timeout "${AC022_REAL_STACK_TEST_TIMEOUT:-210000}"
read -r ac022_key ac022_import_id < <(
  python3 - "$TEMP_ARTIFACTS/ac022-browser-result.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    trace = json.load(stream)
print(trace["idempotency_key"], trace["accepted_import_id"])
PY
)
cd "$PROJECT_DIR"
compose exec -T backend python /app/backend/e2e/assert_ac022_upload_trace.py \
  "$ac022_key" "$ac022_import_id" >"$TEMP_ARTIFACTS/ac022-db-trace.json"
if [ "${REAL_STACK_ONLY_AC022:-0}" = "1" ]; then
  exit 0
fi

cd "$PROJECT_DIR/frontend"
REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL="$BASE_URL" \
  run_frontend_playwright tests/e2e/real-stack-smoke.spec.js \
  --timeout "${REAL_STACK_TEST_TIMEOUT:-120000}"

# AC-028: keep the API/Redis/provider/frontend stack alive but stop its worker.
# The browser submits through the real UI and waits until its durable root job
# is visible as queued. Its explicit signal lets this runner restart the same
# worker container at that point, after which the browser opens the saved result.
cd "$PROJECT_DIR"
compose stop worker
restart_signal="$TEMP_ARTIFACTS/ac028-worker-restart"
restart_log="$TEMP_ARTIFACTS/ac028-worker-restart.log"
restart_worker_after_browser_queue() {
  local attempt=0
  while [ "$attempt" -lt 1200 ]; do
    if [ -f "$restart_signal" ]; then
      compose up -d --wait --wait-timeout 120 worker >>"$restart_log" 2>&1
      touch "$restart_signal.done"
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 0.25
  done
  printf 'Timed out waiting for the browser to observe a queued AC-028 upload.\n' >"$restart_log"
  return 1
}
restart_worker_after_browser_queue &
restart_monitor_pid=$!

cd "$PROJECT_DIR/frontend"
set +e
REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL="$BASE_URL" \
  AC028_WORKER_RESTART_SIGNAL="$TEMP_ARTIFACTS/ac028-worker-restart" \
  AC028_BROWSER_RESULT_SCREENSHOT="$TEMP_ARTIFACTS/ac028-browser-result.png" \
  AC028_BROWSER_RESULT_TRACE="$TEMP_ARTIFACTS/ac028-browser-result.json" \
  run_frontend_playwright tests/e2e/upload-recovery-real-stack.spec.js \
  --timeout "${AC028_REAL_STACK_TEST_TIMEOUT:-210000}"
browser_status=$?
if [ "$browser_status" -ne 0 ]; then
  kill "$restart_monitor_pid" >/dev/null 2>&1 || true
  wait "$restart_monitor_pid" >/dev/null 2>&1 || true
  exit "$browser_status"
fi
wait "$restart_monitor_pid"

# AC-029 seeds a known public canonical, then exercises U1 upload, U2 privacy,
# admin review/redaction, partial publication, and retry after a worker restart.
compose exec -T backend python /app/backend/e2e/seed_ac029_public_canonical.py
ac029_control="$TEMP_ARTIFACTS/ac029-worker"
ac029_monitor_log="$TEMP_ARTIFACTS/ac029-worker-monitor.log"
control_ac029_worker() {
  local attempt=0
  while [ "$attempt" -lt 7200 ]; do
    if [ -f "$ac029_control.stop" ]; then
      compose stop worker >>"$ac029_monitor_log" 2>&1
      touch "$ac029_control.stopped"
      break
    fi
    attempt=$((attempt + 1))
    sleep 0.25
  done
  if [ "$attempt" -ge 7200 ]; then
    printf 'Timed out waiting for the AC-029 failed-item boundary.\n' >"$ac029_monitor_log"
    return 1
  fi

  attempt=0
  while [ "$attempt" -lt 7200 ]; do
    if [ -f "$ac029_control.restart" ]; then
      compose up -d --wait --wait-timeout 120 worker >>"$ac029_monitor_log" 2>&1
      touch "$ac029_control.done"
      return 0
    fi
    attempt=$((attempt + 1))
    sleep 0.25
  done
  printf 'Timed out waiting for the AC-029 worker restart signal.\n' >"$ac029_monitor_log"
  return 1
}
control_ac029_worker &
ac029_monitor_pid=$!

cd "$PROJECT_DIR/frontend"
set +e
REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL="$BASE_URL" \
  AC029_WORKER_CONTROL_PREFIX="$ac029_control" \
  AC029_BROWSER_RESULT_TRACE="$TEMP_ARTIFACTS/ac029-browser-result.json" \
  run_frontend_playwright tests/e2e/public-contribution-real-stack.spec.js \
  --timeout "${AC029_REAL_STACK_TEST_TIMEOUT:-1440000}"
browser_status=$?
if [ "$browser_status" -ne 0 ]; then
  kill "$ac029_monitor_pid" >/dev/null 2>&1 || true
  wait "$ac029_monitor_pid" >/dev/null 2>&1 || true
  exit "$browser_status"
fi
wait "$ac029_monitor_pid"

read -r ac029_import_id ac029_request_id < <(
  python3 - "$TEMP_ARTIFACTS/ac029-browser-result.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    trace = json.load(stream)
print(trace["import_id"], trace["contribution_request_id"])
PY
)
compose exec -T backend python /app/backend/e2e/assert_ac029_public_trace.py \
  "$ac029_import_id" "$ac029_request_id" \
  >"$TEMP_ARTIFACTS/ac029-db-trace.json"
