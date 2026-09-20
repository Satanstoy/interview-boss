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
  local item_label="${3:-backup}"
  local min_keep_override="${4:-}"
  local max_bytes="${5:-}"
  local retention_days="${BACKUP_RETENTION_DAYS:-7}"
  local min_keep="${min_keep_override:-${BACKUP_MIN_KEEP_FILES:-3}}"
  local rm_bin="${STORAGE_RM_BIN:-rm}"
  local cutoff_epoch
  local cleanup_rc=0
  local total_bytes=0 entry_size
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
  if [[ -n "$max_bytes" && ! "$max_bytes" =~ ^[0-9]+$ ]]; then
    storage_retention_log "invalid max_bytes=$max_bytes for $item_label"
    return 2
  fi

  cutoff_epoch=$(( $(date +%s) - retention_days * 86400 ))
  while IFS= read -r entry; do
    entries+=("$entry")
  done < <(
    find "$directory/." -maxdepth 1 -type f -name "$pattern" -printf '%T@ %p\n' |
      sort -nr
  )

  for entry in "${entries[@]}"; do
    path="${entry#* }"
    entry_size=$(stat -c %s -- "$path" 2>/dev/null || echo 0)
    total_bytes=$((total_bytes + entry_size))
  done

  for entry in "${entries[@]}"; do
    path="${entry#* }"
    mtime_epoch="${entry%%.*}"

    if (( index < min_keep )); then
      index=$((index + 1))
      continue
    fi

    entry_size=$(stat -c %s -- "$path" 2>/dev/null || echo 0)
    if (( mtime_epoch < cutoff_epoch )) || {
      [[ -n "$max_bytes" ]] && (( total_bytes > max_bytes ));
    }; then
      if [[ "${STORAGE_RETENTION_DRY_RUN:-0}" == "1" ]]; then
        storage_retention_log "would remove expired $item_label: $path"
        total_bytes=$((total_bytes - entry_size))
      elif "$rm_bin" -f -- "$path"; then
        storage_retention_log "removed expired $item_label: $path"
        total_bytes=$((total_bytes - entry_size))
      else
        storage_retention_log "WARNING: failed to remove expired $item_label: $path"
        cleanup_rc=1
      fi
    fi
    index=$((index + 1))
  done
  return "$cleanup_rc"
}

storage_cleanup_evaluations() {
  local directory="$1"
  storage_prune_file_family "$directory" '*' "evaluation artifact" "" \
    "${EVALUATION_MAX_BYTES:-10737418240}"
}

storage_data_total_mb() {
  df -Pm /data 2>/dev/null | awk 'NR == 2 {print $2}'
}

storage_data_free_mb() {
  df -Pm /data 2>/dev/null | awk 'NR == 2 {print $4}'
}

storage_default_data_hard_min_mb() {
  local total_mb threshold
  total_mb=$(storage_data_total_mb)
  [[ "$total_mb" =~ ^[0-9]+$ && "$total_mb" -gt 1 ]] || return 1
  threshold=$((total_mb / 10))
  (( threshold < 1024 )) && threshold=1024
  (( threshold >= total_mb )) && threshold=$((total_mb - 1))
  printf '%s\n' "$threshold"
}

storage_default_data_warn_mb() {
  local total_mb hard_mb threshold
  total_mb=$(storage_data_total_mb)
  hard_mb=$(storage_default_data_hard_min_mb) || return 1
  threshold=$((total_mb / 5))
  (( threshold <= hard_mb )) && threshold=$((hard_mb * 2))
  (( threshold >= total_mb )) && threshold=$((total_mb - 1))
  printf '%s\n' "$threshold"
}

