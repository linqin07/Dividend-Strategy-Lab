# -*- coding: utf-8 -*-
"""创业板指 / 中证红利 跷跷板面板数据构建

拉取两只指数日线（复用 datasource 多源链 + 缓存），按日期对齐后截取近五年，
返回并落盘 output/rotation.json，供：
  - GET /api/rotation/data（FastAPI 实时接口）
  - python run.py rotation（CI 周刷新，静态托管页面直接读 output/rotation.json）

返回结构：
{
  "asof": "YYYY-MM-DD HH:MM:SS",      # 生成时间
  "growth_code": "399006",  "growth_name": "创业板指",
  "dividend_code": "000922", "dividend_name": "中证红利",
  "providers": {"growth": "...", "dividend": "..."},
  "stale": false,                      # 任一源为缓存兜底则为 true
  "dates": [...], "growth": [...], "dividend": [...]
}
"""
from __future__ import annotations

import os
from datetime import datetime

from strategy_lab.config import Fund, OUTPUT_DIR, atomic_write_json, ensure_dirs

GROWTH_FUND = Fund(code="399006", name="创业板指", kind="index", market="SZ")
DIVIDEND_FUND = Fund(code="000922", name="中证红利", kind="index", market="SH")

ROTATION_JSON = os.path.join(OUTPUT_DIR, "rotation.json")
YEARS = 5   # 面板展示窗口（近五年）


def build_rotation_data(force: bool = False) -> dict:
    """拉取并对齐两只指数日线，返回面板数据 dict（不落盘）。"""
    from strategy_lab.datasource import get_daily

    g_df, g_meta = get_daily(GROWTH_FUND, force=force)
    d_df, d_meta = get_daily(DIVIDEND_FUND, force=force)
    if g_df is None or not len(g_df):
        raise RuntimeError(f"创业板指行情获取失败: {g_meta.get('errors')}")
    if d_df is None or not len(d_df):
        raise RuntimeError(f"中证红利行情获取失败: {d_meta.get('errors')}")

    # 按交易日取交集对齐（两只指数交易日历一致，交集即可）
    g = {dt.strftime("%Y-%m-%d"): float(c) for dt, c in zip(g_df["date"], g_df["close"])}
    d = {dt.strftime("%Y-%m-%d"): float(c) for dt, c in zip(d_df["date"], d_df["close"])}
    dates = sorted(set(g) & set(d))

    # 截取近五年
    cutoff = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
              .toordinal() - int(365.25 * YEARS))
    cutoff_s = datetime.fromordinal(cutoff).strftime("%Y-%m-%d")
    dates = [x for x in dates if x >= cutoff_s]
    if len(dates) < 250:
        raise RuntimeError(f"对齐后有效交易日不足（{len(dates)}），无法构建面板")

    return {
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "growth_code": GROWTH_FUND.code, "growth_name": GROWTH_FUND.name,
        "dividend_code": DIVIDEND_FUND.code, "dividend_name": DIVIDEND_FUND.name,
        "providers": {"growth": g_meta.get("provider"), "dividend": d_meta.get("provider")},
        "stale": bool(g_meta.get("stale") or d_meta.get("stale")),
        "dates": dates,
        "growth": [round(g[x], 2) for x in dates],
        "dividend": [round(d[x], 2) for x in dates],
    }


def write_rotation_json(force: bool = False) -> dict:
    """构建并落盘 output/rotation.json，返回数据 dict。"""
    ensure_dirs()
    data = build_rotation_data(force=force)
    atomic_write_json(ROTATION_JSON, data)
    return data
