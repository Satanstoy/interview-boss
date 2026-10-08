#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.real-e2e.yml"
PROJECT="interview-boss-real-e2e-${BASHPID}-$(date +%s)"
PORT="${REAL_STACK_PORT:-18081}"
STUB_PORT="${REAL_STACK_STUB_PORT:-$((PORT + 1))}"
BASE_URL="http://127.0.0.1:${PORT}"
STUB_URL="http://127.0.0.1:${STUB_PORT}"
REAL_STACK_BUILDER="${BUILDKIT_BUILDER:-interview-boss}"
TEMP_ARTIFACTS="$(mktemp -d "${TMPDIR:-/tmp}/interview-boss-real-stack.XXXXXX")"
FINAL_ARTIFACT_ROOT="$PROJECT_DIR/test-results/real-stack"
RUN_STATUS=0

compose() {
  REAL_STACK_PORT="$PORT" REAL_STACK_STUB_PORT="$STUB_PORT" \
    docker compose --project-name "$PROJECT" -f "$COMPOSE_FILE" "$@"
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
    ac001-ac002-browser-result.json.responses.json \
    ac001-ac002-db-trace.json \
    ac022-browser-result.json \
    ac022-db-trace.json \
    ac007-seed.json \
    ac007-browser-result.json \
    ac007-db-trace.json \
    ac007-queue-seed.json \
    ac007-queue-fairness.json \
    ac007-queue-idle.json \
    ac007-lost-dispatch-seed.json \
    ac007-lost-notification.json \
    ac007-dispatch-recovery.json \
    ac007-lost-dispatch-final.json \
    ac007-rootless-reconcile-recovery.json \
    ac010-seed.json \
    ac010-revision7.json \
    ac010-browser-result.json \
    ac010-db-trace.json \
    ac011-seed.json \
    ac011-first-pass-db-trace.json \
    ac011-final-db-trace.json \
    ac011-browser-result.json \
    ac011-trace-assertion.json \
    ac013-browser-result.json \
    ac013-auth_401-db-trace.json \
    ac013-permission_403-db-trace.json \
    ac013-rate_429-db-trace.json \
    ac013-format_invalid-db-trace.json \
    ac013-timeout_once-db-trace.json \
    ac013-stub-access.json \
    ac013-log-redaction.json \
    ac016-seed.json \
    ac016-source-update.json \
    ac016-browser-result.json \
    ac016-first-pass-db-trace.json \
    ac016-db-trace.json \
    ac017-seed.json \
    ac017-retry-db-trace.json \
    ac017-parallel-answers.json \
    ac017-parallel-answers-inflight.json \
    ac017-parallel-answers-final.json \
    ac017-browser-result.json \
    ac024-seed.json \
    ac024-browser-result.json \
    ac024-read-baseline.json \
    ac024-provider-access.json \
    ac024-db-trace.json \
    ac009-browser-result.json \
    ac009-same-second.json \
    ac009-db-trace.json \
    ac009-provider-overlap.json \
    ac029-browser-result.json \
    ac029-first-pass-resolutions.json \
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

run_ac011_real_stack() {
  local control_prefix="$TEMP_ARTIFACTS/ac011-control"
  local browser_log="$TEMP_ARTIFACTS/ac011-browser.log"
  local monitor_log="$TEMP_ARTIFACTS/ac011-monitor.log"
  local browser_pid
  local attempt=0

  compose exec -T llm-stub python -c \
    'import urllib.request; urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8080/__e2e/reset", data=b"{}", method="POST"), timeout=5).read()'
  compose exec -T backend python /app/backend/e2e/seed_ac011_partial_answers.py \
    >"$TEMP_ARTIFACTS/ac011-seed.json"

  cd "$PROJECT_DIR/frontend"
  set +e
  REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL="$BASE_URL" \
    AC011_SEED_PATH="$TEMP_ARTIFACTS/ac011-seed.json" \
    AC011_RELEASE_SIGNAL="$control_prefix.release" \
    AC011_RELEASE_DONE="$control_prefix.released" \
    AC011_BROWSER_DONE="$control_prefix.browser-done" \
    AC011_BROWSER_TRACE="$TEMP_ARTIFACTS/ac011-browser-result.json" \
    run_frontend_playwright tests/e2e/upload-answer-partial-ac011-real-stack.spec.js \
      --timeout "${AC011_REAL_STACK_TEST_TIMEOUT:-720000}" \
      >"$browser_log" 2>&1 &
  browser_pid=$!
  set -e

  while [ "$attempt" -lt "${AC011_REAL_STACK_DRIVER_POLLS:-1800}" ]; do
    if ! kill -0 "$browser_pid" >/dev/null 2>&1; then
      set +e
      wait "$browser_pid"
      local early_status=$?
      set -e
      cat "$browser_log"
      if [ "$early_status" -ne 0 ]; then
        return "$early_status"
      fi
      if [ -f "$control_prefix.browser-done" ]; then
        break
      fi
      printf 'The AC-011 browser exited without writing its completion signal.\n' >&2
      return 1
    fi

    compose exec -T backend python -c \
      'import asyncio; from app.worker_scheduled import scheduled_submit_job_dispatch_task; asyncio.run(scheduled_submit_job_dispatch_task({}))' \
      >>"$monitor_log" 2>&1 || true

    if [ -f "$control_prefix.release" ] && [ ! -f "$control_prefix.released" ]; then
      compose exec -T backend python /app/backend/e2e/ac011_answer_trace.py first \
        "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["import_id"])' "$TEMP_ARTIFACTS/ac011-seed.json")" \
        >"$TEMP_ARTIFACTS/ac011-first-pass-db-trace.json"
      compose exec -T llm-stub python -c \
        'import urllib.request; urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8080/__e2e/release", data=b"{\"marker\":\"AC011_QUESTION_09\"}", headers={"Content-Type":"application/json"}, method="POST"), timeout=5).read()'
      compose exec -T llm-stub python -c \
        'import urllib.request; urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8080/__e2e/release", data=b"{\"marker\":\"AC011_QUESTION_10\"}", headers={"Content-Type":"application/json"}, method="POST"), timeout=5).read()'
      printf '%s\n' "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["import_id"])' "$TEMP_ARTIFACTS/ac011-seed.json")" \
        >"$control_prefix.released"
    fi

    if [ -f "$control_prefix.browser-done" ]; then
      break
    fi
    attempt=$((attempt + 1))
    sleep 1
  done

  if [ "$attempt" -ge "${AC011_REAL_STACK_DRIVER_POLLS:-1800}" ]; then
    printf 'Timed out driving the real AC-011 worker and browser scenario.\n' >&2
    cat "$monitor_log" >&2
    return 1
  fi

  set +e
  wait "$browser_pid"
  local browser_status=$?
  set -e
  cat "$browser_log"
  if [ "$browser_status" -ne 0 ]; then
    return "$browser_status"
  fi

  local import_id
  import_id=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["import_id"])' "$TEMP_ARTIFACTS/ac011-seed.json")
  compose exec -T backend python /app/backend/e2e/ac011_answer_trace.py final "$import_id" \
    >"$TEMP_ARTIFACTS/ac011-final-db-trace.json"
  python3 "$PROJECT_DIR/backend/e2e/assert_ac011_answer_trace.py" \
    "$TEMP_ARTIFACTS/ac011-first-pass-db-trace.json" \
    "$TEMP_ARTIFACTS/ac011-final-db-trace.json" \
    >"$TEMP_ARTIFACTS/ac011-trace-assertion.json"
}

