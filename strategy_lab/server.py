# -*- coding: utf-8 -*-
"""轻量本地服务：http.server 托管 web/ 静态页 + JSON API（供页面手动回测/基金管理）"""
from __future__ import annotations

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from strategy_lab.config import (BASE_DIR, OUTPUT_DIR, WEB_DIR, Fund,
                                 load_funds, save_funds, validate_position)
from strategy_lab.jobs import JOBS
from strategy_lab.report import run_fund_backtest, write_summary
from strategy_lab.signal import latest_signal
from strategy_lab.strategies import list_strategies

_LOCK = threading.Lock()   # funds.json 写锁


class Handler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        pass   # 静默访问日志

    # ---------- 通用响应 ----------
    def _send(self, code: int, body, content_type: str = "application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    # ---------- 路由 ----------
    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/api/ping":
            self._send(200, {"ok": True, "mode": "serve",
                             "strategies": list_strategies()})
        elif path == "/api/funds":
            self._send(200, {"funds": [f.__dict__ for f in load_funds()]})
        elif path == "/api/yields":
            # 实时股息率汇总（中证官网估值为主，动态 TTM 兜底）；?force=1 绕过短缓存
            try:
                from strategy_lab.datasource.dividend_yield import summarize_yields, clear_cache
                if "force=1" in self.path:
                    clear_cache()
                self._send(200, summarize_yields())
            except Exception as e:
                self._send(500, {"error": f"股息率汇总失败: {e}"})
        elif path.startswith("/api/job/"):
            job = JOBS.get(path.split("/")[-1])
            self._send(200 if job else 404, job or {"error": "job不存在"})
        elif path.startswith("/api/signal/"):
            code = path.split("/")[-1]
            f = _find_fund(code)
            if not f:
                self._send(404, {"error": f"基金 {code} 未配置"})
            else:
                self._send(200, latest_signal(f))
        elif path.startswith("/api/"):
            self._send(404, {"error": "未知API"})
        else:
            self._static(path)

    def do_POST(self):
        path = self.path.split("?")[0]
        body = self._json_body()
        if path == "/api/funds":
            self._add_fund(body)
        elif path == "/api/backtest":
            code = str(body.get("code") or "932305")
            start = body.get("start") or "2022-01-01"
            end = body.get("end") or None
            f = _find_fund(code)
            if not f:
                self._send(404, {"error": f"基金 {code} 未配置，请先在基金管理中添加"})
                return

            def task(progress):
                progress(f"正在获取 {f.name} 行情数据...")
                r = run_fund_backtest(f, start=start, end=end)
                if "error" not in r:
                    progress("汇总全部策略指标...")
                    write_summary([f], [r])
                return {"code": f.code}
            job_id = JOBS.submit(task, f"回测 {f.code} {start}~{end or '最新'}")
            self._send(200, {"job_id": job_id})
        elif path == "/api/refresh":
            code = str(body.get("code") or "")
            def task(progress):
                funds = load_funds()
                targets = [f for f in funds if (not code or f.code == code) and f.enabled]
                out = {}
                for f in targets:
                    progress(f"刷新 {f.name} 行情...")
                    df, meta = _refresh_fund(f)
                    out[f.code] = {"provider": meta.get("provider"),
                                   "stale": meta.get("stale", False),
                                   "bars": 0 if df is None else len(df)}
                return out
            job_id = JOBS.submit(task, "刷新行情缓存")
            self._send(200, {"job_id": job_id})
        else:
            self._send(404, {"error": "未知API"})

    def do_PUT(self):
        m = re.match(r"^/api/funds/(\w+)$", self.path.split("?")[0])
        if not m:
            self._send(404, {"error": "未知API"})
            return
        code = m.group(1)
        body = self._json_body()
        with _LOCK:
            funds = load_funds()
            fund = next((f for f in funds if f.code == code), None)
            if not fund:
                self._send(404, {"error": f"基金 {code} 未配置"})
                return
            err = _apply_fund_fields(fund, body)
            if err:
                self._send(400, {"error": err})
                return
            save_funds(funds)
        self._send(200, {"ok": True, "fund": fund.__dict__})

    def do_DELETE(self):
        m = re.match(r"^/api/funds/(\w+)$", self.path.split("?")[0])
        if not m:
            self._send(404, {"error": "未知API"})
            return
        code = m.group(1)
        with _LOCK:
            funds = load_funds()
            funds = [f for f in funds if f.code != code]
            save_funds(funds)
        self._send(200, {"ok": True, "funds": [f.__dict__ for f in load_funds()]})

    # ---------- 业务 ----------
    def _add_fund(self, body: dict):
        code = str(body.get("code") or "").strip()
        if not re.fullmatch(r"\d{6}", code):
            self._send(400, {"error": "编码必须为6位数字"})
            return
        if _find_fund(code):
            self._send(409, {"error": f"{code} 已存在"})
            return
        try:
            f = Fund(
                code=code,
                name=str(body.get("name") or code),
                kind=body.get("kind") or "index",
                market=body.get("market") or ("SH" if code.startswith("5") else "SZ"),
                rsi_buy=float(body.get("rsi_buy") or 45),
                rsi_sell=float(body.get("rsi_sell") or 65),
            )
        except Exception as e:
            self._send(400, {"error": f"参数错误：{e}"})
            return
        err = _apply_fund_fields(f, body)
        if err:
            self._send(400, {"error": err})
            return
        with _LOCK:
            funds = load_funds()
            funds.append(f)
            save_funds(funds)
        self._send(200, {"ok": True, "fund": f.__dict__})

    # ---------- 静态文件 ----------
    def _static(self, path: str):
        if path in ("/", "/index.html"):
            fp = os.path.join(WEB_DIR, "index.html")
        else:
            rel = os.path.normpath(path.lstrip("/"))
            if rel.startswith(".."):
                self._send(403, "forbidden", "text/plain")
                return
            fp = os.path.join(WEB_DIR, rel)
            # output/ 下的结果 JSON 也允许直接 fetch（相对路径 /output/xxx.json）
            if not os.path.exists(fp):
                fp2 = os.path.join(BASE_DIR, rel)
                if os.path.exists(fp2) and fp2.startswith((WEB_DIR, OUTPUT_DIR)):
                    fp = fp2
        if not os.path.exists(fp) or not os.path.isfile(fp):
            self._send(404, "not found", "text/plain")
            return
        ctype = _guess_type(fp)
        with open(fp, "rb") as f:
            data = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _guess_type(fp: str) -> str:
    ext = os.path.splitext(fp)[1].lower()
    return {
        ".html": "text/html; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".css": "text/css; charset=utf-8",
        ".json": "application/json; charset=utf-8",
        ".svg": "image/svg+xml",
        ".png": "image/png",
        ".ico": "image/x-icon",
    }.get(ext, "application/octet-stream")


def _find_fund(code: str):
    for f in load_funds():
        if f.code == code:
            return f
    return None


def _apply_fund_fields(fund: Fund, body: dict) -> str | None:
    """把请求中的白名单字段应用到 fund（缺失键不动原值），返回错误信息或 None。

    覆盖基础字段（name/kind/rsi_buy/rsi_sell）与仓位资金字段
    （position_amount/position_ratio/mult_mode/mult_factor）。
    """
    if "name" in body and body["name"]:
        fund.name = str(body["name"])
    if "kind" in body and body["kind"]:
        fund.kind = str(body["kind"])
    if "market" in body and body["market"]:
        fund.market = str(body["market"])
    if "rsi_buy" in body and body["rsi_buy"] not in (None, ""):
        try:
            fund.rsi_buy = float(body["rsi_buy"])
        except (TypeError, ValueError):
            return "rsi_buy 必须为数字"
    if "rsi_sell" in body and body["rsi_sell"] not in (None, ""):
        try:
            fund.rsi_sell = float(body["rsi_sell"])
        except (TypeError, ValueError):
            return "rsi_sell 必须为数字"

    # 仓位资金字段
    if "position_amount" in body and body["position_amount"] not in (None, ""):
        try:
            fund.position_amount = float(body["position_amount"])
        except (TypeError, ValueError):
            return "仓位金额必须为数字"
    if "position_ratio" in body and body["position_ratio"] not in (None, ""):
        try:
            fund.position_ratio = float(body["position_ratio"])
        except (TypeError, ValueError):
            return "仓位比例必须为数字"
    if "mult_mode" in body and body["mult_mode"] not in (None, ""):
        fund.mult_mode = str(body["mult_mode"])
    if "mult_factor" in body and body["mult_factor"] not in (None, ""):
        try:
            fund.mult_factor = float(body["mult_factor"])
        except (TypeError, ValueError):
            return "倍率系数必须为数字"

    # 实时股息率：跟踪的中证指数代码（如 000922 / H30269 / 932305）
    if "index_code" in body:
        v = str(body["index_code"] or "").strip()
        fund.index_code = v or None

    return validate_position(fund.position_amount, fund.position_ratio,
                             fund.mult_mode, fund.mult_factor)


def _refresh_fund(f: Fund):
    from strategy_lab.datasource import get_daily
    return get_daily(f, force=True)


def serve(port: int = 8000):
    # 清理残留的原子写临时文件（超过 10 分钟，避免误删正在写入的）
    import time as _t
    from strategy_lab.config import DATA_DIR
    try:
        cutoff = _t.time() - 600
        for fn in os.listdir(DATA_DIR):
            if fn.endswith(".tmp"):
                fp = os.path.join(DATA_DIR, fn)
                try:
                    if os.path.getmtime(fp) < cutoff:
                        os.remove(fp)
                except OSError:
                    pass
    except Exception:
        pass
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"服务已启动: http://127.0.0.1:{port}  （Ctrl+C 退出）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已停止")
