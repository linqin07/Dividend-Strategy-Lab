# -*- coding: utf-8 -*-
"""本地 JSON 缓存：data/{code}_daily.json，当日有效跳网，增量合并"""
from __future__ import annotations

import json
import os
from datetime import datetime

from strategy_lab.config import DATA_DIR, atomic_write_json


def _path(code: str) -> str:
    return os.path.join(DATA_DIR, f"{code}_daily.json")


def load_cache(code: str) -> dict | None:
    p = _path(code)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def cache_is_fresh(code: str) -> bool:
    """当日已抓取过则视为新鲜（收盘后数据不再变）"""
    c = load_cache(code)
    if not c:
        return False
    return str(c.get("fetched_at", ""))[:10] == datetime.now().strftime("%Y-%m-%d")


def merge_and_save(code: str, bars: list, provider: str) -> dict:
    """新数据与缓存按日期去重合并后原子写盘"""
    old = load_cache(code) or {"bars": []}
    merged = {b[0]: b for b in old.get("bars", [])}
    for b in bars:
        merged[b[0]] = b
    out = {
        "fetched_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "provider": provider,
        "start": min(merged.keys()),
        "end": max(merged.keys()),
        "bars": [merged[k] for k in sorted(merged.keys())],
    }
    atomic_write_json(_path(code), out)
    return out


def bars_to_df(bars: list):
    import pandas as pd
    if not bars:
        return None
    df = pd.DataFrame(bars, columns=["date", "open", "high", "low", "close", "volume"])
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close", "volume"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.dropna(subset=["close"]).sort_values("date").reset_index(drop=True)