run_ac013_real_stack() {
  local browser_log="$TEMP_ARTIFACTS/ac013-browser.log"
  local import_id
  local marker
  local scenario

  compose exec -T llm-stub python -c \
    'import urllib.request; urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8080/__e2e/reset", data=b"{}", method="POST"), timeout=5).read()'
  compose exec -T backend python /app/backend/e2e/seed_ac013_error_contract.py \
    >"$TEMP_ARTIFACTS/ac013-seed.json"

  cd "$PROJECT_DIR/frontend"
  REAL_STACK_E2E=1 \
    PLAYWRIGHT_BASE_URL="$BASE_URL" \
    AC013_SEED_PATH="$TEMP_ARTIFACTS/ac013-seed.json" \
    AC013_BROWSER_TRACE="$TEMP_ARTIFACTS/ac013-browser-result.json" \
    AC013_STUB_URL="$STUB_URL" \
    run_frontend_playwright tests/e2e/upload-ac013-real-stack.spec.js \
      --timeout "${AC013_REAL_STACK_TEST_TIMEOUT:-720000}" \
      >"$browser_log" 2>&1 || {
        cat "$browser_log"
        return 1
      }
  cat "$browser_log"

  for marker in \
    AC013_AUTH_401 \
    AC013_PERMISSION_403 \
    AC013_RATE_429 \
    AC013_FORMAT_INVALID \
    AC013_TIMEOUT_ONCE; do
    case "$marker" in
      AC013_AUTH_401) scenario=auth_401 ;;
      AC013_PERMISSION_403) scenario=permission_403 ;;
      AC013_RATE_429) scenario=rate_429 ;;
      AC013_FORMAT_INVALID) scenario=format_invalid ;;
      AC013_TIMEOUT_ONCE) scenario=timeout_once ;;
    esac
    import_id=$(python3 -c \
      'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["import_ids"][sys.argv[2]])' \
      "$TEMP_ARTIFACTS/ac013-browser-result.json" "$scenario")
    compose exec -T backend python /app/backend/e2e/ac013_error_trace.py "$import_id" "$marker" \
      >"$TEMP_ARTIFACTS/ac013-${scenario}-db-trace.json"
  done

  compose exec -T llm-stub python -c \
    'import json,urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/__e2e/access", timeout=5).read().decode())' \
    >"$TEMP_ARTIFACTS/ac013-stub-access.json"
  compose logs --no-color backend worker llm-stub >"$TEMP_ARTIFACTS/ac013-compose.log" 2>&1
  python3 "$PROJECT_DIR/backend/e2e/assert_ac013_log_redaction.py" \
    "$TEMP_ARTIFACTS/ac013-compose.log" \
    >"$TEMP_ARTIFACTS/ac013-log-redaction.json"
}

