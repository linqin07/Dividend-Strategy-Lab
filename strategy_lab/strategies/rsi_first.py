# -*- coding: utf-8 -*-
"""① 纯RSI首次建仓：空仓等待，周RSI<买入线首次全仓买入；持仓后 RSI>卖出线全卖。
状态机只有 空仓↔持仓 两态，同向重复信号一律忽略。"""
from __future__ import annotations

import pandas as pd

from strategy_lab.strategies.base import Sig, Strategy


class RsiFirstStrategy(Strategy):
    id = "rsi_first"
    name = "纯RSI首次建仓"

    def plan(self, daily: pd.DataFrame, start: str, end: str) -> list[Sig]:
        adj, weekly, rsi, _, _ = self._context(daily)
        buy, sell = self.fund.rsi_buy, self.fund.rsi_sell
        sigs: list[Sig] = []
        holding = False
        for i in range(len(weekly)):
            r = rsi.iloc[i]
            if pd.isna(r):
                continue
            sig_date = weekly["date"].iloc[i]
            d_str = sig_date.strftime("%Y-%m-%d")
            if not self._in_window(d_str, start, end):
                continue
            exec_d = self._next_trading_day(daily, sig_date)
            if not holding and r < buy:
                holding = True
                sigs.append(Sig(d_str, exec_d, 1.0, f"周RSI={r:.1f} < {buy:.0f}，空仓→全仓买入"))
            elif holding and r > sell:
                holding = False
                sigs.append(Sig(d_str, exec_d, 0.0, f"周RSI={r:.1f} > {sell:.0f}，持仓→全仓卖出"))
        return sigs
