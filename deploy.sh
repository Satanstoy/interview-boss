#!/bin/bash
# InterviewBoss 一键部署脚本
# 用法：./deploy.sh [frontend|backend|all]
#   frontend — 构建并部署前端
#   backend  — 重启后端服务
#   all      — 前端构建部署 + 后端重启（默认）

set -euo pipefail

PROJECT_DIR="/root/sj/interview-boss"
SERVICE_NAME="interview-boss"

deploy_frontend() {
  local DEPLOY_DIR="/var/www/interview-boss/dist"
  local DIST_DIR="$PROJECT_DIR/frontend/dist"

  echo "=== 前端构建 ==="
  cd "$PROJECT_DIR/frontend"
  sudo chown -R $(whoami):$(whoami) "$DIST_DIR" 2>/dev/null || true
  npm run build
  echo ""

  echo "=== 前端部署 ==="
  if [ ! -d "$DIST_DIR" ] || [ -z "$(ls -A "$DIST_DIR" 2>/dev/null)" ]; then
    echo "错误: $DIST_DIR 为空，请先执行 npm run build"
    exit 1
  fi

  sudo rm -rf "${DEPLOY_DIR:?}"/*
  sudo cp -r "$DIST_DIR"/* "$DEPLOY_DIR/"
  sudo chown -R www-data:www-data "$DEPLOY_DIR"
  echo "前端部署完成"
  echo ""
}

restart_backend() {
  echo "=== 重启后端服务 ==="
  sudo systemctl restart "$SERVICE_NAME"

  # 等待服务启动
  sleep 2
  if sudo systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "后端服务已启动"
    sudo systemctl status "$SERVICE_NAME" --no-pager | head -5
  else
    echo "错误: 后端服务启动失败"
    sudo journalctl -u "$SERVICE_NAME" -n 20 --no-pager
    exit 1
  fi

  # 重启 ARQ Worker（如果服务已安装）
  WORKER_SERVICE="interview-boss-worker"
  if sudo systemctl list-unit-files | grep -q "$WORKER_SERVICE"; then
    echo "=== 重启 ARQ Worker ==="
    sudo systemctl restart "$WORKER_SERVICE"
    sleep 1
    if sudo systemctl is-active --quiet "$WORKER_SERVICE"; then
      echo "ARQ Worker 已启动"
    else
      echo "警告: ARQ Worker 启动失败（Redis 可能未运行）"
    fi
  fi
  echo ""
}

MODE="${1:-all}"

case "$MODE" in
  frontend)
    deploy_frontend
    ;;
  backend)
    restart_backend
    ;;
  all)
    deploy_frontend
    restart_backend
    ;;
  *)
    echo "用法: ./deploy.sh [frontend|backend|all]"
    exit 1
    ;;
esac

echo "=== 部署完成 ==="
