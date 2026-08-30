# -*- coding: utf-8 -*-
"""FastAPI 服务（前后端分离）

前端 web/ 只通过 /api/* 接口取数，不再直接读取 output/*.json：

  GET    /api/ping                 服务状态 + 策略清单（前端探测后端是否在线）
  GET    /api/codes                可用标的列表（页面顶部 Tabs）
  GET    /api/funds                标的配置列表
  POST   /api/funds                新增标的
  PUT    /api/funds/{code}         编辑标的
  DELETE /api/funds/{code}         删除标的
  GET    /api/backtest/{code}      已生成的回测结果（含策略指标/交易明细/净值曲线）
  POST   /api/backtest             触发回测（异步任务）
  GET    /api/summary              多标的汇总表
  GET    /api/signal/{code}        最新信号（默认读缓存，?force=1 实时重算）
  POST   /api/refresh              刷新行情缓存（异步任务）
  GET    /api/job/{job_id}         任务状态与结果
  GET    /api/yields               实时股息率汇总（?force=1 绕过短缓存）

根路径 / 挂载 web/ 静态前端；前后端分离部署时前端可独立托管，
只需在页面设置 window.API_BASE 指向本服务地址。
"""
from __future__ import annotations

import json
import os
import threading

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from strategy_lab.config import (BASE_DIR, OUTPUT_DIR, WEB_DIR, Fund,
                                 ensure_dirs, load_funds, save_funds)
# 复用旧版 server.py 中已校验过的纯业务函数，避免重复实现
from strategy_lab.server import _apply_fund_fields, _find_fund
from strategy_lab.jobs import JOBS
from strategy_lab.report import run_fund_backtest, write_summary
from strategy_lab.signal import latest_signal
from strategy_lab.strategies import list_strategies

_LOCK = threading.Lock()   # funds.json 写锁

app = FastAPI(
    title="红利策略实验室 API",
    version="2.0.0",
    description="前后端分离接口：前端 web/ 通过 /api/* 获取全部数据",
)

# 前后端分离部署：允许跨域（本地开发/独立前端域名）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- 请求模型 ----------
class FundIn(BaseModel):
    code: str | None = None
    name: str | None = None
    kind: str | None = None
    market: str | None = None
    rsi_buy: float | None = None
    rsi_sell: float | None = None
    index_code: str | None = None
    position_amount: float | None = None
    position_ratio: float | None = None
    mult_mode: str | None = None
    mult_factor: float | None = None


class BacktestIn(BaseModel):
    code: str = "932305"
    start: str = "2022-01-01"
    end: str | None = None


class RefreshIn(BaseModel):
    code: str | None = None


# ---------- 工具 ----------
def _read_output(name: str):
    """读取 output/ 下的结果 JSON；不存在返回 None"""
    fp = os.path.join(OUTPUT_DIR, name)
    if not os.path.exists(fp):
        return None
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _job_task_submit(fn, desc: str) -> dict:
    job_id = JOBS.submit(fn, desc)
    return {"job_id": job_id}


# ---------- 基础 ----------
@app.get("/api/ping")
def api_ping():
    return {"ok": True, "mode": "fastapi", "strategies": list_strategies()}


# ---------- 标的 ----------
@app.get("/api/codes")
def api_codes():
    """可用标的：summary.json 为主，funds.json 配置补充，并标记是否已有回测结果"""
    found: dict = {}
    summary = _read_output("summary.json") or {}
    for r in summary.get("rows", []):
        if r.get("code"):
            found[r["code"]] = {"code": r["code"], "name": r.get("name", r["code"]),
                                "has_backtest": False}
    for f in load_funds():
        item = found.setdefault(f.code, {"code": f.code, "name": f.name, "has_backtest": False})
        if f.enabled:
            item["name"] = f.name
    for item in found.values():
        item["has_backtest"] = _read_output(f"{item['code']}_backtest.json") is not None
    return {"codes": list(found.values())}


@app.get("/api/funds")
def api_funds():
    return {"funds": [f.__dict__ for f in load_funds()]}


@app.post("/api/funds")
def api_add_fund(body: FundIn):
    code = str(body.code or "").strip()
    if not code.isdigit() or len(code) != 6:
        raise HTTPException(400, "编码必须为6位数字")
    if _find_fund(code):
        raise HTTPException(409, f"{code} 已存在")
    raw = body.model_dump(exclude_none=True)
    f = Fund(code=code, name=raw.get("name") or code,
             kind=raw.get("kind") or "index",
             market=raw.get("market") or ("SH" if code.startswith("5") else "SZ"),
             rsi_buy=raw.get("rsi_buy") or 45.0,
             rsi_sell=raw.get("rsi_sell") or 65.0)
    err = _apply_fund_fields(f, raw)
    if err:
        raise HTTPException(400, err)
    with _LOCK:
        funds = load_funds()
        funds.append(f)
        save_funds(funds)
    return {"ok": True, "fund": f.__dict__}


