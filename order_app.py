#!/usr/bin/env python3
"""order_app — 演示用「迷你订单系统」（Flask + SQLite）。

接口：
  GET  /                     业务前台（web/business.html）
  GET  /healthz              健康检查
  GET  /metrics              CPU/内存/QPS/错误率/订单数
  GET  /api/inventory        库存列表
  POST /api/orders           下单
  GET  /api/orders           订单列表
  POST /api/pay              支付
  POST /admin/inject?mode=   注入故障：crash|hang|slow|dirty|flood|db_lock
  POST /admin/reset          清除故障

故障会被「自己上报」给 Router（http://127.0.0.1:8000/webhook），
Router 再按规则分派给 Worker 处置。
"""

import json
import os
import signal
import sqlite3
import sys
import threading
import time
import urllib.request
from collections import deque
from datetime import datetime

from flask import Flask, jsonify, request, send_file

APP_DIR = os.path.dirname(os.path.abspath(__file__))
PID_FILE = os.path.join(APP_DIR, "order_app.pid")
DB_PATH = os.path.join(APP_DIR, "order.db")
ROUTER_URL = "http://127.0.0.1:8000/webhook"
PORT = int(os.environ.get("ORDER_PORT", "8081"))

app = Flask(__name__)
_start = time.time()
_state = {"fault": None, "fault_hist": [], "flood_on": False, "orders": 0, "errors": 0}
_lock = threading.Lock()


