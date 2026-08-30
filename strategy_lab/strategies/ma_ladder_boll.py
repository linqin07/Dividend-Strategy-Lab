# -*- coding: utf-8 -*-
"""⑤ 年线阶梯建仓 + 布林带滚动浮动仓：固定50%（年线下5批各10%）+ 浮动50%按周布林滚动。
滚动规则：周收盘上穿上轨 → 卖浮动仓；周收盘回落至中轨下方 → 买回浮动仓。"""
from __future__ import annotations

import pandas as pd

from strategy_lab.strategies.base import Sig, Strategy
from strategy_lab.strategies.ma_ladder_rsi import FIXED_TOTAL, FLOAT_TOTAL, STEP


class MaLadderBollStrategy(Strategy):
    id = "ma_ladder_boll"
    name = "年线建仓+布林带滚动"

    def plan(self, daily: pd.DataFrame, start: str, end: str) -> list[Sig]:
        adj, weekly, _, ma250, boll_df = self._context(daily)
        ladder = self.fund.ladder

        df = daily[daily["date"] >= pd.to_datetime(start)] if start else daily
        if end:
            df = df[df["date"] <= pd.to_datetime(end)]
        df = df.reset_index(drop=True)
        ma_series = ma250.reindex(daily.index)

        events: list[tuple] = []   # (exec_date, sig_date, fixed_after, float_after, reason)

        # ---- 固定仓阶梯 ----
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

        # ---- 浮动仓：周布林 ----
        for i in range(len(weekly)):
            up = boll_df["up"].iloc[i]
            mid = boll_df["mid"].iloc[i]
            c = weekly["close"].iloc[i]
            if pd.isna(up) or pd.isna(mid):
                continue
            sig_date = weekly["date"].iloc[i]
            d_str = sig_date.strftime("%Y-%m-%d")
            if not self._in_window(d_str, start, end):
                continue
            exec_d = self._next_trading_day(daily, sig_date)
            if c < mid:
                events.append((exec_d, d_str, None, True, f"周收盘{c:.3f} 回落至中轨下方，浮动50%买入"))
            elif c > up:
                events.append((exec_d, d_str, None, False, f"周收盘{c:.3f} 上穿上轨，浮动50%卖出"))

        # 统一时间线合并
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
        out = []
        for s in sigs:
            if out and abs(out[-1].target_pos - s.target_pos) < 1e-9 and s.exec_date == out[-1].exec_date:
                continue
            out.append(s)
        return out
