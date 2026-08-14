#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_FILE="${EVAL_WORKER_LOCK_FILE:-/tmp/interview-boss-eval-worker.lock}"
DB_PATH="${EVAL_DB_PATH:-${PROJECT_DIR}/backend/data/interview-boss.db}"

mkdir -p "$(dirname "$LOCK_FILE")"
exec 9>"$LOCK_FILE"
flock -n 9 || exit 0

if [[ ! -f "$DB_PATH" ]]; then
  exit 0
fi

pending="$(DB_PATH="$DB_PATH" python3 - <<'PY'
import os
import sqlite3

path = os.environ["DB_PATH"]
try:
    with sqlite3.connect(path, timeout=2) as conn:
        row = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM eval_runs "
            "WHERE status IN ('created', 'queued', 'running'))"
        ).fetchone()
except (sqlite3.DatabaseError, OSError):
    row = (0,)
print(row[0])
PY
)"

if [[ "$pending" != "1" ]]; then
  exit 0
fi

cd "$PROJECT_DIR"
exec docker compose --profile eval run --rm --no-deps eval-worker
