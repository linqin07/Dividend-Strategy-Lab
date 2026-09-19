# -*- coding: utf-8 -*-
"""腾讯行情接口（web.ifzq.gtimg.cn）：ETF / 股票日K（不复权），二级兜底

注意：
1. 域名必须是 web.ifzq.gtimg.cn，直接用 ifzq.gtimg.cn 会返回空数据；
2. param 的 count 字段上限约 2000 根，传 60000 这类大值会返回空数据；
3. 中证指数（如 932305）腾讯不支持，需走 csindex 源。
"""
from __future__ import annotations

from datetime import datetime

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
        url = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"
        # 不复权（fq 字段留空）；count 超过 2000 会被接口判为非法并返回空
        day_start = (start or "1990-01-01").replace("/", "-")
        day_end = (end or datetime.now().strftime("%Y-%m-%d")).replace("/", "-")
        params = {"param": f"{sym},day,{day_start},{day_end},2000,"}
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