run_ac016_real_stack() {
  local control_prefix="$TEMP_ARTIFACTS/ac016-worker"
  local browser_log="$TEMP_ARTIFACTS/ac016-browser.log"
  local monitor_log="$TEMP_ARTIFACTS/ac016-worker-monitor.log"
  local browser_pid
  local monitor_pid

  compose exec -T backend python /app/backend/e2e/seed_ac016_append_projection.py \
    >"$TEMP_ARTIFACTS/ac016-seed.json"

  control_ac016_worker() {
    local attempt=0
    local interview_id
    while [ "$attempt" -lt "${AC016_REAL_STACK_DRIVER_POLLS:-7200}" ]; do
      if [ -f "$control_prefix.append-b" ] && [ ! -f "$control_prefix.source-updated" ]; then
        interview_id=$(python3 - "$TEMP_ARTIFACTS/ac016-seed.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["interview_id"])
PY
)
        compose exec -T backend python /app/backend/e2e/append_ac016_question_b.py \
          "$interview_id" >"$TEMP_ARTIFACTS/ac016-source-update.json"
        touch "$control_prefix.source-updated"
      fi

      if [ -f "$control_prefix.stop" ] && [ ! -f "$control_prefix.stopped" ]; then
        local failed_request_id
        failed_request_id=$(cat "$control_prefix.stop")
        compose stop worker >>"$monitor_log" 2>&1
        compose exec -T backend python /app/backend/e2e/assert_ac016_failure_boundary.py \
          "$failed_request_id" >"$TEMP_ARTIFACTS/ac016-first-pass-db-trace.json"
        touch "$control_prefix.stopped"
        compose up -d --wait --wait-timeout 120 worker >>"$monitor_log" 2>&1
        touch "$control_prefix.restarted"
      fi

      if [ -f "$control_prefix.restart" ] && [ ! -f "$control_prefix.done" ]; then
        local request_id
        local dispatch_attempt=0
        local dispatch_state
        request_id=$(cat "$control_prefix.restart")
        while [ "$dispatch_attempt" -lt 120 ]; do
          dispatch_state=$(compose exec -T backend python \
            /app/backend/e2e/ac016_retry_dispatch_gate.py "$request_id")
          if [ "$dispatch_state" = "dispatched" ] || [ "$dispatch_state" = "completed" ]; then
            break
          fi
          compose exec -T backend python -c \
            'import asyncio; from app.worker_scheduled import scheduled_submit_job_dispatch_task; print(asyncio.run(scheduled_submit_job_dispatch_task({})))' \
            >>"$monitor_log" 2>&1
          dispatch_attempt=$((dispatch_attempt + 1))
          sleep 1
        done
        if [ "$dispatch_attempt" -ge 120 ]; then
          printf 'Timed out dispatching the retried AC-016 contribution job.\n' >"$monitor_log"
          return 1
        fi
        touch "$control_prefix.done"
        return 0
      fi

      attempt=$((attempt + 1))
      sleep 0.25
    done
    printf 'Timed out driving the AC-016 source append or worker restart.\n' >"$monitor_log"
    return 1
  }

  control_ac016_worker &
  monitor_pid=$!
  cd "$PROJECT_DIR/frontend"
  set +e
  REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL="$BASE_URL" \
    AC016_SEED_PATH="$TEMP_ARTIFACTS/ac016-seed.json" \
    AC016_WORKER_CONTROL_PREFIX="$control_prefix" \
    AC016_BROWSER_RESULT_TRACE="$TEMP_ARTIFACTS/ac016-browser-result.json" \
    run_frontend_playwright tests/e2e/public-contribution-ac016-real-stack.spec.js \
      --timeout "${AC016_REAL_STACK_TEST_TIMEOUT:-1440000}" \
      >"$browser_log" 2>&1
  local browser_status=$?
  set -e
  if [ "$browser_status" -ne 0 ]; then
    kill "$monitor_pid" >/dev/null 2>&1 || true
    wait "$monitor_pid" >/dev/null 2>&1 || true
    cat "$browser_log"
    return "$browser_status"
  fi
  wait "$monitor_pid"
  cat "$browser_log"

  local backend_container
  backend_container=$(compose ps -q backend)
  docker cp "$TEMP_ARTIFACTS/ac016-seed.json" "$backend_container:/tmp/ac016-seed.json" >/dev/null
  docker cp "$TEMP_ARTIFACTS/ac016-browser-result.json" "$backend_container:/tmp/ac016-browser-result.json" >/dev/null
  docker cp "$TEMP_ARTIFACTS/ac016-first-pass-db-trace.json" "$backend_container:/tmp/ac016-first-pass-db-trace.json" >/dev/null
  compose exec -T backend python /app/backend/e2e/assert_ac016_append_projection.py \
    /tmp/ac016-seed.json \
    /tmp/ac016-browser-result.json \
    /tmp/ac016-first-pass-db-trace.json \
    >"$TEMP_ARTIFACTS/ac016-db-trace.json"
}

