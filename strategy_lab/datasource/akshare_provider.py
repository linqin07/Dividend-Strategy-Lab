# -*- coding: utf-8 -*-
"""akshare 数据源：指数/ETF 日K、场外基金历史净值"""
from __future__ import annotations

from strategy_lab.datasource.base import DataProvider


class AkshareProvider(DataProvider):
    name = "akshare"

    def _ak(self):
        import akshare as ak
        return ak

    def fetch_daily(self, code, market, kind, start=None, end=None):
        try:
            ak = self._ak()
            if kind == "index":
                df = ak.index_zh_a_hist(symbol=code, period="daily")
            elif kind == "fund":
                # 场外基金历史净值（单位净值）
                df = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
                df = df.rename(columns={"净值日期": "日期", "单位净值": "收盘"})
                df["开盘"] = df["收盘"]
                df["最高"] = df["收盘"]
                df["最低"] = df["收盘"]
                df["成交量"] = 0
            else:
                df = ak.fund_etf_hist_em(symbol=code, period="daily", adjust="")
                df = df.rename(columns={"日期": "日期"})
            # 统一列名 → 内部标准
            ren = {}
            for src, dst in [("日期", "date"), ("开盘", "open"), ("收盘", "close"),
                             ("最高", "high"), ("最低", "low"), ("成交量", "volume")]:
                if src in df.columns:
                    ren[src] = dst
            df = df.rename(columns=ren)
            if "date" not in df.columns:
                return None
            df["date"] = df["date"].astype(str).str.replace("/", "-")
            df = df[["date", "open", "high", "low", "close", "volume"]]
            from strategy_lab.datasource.base import normalize_bars
            bars = df.values.tolist()
            out = normalize_bars(bars)
            if out is not None and len(out) > 30:
                return out
            return None
        except Exception:
            return None

    def fetch_dividends(self, fund):
        if fund.kind != "fund":
            return None
        try:
            ak = self._ak()
            df = ak.fund_open_fund_info_em(symbol=fund.code, indicator="累计净值走势")
            # 场外基金分红由累计净值与单位净值差推得，此处不精确，返回 None 走手工表
            return None
        except Exception:
            return None
