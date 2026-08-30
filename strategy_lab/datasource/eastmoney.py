# -*- coding: utf-8 -*-
"""东方财富行情接口（push2his）：指数 / ETF / 股票日K（不复权），ETF 分红"""
from __future__ import annotations

import json
import re

import requests

from strategy_lab.config import Fund
from strategy_lab.datasource.base import DataProvider, normalize_bars

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _secid(code: str, market: str, kind: str) -> str:
    if kind == "index":
        # 中证 9 系指数走 secid=2；沪综指等 000 开头指数在东财也归 1.x
        if code.startswith("9"):
            return f"2.{code}"
        return f"1.{code}" if market == "SH" else f"0.{code}"
    # ETF/股票
    return f"1.{code}" if market == "SH" else f"0.{code}"


class EastmoneyProvider(DataProvider):
    name = "eastmoney"

    def fetch_daily(self, code, market, kind, start=None, end=None):
        url = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
        params = {
            "secid": _secid(code, market, kind),
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56",
            "klt": "101",          # 日线
            "fqt": "0",            # 不复权（实际盘面价）
            "beg": (start or "19900101").replace("-", ""),
            "end": (end or "20500101").replace("-", ""),
            "lmt": "1000000",
        }
        try:
            r = requests.get(url, params=params, headers=UA, timeout=15)
            data = r.json().get("data") or {}
            klines = data.get("klines") or []
            bars = []
            for line in klines:
                p = line.split(",")
                # f51 日期, f52 开, f53 收, f54 高, f55 低, f56 量
                bars.append([p[0], p[1], p[4], p[2], p[3], p[5]])
            df = normalize_bars(bars)
            if df is not None and len(df) > 30:
                return df
            return None
        except Exception:
            return None

    def fetch_dividends(self, fund: Fund):
        """天天基金 F10 分红送配页解析（ETF 亦适用，如 515080）。
        表行格式：<tr><td>2026年</td><td>权益登记日</td><td>除息日</td><td>每10份派现金X元</td><td>发放日</td></tr>"""
        url = f"https://fundf10.eastmoney.com/fhsp_{fund.code}.html"
        try:
            r = requests.get(url, headers=UA, timeout=15)
            r.encoding = "utf-8"
            html = r.text
            rows = re.findall(
                r"<tr><td>\d{4}年</td>\s*<td>(\d{4}-\d{2}-\d{2})</td>\s*"
                r"<td>(\d{4}-\d{2}-\d{2})</td>\s*<td>每10份派现金([\d.]+)元</td>",
                html)
            out = []
            for _reg, ex_date, cash in rows:
                # 除息日为价格调整日，以该日计分红现金
                out.append({"date": ex_date, "cash_per_unit": float(cash) / 10.0})
            out.sort(key=lambda x: x["date"])
            return out if out else None
        except Exception:
            return None
