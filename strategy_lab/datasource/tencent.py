# -*- coding: utf-8 -*-
"""腾讯行情接口（ifzq.gtimg.cn）：指数 / ETF 日K（不复权），二级兜底"""
from __future__ import annotations

import requests

from strategy_lab.datasource.base import DataProvider, normalize_bars

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _symbol(code: str, market: str, kind: str) -> str:
    if kind == "index":
        if code.startswith("9"):
            return f"cs{code}"        # 中证指数
        return ("sh" if market == "SH" else "sz") + code
    return ("sh" if market == "SH" else "sz") + code


class TencentProvider(DataProvider):
    name = "tencent"

    def fetch_daily(self, code, market, kind, start=None, end=None):
        sym = _symbol(code, market, kind)
        url = "https://ifzq.gtimg.cn/appstock/app/fqkline/get"
        params = {"param": f"{sym},day,,,,60000,"}   # 不复权
        try:
            r = requests.get(url, params=params, headers=UA, timeout=15)
            data = (r.json().get("data") or {}).get(sym) or {}
            rows = data.get("day") or []
            bars = []
            for p in rows:
                # [日期, 开, 收, 高, 低, 量, ...]
                if isinstance(p, dict):
                    continue
                bars.append([p[0], p[1], p[3], p[2], p[4], p[5] if len(p) > 5 else 0])
            df = normalize_bars(bars)
            if df is not None and len(df) > 30:
                return df
            return None
        except Exception:
            return None
