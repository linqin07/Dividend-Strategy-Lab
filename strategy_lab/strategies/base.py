# -*- coding: utf-8 -*-
"""策略基类：输出『目标仓位计划』，与回测引擎解耦。"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

from strategy_lab.config import Fund
from strategy_lab.indicators import boll, ma, rsi_wilder, split_adjusted, to_weekly


@dataclass
class Sig:
    date: str          # 信号确认日（周最后交易日 / 触发日）
    exec_date: str     # 执行日（下一交易日，年首/首建可为当日）
    target_pos: float  # 执行后的目标仓位（0~1，占权益比例）
    reason: str        # 触发原因（供页面/邮件展示）


class Strategy(ABC):
    id: str = "base"
    name: str = "基类"

    def __init__(self, fund: Fund):
        self.fund = fund

    @abstractmethod
    def plan(self, daily: pd.DataFrame, start: str, end: str) -> list[Sig]:
        """生成目标仓位信号序列。daily 含预热数据（start 前 400 日历日）。"""

    # ---------- 公共工具 ----------
    def _context(self, daily: pd.DataFrame):
        """拆分抹平后的指标上下文：周线RSI、周线、MA250、周布林"""
        adj = split_adjusted(daily, self.fund.splits or [])
        weekly = to_weekly(adj)
        rsi = rsi_wilder(weekly["close"], 14)
        ma250 = ma(adj["close"], 250)
        boll_df = boll(weekly["close"], self.fund.boll_params.get("period", 20),
                       self.fund.boll_params.get("k", 2))
        return adj, weekly, rsi, ma250, boll_df

    def _next_trading_day(self, daily: pd.DataFrame, after: pd.Timestamp) -> str:
        days = daily["date"]
        idx = days.searchsorted(after, side="right")
        if idx < len(days):
            return days.iloc[idx].strftime("%Y-%m-%d")
        return after.strftime("%Y-%m-%d")   # 数据尽头，兜底返回自身

    def _in_window(self, d: str, start: str, end: str) -> bool:
        if start and d < start:
            return False
        if end and d > end:
            return False
        return True