def log(msg):
    """业务日志：带时间戳，方便诊断官按时间过滤历史噪音。"""
    print(f"[order_app {datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
    CREATE TABLE IF NOT EXISTS inventory (id INTEGER PRIMARY KEY, name TEXT, qty INTEGER, price REAL);
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, item_id INTEGER, qty INTEGER,
        price REAL, status TEXT, created_at TEXT);
    """)
    if con.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0:
        con.executemany("INSERT INTO inventory (id,name,qty,price) VALUES (?,?,?,?)",
                        [(1, "机械键盘", 100, 199.0),
                         (2, "无线鼠标", 200, 89.0),
                         (3, "27寸显示器", 50, 1299.0)])
    con.commit()
    con.close()


def _snapshot():
    """告警时刻的状态快照，供 AI 诊断对齐时间点（避免被后续故障带偏）。"""
    with _lock:
        return {
            "at": datetime.now().isoformat(timespec="seconds"),
            "fault": _state["fault"],
            "fault_hist": [dict(h) for h in _state.get("fault_hist", [])][-5:],
            "cpu": cpu_pct(),
            "mem": mem_pct(),
            "orders": _state["orders"],
            "errors": _state["errors"],
        }


def report(status, keyword, src="127.0.0.1"):
    """把异常上报给 Router（真实异常路径），附带告警时刻快照。"""
    body = {"service": "order_app", "status": status, "keyword": keyword,
            "src": src, "snapshot": _snapshot()}
    try:
        req = urllib.request.Request(ROUTER_URL, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=3)
        log(f"已上报 Router: {status}/{keyword}")
    except Exception as e:  # noqa: BLE001
        log(f"上报 Router 失败: {e}")


def cpu_pct():
    try:
        with open("/proc/loadavg") as f:
            load = float(f.read().split()[0])
        return round(min(100.0, load / (os.cpu_count() or 1) * 100), 1)
    except OSError:
        return 0.0


def mem_pct():
    try:
        with open("/proc/meminfo") as f:
            lines = f.readlines()
        total = int(lines[0].split()[1])
        avail = int(lines[2].split()[1])
        return round((total - avail) / total * 100, 1)
    except (OSError, IndexError, ValueError):
        return 0.0


def fault_guard():
    """在每个业务接口前调用：把故障表现出来。"""
    f = _state["fault"]
    if f == "hang":
        time.sleep(120)
    elif f == "slow":
        time.sleep(5)
    elif f == "db_lock":
        raise sqlite3.OperationalError("database is locked")


# ---------- 实时指标（最近 10 秒滑动窗口） ----------

_WINDOW = 10.0
_recent = deque()          # [(ts, ok_bool)]
_recent_lock = threading.Lock()


def _record(ok):
    now = time.time()
    with _recent_lock:
        _recent.append((now, ok))
        while _recent and now - _recent[0][0] > _WINDOW:
            _recent.popleft()


def _window_stats():
    now = time.time()
    with _recent_lock:
        while _recent and now - _recent[0][0] > _WINDOW:
            _recent.popleft()
        n = len(_recent)
        e = sum(1 for _, ok in _recent if not ok)
    return n, e


def _qps():
    n, _ = _window_stats()
    return round(n / _WINDOW, 2)


def _err_rate():
    n, e = _window_stats()
    return round(e / n * 100, 1) if n else 0.0


@app.after_request
def _track_response(resp):
    try:
        _record(resp.status_code < 400)
    except Exception:  # noqa: BLE001
        pass
    return resp


@app.get("/healthz")
def healthz():
    return jsonify(status="ok", pid=os.getpid(), uptime=int(time.time() - _start),
                   fault=_state["fault"])


@app.get("/metrics")
def metrics():
    with _lock:
        orders = _state["orders"]
        errors = _state["errors"]
    return jsonify(cpu=cpu_pct(), mem=mem_pct(),
                   qps=_qps(), error_rate=_err_rate(),
                   orders=orders, errors=errors, fault=_state["fault"])


@app.get("/api/inventory")
def inventory():
    fault_guard()
    con = sqlite3.connect(DB_PATH, timeout=3)
    try:
        rows = con.execute("SELECT id,name,qty,price FROM inventory").fetchall()
    finally:
        con.close()
    return jsonify([{"id": r[0], "name": r[1], "qty": r[2], "price": r[3]} for r in rows])


@app.post("/api/orders")
def create_order():
    fault_guard()
    data = request.get_json(silent=True) or {}
    try:
        item_id = int(data.get("item_id", 1))
        qty = int(data.get("qty", 1))
    except (TypeError, ValueError):
        with _lock:
            _state["errors"] += 1
        report("dirty_data", "非法参数：item_id/qty 非数字", src="198.51.100.23")
        return jsonify(error="bad params"), 400

    # 脏数据故障：写入非法订单（不扣库存），并自报
    if _state["fault"] == "dirty":
        con = sqlite3.connect(DB_PATH, timeout=3)
        try:
            con.execute("INSERT INTO orders (item_id,qty,price,status,created_at) VALUES (?,?,?,?,?)",
                        (item_id, -1, float("nan"), "created",
                         datetime.now().isoformat(timespec="seconds")))
            con.commit()
            with _lock:
                _state["orders"] += 1
        finally:
            con.close()
        report("dirty_data", "非法参数：写入 qty=-1 / price=NaN", src="198.51.100.23")
        return jsonify(ok=True, item_id=item_id, qty=-1, price=None), 201

    con = sqlite3.connect(DB_PATH, timeout=3)
    try:
        row = con.execute("SELECT qty,price FROM inventory WHERE id=?", (item_id,)).fetchone()
        if not row:
            return jsonify(error="商品不存在"), 404
        if row[0] < qty:
            return jsonify(error=f"库存不足（剩 {row[0]}）"), 400
        price = row[1]
        con.execute("UPDATE inventory SET qty = qty - ? WHERE id=?", (qty, item_id))
        con.execute("INSERT INTO orders (item_id,qty,price,status,created_at) VALUES (?,?,?,?,?)",
                    (item_id, qty, price, "created", datetime.now().isoformat(timespec="seconds")))
        con.commit()
        with _lock:
            _state["orders"] += 1
    except Exception as e:  # noqa: BLE001
        with _lock:
            _state["errors"] += 1
        report("db_error", f"数据库异常：{e}", src="198.51.100.24")
        return jsonify(error=str(e)), 500
    finally:
        con.close()

    return jsonify(ok=True, item_id=item_id, qty=qty, price=price), 201


@app.get("/api/orders")
def list_orders():
    fault_guard()
    con = sqlite3.connect(DB_PATH, timeout=3)
    try:
        rows = con.execute(
            "SELECT id,item_id,qty,price,status,created_at FROM orders ORDER BY id DESC LIMIT 50"
        ).fetchall()
    finally:
        con.close()
    return jsonify([{"id": r[0], "item_id": r[1], "qty": r[2], "price": r[3],
                     "status": r[4], "created_at": r[5]} for r in rows])


@app.post("/api/pay")
def pay():
    fault_guard()
    data = request.get_json(silent=True) or {}
    order_id = data.get("order_id")
    if order_id is None:
        return jsonify(error="order_id required"), 400
    con = sqlite3.connect(DB_PATH, timeout=3)
    try:
        cur = con.execute("UPDATE orders SET status='paid' WHERE id=?", (order_id,))
        con.commit()
        if cur.rowcount == 0:
            return jsonify(error="订单不存在"), 404
    finally:
        con.close()
    return jsonify(ok=True, order_id=order_id)


# ---------- 故障注入（演示） ----------

def _flood_burst(n=120):
    def worker():
        for _ in range(n):
            if not _state.get("flood_on"):
                break
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{PORT}/api/orders",
                    data=b'{"item_id":1,"qty":1}',
                    headers={"Content-Type": "application/json"}, method="POST")
                urllib.request.urlopen(req, timeout=2)
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.02)
    threading.Thread(target=worker, daemon=True).start()


@app.post("/admin/inject")
def admin_inject():
    mode = request.args.get("mode", "")
    if mode == "crash":
        threading.Timer(0.4, lambda: os._exit(1)).start()
        return jsonify(mode=mode, note="进程 0.4s 后退出")
    if mode not in ("hang", "slow", "dirty", "flood", "db_lock"):
        return jsonify(error="unknown mode"), 400
    _state["fault"] = mode
    _state["fault_hist"].append({"at": datetime.now().isoformat(timespec="seconds"), "mode": mode})
    _state["fault_hist"] = _state["fault_hist"][-20:]
    log(f"注入故障: {mode}")
    if mode == "hang":
        report("hang", "服务无响应（接口卡死）")
    elif mode == "slow":
        report("slow", "接口延迟 5s")
    elif mode == "dirty":
        report("dirty_data", "非法参数：脏数据写入", src="198.51.100.23")
    elif mode == "flood":
        _state["flood_on"] = True
        _flood_burst()
        report("high_freq", "高频访问触发熔断", src="203.0.113.77")
    elif mode == "db_lock":
        report("db_error", "数据库锁表", src="198.51.100.24")
    return jsonify(mode=mode, fault=_state["fault"])


@app.post("/admin/reset")
def admin_reset():
    _state["fault"] = None
    _state["fault_hist"].append({"at": datetime.now().isoformat(timespec="seconds"), "mode": "cleared"})
    _state["fault_hist"] = _state["fault_hist"][-20:]
    _state["flood_on"] = False
    log("故障已清除")
    return jsonify(ok=True)


@app.post("/admin/reset-data")
def admin_reset_data():
    con = sqlite3.connect(DB_PATH)
    try:
        con.execute("DELETE FROM orders")
        con.execute("UPDATE inventory SET qty = CASE id WHEN 1 THEN 100 WHEN 2 THEN 200 WHEN 3 THEN 50 ELSE qty END")
        con.commit()
    finally:
        con.close()
    with _lock:
        _state["orders"] = 0
        _state["errors"] = 0
    log("演示数据已重置")
    return jsonify(ok=True)


@app.get("/")
def index():
    return send_file(os.path.join(APP_DIR, "web", "business.html"))


def _on_terminate(signum, _frame):
    log(f"收到信号 {signum}，进程退出。")
    os._exit(0)  # 立即退出，确保端口释放


def main():
    import logging
    logging.getLogger("werkzeug").setLevel(logging.ERROR)  # 关闭访问日志噪音
    init_db()
    with open(PID_FILE, "w") as f:
        f.write(str(os.getpid()))
    signal.signal(signal.SIGTERM, _on_terminate)
    signal.signal(signal.SIGINT, _on_terminate)
    log(f"启动成功，监听 127.0.0.1:{PORT} (pid={os.getpid()})")
    app.run(host="127.0.0.1", port=PORT, threaded=True)


if __name__ == "__main__":
    main()
