# -*- coding: utf-8 -*-
"""策略注册表：新增策略 = 新文件 + 此处一行注册。"""
from __future__ import annotations

from strategy_lab.strategies.base import Sig, Strategy
from strategy_lab.strategies.buy_hold import BuyHoldStrategy
from strategy_lab.strategies.ma_ladder_boll import MaLadderBollStrategy
from strategy_lab.strategies.ma_ladder_rsi import MaLadderRsiStrategy
from strategy_lab.strategies.rsi_first import RsiFirstStrategy
from strategy_lab.strategies.year_start_full import YearStartFullStrategy
from strategy_lab.strategies.year_start_half import YearStartHalfStrategy

REGISTRY: dict = {
    cls.id: cls
    for cls in (
        RsiFirstStrategy,
        YearStartFullStrategy,
        YearStartHalfStrategy,
        MaLadderRsiStrategy,
        MaLadderBollStrategy,
        BuyHoldStrategy,
    )
}

__all__ = ["REGISTRY", "Strategy", "Sig"]


def list_strategies() -> list:
    return [{"id": k, "name": v.name} for k, v in REGISTRY.items()]
