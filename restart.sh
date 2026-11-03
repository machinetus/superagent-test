#!/usr/bin/env bash
# restart.sh — 重启 business_app.py（可选参数，默认 10）
#
# 关键：用 setsid 让业务进程进入【独立会话】，避免它随 Worker(dsh) 退出时
# 被进程组清理一并 SIGTERM；业务进程自己写 pidfile。
set -euo pipefail

APP_DIR="$HOME/aiops-demo"
APP="$APP_DIR/business_app.py"
PID_FILE="$APP_DIR/business_app.pid"
LOG_FILE="$APP_DIR/business_app.log"
ARG="${1:-10}"

cd "$APP_DIR"

# 1) 停掉旧进程（读 pidfile；已死则跳过）
if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "[restart] 停止旧进程 PID=$OLD_PID"
    kill "$OLD_PID" 2>/dev/null || true
    sleep 1
  fi
  rm -f "$PID_FILE"
fi

# 2) 独立会话启动（setsid），业务进程自己写 pidfile
setsid python3 "$APP" "$ARG" >> "$LOG_FILE" 2>&1 < /dev/null &

# 3) 等业务进程写 pidfile
sleep 0.5
NEW_PID="$(cat "$PID_FILE" 2>/dev/null || echo "")"
echo "[restart] business_app 已启动（setsid 独立会话），PID=${NEW_PID:-?}，参数=$ARG"
