#!/usr/bin/env python3
"""business_app.py — 演示用「脆弱业务程序」。

行为：
1. 常驻后台，周期性打印「服务运行中」；
2. 收到 SIGTERM / SIGINT（被 kill）时退出；
3. 收到非法参数（非整数，或整数 0）时抛 ZeroDivisionError，模拟业务代码 Bug。
"""

import signal
import sys
import time


def _on_terminate(signum, _frame):
    print(f"[business_app] 收到信号 {signum}，进程退出。", flush=True)
    sys.exit(0)


def main():
    # 参数解析：非法参数 -> ZeroDivisionError（模拟业务代码 Bug）
    if len(sys.argv) > 1:
        raw = sys.argv[1]
        try:
            value = int(raw)
        except ValueError:
            raise ZeroDivisionError(f"非法参数（非整数）: {raw!r}")
        if value == 0:
            raise ZeroDivisionError("非法参数：除数为 0")
    else:
        value = 2  # 默认心跳间隔（秒）

    signal.signal(signal.SIGTERM, _on_terminate)
    signal.signal(signal.SIGINT, _on_terminate)

    print(f"[business_app] 启动成功，心跳间隔 {value}s", flush=True)
    i = 0
    while True:
        i += 1
        print(f"[business_app] 服务运行中 (心跳 #{i})", flush=True)
        time.sleep(value)


if __name__ == "__main__":
    main()
