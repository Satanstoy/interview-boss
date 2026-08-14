#!/bin/bash
# Line-guard: blocking gate preventing source files from growing beyond MAX_LINES.
# Known over-limit files (God-files, Stage B targets) are listed in
# scripts/line_guard_overrides.txt as "relative/path  current_lines".
# The gate FAILs when:
#   (1) any file NOT in the list exceeds MAX_LINES, or
#   (2) an allowlisted file grows beyond its recorded count (blocks further bloat).
# Stage B shrinks/removes entries as god-files get split.
set -uo pipefail

MAX_LINES="${MAX_LINES:-1500}"
PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
OVERRIDES_FILE="$PROJECT_DIR/scripts/line_guard_overrides.txt"
failed=0

declare -A cap_by_rel=()
if [ -f "$OVERRIDES_FILE" ]; then
  while IFS= read -r line; do
    [ -z "$line" ] && continue
    case "$line" in \#*) continue;; esac
    rel="${line%% *}"
    cap="${line##* }"
    cap_by_rel["$rel"]="$cap"
  done < "$OVERRIDES_FILE"
fi

check_one() {
  local fpath="$1"
  local rel="${fpath#"$PROJECT_DIR"/}"
  local n="$(( $(wc -l < "$fpath") ))"
  local limit="$MAX_LINES"
  if [ -n "${cap_by_rel[$rel]:-}" ]; then
    limit="${cap_by_rel[$rel]}"
  fi
  if [ "$n" -gt "$limit" ]; then
    if [ "$limit" -eq "$MAX_LINES" ]; then
      printf 'FAIL line-guard: %s %s lines (max %s)\n' "$rel" "$n" "$MAX_LINES"
    else
      printf 'FAIL line-guard: %s %s lines (overrides cap %s, must not grow)\n' "$rel" "$n" "$limit"
    fi
    failed=1
  fi
}

while IFS= read -r f; do
  [ -n "$f" ] || continue
  check_one "$f"
done < <(find "$PROJECT_DIR/backend/app" -name '*.py' -type f)

while IFS= read -r f; do
  [ -n "$f" ] || continue
  check_one "$f"
done < <(find "$PROJECT_DIR/frontend/src" \( -name '*.vue' -o -name '*.js' \) -type f)

if [ "$failed" -eq 0 ]; then
  printf 'PASS line-guard: no file exceeds %s lines / overrides caps\n' "$MAX_LINES"
  exit 0
else
  exit 1
fi
