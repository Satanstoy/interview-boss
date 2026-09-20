#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND_DIR="$PROJECT_DIR/frontend"

"$PROJECT_DIR/scripts/frontend-deps.sh" prepare

export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/data/home/ubuntu/cache/ms-playwright}"
playwright_bin="$FRONTEND_DIR/node_modules/.bin/playwright"
[ -x "$playwright_bin" ] || {
  echo "[frontend-test] ERROR: 本地 Playwright 不存在，请先准备前端依赖" >&2
  exit 1
}

exec "$playwright_bin" test --config "$FRONTEND_DIR/playwright.config.js" "$@"
