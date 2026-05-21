#!/bin/bash
# Entrypoint: 以 root 修复数据目录权限，然后以 appuser 运行主进程
set -e

# 确保数据目录可写（bind mount 时宿主机目录可能为 root 所有）
chown -R appuser:appuser /app/backend/data 2>/dev/null || true

# 以 appuser 身份执行 CMD
exec runuser -u appuser -- "$@"
