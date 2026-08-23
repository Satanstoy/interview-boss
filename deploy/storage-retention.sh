#!/usr/bin/env bash

# Shared storage retention helpers. This file is sourced by docker-deploy.sh
# and deliberately has no top-level side effects.

storage_retention_log() {
  printf '[storage-retention] %s\n' "$*"
}

storage_data_mount_available() {
  local findmnt_bin="${STORAGE_FINDMNT_BIN:-findmnt}"
  local mount_info target source fstype
  mount_info=$("$findmnt_bin" -M /data -n -o TARGET,SOURCE,FSTYPE 2>/dev/null || true)
  read -r target source fstype <<< "$mount_info"
  [[ "$target" == "/data" ]] || return 1
  [[ "$source" == /dev/* ]] || return 1
  [[ "$fstype" != "tmpfs" && "$fstype" != "overlay" ]] || return 1
}

storage_require_data_mount() {
  if storage_data_mount_available; then
    return 0
  fi
  storage_retention_log "ERROR: /data is not a real mount; refusing cache/backup writes"
  return 1
}

storage_prune_file_family() {
  local directory="$1"
  local pattern="$2"
  local retention_days="${BACKUP_RETENTION_DAYS:-7}"
  local min_keep="${BACKUP_MIN_KEEP_FILES:-3}"
  local cutoff_epoch
  local -a entries=()
  local entry path mtime_epoch index=0

  [[ -d "$directory" ]] || return 0

  [[ "$retention_days" =~ ^[0-9]+$ ]] || {
    storage_retention_log "invalid BACKUP_RETENTION_DAYS=$retention_days"
    return 2
  }
  [[ "$min_keep" =~ ^[0-9]+$ ]] || {
    storage_retention_log "invalid BACKUP_MIN_KEEP_FILES=$min_keep"
    return 2
  }

  cutoff_epoch=$(( $(date +%s) - retention_days * 86400 ))
  while IFS= read -r entry; do
    entries+=("$entry")
  done < <(
    find "$directory/." -maxdepth 1 -type f -name "$pattern" -printf '%T@ %p\n' |
      sort -nr
  )

  for entry in "${entries[@]}"; do
    path="${entry#* }"
    mtime_epoch="${entry%%.*}"

    if (( index < min_keep )); then
      index=$((index + 1))
      continue
    fi

    if (( mtime_epoch < cutoff_epoch )); then
      if [[ "${STORAGE_RETENTION_DRY_RUN:-0}" == "1" ]]; then
        storage_retention_log "would remove expired backup: $path"
      else
        rm -f -- "$path"
        storage_retention_log "removed expired backup: $path"
      fi
    fi
    index=$((index + 1))
  done
}

storage_cleanup_project_archives() {
  local archive_dir="${PROJECT_ARCHIVE_DIR:-/data/projects/archive}"
  local cutoff_epoch archive link target referenced

  storage_data_mount_available || {
    storage_retention_log "WARNING: /data is not mounted; skipped full project archive cleanup"
    return 0
  }
  [[ -d "$archive_dir" ]] || return 0
  cutoff_epoch=$(( $(date +%s) - ${BACKUP_RETENTION_DAYS:-7} * 86400 ))

  for archive in "$archive_dir"/interview-boss-backup-*; do
    [[ -d "$archive" && ! -L "$archive" ]] || continue
    referenced=0
    while IFS= read -r -d '' link; do
      target=$(readlink -f "$link" 2>/dev/null || true)
      if [[ "$target" == "$archive" ]]; then
        referenced=1
        break
      fi
    done < <(find /opt -maxdepth 1 -type l -name 'interview-boss-backup-*' -print0 2>/dev/null)
    (( referenced == 0 )) || continue

    if [[ "$(stat -c %Y "$archive" 2>/dev/null || echo 0)" -lt "$cutoff_epoch" ]]; then
      if [[ "${STORAGE_RETENTION_DRY_RUN:-0}" == "1" ]]; then
        storage_retention_log "would remove expired full project archive: $archive"
      else
        rm -rf -- "$archive"
        storage_retention_log "removed expired full project archive: $archive"
      fi
    fi
  done
}

storage_cleanup_backups() {
  local project_dir="$1"

  if storage_data_mount_available; then
    storage_prune_file_family "$project_dir/backups" 'interview-boss_*.db'
    storage_prune_file_family "$project_dir/backups" 'redis_*.rdb'
  else
    storage_retention_log "WARNING: /data is not mounted; skipped /data-backed project backups"
  fi
  storage_cleanup_project_archives
  storage_prune_file_family "$project_dir/backend/data/backups" '*.db'
  storage_prune_file_family "$project_dir/backend/data" 'interview-boss.db.bak.*'
}
