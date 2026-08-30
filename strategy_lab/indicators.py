# -*- coding: utf-8 -*-
"""技术指标：周线重采样、RSI(14) Wilder、BOLL(20,2)、MA250、拆分抹平"""
from __future__ import annotations

import pandas as pd


def split_adjusted(daily: pd.DataFrame, splits: list) -> pd.DataFrame:
    """拆分抹平：拆分日之前的价格除以 ratio，仅用于指标计算（消除 512890 1:2 假缺口）。
    引擎成交仍用真实盘面价。"""
    df = daily.copy()
    if not splits:
        return df
    for sp in splits:
        d = pd.to_datetime(sp["date"])
        ratio = float(sp["ratio"])
        mask = df["date"] < d
        for col in ("open", "high", "low", "close"):
            df.loc[mask, col] = df.loc[mask, col] / ratio
    return df


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """日线重采样为周线：周一~周五一组，o=首日开、c=末日收、h/l 极值。
    使用 ISO 周分组，与通达信/行情软件周线口径一致。"""
    df = daily.copy()
    df["week"] = df["date"].dt.strftime("%G-%V")   # ISO 年-周
    g = df.groupby("week", sort=True)
    weekly = pd.DataFrame({
        "date": g["date"].last(),        # 周最后交易日（通常周五）
        "open": g["open"].first(),
        "high": g["high"].max(),
        "low": g["low"].min(),
        "close": g["close"].last(),
    })
    weekly = weekly.reset_index(drop=True)
    return weekly


def rsi_wilder(close: pd.Series, period: int = 14) -> pd.Series:
    """Wilder 平滑 RSI。首值用 SMA 初始化，之后 Wilder 递推。"""
    delta = close.astype(float).diff()
    gain = delta.clip(lower=0.0)
    loss = (-delta).clip(lower=0.0)
    avg_gain = gain.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100.0 - 100.0 / (1.0 + rs)
    rsi[avg_loss == 0] = 100.0
    return rsi


def boll(close: pd.Series, period: int = 20, k: float = 2.0) -> pd.DataFrame:
    """布林带 BOLL(period, k)"""
    mid = close.rolling(period).mean()
    std = close.rolling(period).std(ddof=0)
    return pd.DataFrame({"mid": mid, "up": mid + k * std, "low": mid - k * std})


def ma(close: pd.Series, period: int = 250) -> pd.Series:
    """年线 MA250"""
    return close.rolling(period).mean()
