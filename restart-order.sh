#!/usr/bin/env bash
# 重启 order_app（setsid 独立会话，脱离父进程存活）
set -uo pipefail
cd "$(dirname "$0")"

APP="order_app.py"
PIDFILE="order_app.pid"
LOG="order_app.log"

OLD=""
[ -f "$PIDFILE" ] && OLD="$(cat "$PIDFILE" 2>/dev/null || true)"
if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
    echo "[restart] 停止旧进程 PID=$OLD"
    kill "$OLD" 2>/dev/null || true
    sleep 1
fi

PY="venv/bin/python"
[ -x "$PY" ] || PY="python3"

setsid "$PY" "$APP" >> "$LOG" 2>&1 < /dev/null &
sleep 0.6

NEW_PID="$(cat "$PIDFILE" 2>/dev/null || true)"
echo "[restart] order_app 已启动（setsid 独立会话），PID=${NEW_PID:-?}"
