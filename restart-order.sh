#!/usr/bin/env bash
# 重启 order_app（彻底清理旧实例 + 等待端口释放 + setsid 独立会话）
set -uo pipefail
cd "$(dirname "$0")"

APP="order_app.py"
PIDFILE="order_app.pid"
LOG="order_app.log"
PORT=8081

port_busy() {
    python3 - "$PORT" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket()
s.settimeout(0.3)
try:
    s.connect(("127.0.0.1", int(sys.argv[1])))
    sys.exit(0)      # 端口被占用
except Exception:
    sys.exit(1)      # 端口空闲
finally:
    s.close()
PY
}

echo "[restart] 清理旧 order_app 实例"
pkill -f "python.*$APP" 2>/dev/null || true
sleep 1

# 最多等 5 秒让端口释放；仍占用则强杀
for _ in $(seq 1 10); do
    port_busy || break
    sleep 0.5
done
if port_busy; then
    echo "[restart] 端口仍被占用，强制清理"
    pkill -9 -f "python.*$APP" 2>/dev/null || true
    sleep 1
fi

PY="venv/bin/python"
[ -x "$PY" ] || PY="python3"

# 启动前确认端口确实空闲（此时占用说明还有旧进程）
if port_busy; then
    echo "[restart] 错误：端口 $PORT 在启动前仍被占用，放弃启动"
    exit 1
fi

setsid "$PY" "$APP" >> "$LOG" 2>&1 < /dev/null &

# 等新实例真正开始监听端口，再读 pidfile
for _ in $(seq 1 20); do
    sleep 0.5
    port_busy && break
done

NEW_PID="$(cat "$PIDFILE" 2>/dev/null || true)"
if port_busy; then
    echo "[restart] order_app 已启动（setsid），PID=${NEW_PID:-?}"
else
    echo "[restart] 启动失败：端口 $PORT 未监听"
    exit 1
fi