run_ac017_real_stack() {
  local control_prefix="$TEMP_ARTIFACTS/ac017-control"
  local browser_log="$TEMP_ARTIFACTS/ac017-browser.log"
  local browser_pid
  local attempt=0

  compose stop worker >/dev/null
  compose exec -T llm-stub python -c \
    'import urllib.request; urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8080/__e2e/reset", data=b"{}", method="POST"), timeout=5).read()'
  compose exec -T backend python /app/backend/e2e/seed_ac017_retry_chain.py \
    >"$TEMP_ARTIFACTS/ac017-seed.json"

  cd "$PROJECT_DIR/frontend"
  set +e
  REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL="$BASE_URL" \
    AC017_SEED_PATH="$TEMP_ARTIFACTS/ac017-seed.json" \
    AC017_CONTROL_PREFIX="$control_prefix" \
    AC017_BROWSER_TRACE="$TEMP_ARTIFACTS/ac017-browser-result.json" \
    run_frontend_playwright tests/e2e/upload-retry-ac017-real-stack.spec.js \
      --timeout "${AC017_REAL_STACK_TEST_TIMEOUT:-240000}" \
      >"$browser_log" 2>&1 &
  browser_pid=$!
  set -e

  while [ "$attempt" -lt "${AC017_REAL_STACK_DRIVER_POLLS:-600}" ]; do
    if [ -f "$control_prefix.retry-actions-done" ]; then
      break
    fi
    if ! kill -0 "$browser_pid" >/dev/null 2>&1; then
      wait "$browser_pid" || true
      cat "$browser_log"
      return 1
    fi
    attempt=$((attempt + 1))
    sleep 0.5
  done
  if [ ! -f "$control_prefix.retry-actions-done" ]; then
    kill "$browser_pid" >/dev/null 2>&1 || true
    wait "$browser_pid" >/dev/null 2>&1 || true
    cat "$browser_log"
    printf 'Timed out waiting for AC-017 browser retry assertions.\n' >&2
    return 1
  fi

  compose exec -T backend python /app/backend/e2e/assert_ac017_retry_chain.py \
    >"$TEMP_ARTIFACTS/ac017-retry-db-trace.json"
  compose exec -T backend python /app/backend/e2e/prepare_ac017_parallel_answers.py \
    >"$TEMP_ARTIFACTS/ac017-parallel-answers.json"

  compose up -d --scale worker=2 --wait --wait-timeout 120 worker
  compose exec -T backend python -c \
    'import asyncio; from app.worker_scheduled import scheduled_submit_job_dispatch_task; print(asyncio.run(scheduled_submit_job_dispatch_task({})))'

  python3 - "$STUB_URL" <<'PY'
import json
import sys
import time
import urllib.request

url = sys.argv[1].rstrip("/") + "/__e2e/access"
deadline = time.monotonic() + 90
while time.monotonic() < deadline:
    with urllib.request.urlopen(url, timeout=5) as response:
        access = json.load(response)
    if access.get("parallel_answers", {}).get("active") == 2:
        break
    time.sleep(0.05)
else:
    raise SystemExit("AC-017 parallel provider calls did not overlap")
PY
  touch "$control_prefix.parallel-answers-inflight"

  attempt=0
  while [ "$attempt" -lt "${AC017_REAL_STACK_DRIVER_POLLS:-600}" ]; do
    if [ -f "$control_prefix.parallel-retries-done" ]; then
      break
    fi
    if ! kill -0 "$browser_pid" >/dev/null 2>&1; then
      wait "$browser_pid" || true
      cat "$browser_log"
      return 1
    fi
    attempt=$((attempt + 1))
    sleep 0.5
  done
  if [ ! -f "$control_prefix.parallel-retries-done" ]; then
    cat "$browser_log"
    printf 'Timed out waiting for AC-017 same-root retries during worker claims.\n' >&2
    return 1
  fi

  compose exec -T backend python /app/backend/e2e/assert_ac017_parallel_answers_inflight.py \
    >"$TEMP_ARTIFACTS/ac017-parallel-answers-inflight.json"
  for marker in AC017_PARALLEL_ANSWER_A AC017_PARALLEL_ANSWER_B; do
    compose exec -T llm-stub python -c \
      'import json,sys,urllib.request; data=json.dumps({"marker":sys.argv[1]}).encode(); urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8080/__e2e/release", data=data, headers={"Content-Type":"application/json"}, method="POST"), timeout=5).read()' \
      "$marker"
  done
  compose exec -T backend python /app/backend/e2e/assert_ac017_parallel_answers.py \
    180 >"$TEMP_ARTIFACTS/ac017-parallel-answers-final.json"
  touch "$control_prefix.answers-complete"

  set +e
  wait "$browser_pid"
  local browser_status=$?
  set -e
  cat "$browser_log"
  if [ "$browser_status" -ne 0 ]; then
    return "$browser_status"
  fi
}