@app.put("/api/funds/{code}")
def api_update_fund(code: str, body: FundIn):
    with _LOCK:
        funds = load_funds()
        fund = next((x for x in funds if x.code == code), None)
        if not fund:
            raise HTTPException(404, f"基金 {code} 未配置")
        err = _apply_fund_fields(fund, body.model_dump(exclude_none=True))
        if err:
            raise HTTPException(400, err)
        save_funds(funds)
    return {"ok": True, "fund": fund.__dict__}


@app.delete("/api/funds/{code}")
def api_delete_fund(code: str):
    with _LOCK:
        funds = load_funds()
        funds = [f for f in funds if f.code != code]
        save_funds(funds)
    return {"ok": True, "funds": [f.__dict__ for f in load_funds()]}


# ---------- 回测数据 ----------
@app.get("/api/backtest/{code}")
def api_backtest_result(code: str):
    """已生成的回测结果（策略指标、交易明细、净值曲线、日线）"""
    data = _read_output(f"{code}_backtest.json")
    if data is None:
        raise HTTPException(404, f"{code} 暂无回测结果，请在页面点击「立即回测」")
    return data


@app.post("/api/backtest")
def api_backtest_run(body: BacktestIn):
    f = _find_fund(body.code)
    if not f:
        raise HTTPException(404, f"基金 {body.code} 未配置，请先在基金管理中添加")

    def task(progress):
        progress(f"正在获取 {f.name} 行情数据...")
        r = run_fund_backtest(f, start=body.start, end=body.end)
        if "error" not in r:
            progress("汇总全部策略指标...")
            write_summary([f], [r])
        return {"code": f.code}

    return _job_task_submit(task, f"回测 {f.code} {body.start}~{body.end or '最新'}")


@app.get("/api/summary")
def api_summary():
    data = _read_output("summary.json")
    if data is None:
        raise HTTPException(404, "暂无回测汇总")
    return data


# ---------- 信号 ----------
@app.get("/api/signal/{code}")
def api_signal(code: str, force: bool = Query(False, description="true=忽略缓存实时重算")):
    f = _find_fund(code)
    if not f:
        raise HTTPException(404, f"基金 {code} 未配置")
    if not force:
        cached = _read_output(f"{code}_signal.json")
        if cached:
            cached["_source"] = "cache"
            return cached
    return latest_signal(f, force=force)


# ---------- 行情刷新 ----------
@app.post("/api/refresh")
def api_refresh(body: RefreshIn | None = None):
    code = (body.code if body and body.code else "") or ""

    def task(progress):
        from strategy_lab.datasource import get_daily
        targets = [x for x in load_funds() if (not code or x.code == code) and x.enabled]
        out = {}
        for f in targets:
            progress(f"刷新 {f.name} 行情...")
            df, meta = get_daily(f, force=True)
            out[f.code] = {"provider": meta.get("provider"),
                           "stale": meta.get("stale", False),
                           "bars": 0 if df is None else len(df)}
        return out

    return _job_task_submit(task, "刷新行情缓存")


@app.get("/api/job/{job_id}")
def api_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job不存在")
    return job


# ---------- 实时股息率 ----------
@app.get("/api/yields")
def api_yields(force: bool = Query(False, description="true=绕过进程内短缓存重新抓取")):
    try:
        from strategy_lab.datasource.dividend_yield import summarize_yields, clear_cache
        if force:
            clear_cache()
        return summarize_yields()
    except Exception as e:
        raise HTTPException(500, f"股息率汇总失败: {e}")


# ---------- 前端静态页（放最后，保证 /api 路由优先） ----------
app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


def serve(port: int = 8000, host: str = "127.0.0.1", reload: bool = False) -> None:
    import uvicorn
    ensure_dirs()
    # flush=True：避免 print 被 stdout 缓冲，导致"服务已启动"日志与 uvicorn 日志顺序错乱
    print(f"FastAPI 服务已启动: http://{host}:{port}  （API 文档 /docs）", flush=True)
    uvicorn.run(app, host=host, port=port, reload=reload, log_level="info")
