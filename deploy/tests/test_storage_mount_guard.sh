#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
STORAGE_LIB="$PROJECT_DIR/deploy/storage-retention.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

[[ -f "$STORAGE_LIB" ]] || fail "storage retention library is not implemented"
# shellcheck source=/dev/null
source "$STORAGE_LIB"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT
fake_findmnt="$tmp_dir/findmnt"

cat > "$fake_findmnt" <<'EOF'
#!/usr/bin/env bash
case "${FAKE_FINDMNT_STATE:-unmounted}" in
  mounted) printf '/data /dev/vdb ext4\n' ;;
  tmpfs) printf '/data tmpfs tmpfs\n' ;;
  bind) printf '/data /home/ubuntu/fallback ext4\n' ;;
esac
EOF
chmod +x "$fake_findmnt"

STORAGE_FINDMNT_BIN="$fake_findmnt" FAKE_FINDMNT_STATE=unmounted \
  storage_data_mount_available && fail "unmounted /data was accepted"

STORAGE_FINDMNT_BIN="$fake_findmnt" FAKE_FINDMNT_STATE=unmounted \
  storage_require_data_mount >/dev/null 2>&1 && fail "unmounted /data allowed writes"

STORAGE_FINDMNT_BIN="$fake_findmnt" FAKE_FINDMNT_STATE=tmpfs \
  storage_data_mount_available && fail "tmpfs /data was accepted"

STORAGE_FINDMNT_BIN="$fake_findmnt" FAKE_FINDMNT_STATE=bind \
  storage_data_mount_available && fail "root-backed bind mount was accepted"

STORAGE_FINDMNT_BIN="$fake_findmnt" FAKE_FINDMNT_STATE=mounted \
  storage_data_mount_available || fail "real /data mount was rejected"

project_dir="$tmp_dir/project"
mkdir -p "$project_dir/backend/data" "$project_dir/backups"
touch "$project_dir/backend/data/interview-boss.db"
touch "$project_dir/backend/data/interview-boss.db-wal"
touch "$project_dir/backend/data/interview-boss.db-shm"
mkdir -p "$tmp_dir/cache/ms-playwright"
touch -d '10 days ago' "$tmp_dir/cache/ms-playwright/browser.bin"

BACKUP_RETENTION_DAYS=7 BACKUP_MIN_KEEP_FILES=3 \
  storage_cleanup_backups "$project_dir"

[[ -f "$project_dir/backend/data/interview-boss.db" ]] || fail "current database was removed"
[[ -f "$project_dir/backend/data/interview-boss.db-wal" ]] || fail "database WAL was removed"
[[ -f "$project_dir/backend/data/interview-boss.db-shm" ]] || fail "database SHM was removed"
[[ -f "$tmp_dir/cache/ms-playwright/browser.bin" ]] || fail "Playwright cache was removed"

echo "PASS: mount guard protects unmounted /data, runtime DB, WAL/SHM, and Playwright cache"
