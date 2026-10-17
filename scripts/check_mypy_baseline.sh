#!/bin/bash
set -uo pipefail

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BASELINE_FILE="${MYPY_BASELINE_FILE:-$PROJECT_DIR/scripts/mypy_baseline.txt}"
TARGET="${MYPY_TARGET:-backend/app}"
MYPY_BASELINE="${MYPY_BASELINE:-$(tr -d '[:space:]' < "$BASELINE_FILE")}"

if ! [[ "$MYPY_BASELINE" =~ ^[0-9]+$ ]]; then
  echo "mypy baseline is not numeric: $MYPY_BASELINE" >&2
  exit 1
fi

set +e
MYPY_OUTPUT="$(uv run mypy "$TARGET" 2>&1)"
MYPY_STATUS=$?
set -e
printf '%s\n' "$MYPY_OUTPUT"

MYPY_ERRORS="$(printf '%s\n' "$MYPY_OUTPUT" | sed -n 's/^Found \([0-9][0-9]*\) errors\{0,1\}.*/\1/p' | tail -n 1)"
if ! [[ "$MYPY_ERRORS" =~ ^[0-9]+$ ]]; then
  echo "mypy did not report a stable error count" >&2
  exit 1
fi

if [ "$MYPY_ERRORS" -gt "$MYPY_BASELINE" ]; then
  echo "FAIL mypy baseline: $MYPY_ERRORS errors > budget $MYPY_BASELINE" >&2
  exit 1
fi

if [ "$MYPY_ERRORS" -eq 0 ] && [ "$MYPY_STATUS" -eq 0 ]; then
  echo "PASS mypy baseline: no errors"
else
  echo "WARN mypy baseline: $MYPY_ERRORS existing errors (budget $MYPY_BASELINE)"
fi
exit 0
