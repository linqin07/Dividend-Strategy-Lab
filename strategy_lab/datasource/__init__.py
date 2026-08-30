# -*- coding: utf-8 -*-
"""数据门面：供应商链 + 缓存 + 多源合并降级。
设计：按 fund.provider_order 逐个供应商抓取，结果按日期合并（先到者优先），
当合并结果已覆盖请求区间起点并足够新鲜时提前停止。全部失败用缓存兜底并标 stale。"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from strategy_lab.config import Fund
from strategy_lab.datasource import cache
from strategy_lab.datasource.base import normalize_bars

_providers: dict | None = None


def _get_providers() -> dict:
    global _providers
    if _providers is not None:
        return _providers
    from strategy_lab.datasource.eastmoney import EastmoneyProvider
    from strategy_lab.datasource.tencent import TencentProvider
    from strategy_lab.datasource.csindex import CsindexProvider
    from strategy_lab.datasource.akshare_provider import AkshareProvider
    ps = {
        "eastmoney": EastmoneyProvider(),
        "tencent": TencentProvider(),
        "csindex": CsindexProvider(),
        "akshare": AkshareProvider(),
    }
    try:
        from strategy_lab.datasource.tdx import TdxProvider
        ps["tdx"] = TdxProvider()
    except Exception:
        pass
    _providers = ps
    return ps


def get_daily(fund: Fund, start: str | None = None, end: str | None = None,
              force: bool = False) -> tuple[pd.DataFrame | None, dict]:
    """取不复权日线（多源合并）。返回 (DataFrame, meta)。
    meta: {"provider","stale","cached","merged_from":[...]}"""
    meta = {"provider": None, "stale": False, "cached": False, "merged_from": []}

    # 策略指标需要预热（MA250 / RSI14周），向前多取 400 个日历日
    want_start = (start or "2004-01-01")
    warm_start = (pd.to_datetime(want_start) - timedelta(days=400)).strftime("%Y-%m-%d")
    fresh_line = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")

    if not force and cache.cache_is_fresh(fund.code):
        c = cache.load_cache(fund.code)
        df = cache.bars_to_df(c.get("bars", []))
        if df is not None and len(df) > 30:
            meta["provider"] = c.get("provider", "cache")
            meta["cached"] = True
            meta["merged_from"] = [meta["provider"]]
            return _clip(df, start, end), meta

    providers = _get_providers()
    merged: dict = {}          # date -> bar，先到者优先
    errors = []
    for name in fund.resolved_provider_order():
        p = providers.get(name)
        if p is None:
            errors.append(f"{name}: 不可用")
            continue
        try:
            df = p.fetch_daily(fund.code, fund.market, fund.kind, warm_start, end)
        except Exception as e:
            errors.append(f"{name}: {e}")
            df = None
        if df is None or len(df) <= 30:
            errors.append(f"{name}: 无数据")
            continue
        meta["merged_from"].append(name)
        new_dates = 0
        for d, o, h, l, c, v in zip(df["date"], df["open"], df["high"],
                                    df["low"], df["close"], df["volume"]):
            key = d.strftime("%Y-%m-%d")
            if key not in merged:
                merged[key] = [key, o, h, l, c, v]
                new_dates += 1
        if new_dates == 0 and name not in ("eastmoney", "tdx"):
            continue   # 无新增且非主源
        # 覆盖判断：合并起点 <= 预热线起点（拿到底了）且终点足够新鲜
        if merged and min(merged.keys()) <= warm_start and max(merged.keys()) >= fresh_line:
            break

    if merged:
        bars = [merged[k] for k in sorted(merged.keys())]
        provider_tag = meta["merged_from"][0] if meta["merged_from"] else "unknown"
        try:
            cache.merge_and_save(fund.code, bars, "+".join(meta["merged_from"]) or provider_tag)
        except Exception:
            # 缓存写盘失败（目标被占用/权限拒绝）不影响本次结果：数据已在内存，仅不落盘
            meta["cached"] = False
        df = cache.bars_to_df(bars)
        meta["provider"] = "+".join(meta["merged_from"])
        return _clip(df, start, end), meta

    # 全部在线源失败 → 缓存兜底
    c = cache.load_cache(fund.code)
    if c and c.get("bars"):
        df = cache.bars_to_df(c.get("bars", []))
        meta.update({"provider": c.get("provider", "cache"), "stale": True,
                     "errors": errors})
        return _clip(df, start, end), meta
    meta["errors"] = errors
    return None, meta


def _clip(df: pd.DataFrame, start, end) -> pd.DataFrame:
    if df is None or not len(df):
        return df
    if start:
        df = df[df["date"] >= pd.to_datetime(start)]
    if end:
        df = df[df["date"] <= pd.to_datetime(end)]
    return df.reset_index(drop=True)


def get_corporate_actions(fund: Fund) -> tuple[list, list]:
    """分红、拆分：供应商抓取优先，funds.json 手工表兜底合并（手工优先）"""
    dividends = []
    splits = []
    providers = _get_providers()
    for name in fund.resolved_provider_order():
        p = providers.get(name)
        if p is None:
            continue
        try:
            d = p.fetch_dividends(fund)
            if d:
                dividends = d
                break
        except Exception:
            pass
    if fund.splits:
        splits = fund.splits
    if fund.dividends:
        by_date = {d["date"]: d for d in dividends}
        for d in fund.dividends:
            by_date[d["date"]] = d
        dividends = sorted(by_date.values(), key=lambda x: x["date"])
    return dividends, splits
