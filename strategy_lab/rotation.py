# -*- coding: utf-8 -*-
"""风格轮动 & 纳指波动监控面板数据构建（创业板 / 中证红利 / 纳指三资产）

三条件信号（口径与看板页一致）：
  条件① 创红比 x = 创业板指(399006) / 中证红利(000922)
         x > 0.60 → 观察中证红利（成长高估区）；
         0.35 ≤ x ≤ 0.60 → 中性；
         x < 0.35 → 观察创业板（成长极度低估区）。
  条件② VXN（Cboe 纳斯达克100波动率）> 30 → 触发「大笔买入纳斯达克」。
  条件③ 纳指100 ETF 溢价率（513100 / 513300）：>5% 高溢价观察、>10% 严重溢价，
         暂缓买入纳指 ETF，等溢价回落再执行。

组合配置（非全仓红利）：三资产基础配置由条件①区间决定，条件②触发时纳指加仓：
  观察中证红利区  红利60% / 创业板20% / 纳指20%（VXN>30 → 50/10/40）
  中性区          红利40% / 创业板40% / 纳指20%（VXN>30 → 30/30/40）
  观察创业板区    红利20% / 创业板60% / 纳指20%（VXN>30 → 10/50/40）

数据来源：
  创业板指 / 中证红利 / 513100 / 513300 → 复用 datasource 多源链 + 缓存；
  VXN → Cboe 官方历史 JSON（cdn.cboe.com），本地缓存 data/vxn.json；
  513100 / 513300 单位净值 → 东财 f10 lsjz 接口翻页抓取，本地缓存 data/nav_<code>.json。

落盘 output/rotation.json，供：
  - GET /api/rotation/data（FastAPI 实时接口）
  - python run.py rotation（CI 周刷新，静态托管页面直接读 output/rotation.json）
"""
from __future__ import annotations

import json
import os
from datetime import datetime

import requests

from strategy_lab.config import DATA_DIR, Fund, OUTPUT_DIR, atomic_write_json, ensure_dirs

GROWTH_FUND = Fund(code="399006", name="创业板指", kind="index", market="SZ")
DIVIDEND_FUND = Fund(code="000922", name="中证红利", kind="index", market="SH")
NDX_ETFS = [
    Fund(code="513100", name="纳指100ETF(国泰)", kind="etf", market="SH"),
    Fund(code="513300", name="纳指100ETF(华夏)", kind="etf", market="SH"),
]

ROTATION_JSON = os.path.join(OUTPUT_DIR, "rotation.json")
YEARS = 5   # 面板展示窗口（近五年）

# ---------------- 策略参数（硬编码，与 web/rotation.html 前端同口径） ----------------
X_HI, X_LO = 0.60, 0.35          # 条件① 创红比区间边界
VXN_TRIGGER = 30.0               # 条件② VXN 触发线（>30 大笔买入纳斯达克）
PREMIUM_WARN, PREMIUM_HIGH = 0.05, 0.10   # 条件③ 溢价率预警/严重线
ZONE_ALLOC = {                   # 基础配置：红利 / 创业板 / 纳指
    "dividend": {"div": 0.60, "gem": 0.20, "ndx": 0.20},   # x > 0.60
    "neutral":  {"div": 0.40, "gem": 0.40, "ndx": 0.20},   # 0.35 ≤ x ≤ 0.60
    "growth":   {"div": 0.20, "gem": 0.60, "ndx": 0.20},   # x < 0.35
}
VXN_SHIFT = {"div": -0.10, "gem": -0.10, "ndx": 0.20}      # VXN>30 时纳指加仓 20%
COST = 0.001                     # 调仓成本（单边换手 0.1%）

ZONE_NAME = {"dividend": "观察中证红利", "neutral": "中性", "growth": "观察创业板"}

_VXN_URL = "https://cdn.cboe.com/api/global/delayed_quotes/charts/historical/_VXN.json"
_VXN_CACHE = os.path.join(DATA_DIR, "vxn.json")
_NAV_CACHE_TPL = os.path.join(DATA_DIR, "nav_{code}.json")
_LSJZ_URL = "https://api.fund.eastmoney.com/f10/lsjz"


