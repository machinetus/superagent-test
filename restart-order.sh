#!/usr/bin/env bash
# 重启 order_app
#
# 关键：必须跑在**独立的 systemd 用户单元**里，不能继承 aiops-router.service 的 cgroup。
# 否则 `systemctl --user restart aiops-router` 会连带把 order_app 一起 SIGTERM 掉
# （setsid 只能脱离进程组，脱离不了 cgroup）。
set -uo pipefail
cd "$(dirname "$0")" || exit 1

APP="order_app.py"
PIDFILE="order_app.pid"
LOG="order_app.log"
PORT=8081
UNIT="order-app"
WORKDIR="$(pwd)"

port_busy() {
    python3 - "$PORT" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket()
s.settimeout(0.3)
try:
    s.connect(("127.0.0.1", int(sys.argv[1])))
    sys.exit(0)      # 占用
except Exception:
    sys.exit(1)      # 空闲
finally:
    s.close()
PY
}

echo "[restart] 停止旧的 order_app（systemd 单元 + 裸进程）"
systemctl --user stop "$UNIT" 2>/dev/null || true
systemctl --user reset-failed "$UNIT" 2>/dev/null || true
pkill -f "python.*$APP" 2>/dev/null || true
sleep 1

for _ in $(seq 1 10); do
    port_busy || break
    sleep 0.5
done
if port_busy; then
    echo "[restart] 端口仍被占用，强制清理"
    pkill -9 -f "python.*$APP" 2>/dev/null || true
    sleep 1
fi
if port_busy; then
    echo "[restart] 错误：端口 $PORT 在启动前仍被占用，放弃启动"
    exit 1
fi

PY="$WORKDIR/venv/bin/python"
[ -x "$PY" ] || PY="$(command -v python3)"

if systemctl --user show-environment >/dev/null 2>&1; then
    # ---- 独立 cgroup：Router 重启不会带死它 ----
    systemd-run --user --unit="$UNIT" --collect --quiet \
        --working-directory="$WORKDIR" \
        --setenv=PATH="$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin" \
        /bin/bash -c "exec '$PY' '$WORKDIR/$APP' >> '$WORKDIR/$LOG' 2>&1"
    MODE="systemd-unit($UNIT)"
else
    setsid "$PY" "$APP" >> "$LOG" 2>&1 < /dev/null &
    MODE="setsid(无 systemd 兜底)"
fi

for _ in $(seq 1 24); do
    sleep 0.5
    port_busy && break
done

NEW_PID="$(cat "$PIDFILE" 2>/dev/null || true)"
if [ -z "$NEW_PID" ]; then
    NEW_PID="$(systemctl --user show "$UNIT" -p MainPID 2>/dev/null | cut -d= -f2)"
fi

if port_busy; then
    echo "[restart] order_app 已启动（$MODE），PID=${NEW_PID:-?}"
    # 打印 cgroup，便于确认已脱离 Router
    if [ -r "/proc/${NEW_PID}/cgroup" ]; then
        echo "[restart] cgroup: $(head -1 "/proc/${NEW_PID}/cgroup" 2>/dev/null)"
    fi
else
    echo "[restart] 启动失败：端口 $PORT 未监听"
    exit 1
fi
