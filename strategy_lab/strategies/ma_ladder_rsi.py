# -*- coding: utf-8 -*-
"""④ 年线阶梯建仓 + RSI 滚动浮动仓：固定50%（年线下方5批各10%）+ 浮动50%按周RSI滚动。
固定仓与浮动仓事件统一时间线合并，保证目标仓位 = 固定仓 + 浮动仓。"""
from __future__ import annotations

import pandas as pd

from strategy_lab.strategies.base import Sig, Strategy

FIXED_TOTAL = 0.5
FLOAT_TOTAL = 0.5
STEP = 0.1   # 每档 10%


class MaLadderRsiStrategy(Strategy):
    id = "ma_ladder_rsi"
    name = "年线建仓+RSI滚动"

    def plan(self, daily: pd.DataFrame, start: str, end: str) -> list[Sig]:
        adj, weekly, rsi, ma250, _ = self._context(daily)
        buy, sell = self.fund.rsi_buy, self.fund.rsi_sell
        ladder = self.fund.ladder

        df = daily[daily["date"] >= pd.to_datetime(start)] if start else daily
        if end:
            df = df[df["date"] <= pd.to_datetime(end)]
        df = df.reset_index(drop=True)
        ma_series = ma250.reindex(daily.index)

        # 事件流：(exec_date, fixed_level_after, float_after, reason)
        events: list[tuple] = []

        # ---- 固定仓：价格首次跌破 年线×(1+档位) 各建 10% ----
        fixed = 0.0
        bought_levels = set()
        for idx, row in df.iterrows():
            m = ma_series.iloc[idx]
            if pd.isna(m):
                continue
            close = row["close"]
            for li, lv in enumerate(ladder):
                if li in bought_levels:
                    continue
                if close < m * (1 + lv / 100.0):
                    bought_levels.add(li)
                    fixed = min(FIXED_TOTAL, fixed + STEP)
                    d_str = row["date"].strftime("%Y-%m-%d")
                    exec_d = self._next_trading_day(daily, row["date"])
                    events.append((exec_d, d_str, fixed, None,
                                   f"收盘{close:.3f} 跌破年线×{1+lv/100:.3f}（{lv:.1f}%档），固定仓至{fixed:.0%}"))

        # ---- 浮动仓：RSI 滚动 ----
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
                events.append((exec_d, d_str, None, True,
                               f"周RSI={r:.1f} < {buy:.0f}，浮动50%买入"))
            elif r > sell:
                events.append((exec_d, d_str, None, False,
                               f"周RSI={r:.1f} > {sell:.0f}，浮动50%卖出"))

        return self._merge_events(events)

    def _merge_events(self, events: list) -> list[Sig]:
        """统一时间线：fixed=None 表示不变，float∈{True,False}。"""
        events.sort(key=lambda e: (e[0], e[1]))
        fixed = 0.0
        float_on = False
        sigs = []
        for exec_d, d_str, f, fl, reason in events:
            if f is not None:
                fixed = f
            if fl is not None:
                float_on = fl
            target = fixed + (FLOAT_TOTAL if float_on else 0.0)
            sigs.append(Sig(d_str, exec_d, round(target, 4), reason))
        # 去掉连续重复的同目标信号
        out = []
        for s in sigs:
            if out and abs(out[-1].target_pos - s.target_pos) < 1e-9 and s.exec_date == out[-1].exec_date:
                continue
            out.append(s)
        return out