storage_check_data_capacity() {
  local free_mb total_mb warn_mb hard_mb
  storage_data_mount_available || return 1
  free_mb=$(storage_data_free_mb)
  total_mb=$(storage_data_total_mb)
  warn_mb="${DATA_WARN_FREE_MB:-$(storage_default_data_warn_mb)}"
  hard_mb="${DATA_HARD_MIN_FREE_MB:-$(storage_default_data_hard_min_mb)}"
  [[ "$free_mb" =~ ^[0-9]+$ && "$total_mb" =~ ^[0-9]+$ && "$warn_mb" =~ ^[0-9]+$ && "$hard_mb" =~ ^[0-9]+$ ]] || {
    storage_retention_log "invalid /data capacity thresholds: warn=$warn_mb hard=$hard_mb"
    return 2
  }
  if (( hard_mb >= total_mb || warn_mb >= total_mb )); then
    storage_retention_log "capacity thresholds exceed /data size: total=${total_mb}MB warn=${warn_mb}MB hard=${hard_mb}MB"
    return 2
  fi
  if (( free_mb < hard_mb )); then
    storage_retention_log "ALERT: /data free space ${free_mb}MB is below hard threshold ${hard_mb}MB"
    return 2
  fi
  if (( free_mb < warn_mb )); then
    storage_retention_log "WARNING: /data free space ${free_mb}MB is below warning threshold ${warn_mb}MB"
  fi
  return 0
}

storage_emit_alert() {
  local level="$1"
  shift
  local message="$*"
  local webhook="${STORAGE_ALERT_WEBHOOK_URL:-}"
  storage_retention_log "ALERT [$level] $message"
  [[ -n "$webhook" && "${STORAGE_ALERT_ENABLED:-1}" == "1" ]] || return 0
  command -v curl >/dev/null 2>&1 || {
    storage_retention_log "WARNING: STORAGE_ALERT_WEBHOOK_URL configured but curl is unavailable"
    return 0
  }

  local payload
  if command -v python3 >/dev/null 2>&1; then
    payload=$(printf '%s' "$message" | python3 -c \
      'import json, sys; print(json.dumps({"text": sys.stdin.read()}))')
  else
    payload='{"text":"InterviewBoss storage alert"}'
  fi
  curl --fail --silent --show-error --max-time "${STORAGE_ALERT_TIMEOUT_SECONDS:-5}" \
    -H 'Content-Type: application/json' --data "$payload" "$webhook" >/dev/null \
    || storage_retention_log "WARNING: storage alert webhook delivery failed"
}

storage_write_metrics() {
  local target="${STORAGE_METRICS_FILE:-/data/interview-boss/storage.prom}"
  local free_mb total_mb tmp
  storage_data_mount_available || return 1
  free_mb=$(storage_data_free_mb)
  total_mb=$(storage_data_total_mb)
  [[ "$free_mb" =~ ^[0-9]+$ && "$total_mb" =~ ^[0-9]+$ ]] || return 2
  mkdir -p "$(dirname "$target")" || return 1
  tmp="${target}.tmp.$$"
  {
    printf '# HELP interview_boss_storage_data_free_bytes Free bytes on the /data filesystem.\n'
    printf '# TYPE interview_boss_storage_data_free_bytes gauge\n'
    printf 'interview_boss_storage_data_free_bytes %s\n' "$((free_mb * 1024 * 1024))"
    printf '# HELP interview_boss_storage_data_capacity_bytes Total bytes on the /data filesystem.\n'
    printf '# TYPE interview_boss_storage_data_capacity_bytes gauge\n'
    printf 'interview_boss_storage_data_capacity_bytes %s\n' "$((total_mb * 1024 * 1024))"
  } > "$tmp" || { rm -f -- "$tmp"; return 1; }
  chmod 644 "$tmp" && mv -f -- "$tmp" "$target"
}