run_ac024_real_stack() {
  local control_prefix="$TEMP_ARTIFACTS/ac024-control"
  local browser_log="$TEMP_ARTIFACTS/ac024-browser.log"
  local browser_pid
  local attempt=0

  compose exec -T llm-stub python -c \
    'import urllib.request; urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8080/__e2e/reset", data=b"{}", method="POST"), timeout=5).read()'
  compose exec -T backend python /app/backend/e2e/seed_ac024_legacy_jd.py \
    >"$TEMP_ARTIFACTS/ac024-seed.json"

  cd "$PROJECT_DIR/frontend"
  set +e
  REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL="$BASE_URL" \
    AC024_SEED_PATH="$TEMP_ARTIFACTS/ac024-seed.json" \
    AC024_CONTROL_PREFIX="$control_prefix" \
    AC024_BROWSER_TRACE="$TEMP_ARTIFACTS/ac024-browser-result.json" \
    run_frontend_playwright tests/e2e/upload-legacy-jd-ac024-real-stack.spec.js \
      --timeout "${AC024_REAL_STACK_TEST_TIMEOUT:-240000}" \
      >"$browser_log" 2>&1 &
  browser_pid=$!
  set -e

  while [ "$attempt" -lt "${AC024_REAL_STACK_DRIVER_POLLS:-600}" ]; do
    if [ -f "$control_prefix.approved" ]; then
      break
    fi
    if ! kill -0 "$browser_pid" >/dev/null 2>&1; then
      wait "$browser_pid" || true
      cat "$browser_log"
      return 1
    fi
    attempt=$((attempt + 1))
    sleep 0.5
  done
  if [ ! -f "$control_prefix.approved" ]; then
    kill "$browser_pid" >/dev/null 2>&1 || true
    wait "$browser_pid" >/dev/null 2>&1 || true
    cat "$browser_log"
    printf 'Timed out waiting for AC-024 approval assertions.\n' >&2
    return 1
  fi

  compose exec -T backend python /app/backend/e2e/capture_ac024_read_baseline.py \
    /tmp/ac024-read-baseline.json \
    >"$TEMP_ARTIFACTS/ac024-read-baseline.json"
  touch "$control_prefix.read-baseline-ready"

  set +e
  wait "$browser_pid"
  local browser_status=$?
  set -e
  cat "$browser_log"
  if [ "$browser_status" -ne 0 ]; then
    return "$browser_status"
  fi

  compose exec -T llm-stub python -c \
    'import json,urllib.request; print(json.dumps(json.load(urllib.request.urlopen("http://127.0.0.1:8080/__e2e/access", timeout=5))))' \
    >"$TEMP_ARTIFACTS/ac024-provider-access.json"

  local backend_container
  backend_container=$(compose ps -q backend)
  docker cp "$TEMP_ARTIFACTS/ac024-seed.json" "$backend_container:/tmp/ac024-seed.json" >/dev/null
  docker cp "$TEMP_ARTIFACTS/ac024-browser-result.json" "$backend_container:/tmp/ac024-browser-result.json" >/dev/null
  docker cp "$TEMP_ARTIFACTS/ac024-read-baseline.json" "$backend_container:/tmp/ac024-read-baseline.json" >/dev/null
  docker cp "$TEMP_ARTIFACTS/ac024-provider-access.json" "$backend_container:/tmp/ac024-provider-access.json" >/dev/null
  docker cp "$PROJECT_DIR/backend/e2e/assert_ac024_legacy_jd.py" \
    "$backend_container:/app/backend/e2e/assert_ac024_legacy_jd.py" >/dev/null
  compose exec -T backend python /app/backend/e2e/assert_ac024_legacy_jd.py \
    /tmp/ac024-seed.json \
    /tmp/ac024-browser-result.json \
    /tmp/ac024-read-baseline.json \
    /tmp/ac024-provider-access.json \
    >"$TEMP_ARTIFACTS/ac024-db-trace.json"
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

if [ "${REAL_STACK_ONLY_AC016:-0}" = "1" ]; then
  run_ac016_real_stack
  exit 0
fi

if [ "${REAL_STACK_ONLY_AC017:-0}" = "1" ]; then
  run_ac017_real_stack
  exit 0
fi

if [ "${REAL_STACK_ONLY_AC024:-0}" = "1" ]; then
  run_ac024_real_stack
  exit 0
fi

if [ "${REAL_STACK_ONLY_AC011:-0}" = "1" ] \
  || {
    [ "${REAL_STACK_ONLY_AC013:-0}" != "1" ] \
      && \
    [ "${REAL_STACK_ONLY_AC001_AC002:-0}" != "1" ] \
      && [ "${REAL_STACK_ONLY_AC022:-0}" != "1" ] \
      && [ "${REAL_STACK_ONLY_AC007:-0}" != "1" ] \
      && [ "${REAL_STACK_ONLY_AC007_QUEUE:-0}" != "1" ] \
      && [ "${REAL_STACK_ONLY_AC009:-0}" != "1" ] \
      && [ "${REAL_STACK_ONLY_AC010:-0}" != "1" ]
  }; then
  run_ac011_real_stack
  if [ "${REAL_STACK_ONLY_AC011:-0}" = "1" ]; then
    exit 0
  fi
fi

if [ "${REAL_STACK_ONLY_AC013:-0}" = "1" ]; then
  run_ac013_real_stack
  exit 0
fi

if [ "${REAL_STACK_ONLY_AC010:-0}" = "1" ]; then
  compose stop worker >/dev/null
  compose exec -T backend python /app/backend/e2e/seed_ac010_tasks.py \
    >"$TEMP_ARTIFACTS/ac010-seed.json"
  ac010_control="$TEMP_ARTIFACTS/ac010-revision7"
  ac010_browser_log="$TEMP_ARTIFACTS/ac010-browser.log"

  cd "$PROJECT_DIR/frontend"
  REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL="$BASE_URL" \
    AC010_SEED_PATH="$TEMP_ARTIFACTS/ac010-seed.json" \
    AC010_REVISION7_SIGNAL="$ac010_control.signal" \
    AC010_REVISION7_SIGNAL_READY="$ac010_control.ready" \
    AC010_BROWSER_TRACE="$TEMP_ARTIFACTS/ac010-browser-result.json" \
    run_frontend_playwright tests/e2e/upload-task-center-ac010-real-stack.spec.js \
      --timeout "${AC010_REAL_STACK_TEST_TIMEOUT:-180000}" \
      >"$ac010_browser_log" 2>&1 &
  ac010_browser_pid=$!

  ac010_wait=0
  while [ ! -f "$ac010_control.signal" ] && [ "$ac010_wait" -lt 600 ]; do
    if ! kill -0 "$ac010_browser_pid" >/dev/null 2>&1; then
      wait "$ac010_browser_pid" || true
      cat "$ac010_browser_log" >&2
      exit 1
    fi
    ac010_wait=$((ac010_wait + 1))
    sleep 0.2
  done
  if [ ! -f "$ac010_control.signal" ]; then
    printf 'Timed out waiting for the real AC-010 revision 8 SSE frame.\n' >&2
    kill "$ac010_browser_pid" >/dev/null 2>&1 || true
    wait "$ac010_browser_pid" >/dev/null 2>&1 || true
    cat "$ac010_browser_log" >&2
    exit 1
  fi

  ac010_import_id=$(python3 - "$ac010_control.signal" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["import_id"])
PY
)
  compose exec -T backend python /app/backend/e2e/prepare_ac010_tasks.py \
    --revision "$ac010_import_id" 7 >"$TEMP_ARTIFACTS/ac010-revision7.json"
  touch "$ac010_control.ready"

  set +e
  wait "$ac010_browser_pid"
  ac010_browser_status=$?
  set -e
  cat "$ac010_browser_log"
  if [ "$ac010_browser_status" -ne 0 ]; then
    exit "$ac010_browser_status"
  fi

  read -r ac010_import_a ac010_import_b ac010_import_b_failed < <(
    python3 - "$TEMP_ARTIFACTS/ac010-seed.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(*(root["import_id"] for root in json.load(stream)["roots"]))
PY
  )
  cd "$PROJECT_DIR"
  compose exec -T backend python /app/backend/e2e/assert_ac010_task_trace.py \
    "$ac010_import_a" "$ac010_import_b" "$ac010_import_b_failed" \
    >"$TEMP_ARTIFACTS/ac010-db-trace.json"
  exit 0
fi

