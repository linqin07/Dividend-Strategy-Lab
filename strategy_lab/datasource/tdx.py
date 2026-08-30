# -*- coding: utf-8 -*-
"""TDX 数据源：基于 tdx-mcp wheel 内置的 opentdx 顶层包（通达信行情服务器）。
失败静默返回 None，由供应商链降级。"""
from __future__ import annotations

from strategy_lab.config import Fund
from strategy_lab.datasource.base import DataProvider, normalize_bars

_PAGE = 800   # 单次 K 线请求上限


class TdxProvider(DataProvider):
    name = "tdx"

    def _client(self):
        from opentdx import TdxClient
        return TdxClient()

    def fetch_daily(self, code, market, kind, start=None, end=None):
        if kind != "etf":
            # 中证 9 系指数在 TDX 标准行情里通常不可得，指数走 HTTP 源更稳
            return None
        try:
            from opentdx import MARKET, PERIOD, ADJUST
            mkt = MARKET.SH if market == "SH" else MARKET.SZ
            with self._client() as client:
                rows = []
                offset = 0
                oldest_needed = str(start or "1990-01-01")
                for _ in range(20):   # 最多 20 页 = 16000 根
                    batch = client.stock_kline(mkt, code, PERIOD.DAILY,
                                               start=offset, count=_PAGE,
                                               adjust=ADJUST.NONE)
                    if not batch:
                        break
                    rows.extend(batch)
                    oldest = str(batch[-1].get("datetime", ""))[:10]
                    if oldest <= oldest_needed or len(batch) < _PAGE:
                        break
                    offset += _PAGE
            bars = []
            for b in rows:
                d = str(b.get("datetime", ""))[:10]
                if not d or d < "1990-01-01":
                    continue
                bars.append([d, b.get("open"), b.get("high"), b.get("low"),
                             b.get("close"), b.get("vol", 0)])
            df = normalize_bars(bars)
            if df is not None and len(df) > 30:
                return df
            return None
        except Exception:
            return None