storage_cleanup_project_archives() {
  local archive_dir="${PROJECT_ARCHIVE_DIR:-/data/projects/archive}"
  local link_dir="${PROJECT_ARCHIVE_LINK_DIR:-/opt}"
  local rm_bin="${STORAGE_RM_BIN:-rm}"
  local cutoff_epoch archive link target referenced link_mtime archive_size
  local max_bytes="${PROJECT_ARCHIVE_MAX_BYTES:-21474836480}"
  local min_keep="${PROJECT_ARCHIVE_MIN_KEEP_FILES:-0}"
  local total_bytes=0 index=0
  local cleanup_rc=0
  local -a entries=()

  storage_data_mount_available || {
    storage_retention_log "WARNING: /data is not mounted; skipped full project archive cleanup"
    return 0
  }
  [[ -d "$archive_dir" ]] || return 0
  [[ "$max_bytes" =~ ^[0-9]+$ && "$min_keep" =~ ^[0-9]+$ ]] || {
    storage_retention_log "invalid project archive retention limits: max_bytes=$max_bytes min_keep=$min_keep"
    return 2
  }
  cutoff_epoch=$(( $(date +%s) - ${BACKUP_RETENTION_DAYS:-7} * 86400 ))

  while IFS= read -r archive; do
    entries+=("$archive")
    archive_size=$(du -sb -- "$archive" 2>/dev/null | awk '{print $1 + 0}')
    total_bytes=$((total_bytes + archive_size))
  done < <(
    find "$archive_dir" -mindepth 1 -maxdepth 1 -type d \
      -name 'interview-boss-backup-*' -printf '%T@ %p\n' | sort -nr | cut -d' ' -f2-
  )

  for archive in "${entries[@]}"; do
    referenced=0
    while IFS= read -r -d '' link; do
      target=$(readlink -f "$link" 2>/dev/null || true)
      if [[ "$target" == "$archive" ]]; then
        link_mtime=$(stat -c %Y -- "$link" 2>/dev/null || echo 0)
        if (( link_mtime >= cutoff_epoch )); then
          referenced=1
          break
        fi
        if [[ "${STORAGE_RETENTION_DRY_RUN:-0}" == "1" ]]; then
          storage_retention_log "would remove stale project archive link: $link"
        elif "$rm_bin" -f -- "$link"; then
          storage_retention_log "removed stale project archive link: $link"
        else
          storage_retention_log "WARNING: failed to remove stale project archive link: $link"
          cleanup_rc=1
          referenced=1
          break
        fi
      fi
    done < <(find "$link_dir" -maxdepth 1 -type l -name 'interview-boss-backup-*' -print0 2>/dev/null)
    if (( referenced != 0 )); then
      index=$((index + 1))
      continue
    fi

    if (( index < min_keep )); then
      index=$((index + 1))
      continue
    fi

    archive_size=$(du -sb -- "$archive" 2>/dev/null | awk '{print $1 + 0}')
    if [[ "$(stat -c %Y "$archive" 2>/dev/null || echo 0)" -lt "$cutoff_epoch" ]] || (( total_bytes > max_bytes )); then
      if [[ "${STORAGE_RETENTION_DRY_RUN:-0}" == "1" ]]; then
        storage_retention_log "would remove expired full project archive: $archive"
        total_bytes=$((total_bytes - archive_size))
      elif "$rm_bin" -rf -- "$archive"; then
        storage_retention_log "removed expired full project archive: $archive"
        total_bytes=$((total_bytes - archive_size))
      else
        storage_retention_log "WARNING: failed to remove expired full project archive: $archive"
        cleanup_rc=1
      fi
    fi
    index=$((index + 1))
  done
  return "$cleanup_rc"
}

storage_cleanup_backups() {
  local project_dir="$1"
  local cleanup_rc=0
  local backup_max="${BACKUP_MAX_BYTES:-10737418240}"
  local migration_max="${MIGRATION_BACKUP_MAX_BYTES:-10737418240}"
  local local_backup_max="${LOCAL_BACKUP_MAX_BYTES:-10737418240}"

  if storage_data_mount_available; then
    storage_prune_file_family "$project_dir/backups" 'interview-boss_*.db' 'backup' "" "$backup_max" || cleanup_rc=1
    storage_prune_file_family "$project_dir/backups" 'redis_*.rdb' 'Redis RDB' 0 "$backup_max" || cleanup_rc=1
  else
    storage_retention_log "WARNING: /data is not mounted; skipped /data-backed project backups"
  fi
  storage_cleanup_project_archives || cleanup_rc=1
  storage_prune_file_family "$project_dir/backend/data/backups" '*.db' 'backup' "" "$migration_max" || cleanup_rc=1
  storage_prune_file_family "$project_dir/backend/data" 'interview-boss.db.bak.*' 'backup' "" "$local_backup_max" || cleanup_rc=1
  storage_cleanup_evaluations "$project_dir/backend/data/evaluations" || cleanup_rc=1
  return "$cleanup_rc"
}
