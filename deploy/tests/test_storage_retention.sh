#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
STORAGE_LIB="$PROJECT_DIR/deploy/storage-retention.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

assert_file() {
  local path="$1"
  [[ -f "$path" ]] || fail "expected file: $path"
}

assert_absent() {
  local path="$1"
  [[ ! -e "$path" ]] || fail "expected path to be removed: $path"
}

[[ -f "$STORAGE_LIB" ]] || fail "storage retention library is not implemented"
# shellcheck source=/dev/null
source "$STORAGE_LIB"

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

mkdir -p "$tmp_dir/backups" "$tmp_dir/backend/data/backups" "$tmp_dir/backend/data/evaluations" "$tmp_dir/backend/data" "$tmp_dir/archive"

for index in 1 2 3 4 5; do
  touch -d "10 days ago" "$tmp_dir/backups/interview-boss_2026081${index}_000000.db"
done
touch -d "1 day ago" "$tmp_dir/backups/interview-boss_20260824_000000.db"

for index in 1 2 3 4 5; do
  touch -d "10 days ago" "$tmp_dir/backups/redis_2026081${index}_000000.rdb"
done
touch -d "1 day ago" "$tmp_dir/backups/redis_20260824_000000.rdb"

for index in 1 2 3 4 5; do
  touch -d "10 days ago" "$tmp_dir/backend/data/backups/pre_migration_v00${index}_2026081${index}.db"
done

for index in 1 2 3 4; do
  touch -d "10 days ago" "$tmp_dir/backend/data/interview-boss.db.bak.2026081${index}"
done

for index in 1 2 3 4 5; do
  touch -d "10 days ago" "$tmp_dir/backend/data/evaluations/eval_history_2026081${index}.json"
done
touch -d "1 day ago" "$tmp_dir/backend/data/evaluations/eval_history_20260824.json"

for index in 1 2 3 4 5; do
  mkdir -p "$tmp_dir/archive/interview-boss-backup-2026081${index}"
  touch -d "10 days ago" "$tmp_dir/archive/interview-boss-backup-2026081${index}"
done
mkdir -p "$tmp_dir/archive/interview-boss-backup-20260824"
touch -d "1 day ago" "$tmp_dir/archive/interview-boss-backup-20260824"

touch "$tmp_dir/backups/keep-unrelated.txt"

PROJECT_ARCHIVE_DIR="$tmp_dir/archive" BACKUP_RETENTION_DAYS=7 BACKUP_MIN_KEEP_FILES=3 \
  storage_cleanup_backups "$tmp_dir"

backup_count="$(find "$tmp_dir/backups" -maxdepth 1 -type f -name 'interview-boss_*.db' | wc -l)"
[[ "$backup_count" -eq 3 ]] || fail "expected 3 project DB backups, got $backup_count"
assert_file "$tmp_dir/backups/interview-boss_20260824_000000.db"

redis_count="$(find "$tmp_dir/backups" -maxdepth 1 -type f -name 'redis_*.rdb' | wc -l)"
[[ "$redis_count" -eq 1 ]] || fail "expected only the recent Redis backup, got $redis_count"
assert_file "$tmp_dir/backups/redis_20260824_000000.rdb"
assert_absent "$tmp_dir/backups/redis_20260811_000000.rdb"

migration_count="$(find "$tmp_dir/backend/data/backups" -maxdepth 1 -type f -name '*.db' | wc -l)"
[[ "$migration_count" -eq 3 ]] || fail "expected 3 migration backups, got $migration_count"

bak_count="$(find "$tmp_dir/backend/data" -maxdepth 1 -type f -name 'interview-boss.db.bak.*' | wc -l)"
[[ "$bak_count" -eq 3 ]] || fail "expected 3 database side backups, got $bak_count"

storage_cleanup_evaluations "$tmp_dir/backend/data/evaluations"
evaluation_count="$(find "$tmp_dir/backend/data/evaluations" -maxdepth 1 -type f -name 'eval_*' | wc -l)"
[[ "$evaluation_count" -eq 3 ]] || fail "expected 3 evaluation artifacts (minimum retention including the recent artifact), got $evaluation_count"
assert_file "$tmp_dir/backend/data/evaluations/eval_history_20260824.json"

archive_count="$(find "$tmp_dir/archive" -mindepth 1 -maxdepth 1 -type d -name 'interview-boss-backup-*' | wc -l)"
[[ "$archive_count" -eq 1 ]] || fail "expected 1 recent full project archive, got $archive_count"
[[ -d "$tmp_dir/archive/interview-boss-backup-20260824" ]] || fail "recent full project archive was removed"

assert_file "$tmp_dir/backups/keep-unrelated.txt"
assert_absent "$tmp_dir/backups/interview-boss_20260811_000000.db"

failure_dir="$tmp_dir/failure"
mkdir -p "$failure_dir"
touch -d "10 days ago" "$failure_dir/redis_old.rdb"
failing_rm="$tmp_dir/failing-rm"
cat > "$failing_rm" <<'EOF'
#!/usr/bin/env bash
exit 19
EOF
chmod +x "$failing_rm"
set +e
STORAGE_RM_BIN="$failing_rm" BACKUP_MIN_KEEP_FILES=0 \
  storage_prune_file_family "$failure_dir" 'redis_*.rdb' 'Redis RDB' 0
failure_rc=$?
set -e
[[ "$failure_rc" -ne 0 ]] || fail "failed backup deletion was reported as success"
assert_file "$failure_dir/redis_old.rdb"

echo "PASS: storage retention keeps recent/minimum backups and removes only expired families"
