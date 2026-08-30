# -*- coding: utf-8 -*-
"""回测指标：累计收益、最大回撤、夏普（月度年化-2%无风险）、卡玛、平均仓位"""
from __future__ import annotations

import numpy as np
import pandas as pd

from strategy_lab.config import RF_ANNUAL


def compute_metrics(equity_curve: list, init_cash: float) -> dict:
    if not equity_curve or len(equity_curve) < 2:
        return {}
    eq = pd.Series([row[1] for row in equity_curve],
                   index=pd.to_datetime([row[0] for row in equity_curve]))
    pos = pd.Series([row[2] for row in equity_curve], index=eq.index)

    cumulative_return = eq.iloc[-1] / init_cash - 1.0

    # 最大回撤
    peak = eq.cummax()
    dd = eq / peak - 1.0
    max_drawdown = float(dd.min())

    # 月度收益 → 年化
    monthly = eq.resample("ME").last().pct_change().dropna()
    if len(monthly) >= 3 and monthly.std() > 0:
        ann_ret = monthly.mean() * 12
        ann_vol = monthly.std() * np.sqrt(12)
        sharpe = (ann_ret - RF_ANNUAL) / ann_vol
    else:
        ann_ret = cumulative_return
        ann_vol = 0.0
        sharpe = 0.0
    # 年化收益（几何）
    n_years = max((eq.index[-1] - eq.index[0]).days / 365.25, 1e-9)
    ann_ret_geo = (eq.iloc[-1] / init_cash) ** (1 / n_years) - 1

    calmar = ann_ret_geo / abs(max_drawdown) if max_drawdown < 0 else 0.0

    return {
        "cumulative_return": round(float(cumulative_return), 4),
        "max_drawdown": round(max_drawdown, 4),
        "sharpe": round(float(sharpe), 2),
        "calmar": round(float(calmar), 2),
        "ann_return": round(float(ann_ret_geo), 4),
        "avg_position": round(float(pos.mean()), 4),
    }
