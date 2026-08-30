# -*- coding: utf-8 -*-
"""回测/信号结果序列化为 output/*.json（前端直接 fetch）"""
from __future__ import annotations

import json
import os
from datetime import datetime

from strategy_lab.config import OUTPUT_DIR, Fund, atomic_write_json
from strategy_lab.strategies import REGISTRY
from strategy_lab.backtest import run_backtest
from strategy_lab.datasource import get_daily, get_corporate_actions

DEFAULT_START = "2022-01-01"


def run_fund_backtest(fund: Fund, start: str = DEFAULT_START, end: str | None = None,
                      strategy_ids: list | None = None, force: bool = False) -> dict:
    """对单个标的跑全部（或指定）策略回测，返回可 JSON 化的 dict 并落盘。"""
    daily, meta = get_daily(fund, start=start, end=end, force=force)
    if daily is None or not len(daily):
        return {"code": fund.code, "name": fund.name, "error": "无行情数据",
                "errors": meta.get("errors", [])}
    divs, splits = get_corporate_actions(fund)
    if fund.splits:
        splits = fund.splits

    end = end or datetime.now().strftime("%Y-%m-%d")
    init_cash = fund.base_amount()
    out = {
        "code": fund.code,
        "name": fund.name,
        "kind": fund.kind,
        "start": start,
        "end": end,
        "provider": meta.get("provider"),
        "stale": meta.get("stale", False),
        "params": {"rsi_buy": fund.rsi_buy, "rsi_sell": fund.rsi_sell,
                   "ladder": fund.ladder, "init_cash": init_cash,
                   "position_amount": fund.position_amount,
                   "position_ratio": fund.position_ratio},
        "splits": splits,
        "dividends": divs,
        "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "strategies": [],
        "daily": [[d.strftime("%Y-%m-%d"), round(float(o), 4), round(float(h), 4),
                   round(float(l), 4), round(float(c), 4), float(v)]
                  for d, o, h, l, c, v in zip(daily["date"], daily["open"], daily["high"],
                                              daily["low"], daily["close"], daily["volume"])],
    }
    ids = strategy_ids or list(REGISTRY.keys())
    for sid in ids:
        cls = REGISTRY.get(sid)
        if cls is None:
            continue
        st = cls(fund)
        r = run_backtest(fund, st, daily, divs, splits, start, end, init_cash=init_cash)
        out["strategies"].append({
            "id": sid,
            "name": st.name,
            "metrics": r.metrics,
            "trades": r.trades,
            "equity_curve": r.equity_curve,
            "signals": r.signals,
        })
    _atomic_write(os.path.join(OUTPUT_DIR, f"{fund.code}_backtest.json"), out)
    return out


def write_signal_json(fund: Fund, sig: dict) -> None:
    _atomic_write(os.path.join(OUTPUT_DIR, f"{fund.code}_signal.json"), sig)


def write_summary(funds: list, results: list | None = None) -> None:
    """全部标的×策略指标汇总表"""
    by_code = {r.get("code"): r for r in (results or [])}
    rows = []
    for f in funds:
        r = by_code.get(f.code)
        if not r or "strategies" not in r:
            continue
        for s in r["strategies"]:
            m = s.get("metrics") or {}
            rows.append({
                "code": f.code, "name": f.name, "strategy": s["name"],
                "strategy_id": s["id"],
                "cumulative_return": m.get("cumulative_return"),
                "max_drawdown": m.get("max_drawdown"),
                "sharpe": m.get("sharpe"),
                "calmar": m.get("calmar"),
                "avg_position": m.get("avg_position"),
                "ann_return": m.get("ann_return"),
            })
    summary = {"updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "rows": rows}
    _atomic_write(os.path.join(OUTPUT_DIR, "summary.json"), summary)


def _atomic_write(path: str, obj) -> None:
    atomic_write_json(path, obj)
