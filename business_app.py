#!/usr/bin/env python3
"""business_app.py — 演示用「脆弱业务程序」。

S2 修复：移除启动时无条件的 `crash = 100 / 0` 除零缺陷，
恢复「按心跳间隔正常运行」的原有行为。
"""

import os
import signal
import sys
import time

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(APP_DIR, "business_app.pid")


def _on_terminate(signum, _frame):
    print(f"[business_app] 收到信号 {signum}，进程退出。", flush=True)
    sys.exit(0)


def main():
    if len(sys.argv) > 1:
        raw = sys.argv[1]
        try:
            value = int(raw)
        except ValueError:
            raise ZeroDivisionError(f"非法参数（非整数）: {raw!r}")
        if value == 0:
            raise ZeroDivisionError("非法参数：除数为 0")
    else:
        value = 2

    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))

    signal.signal(signal.SIGTERM, _on_terminate)
    signal.signal(signal.SIGINT, _on_terminate)

    print(f"[business_app] 启动成功，心跳间隔 {value}s (pid={os.getpid()})", flush=True)
    i = 0
    while True:
        i += 1
        print(f"[business_app] 服务运行中 (心跳 #{i})", flush=True)
        time.sleep(value)


if __name__ == "__main__":
    main()
