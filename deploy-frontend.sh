#!/bin/bash
# InterviewBoss 前端部署脚本
# sudoers 免密配置：claude_runner ALL=(root) NOPASSWD: 此脚本
# 用法：先 npm run build，再 sudo 此脚本部署到 nginx 目录

set -euo pipefail

DEPLOY_DIR="/var/www/interview-boss/dist"
DIST_DIR="/root/sj/multimodal-parser/frontend/dist"

if [ ! -d "$DIST_DIR" ] || [ -z "$(ls -A "$DIST_DIR" 2>/dev/null)" ]; then
  echo "错误: $DIST_DIR 为空，请先执行 npm run build"
  exit 1
fi

rm -rf "${DEPLOY_DIR:?}"/*
cp -r "$DIST_DIR"/* "$DEPLOY_DIR/"
chown -R www-data:www-data "$DEPLOY_DIR"

echo "前端部署完成"
