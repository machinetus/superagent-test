#!/usr/bin/env bash
# restart.sh — 重启 business_app.py（可选参数，默认 10）
set -euo pipefail

APP_DIR="$HOME/aiops-demo"
APP="$APP_DIR/business_app.py"
PID_FILE="$APP_DIR/business_app.pid"
LOG_FILE="$APP_DIR/business_app.log"
ARG="${1:-10}"

cd "$APP_DIR"

# 1) 停掉旧进程
if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "[restart] 停止旧进程 PID=$OLD_PID"
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

# 2) 启动新进程（后台常驻）
nohup python3 "$APP" "$ARG" >> "$LOG_FILE" 2>&1 &
NEW_PID=$!
echo "$NEW_PID" > "$PID_FILE"
echo "[restart] business_app 已启动，PID=$NEW_PID，参数=$ARG"
