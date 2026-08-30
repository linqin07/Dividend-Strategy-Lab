# -*- coding: utf-8 -*-
"""DataProvider 抽象基类"""
from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from strategy_lab.config import Fund

# 统一日线 DataFrame 列：date(datetime64), open, high, low, close, volume


class DataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def fetch_daily(self, code: str, market: str, kind: str,
                    start: str | None = None, end: str | None = None) -> pd.DataFrame | None:
        """返回不复权日线 DataFrame（date/open/high/low/close/volume），失败返回 None"""

    def fetch_dividends(self, fund: Fund) -> list | None:
        """返回 [{"date","cash_per_unit"}]，无该能力或失败返回 None"""
        return None

    def fetch_splits(self, fund: Fund) -> list | None:
        """返回 [{"date","ratio"}]，无该能力或失败返回 None"""
        return None


def normalize_bars(bars: list) -> pd.DataFrame:
    """把 [[date,open,high,low,close,volume], ...] 规整为标准 DataFrame"""
    if not bars:
        return None
    df = pd.DataFrame(bars, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=["open", "high", "low", "close"]).sort_values("date").reset_index(drop=True)
    return df if len(df) else None
