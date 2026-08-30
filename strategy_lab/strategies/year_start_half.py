# -*- coding: utf-8 -*-
"""③ 每年年初满仓 + RSI 半仓滚动：50% 固定底仓长期持有；另 50% 按 RSI 滚动。
年事件与RSI事件按时间交织；固定 50% 从首个年初起长期持有，永不卖出。"""
from __future__ import annotations

import pandas as pd

from strategy_lab.strategies.base import Sig, Strategy


class YearStartHalfStrategy(Strategy):
    id = "year_start_half"
    name = "年初满仓+RSI半仓滚动"

    def plan(self, daily: pd.DataFrame, start: str, end: str) -> list[Sig]:
        adj, weekly, rsi, _, _ = self._context(daily)
        buy, sell = self.fund.rsi_buy, self.fund.rsi_sell

        events: list[tuple] = []   # (exec_key, sig_date, kind, reason)

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
            events.append((d_str, d_str, "year", f"{y}年首个交易日，建仓50%固定+50%浮动"))

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
                events.append((exec_d, d_str, "float_buy",
                               f"周RSI={r:.1f} < {buy:.0f}，买回浮动50%"))
            elif r > sell:
                events.append((exec_d, d_str, "float_sell",
                               f"周RSI={r:.1f} > {sell:.0f}，卖出浮动50%（固定50%保留）"))

        events.sort(key=lambda e: (e[0], e[1]))
        started = False
        float_on = False
        sigs = []
        for key, d_str, kind, reason in events:
            if kind == "year":
                started = True
                # 每年年初浮动仓恢复满配
                if not float_on:
                    float_on = True
                sigs.append(Sig(d_str, key, 1.0, reason))
            elif started and kind == "float_buy" and not float_on:
                float_on = True
                sigs.append(Sig(d_str, key, 1.0, reason))
            elif started and kind == "float_sell" and float_on:
                float_on = False
                sigs.append(Sig(d_str, key, 0.5, reason))
        return sigs
