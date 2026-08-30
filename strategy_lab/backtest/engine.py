# -*- coding: utf-8 -*-
"""事件驱动日频回测引擎。
口径（严格对应《红利策略报告》）：
- 信号周五收盘确认，下一交易日开盘成交；无下一交易日则顺延（数据尽头丢弃）
- 成交价为实际盘面价（不复权），买卖各扣 0.1% 成本
- 显式分红：持仓日遇除息日分红计入现金；空仓期无分红；下次买入连本带分红投入
- 拆分：拆分日份额×ratio，市值不变
- 累计收益从期初现金起算（不从首日收盘价）
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from strategy_lab.config import FEE, INIT_CASH, Fund
from strategy_lab.strategies.base import Sig, Strategy


@dataclass
class BTResult:
    strategy_id: str
    strategy_name: str
    equity_curve: list = field(default_factory=list)      # [[date, equity, position_ratio]]
    trades: list = field(default_factory=list)            # [{date,side,price,shares,amount,fee,equity}]
    metrics: dict = field(default_factory=dict)
    signals: list = field(default_factory=list)           # 原始信号序列


def run_backtest(fund: Fund, strategy: Strategy, daily: pd.DataFrame,
                 dividends: list, splits: list,
                 start: str, end: str,
                 init_cash: float = INIT_CASH, fee: float = FEE) -> BTResult:
    sigs: list[Sig] = strategy.plan(daily, start, end)

    df = daily[(daily["date"] >= pd.to_datetime(start)) &
               (daily["date"] <= pd.to_datetime(end))].reset_index(drop=True)
    if not len(df):
        return BTResult(strategy.id, strategy.name)

    # 除息/拆分索引
    div_map = {pd.to_datetime(d["date"]): float(d["cash_per_unit"]) for d in (dividends or [])}
    split_map = {pd.to_datetime(s["date"]): float(s["ratio"]) for s in (splits or [])}

    # 信号按执行日归并（同一执行日，后者覆盖前者）
    date_index = {d.strftime("%Y-%m-%d"): i for i, d in enumerate(df["date"])}
    pending: dict = {}
    for s in sigs:
        ed = s.exec_date
        if ed in date_index:
            pending[date_index[ed]] = s
        else:
            # 顺延到下一个交易日
            pos = df["date"].searchsorted(pd.to_datetime(ed))
            if pos < len(df):
                pending[pos] = s

    cash = init_cash
    shares = 0.0
    result = BTResult(strategy.id, strategy.name)
    result.signals = [{"date": s.date, "exec_date": s.exec_date,
                       "target_pos": s.target_pos, "reason": s.reason} for s in sigs]

    for i in range(len(df)):
        row = df.iloc[i]
        d = row["date"]
        price_open = float(row["open"])
        price_close = float(row["close"])

        # 1) 拆分：份额翻倍，价格自然跳低（市值不变）
        if d in split_map:
            shares *= split_map[d]

        # 2) 分红：昨日持仓者获得现金（当日开盘买入者不含）
        if d in div_map and shares > 0:
            cash += shares * div_map[d]

        # 3) 执行信号：调仓至目标仓位（开盘价成交）
        if i in pending:
            s = pending[i]
            equity_pre = cash + shares * price_open
            desired = s.target_pos * equity_pre
            current = shares * price_open
            if desired > current + 1e-9:
                spend = min(desired - current, cash)
                buy_shares = spend * (1 - fee) / price_open
                cash -= spend
                shares += buy_shares
                result.trades.append({
                    "date": d.strftime("%Y-%m-%d"), "side": "买入", "price": price_open,
                    "shares": buy_shares, "amount": spend, "fee": spend * fee,
                    "reason": s.reason, "equity": cash + shares * price_open})
            elif desired < current - 1e-9:
                sell_shares = (current - desired) / price_open
                proceeds = sell_shares * price_open * (1 - fee)
                shares -= sell_shares
                cash += proceeds
                result.trades.append({
                    "date": d.strftime("%Y-%m-%d"), "side": "卖出", "price": price_open,
                    "shares": sell_shares, "amount": sell_shares * price_open,
                    "fee": sell_shares * price_open * fee,
                    "reason": s.reason, "equity": cash + shares * price_open})

        # 4) 收盘记录权益
        equity = cash + shares * price_close
        ratio = (shares * price_close / equity) if equity > 0 else 0.0
        result.equity_curve.append([d.strftime("%Y-%m-%d"), round(equity, 2), round(ratio, 4)])

    # 末日强制按收盘清仓口径不影响累计收益（现金+市值即权益），无需额外处理
    from strategy_lab.backtest.metrics import compute_metrics
    result.metrics = compute_metrics(result.equity_curve, init_cash)
    return result
