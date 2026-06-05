#!/bin/bash
set -e

# Fix data directory permissions (bind mount may be owned by root)
chown -R appuser:appuser /app/backend/data 2>/dev/null || true

# Fix cache directories (may be missing or wrong permissions after volume mount)
mkdir -p /home/appuser/.cache/uv /home/appuser/.cache/pip 2>/dev/null || true
chown -R appuser:appuser /home/appuser/.cache 2>/dev/null || true

exec runuser -u appuser -- "$@"
