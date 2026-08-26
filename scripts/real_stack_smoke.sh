#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="$PROJECT_DIR/docker-compose.real-e2e.yml"
PROJECT="interview-boss-real-e2e-${BASHPID}-$(date +%s)"
PORT="${REAL_STACK_PORT:-18081}"
BASE_URL="http://127.0.0.1:${PORT}"
TEMP_ARTIFACTS="$(mktemp -d "${TMPDIR:-/tmp}/interview-boss-real-stack.XXXXXX")"
FINAL_ARTIFACT_ROOT="$PROJECT_DIR/test-results/real-stack"
RUN_STATUS=0

compose() {
  REAL_STACK_PORT="$PORT" docker compose --project-name "$PROJECT" -f "$COMPOSE_FILE" "$@"
}

copy_failure_artifacts() {
  mkdir -p "$FINAL_ARTIFACT_ROOT/$PROJECT"
  cp -R "$TEMP_ARTIFACTS/." "$FINAL_ARTIFACT_ROOT/$PROJECT/"
  printf 'Real-stack failure artifacts: %s\n' "$FINAL_ARTIFACT_ROOT/$PROJECT" >&2
}

cleanup() {
  RUN_STATUS=$?
  set +e

  compose ps >"$TEMP_ARTIFACTS/compose-ps.txt" 2>&1
  compose logs --no-color >"$TEMP_ARTIFACTS/compose.log" 2>&1
  compose exec -T backend python -c \
    'import sqlite3; c=sqlite3.connect("/app/backend/data/interview-boss.db"); print(c.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1").fetchone())' \
    >"$TEMP_ARTIFACTS/schema-version.txt" 2>&1

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

compose config --quiet
compose build backend worker nginx oauth-gateway llm-stub
compose up -d --wait --wait-timeout 180

curl --fail --silent --show-error --retry 30 --retry-delay 2 --retry-connrefused "$BASE_URL/" >/dev/null
curl --fail --silent --show-error --retry 30 --retry-delay 2 --retry-connrefused "$BASE_URL/api/health" >/dev/null

cd "$PROJECT_DIR/frontend"
REAL_STACK_E2E=1 PLAYWRIGHT_BASE_URL="$BASE_URL" \
  npx playwright test tests/e2e/real-stack-smoke.spec.js \
  --config tests/playwright.config.js \
  --timeout "${REAL_STACK_TEST_TIMEOUT:-120000}"