# AC-001/002 and AC-022 normally run first in the shared candidate stack. The
# focused AC-007 loop can skip them while iterating on the retry scenario.
if [ "${REAL_STACK_ONLY_AC007:-0}" != "1" ] \
  && [ "${REAL_STACK_ONLY_AC007_QUEUE:-0}" != "1" ] \
  && [ "${REAL_STACK_ONLY_AC009:-0}" != "1" ]; then
# AC-022 can run alone without the heavier AC-001/002 browser scenario.
if [ "${REAL_STACK_ONLY_AC022:-0}" != "1" ]; then
# AC-001/002: real API + SQLite + browser pagination and authorized target lookup.
compose exec -T backend python /app/backend/e2e/seed_ac001_ac002.py \
  >"$TEMP_ARTIFACTS/ac001-ac002-seed.json"
cd "$PROJECT_DIR/frontend"
REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL="$BASE_URL" \
  AC001_AC002_BROWSER_TRACE="$TEMP_ARTIFACTS/ac001-ac002-browser-result.json" \
  AC001_AC002_DB_TRACE="$TEMP_ARTIFACTS/ac001-ac002-db-trace.json" \
  run_frontend_playwright tests/e2e/interview-pagination-real-stack.spec.js \
  --timeout "${AC001_AC002_REAL_STACK_TEST_TIMEOUT:-780000}"
cd "$PROJECT_DIR"
compose exec -T backend python /app/backend/e2e/assert_ac001_ac002_trace.py - \
  <"$TEMP_ARTIFACTS/ac001-ac002-browser-result.json" \
  >"$TEMP_ARTIFACTS/ac001-ac002-db-trace.json"
if [ "${REAL_STACK_ONLY_AC001_AC002:-0}" = "1" ]; then
  exit 0
fi
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
fi

# AC-007: two owner sessions race a real retry while worker delivery is stopped.
# Restart the same worker only after both API requests and cross-owner 404 checks.
if [ "${REAL_STACK_ONLY_AC009:-0}" != "1" ] \
  && [ "${REAL_STACK_ONLY_AC007_QUEUE:-0}" != "1" ] \
  && [ "${REAL_STACK_ONLY_AC022:-0}" != "1" ]; then
cd "$PROJECT_DIR"
compose exec -T backend python /app/backend/e2e/seed_ac007_owner_retry.py \
  >"$TEMP_ARTIFACTS/ac007-seed.json"
compose stop worker
ac007_control="$TEMP_ARTIFACTS/ac007-worker"
ac007_monitor_log="$TEMP_ARTIFACTS/ac007-worker-monitor.log"
restart_ac007_worker_after_owner_retry() {
  local attempt=0
  local dispatch_attempt=0
  local dispatch_log="$TEMP_ARTIFACTS/ac007-dispatch.log"
  while [ "$attempt" -lt 1200 ]; do
    if [ -f "$ac007_control.restart" ]; then
      compose up -d --wait --wait-timeout 120 worker >>"$ac007_monitor_log" 2>&1
      while [ ! -f "$ac007_control.restart.finished" ] && [ "$dispatch_attempt" -lt 160 ]; do
        compose exec -T worker python -c \
          'import asyncio; from app.worker_scheduled import scheduled_submit_job_dispatch_task; asyncio.run(scheduled_submit_job_dispatch_task({}))' \
          >>"$dispatch_log" 2>&1 || return 1
        dispatch_attempt=$((dispatch_attempt + 1))
        sleep 2
      done
      touch "$ac007_control.done"
      [ -f "$ac007_control.restart.finished" ] && return 0
      printf 'Timed out waiting for the AC-007 owner retry to complete.\n' >"$ac007_monitor_log"
      return 1
    fi
    attempt=$((attempt + 1))
    sleep 0.25
  done
  printf 'Timed out waiting for the AC-007 owner retry restart signal.\n' >"$ac007_monitor_log"
  return 1
}
restart_ac007_worker_after_owner_retry &
ac007_monitor_pid=$!
ac007_owner_id=$(python3 - "$TEMP_ARTIFACTS/ac007-seed.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["owner_id"])
PY
)
ac007_rootless_queue_id=$(python3 - "$TEMP_ARTIFACTS/ac007-seed.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["rootless_queue_id"])
PY
)
ac007_public_contribution_queue_id=$(python3 - "$TEMP_ARTIFACTS/ac007-seed.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["public_contribution_queue_id"])
PY
)
ac007_public_contribution_question=$(python3 - "$TEMP_ARTIFACTS/ac007-seed.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["public_contribution_question"])
PY
)

cd "$PROJECT_DIR/frontend"
set +e
REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL="$BASE_URL" \
  REAL_STACK_ADMIN_USERNAME=real_stack_admin \
  REAL_STACK_ADMIN_PASSWORD=real-stack-admin-password-123 \
  AC007_EXPECTED_OWNER_ID="$ac007_owner_id" \
  AC007_ROOTLESS_QUEUE_ID="$ac007_rootless_queue_id" \
  AC007_PUBLIC_CONTRIBUTION_QUEUE_ID="$ac007_public_contribution_queue_id" \
  AC007_PUBLIC_CONTRIBUTION_QUESTION="$ac007_public_contribution_question" \
  AC007_BROWSER_TRACE="$TEMP_ARTIFACTS/ac007-browser-result.json" \
  AC007_WORKER_RESTART_SIGNAL="$ac007_control.restart" \
  run_frontend_playwright tests/e2e/upload-owner-retry-real-stack.spec.js \
  --timeout "${AC007_REAL_STACK_TEST_TIMEOUT:-320000}"
browser_status=$?
if [ "$browser_status" -ne 0 ]; then
  kill "$ac007_monitor_pid" >/dev/null 2>&1 || true
  wait "$ac007_monitor_pid" >/dev/null 2>&1 || true
  exit "$browser_status"