# ---------------------------------------------------------------- VXN 数据
def _load_json_cache(path: str) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def fetch_vxn(force: bool = False) -> tuple[dict, bool]:
    """抓取 VXN 历史 {date: close}；失败时读缓存兜底。返回 (dict, stale)。"""
    cached = _load_json_cache(_VXN_CACHE) or {}
    if not force and cached:
        return cached, False
    try:
        r = requests.get(_VXN_URL, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        rows = r.json().get("data") or []
        out = {x["date"]: round(float(x["close"]), 2) for x in rows if x.get("date") and x.get("close")}
        if len(out) < 250:
            raise RuntimeError(f"VXN 数据点过少: {len(out)}")
        ensure_dirs()
        atomic_write_json(_VXN_CACHE, out)
        return out, False
    except Exception:
        if cached:
            return cached, True
        raise RuntimeError("VXN 抓取失败且无本地缓存（data/vxn.json）")


# ---------------------------------------------------------------- 基金净值数据
def fetch_nav_history(code: str, min_date: str, force: bool = False) -> tuple[dict, bool]:
    """东财 f10 lsjz 翻页抓取基金单位净值历史 {date: nav}（截至 min_date 即停止翻页）。

    QDII 净值为 T+1 公布，页面口径：溢价率(t) = 场内价(t) / 净值(早于 t 的最近一期) - 1。
    """
    cache_path = _NAV_CACHE_TPL.format(code=code)
    cached = _load_json_cache(cache_path) or {}
    if not force and cached:
        newest = max(cached)
        if newest >= min_date:
            return cached, False
    headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://fundf10.eastmoney.com/"}
    out: dict = dict(cached)
    page, stale = 1, False
    try:
        while page <= 40:
            r = requests.get(_LSJZ_URL, params={"fundCode": code, "pageIndex": page,
                                                "pageSize": 100}, headers=headers, timeout=20)
            r.raise_for_status()
            rows = ((r.json().get("Data") or {}).get("LSJZList")) or []
            if not rows:
                break
            for x in rows:
                if x.get("FSRQ") and x.get("DWJZ"):
                    try:
                        out[x["FSRQ"]] = float(x["DWJZ"])
                    except (TypeError, ValueError):
                        continue
            oldest = min(x["FSRQ"] for x in rows if x.get("FSRQ"))
            if oldest <= min_date or page * 100 >= 3000:
                break
            page += 1
    except Exception:
        stale = True
    if len(out) < 250:
        if cached:
            return cached, True
        raise RuntimeError(f"{code} 净值抓取失败且无本地缓存")
    ensure_dirs()
    atomic_write_json(cache_path, out)
    return out, stale


# ---------------------------------------------------------------- 面板数据构建
def build_rotation_data(force: bool = False) -> dict:
    """拉取并对齐三资产 + VXN + 溢价率，返回面板数据 dict（不落盘）。"""
    from strategy_lab.datasource import get_daily

    g_df, g_meta = get_daily(GROWTH_FUND, force=force)
    d_df, d_meta = get_daily(DIVIDEND_FUND, force=force)
    if g_df is None or not len(g_df):
        raise RuntimeError(f"创业板指行情获取失败: {g_meta.get('errors')}")
    if d_df is None or not len(d_df):
        raise RuntimeError(f"中证红利行情获取失败: {d_meta.get('errors')}")

    g = {dt.strftime("%Y-%m-%d"): float(c) for dt, c in zip(g_df["date"], g_df["close"])}
    d = {dt.strftime("%Y-%m-%d"): float(c) for dt, c in zip(d_df["date"], d_df["close"])}
    dates = sorted(set(g) & set(d))

    cutoff = (datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
              .toordinal() - int(365.25 * YEARS))
    cutoff_s = datetime.fromordinal(cutoff).strftime("%Y-%m-%d")
    dates = [x for x in dates if x >= cutoff_s]
    if len(dates) < 250:
        raise RuntimeError(f"对齐后有效交易日不足（{len(dates)}），无法构建面板")

    stale = bool(g_meta.get("stale") or d_meta.get("stale"))
    providers = {"growth": g_meta.get("provider"), "dividend": d_meta.get("provider")}

    # 条件② VXN：对齐规则 = A股日期 t 取最近的 VXN 交易日（≤ t）收盘
    vxn_raw, vxn_stale = fetch_vxn(force=force)
    stale = stale or vxn_stale
    vxn_dates = sorted(vxn_raw)
    vxn: list = []
    import bisect
    for t in dates:
        i = bisect.bisect_right(vxn_dates, t) - 1
        vxn.append(vxn_raw[vxn_dates[i]] if i >= 0 else None)
    vxn_asof = vxn_dates[-1] if vxn_dates else None

    # 条件③ 纳指 ETF 溢价率：场内价(t) / 最近一期早于 t 的单位净值 - 1
    premium: dict[str, list] = {}
    nav_latest: dict[str, dict] = {}
    ndx_prices: list = []
    for fi, f in enumerate(NDX_ETFS):
        p_df, p_meta = get_daily(f, force=force)
        if p_df is None or not len(p_df):
            premium[f.code] = [None] * len(dates)
            if fi == 0:
                ndx_prices = [None] * len(dates)
            stale = True
            continue
        providers[f"etf_{f.code}"] = p_meta.get("provider")
        stale = stale or bool(p_meta.get("stale"))
        price = {dt.strftime("%Y-%m-%d"): float(c) for dt, c in zip(p_df["date"], p_df["close"])}
        if fi == 0:
            ndx_prices = [price.get(t) for t in dates]   # 回测用纳指资产 = 513100 场内价
        nav, nav_stale = fetch_nav_history(f.code, dates[0], force=force)
        stale = stale or nav_stale
        nav_dates = sorted(nav)
        nav_latest[f.code] = {"date": nav_dates[-1], "nav": nav[nav_dates[-1]]} if nav_dates else None
        ser: list = []
        for t in dates:
            p = price.get(t)
            j = bisect.bisect_left(nav_dates, t) - 1   # 严格早于 t 的最近净值
            ser.append(round(p / nav[nav_dates[j]] - 1, 4) if (p and j >= 0) else None)
        premium[f.code] = ser

    return {
        "asof": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "growth_code": GROWTH_FUND.code, "growth_name": GROWTH_FUND.name,
        "dividend_code": DIVIDEND_FUND.code, "dividend_name": DIVIDEND_FUND.name,
        "providers": providers,
        "stale": stale,
        "vxn_asof": vxn_asof,
        "nav_latest": nav_latest,
        "dates": dates,
        "growth": [round(g[x], 2) for x in dates],
        "dividend": [round(d[x], 2) for x in dates],
        "vxn": vxn,
        "premium": premium,
        "ndx_prices": ndx_prices,
    }


def write_rotation_json(force: bool = False) -> dict:
    """构建并落盘 output/rotation.json，返回数据 dict。"""
    ensure_dirs()
    data = build_rotation_data(force=force)
    atomic_write_json(ROTATION_JSON, data)
    return data


# ---------------------------------------------------------------- 面板指标（与前端同口径）
def _zone_of(x: float | None) -> str | None:
    if x is None:
        return None
    if x > X_HI:
        return "dividend"
    if x < X_LO:
        return "growth"
    return "neutral"


def alloc_of(zone: str | None, vxn_hit: bool) -> dict:
    base = dict(ZONE_ALLOC[zone or "neutral"])
    if vxn_hit:
        for k, dv in VXN_SHIFT.items():
            base[k] = round(base[k] + dv, 4)
    return base


def compute_panel(data: dict) -> dict:
    """由 {dates,growth,dividend,vxn,premium} 计算新策略面板指标与组合配置序列。

    与前端 rotation.html 完全同口径（参数见上方常量），返回：
    {"dates","ratio","zone","vxn","w","switches","cur","backtest"}
    """
    dates = data["dates"]
    g, d = data["growth"], data["dividend"]
    vxn = data.get("vxn") or [None] * len(dates)
    prem = data.get("premium") or {}
    n = len(dates)

    ratio = [None if (gg is None or dd is None or dd == 0) else round(gg / dd, 4)
             for gg, dd in zip(g, d)]
    zone = [_zone_of(x) for x in ratio]
    vxn_hit = [v is not None and v > VXN_TRIGGER for v in vxn]

    # 三资产权重序列
    w = {"div": [0.0] * n, "gem": [0.0] * n, "ndx": [0.0] * n}
    for i in range(n):
        a = alloc_of(zone[i], vxn_hit[i])
        w["div"][i], w["gem"][i], w["ndx"][i] = a["div"], a["gem"], a["ndx"]

    # 信号切换明细（条件①区间切换 / 条件②触发状态切换）
    zone_reason = {
        "dividend": "上穿 0.60 上边界 → 观察中证红利（成长高估区）",
        "growth": "下破 0.35 下边界 → 观察创业板（成长极度低估区）",
        "neutral": "回落至 0.35~0.60 中性区",
    }
    switches: list[dict] = []
    for i in range(1, n):
        if zone[i] and zone[i] != zone[i - 1]:
            switches.append({
                "date": dates[i], "type": "zone",
                "from": ZONE_NAME[zone[i - 1] or "neutral"], "to": ZONE_NAME[zone[i]],
                "reason": f"创红比 x={ratio[i]:.4f} {zone_reason[zone[i]]}",
            })
        if vxn_hit[i] != vxn_hit[i - 1] and vxn[i] is not None:
            switches.append({
                "date": dates[i], "type": "vxn",
                "from": "未触发" if not vxn_hit[i - 1] else "已触发",
                "to": "已触发" if vxn_hit[i] else "未触发",
                "reason": (f"VXN={vxn[i]:.2f} 上穿 30 → 大笔买入纳斯达克（美股恐慌 = 长线黄金坑）"
                           if vxn_hit[i] else f"VXN={vxn[i]:.2f} 回落至 30 以下 → 触发解除"),
            })

    # 回测：按权重日频持有一篮子（红利/创业板指数 + 513100 场内价），换手日计成本
    ndx = data.get("ndx_prices") or []
    nav = [1.0] * n
    nav_d = [1.0] * n
    nav_b = [1.0] * n
    for i in range(1, n):
        rg = g[i] / g[i - 1] - 1 if (g[i] and g[i - 1]) else 0.0
        rd = d[i] / d[i - 1] - 1 if (d[i] and d[i - 1]) else 0.0
        rn = (ndx[i] / ndx[i - 1] - 1) if (i < len(ndx) and ndx[i] and ndx[i - 1]) else 0.0
        turnover = (abs(w["div"][i] - w["div"][i - 1]) + abs(w["gem"][i] - w["gem"][i - 1])
                    + abs(w["ndx"][i] - w["ndx"][i - 1]))
        r = w["div"][i] * rd + w["gem"][i] * rg + w["ndx"][i] * rn - COST * turnover / 2
        nav[i] = nav[i - 1] * (1 + r)
        nav_d[i] = nav_d[i - 1] * (1 + rd)
        nav_b[i] = nav_b[i - 1] * (1 + 0.5 * rd + 0.5 * rg)

    def _stats(series: list) -> dict:
        years = (n - 1) / 252
        ann = series[-1] ** (1 / years) - 1 if years > 0 else 0.0
        peak, mdd = -1e18, 0.0
        for v in series:
            peak = max(peak, v)
            mdd = max(mdd, 1 - v / peak)
        return {"ann": ann, "mdd": mdd}

    st, st_d = _stats(nav), _stats(nav_d)
    i = n - 1
    cur_prem = {code: (ser[i] if ser else None) for code, ser in prem.items()}
    cur = {
        "date": dates[i],
        "growth": g[i], "dividend": d[i], "ratio": ratio[i],
        "zone": zone[i], "zone_name": ZONE_NAME[zone[i] or "neutral"],
        "vxn": vxn[i], "vxn_hit": vxn_hit[i], "vxn_asof": data.get("vxn_asof"),
        "premium": cur_prem,
        "alloc": alloc_of(zone[i], vxn_hit[i]),
        "switches": switches,
        "last_switch": switches[-1] if switches else None,
    }
    return {
        "dates": dates, "ratio": ratio, "zone": zone, "vxn": vxn, "w": w,
        "switches": switches, "cur": cur,
        "backtest": {
            "nav": nav, "nav_d": nav_d, "nav_b": nav_b,
            "ann": st["ann"], "mdd": st["mdd"],
            "ann_d": st_d["ann"], "mdd_d": st_d["mdd"],
            "excess": st["ann"] - st_d["ann"],
            "turns": len(switches),
        },
    }
