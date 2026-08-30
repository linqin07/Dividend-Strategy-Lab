# -*- coding: utf-8 -*-
"""中证指数官网 index-perf API：中证 9xxxxx / 000xxx 指数完整历史（收盘价，可追溯至基日）"""
from __future__ import annotations

import requests

from strategy_lab.datasource.base import DataProvider, normalize_bars

UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://www.csindex.com.cn/",
}


def _fmt(d: str) -> str:
    return d.replace("-", "")


class CsindexProvider(DataProvider):
    name = "csindex"

    def fetch_daily(self, code, market, kind, start=None, end=None):
        if kind != "index":
            return None
        if not (code.startswith("9") or (code.startswith("0") and code != "000001")):
            # 仅中证系指数；上证综指等交易所指数走其他源
            return None
        url = "https://www.csindex.com.cn/csindex-home/perf/index-perf"
        params = {
            "indexCode": code,
            "startDate": _fmt(start or "2004-01-01"),
            "endDate": _fmt(end or "2099-12-31"),
        }
        try:
            r = requests.get(url, params=params, headers=UA, timeout=25)
            rows = (r.json() or {}).get("data") or []
            bars = []
            for it in rows:
                d = str(it.get("tradeDate", ""))
                if len(d) != 8:
                    continue
                d = f"{d[:4]}-{d[4:6]}-{d[6:]}"
                c = it.get("close")
                if c is None:
                    continue
                o = it.get("open") or c
                h = it.get("high") or c
                l = it.get("low") or c
                v = it.get("tradingVol") or 0
                bars.append([d, o, h, l, c, v])
            df = normalize_bars(bars)
            if df is not None and len(df) > 30:
                return df
            return None
        except Exception:
            return None