fi
wait "$ac007_monitor_pid"
set -e
read -r ac007_import_id ac007_checkpoint_hash ac007_rootless_queue_id \
  ac007_rootless_interview_id ac007_public_contribution_queue_id < <(
  python3 - "$TEMP_ARTIFACTS/ac007-seed.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    seed = json.load(stream)
print(seed["import_id"], seed["checkpoint_hash"], seed["rootless_queue_id"],
      seed["rootless_interview_id"], seed["public_contribution_queue_id"])
PY
)
cd "$PROJECT_DIR"
compose exec -T backend python /app/backend/e2e/assert_ac007_owner_retry_trace.py \
  "$ac007_import_id" "$ac007_checkpoint_hash" "$ac007_rootless_queue_id" \
  "$ac007_rootless_interview_id" "$ac007_public_contribution_queue_id" \
  >"$TEMP_ARTIFACTS/ac007-db-trace.json"
if [ "${REAL_STACK_ONLY_AC007:-0}" = "1" ]; then
  exit 0
fi
fi

if [ "${REAL_STACK_ONLY_AC007_QUEUE:-0}" = "1" ]; then
  cd "$PROJECT_DIR"
  compose stop worker
  compose exec -T backend python /app/backend/e2e/ac007_queue_real_stack.py seed-fairness \
    >"$TEMP_ARTIFACTS/ac007-queue-seed.json"
  read -r ac007_queue_owner ac007_queue_admin ac007_queue_request \
    ac007_queue_private_interview ac007_queue_source_interview ac007_queue_public_interview < <(
      python3 - "$TEMP_ARTIFACTS/ac007-queue-seed.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    seed = json.load(stream)
print(seed["owner_id"], seed["admin_id"], seed["request_id"],
      seed["private_interview_id"], seed["source_interview_id"], seed["public_interview_id"])
PY
    )

  compose exec -T backend python /app/backend/e2e/ac007_queue_real_stack.py \
    watch-fairness "$ac007_queue_request" "$ac007_queue_private_interview" \
    "$ac007_queue_source_interview" "$ac007_queue_public_interview" \
    --timeout "${AC007_QUEUE_FAIRNESS_TIMEOUT:-120}" \
    >"$TEMP_ARTIFACTS/ac007-queue-fairness.json" &
  ac007_fairness_monitor_pid=$!
  compose up -d --scale "worker=${AC007_QUEUE_WORKER_REPLICAS:-2}" \
    --wait --wait-timeout 120 worker
  set +e
  wait "$ac007_fairness_monitor_pid"
  ac007_fairness_status=$?
  set -e
  if [ "$ac007_fairness_status" -ne 0 ]; then
    exit "$ac007_fairness_status"
  fi
  compose exec -T backend python /app/backend/e2e/ac007_queue_real_stack.py \
    wait-fairness-idle "$ac007_queue_request" "$ac007_queue_private_interview" \
    --timeout "${AC007_QUEUE_IDLE_TIMEOUT:-240}" \
    >"$TEMP_ARTIFACTS/ac007-queue-idle.json"

  compose stop worker
  compose exec -T backend python /app/backend/e2e/ac007_queue_real_stack.py \
    seed-lost-dispatch "$ac007_queue_owner" \
    >"$TEMP_ARTIFACTS/ac007-lost-dispatch-seed.json"
  ac007_lost_interview=$(python3 - "$TEMP_ARTIFACTS/ac007-lost-dispatch-seed.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["interview_id"])
PY
  )
  compose stop redis
  compose exec -T -e AC007_EXPECT_QUEUE_OUTAGE=1 backend \
    python /app/backend/e2e/ac007_queue_real_stack.py \
    create-lost-dispatch "$ac007_queue_owner" \
    >"$TEMP_ARTIFACTS/ac007-lost-notification.json"
  ac007_lost_job=$(python3 - "$TEMP_ARTIFACTS/ac007-lost-notification.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(json.load(stream)["job_id"])
PY
  )

  compose up -d --wait --wait-timeout 60 redis
  compose exec -T backend python -c \
    'import asyncio; from app.worker_scheduled import scheduled_submit_job_dispatch_task; print(asyncio.run(scheduled_submit_job_dispatch_task({})))' \
    >"$TEMP_ARTIFACTS/ac007-dispatch-first.log"
  compose exec -T backend python -c \
    'import asyncio; from app.worker_scheduled import scheduled_submit_job_dispatch_task; print(asyncio.run(scheduled_submit_job_dispatch_task({})))' \
    >"$TEMP_ARTIFACTS/ac007-dispatch-second.log"
  compose exec -T backend python /app/backend/e2e/ac007_queue_real_stack.py \
    assert-dispatched "$ac007_lost_job" \
    >"$TEMP_ARTIFACTS/ac007-dispatch-recovery.json"
  compose up -d --scale "worker=${AC007_QUEUE_WORKER_REPLICAS:-2}" \
    --wait --wait-timeout 120 worker
  compose exec -T backend python /app/backend/e2e/ac007_queue_real_stack.py \
    wait-lost-dispatch "$ac007_lost_job" "$ac007_lost_interview" \
    --timeout "${AC007_QUEUE_WORKER_TIMEOUT:-120}" \
    >"$TEMP_ARTIFACTS/ac007-lost-dispatch-final.json"
  compose exec -T backend python /app/backend/e2e/ac007_queue_real_stack.py \
    recover-rootless-retry-gap "$ac007_queue_owner" \
    --timeout "${AC007_QUEUE_WORKER_TIMEOUT:-120}" \
    >"$TEMP_ARTIFACTS/ac007-rootless-reconcile-recovery.json"
  exit 0
fi

