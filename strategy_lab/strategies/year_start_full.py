# -*- coding: utf-8 -*-
"""② 每年年初满仓 + RSI 全仓滚动：每年第一个交易日满仓；此后 RSI>卖出线全卖、RSI<买入线全买。
年事件与RSI事件按时间交织，状态机只有 空仓↔持仓 两态，同向重复信号一律忽略。"""
from __future__ import annotations

import pandas as pd

from strategy_lab.strategies.base import Sig, Strategy


class YearStartFullStrategy(Strategy):
    id = "year_start_full"
    name = "年初满仓+RSI全仓滚动"

    def plan(self, daily: pd.DataFrame, start: str, end: str) -> list[Sig]:
        adj, weekly, rsi, _, _ = self._context(daily)
        buy, sell = self.fund.rsi_buy, self.fund.rsi_sell

        # 事件流：(排序键, exec_date, sig_date, 事件类型, reason)
        events: list[tuple] = []

        df = daily[daily["date"] >= pd.to_datetime(start)] if start else daily
        if end:
            df = df[df["date"] <= pd.to_datetime(end)]
        years_seen = set()
        for _, row in df.iterrows():
            y = row["date"].year
            if y in years_seen:
                continue
            years_seen.add(y)
            d_str = row["date"].strftime("%Y-%m-%d")
            events.append((d_str, d_str, "year", f"{y}年首个交易日，年初满仓"))

        for i in range(len(weekly)):
            r = rsi.iloc[i]
            if pd.isna(r):
                continue
            sig_date = weekly["date"].iloc[i]
            d_str = sig_date.strftime("%Y-%m-%d")
            if not self._in_window(d_str, start, end):
                continue
            exec_d = self._next_trading_day(daily, sig_date)
            if r < buy:
                events.append((exec_d, d_str, "rsi_buy", f"周RSI={r:.1f} < {buy:.0f}，空仓→全仓买入"))
            elif r > sell:
                events.append((exec_d, d_str, "rsi_sell", f"周RSI={r:.1f} > {sell:.0f}，持仓→全仓卖出"))

        # 按执行时间交织处理状态机
        events.sort(key=lambda e: (e[0], e[1]))
        holding = False
        sigs = []
        for key, d_str, kind, reason in events:
            if kind in ("year", "rsi_buy"):
                if not holding:
                    holding = True
                    sigs.append(Sig(d_str, key, 1.0, reason))
            elif kind == "rsi_sell":
                if holding:
                    holding = False
                    sigs.append(Sig(d_str, key, 0.0, reason))
        return sigs
