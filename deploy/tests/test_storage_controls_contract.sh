#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DEPLOY_SCRIPT="$PROJECT_DIR/deploy/docker-deploy.sh"
CHECK_SCRIPT="$PROJECT_DIR/scripts/check.sh"

fail() {
  echo "FAIL: $*" >&2
  exit 1
}

contains() {
  local path="$1"
  local text="$2"
  grep -Fq -- "$text" "$path" || fail "$path is missing: $text"
}

not_contains() {
  local path="$1"
  local text="$2"
  if grep -vE '^[[:space:]]*#' "$path" | grep -Fq -- "$text"; then
    fail "$path must not execute: $text"
  fi
}

contains "$DEPLOY_SCRIPT" 'source "$PROJECT_DIR/deploy/storage-retention.sh"'
contains "$DEPLOY_SCRIPT" 'storage_cleanup_backups "$PROJECT_DIR"'
contains "$DEPLOY_SCRIPT" 'DEPLOY_HARD_MIN_FREE_MB'
contains "$DEPLOY_SCRIPT" 'DEPLOY_HARD_MIN_FREE_MB:-6144'
contains "$DEPLOY_SCRIPT" 'DEPLOY_TARGET_FREE_MB:-8192'
contains "$DEPLOY_SCRIPT" 'BUILDKIT_MAX_USED_SPACE:-1536MB'
contains "$DEPLOY_SCRIPT" 'BUILDKIT_BUILDER:-interview-boss'
contains "$DEPLOY_SCRIPT" 'BACKUP_RETENTION_DAYS:-7'
contains "$DEPLOY_SCRIPT" 'BACKUP_MIN_KEEP_FILES:-3'
contains "$DEPLOY_SCRIPT" 'BUILDKIT_MAX_USED_SPACE'
contains "$DEPLOY_SCRIPT" 'docker buildx prune'
contains "$DEPLOY_SCRIPT" '--builder "$BUILDKIT_BUILDER"'
contains "$DEPLOY_SCRIPT" 'docker compose build --builder "$BUILDKIT_BUILDER"'
contains "$DEPLOY_SCRIPT" 'storage-check)'
contains "$DEPLOY_SCRIPT" 'storage-maintenance)'
contains "$DEPLOY_SCRIPT" 'cleanup [--dry-run]'
contains "$DEPLOY_SCRIPT" 'prune_build_cache light'
contains "$DEPLOY_SCRIPT" 'prune_build_cache aggressive'
contains "$DEPLOY_SCRIPT" 'prune_production_images'
contains "$DEPLOY_SCRIPT" 'interview-boss-app:previous'
contains "$DEPLOY_SCRIPT" 'interview-boss-nginx:previous'
contains "$DEPLOY_SCRIPT" 'interview-boss-oauth-gateway:previous'

not_contains "$DEPLOY_SCRIPT" 'docker system prune'
not_contains "$DEPLOY_SCRIPT" 'docker image prune'
not_contains "$DEPLOY_SCRIPT" 'docker volume prune'
not_contains "$DEPLOY_SCRIPT" 'docker container prune'
not_contains "$DEPLOY_SCRIPT" 'down --volumes --remove-orphans --rmi all'
not_contains "$DEPLOY_SCRIPT" 'buildx create --use'

contains "$CHECK_SCRIPT" 'TEST_COMPOSE_PROJECT'
contains "$CHECK_SCRIPT" 'TEST_BUILDKIT_BUILDER'
contains "$CHECK_SCRIPT" 'build --builder "$TEST_BUILDKIT_BUILDER"'
contains "$CHECK_SCRIPT" 'TEST_HARD_MIN_FREE_MB'
contains "$CHECK_SCRIPT" 'down --volumes --remove-orphans'
not_contains "$CHECK_SCRIPT" 'docker image rm'
not_contains "$CHECK_SCRIPT" 'down --volumes --remove-orphans --rmi all'

echo "PASS: storage control contract is present"
