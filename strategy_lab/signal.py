# -*- coding: utf-8 -*-
"""最新周信号计算：状态机当前状态 + 本周是否触发买卖（供邮件推送 / 页面横幅）"""
from __future__ import annotations

from datetime import datetime

from strategy_lab.config import Fund
from strategy_lab.datasource import get_daily, get_corporate_actions
from strategy_lab.indicators import rsi_wilder, split_adjusted, to_weekly


def latest_signal(fund: Fund, force: bool = False) -> dict:
    """返回最新周信号。基于周线RSI状态机（空仓↔持仓两态，重复信号忽略）。"""
    daily, meta = get_daily(fund, start=_two_years_ago(), force=force)
    if daily is None or not len(daily):
        return {"code": fund.code, "name": fund.name, "error": "无行情数据",
                "errors": meta.get("errors", [])}

    adj = split_adjusted(daily, fund.splits or [])
    weekly = to_weekly(adj)
    rsi = rsi_wilder(weekly["close"], 14)

    buy, sell = fund.rsi_buy, fund.rsi_sell
    holding = False
    last_action_date = None
    for i in range(len(weekly)):
        r = rsi.iloc[i]
        if rsi.isna().iloc[i]:
            continue
        if not holding and r < buy:
            holding = True
            last_action_date = weekly["date"].iloc[i]
        elif holding and r > sell:
            holding = False
            last_action_date = weekly["date"].iloc[i]

    # 最新一周
    i = len(weekly) - 1
    r_last = rsi.iloc[i]
    week_end = weekly["date"].iloc[i]
    r_valid = not rsi.isna().iloc[i]

    action = "观望"
    note = "中间区间，不操作"
    if r_valid:
        if not holding and r_last < buy:
            action = "买入"
            note = f"周RSI={r_last:.1f} < {buy:.0f}，空仓→全仓买入"
        elif holding and r_last > sell:
            action = "卖出"
            note = f"周RSI={r_last:.1f} > {sell:.0f}，持仓→全仓卖出"
        elif holding:
            note = f"周RSI={r_last:.1f} 处于 {buy:.0f}~{sell:.0f} 中间区间，继续持仓"
        else:
            note = f"周RSI={r_last:.1f} 处于 {buy:.0f}~{sell:.0f} 中间区间，继续空仓等待"

    # 下一交易日
    next_day = None
    if action in ("买入", "卖出"):
        days = daily["date"]
        idx = days.searchsorted(week_end, side="right")
        if idx < len(days):
            next_day = days.iloc[idx].strftime("%Y-%m-%d")

    # 仓位资金管理：推荐操作金额（倍率按 RSI 信号强弱线性换算）
    base = fund.base_amount()
    multiplier = 1.0
    if r_valid:
        if action == "买入" and fund.mult_mode in ("buy", "both"):
            # RSI 越低于买入阈值，信号越强，倍率越大（区间 [1, factor]）
            s = (buy - r_last) / buy if buy > 0 else 0.0
            multiplier = 1.0 + max(0.0, fund.mult_factor - 1.0) * min(max(s, 0.0), 1.0)
        elif action == "卖出" and fund.mult_mode in ("sell", "both"):
            # 对称：RSI 越高于卖出阈值，卖出越多（区间 [1, factor]）
            denom = 100.0 - sell
            s = (r_last - sell) / denom if denom > 0 else 0.0
            multiplier = 1.0 + max(0.0, fund.mult_factor - 1.0) * min(max(s, 0.0), 1.0)
    suggested = round(base * multiplier, 2) if action in ("买入", "卖出") else None
    over_position = suggested is not None and suggested > fund.position_amount

    if suggested is not None:
        note += f"，建议{action} ¥{suggested:,.0f}"
        if multiplier > 1.0:
            note += f"（×{multiplier:.2f}）"
        if over_position:
            note += "，⚠超过仓位金额"

    return {
        "code": fund.code,
        "name": fund.name,
        "week_end": week_end.strftime("%Y-%m-%d"),
        "rsi": round(float(r_last), 2) if r_valid else None,
        "state": "持仓" if holding else "空仓",
        "action": action,
        "note": note,
        "exec_note": ("下一交易日开盘执行" if next_day else
                      "下周一开盘执行（以实际交易日为准）"),
        "next_exec_date": next_day,
        "last_flip_date": last_action_date.strftime("%Y-%m-%d") if last_action_date is not None else None,
        "params": {"rsi_buy": fund.rsi_buy, "rsi_sell": fund.rsi_sell,
                   "position_amount": fund.position_amount,
                   "position_ratio": fund.position_ratio,
                   "mult_mode": fund.mult_mode, "mult_factor": fund.mult_factor},
        "suggested_amount": suggested,
        "base_amount": base,
        "multiplier": round(multiplier, 4),
        "over_position": over_position,
        "position_amount": fund.position_amount,
        "provider": meta.get("provider"),
        "stale": meta.get("stale", False),
        "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def _two_years_ago() -> str:
    from datetime import timedelta
    return (datetime.now() - timedelta(days=760)).strftime("%Y-%m-%d")
