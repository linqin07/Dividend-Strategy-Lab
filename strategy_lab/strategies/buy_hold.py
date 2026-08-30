# -*- coding: utf-8 -*-
"""⑥ 买入持有：窗口首个交易日开盘一次性满仓。"""
from __future__ import annotations

import pandas as pd

from strategy_lab.strategies.base import Sig, Strategy


class BuyHoldStrategy(Strategy):
    id = "buy_hold"
    name = "买入持有"

    def plan(self, daily: pd.DataFrame, start: str, end: str) -> list[Sig]:
        df = daily[daily["date"] >= pd.to_datetime(start)] if start else daily
        if end:
            df = df[df["date"] <= pd.to_datetime(end)]
        if not len(df):
            return []
        first = df.iloc[0]
        d_str = first["date"].strftime("%Y-%m-%d")
        return [Sig(d_str, d_str, 1.0, "窗口首日开盘满仓，长期持有")]
