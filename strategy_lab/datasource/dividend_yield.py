# -*- coding: utf-8 -*-
"""实时股息率：中证指数官网估值为主（股息率1=静态 / 股息率2=滚动TTM），动态 TTM 兜底。

口径说明（对应《红利策略报告》2.4 节的分红口径）：
- 中证官网股息率1 = 按上一年度现金分红（静态）；
- 股息率2 = 近12个月滚动现金分红 / 最新收盘价（TTM），更贴近当前持有回报；
- 动态 TTM 兜底 = 在线分红记录（近12个月）÷ 腾讯实时价，仅用于无官方口径的标的。
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta

import requests

from strategy_lab.config import Fund, load_funds

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
      "Referer": "https://www.csindex.com.cn/"}

# 基金代码 → 跟踪的中证指数代码（funds.json 的 index_code 字段优先，此处为兜底）
DEFAULT_INDEX_CODE = {
    "932305": "932305",      # 中证智选高股息策略指数
    "515080": "000922",      # 中证红利
    "512890": "H30269",      # 中证红利低波动
    "501089": "H30094",      # 中证主要消费红利（消费红利增强跟踪）
}

# 进程内短缓存：避免页面频繁刷新打爆上游（官网估值 10 分钟 / 动态 TTM 5 分钟）
_CACHE: dict = {}
_CACHE_TTL = {
    "csindex": 600,
    "dynamic": 300,
}


def _cache_get(key: str) -> dict | None:
    hit = _CACHE.get(key)
    if hit and time.time() - hit["ts"] < _CACHE_TTL.get(hit.get("kind", "csindex"), 600):
        return hit["value"]
    return None


def _cache_set(key: str, value: dict, kind: str) -> None:
    _CACHE[key] = {"ts": time.time(), "value": value, "kind": kind}


def clear_cache() -> None:
    """清空进程内缓存（前端「刷新」时调用，强制重新抓取）"""
    _CACHE.clear()


def resolve_index_code(fund: Fund) -> str | None:
    return fund.index_code or DEFAULT_INDEX_CODE.get(fund.code)


def fetch_index_yield(index_code: str, retries: int = 3) -> dict | None:
    """中证官网指数估值（市盈率1/2、股息率1/2）。

    注意：akshare 该接口存在间歇性断连（RemoteDisconnected，实测约 20%），
    故失败后自动重试（默认 3 次，间隔 1s/2s）；全部失败返回 None。
    """
    key = f"csindex:{index_code}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    import akshare as ak
    for i in range(retries):
        try:
            df = ak.stock_zh_index_value_csindex(symbol=index_code)
            if df is None or len(df) == 0:
                if i < retries - 1:
                    time.sleep(1 + i)
                    continue
                return None
            row = df.iloc[-1]
            out = {
                "date": str(row.get("日期", "")),
                "name": str(row.get("指数中文简称", "") or ""),
                "pe1": _f(row.get("市盈率1")),
                "pe2": _f(row.get("市盈率2")),
                # 中证官网股息率字段为百分数（如 5.81 即 5.81%），统一转为小数
                "dy1": _pct(row.get("股息率1")),     # 静态股息率（上年度分红）
                "dy2": _pct(row.get("股息率2")),     # 滚动股息率（近12个月，TTM）
            }
            if out["dy1"] is None and out["dy2"] is None:
                return None
            _cache_set(key, out, "csindex")
            return out
        except Exception:
            if i < retries - 1:
                time.sleep(1 + i)      # 1s、2s 后重试，规避官网间歇性断连
    return None


def _f(v) -> float | None:
    try:
        x = float(v)
        return x if x == x else None   # NaN → None
    except (TypeError, ValueError):
        return None


def _pct(v) -> float | None:
    """百分数字段（如 5.81 = 5.81%）转为小数 0.0581"""
    x = _f(v)
    return x / 100.0 if x is not None else None


def _latest_price_tencent(code: str, market: str) -> float | None:
    """腾讯实时行情取最新价（字段[3]），失败返回 None"""
    pref = "sh" if market == "SH" else "sz"
    try:
        r = requests.get(f"https://qt.gtimg.cn/q={pref}{code}",
                         headers={"User-Agent": UA["User-Agent"]}, timeout=8)
        r.encoding = "gbk"
        body = r.text
        parts = body.split("~")
        if len(parts) > 4 and parts[3]:
            return float(parts[3])
    except Exception:
        return None
    return None


def dynamic_ttm_yield(fund: Fund) -> dict | None:
    """动态 TTM 股息率：在线分红（近12个月每份分红合计）÷ 最新价。失败返回 None。"""
    key = f"dynamic:{fund.code}"
    hit = _cache_get(key)
    if hit is not None:
        return hit
    try:
        from strategy_lab.datasource import get_corporate_actions
        dividends, _ = get_corporate_actions(fund)
        if not dividends:
            return None
        price = _latest_price_tencent(fund.code, fund.market)
        if not price or price <= 0:
            return None
        end = datetime.now()
        cutoff = (end - timedelta(days=365)).strftime("%Y-%m-%d")
        end_s = end.strftime("%Y-%m-%d")
        total = 0.0
        for d in dividends:
            if cutoff <= d["date"] <= end_s:
                total += float(d.get("cash_per_unit") or 0)
        if total <= 0:
            return None
        out = {"date": end_s, "ttm_dy": total / price, "price": price,
               "div_sum": total}
        _cache_set(key, out, "dynamic")
        return out
    except Exception:
        return None


def get_fund_yield(fund: Fund) -> dict:
    """单基金实时股息率：官网估值优先（dy1 静态 / dy2 滚动TTM），动态 TTM 兜底。"""
    row = {
        "code": fund.code, "name": fund.name, "kind": fund.kind,
        "index_code": None, "date": None, "pe1": None, "pe2": None,
        "dy1": None, "dy2": None, "ttm_dy": None, "source": None,
    }
    idx = resolve_index_code(fund)
    if idx:
        row["index_code"] = idx
        info = fetch_index_yield(idx)
        if info:
            row.update({k: info.get(k) for k in ("date", "pe1", "pe2", "dy1", "dy2")})
            row["source"] = "csindex"
        else:
            row["error"] = "中证官网估值获取失败（网络波动），可稍后重试"
    if row["dy2"] is None and row["dy1"] is None:
        dyn = dynamic_ttm_yield(fund)
        if dyn:
            row["ttm_dy"] = dyn.get("ttm_dy")
            row["date"] = dyn.get("date")
            row["source"] = "dynamic"
        elif not row.get("error"):
            row["error"] = "该标的暂无官方估值与分红记录，无法计算股息率"
    return row


def summarize_yields(funds: list | None = None) -> dict:
    """统计汇总所有启用基金的实时股息率。"""
    funds = funds if funds is not None else [f for f in load_funds() if f.enabled]
    rows = [get_fund_yield(f) for f in funds]
    valid = [r for r in rows if r["dy2"] is not None or r["dy1"] is not None or r["ttm_dy"] is not None]
    # 统计主值：滚动股息率 dy2 优先，动态 TTM 兜底
    def main_dy(r):
        return r["dy2"] if r["dy2"] is not None else r["ttm_dy"]
    mds = [main_dy(r) for r in valid if main_dy(r) is not None]
    summary = {
        "total": len(funds),
        "with_yield": len(valid),
        "avg_dy2": (sum(mds) / len(mds)) if mds else None,
        "max": None, "min": None,
        "rf_annual": 0.02,
        "computed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows": rows,
    }
    if mds:
        mx = max(range(len(mds)), key=lambda i: mds[i])
        mn = min(range(len(mds)), key=lambda i: mds[i])
        summary["max"] = {"code": valid[mx]["code"], "name": valid[mx]["name"], "dy": mds[mx]}
        summary["min"] = {"code": valid[mn]["code"], "name": valid[mn]["name"], "dy": mds[mn]}
    return summary