if [ "${REAL_STACK_ONLY_AC009:-0}" != "1" ]; then
cd "$PROJECT_DIR/frontend"
REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL="$BASE_URL" \
  run_frontend_playwright tests/e2e/real-stack-smoke.spec.js \
  --timeout "${REAL_STACK_TEST_TIMEOUT:-120000}"

# Earlier independent browser scenarios share a proxy IP. Their accumulated
# refresh calls can exhaust the real 30/minute limit before AC-028 starts.
# Restart only this disposable API process to isolate its in-memory limiter;
# preserve SQLite, Redis, credentials and jobs, and keep production limits intact.
cd "$PROJECT_DIR"
compose restart backend
compose up --no-deps -d --wait --wait-timeout 180 backend

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
      compose exec -T backend python /app/backend/e2e/capture_ac029_resolutions.py \
        "$(cat "$ac029_control.stop")" >"$TEMP_ARTIFACTS/ac029-first-pass-resolutions.json" || return 1
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
  "$ac029_import_id" "$ac029_request_id" --baseline-stdin \
  <"$TEMP_ARTIFACTS/ac029-first-pass-resolutions.json" >"$TEMP_ARTIFACTS/ac029-db-trace.json"
fi

# AC-009: two authenticated browsers enqueue distinct private interviews while
# all workers are stopped. Fix both root timestamps to one second, then run two
# independent ARQ processes with a single concurrent task each.
cd "$PROJECT_DIR"
compose stop worker >/dev/null 2>&1 || true
ac009_control="$TEMP_ARTIFACTS/ac009-worker-start"
ac009_browser_log="$TEMP_ARTIFACTS/ac009-browser.log"
ac009_monitor_log="$TEMP_ARTIFACTS/ac009-worker-monitor.log"
cd "$PROJECT_DIR/frontend"
set +e
REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL="$BASE_URL" \
  AC009_WORKER_START_SIGNAL="$ac009_control" \
  AC009_BROWSER_TRACE="$TEMP_ARTIFACTS/ac009-browser-result.json" \
  run_frontend_playwright tests/e2e/upload-two-owner-isolation-real-stack.spec.js \
  --timeout "${AC009_REAL_STACK_TEST_TIMEOUT:-420000}" \
  >"$ac009_browser_log" 2>&1 &
ac009_browser_pid=$!
set -e

ac009_wait=0
while [ ! -f "$ac009_control" ] && [ "$ac009_wait" -lt 1800 ]; do
  if ! kill -0 "$ac009_browser_pid" >/dev/null 2>&1; then
    wait "$ac009_browser_pid" || true
    cat "$ac009_browser_log" >&2
    exit 1
  fi
  ac009_wait=$((ac009_wait + 1))
  sleep 0.25
done
if [ ! -f "$ac009_control" ]; then
  printf 'Timed out waiting for AC-009 browsers to submit both uploads.\n' >"$ac009_monitor_log"
  kill "$ac009_browser_pid" >/dev/null 2>&1 || true
  wait "$ac009_browser_pid" >/dev/null 2>&1 || true
  cat "$ac009_monitor_log" >&2
  exit 1
fi

read -r ac009_import_a ac009_import_b < <(
  python3 - "$ac009_control" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    print(*json.load(stream)["import_ids"])
PY
)
cd "$PROJECT_DIR"
compose exec -T backend python /app/backend/e2e/force_ac009_same_second.py \
  "$ac009_import_a" "$ac009_import_b" >"$TEMP_ARTIFACTS/ac009-same-second.json"
compose up -d --wait --wait-timeout 120 worker-ac009-a worker-ac009-b \
  >>"$ac009_monitor_log" 2>&1
touch "$ac009_control.done"

set +e
wait "$ac009_browser_pid"
ac009_browser_status=$?
set -e
cat "$ac009_browser_log"
if [ "$ac009_browser_status" -ne 0 ]; then
  exit "$ac009_browser_status"
fi

ac009_answer_ready=0
for ac009_answer_attempt in $(seq 1 90); do
  compose exec -T worker-ac009-a python -c \
    'import asyncio; from app.worker_scheduled import scheduled_submit_job_dispatch_task; asyncio.run(scheduled_submit_job_dispatch_task({}))' \
    >>"$ac009_monitor_log" 2>&1 || true
  if compose exec -T backend python /app/backend/e2e/ac009_answers_ready.py \
    "$ac009_import_a" "$ac009_import_b" >/dev/null 2>&1; then
    ac009_answer_ready=1
    break
  fi
  sleep 2
done
if [ "$ac009_answer_ready" -ne 1 ]; then
  printf 'Timed out waiting for the two owner-scoped answer jobs.\n' >>"$ac009_monitor_log"
  cat "$ac009_monitor_log" >&2
  exit 1
fi

read -r ac009_user_a ac009_user_b < <(
  python3 - "$TEMP_ARTIFACTS/ac009-browser-result.json" <<'PY'
import json
import sys
with open(sys.argv[1], encoding="utf-8") as stream:
    trace = json.load(stream)
print(*trace["users"])
PY
)
compose exec -T llm-stub python -c \
  'import urllib.request; print(urllib.request.urlopen("http://127.0.0.1:8080/__e2e/ac009-overlap").read().decode())' \
  >"$TEMP_ARTIFACTS/ac009-provider-overlap.json"
compose exec -T backend python /app/backend/e2e/assert_ac009_isolation_trace.py \
  "$ac009_import_a" "$ac009_import_b" "$ac009_user_a" "$ac009_user_b" \
  <"$TEMP_ARTIFACTS/ac009-provider-overlap.json" >"$TEMP_ARTIFACTS/ac009-db-trace.json"

if [ "${REAL_STACK_ONLY_AC009:-0}" = "1" ]; then
  exit 0
fi
