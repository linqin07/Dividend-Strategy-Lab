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


# ---------- 面板指标（与 web/rotation.html 前端状态机同口径，供邮件/后端复用）----------
# 四档红利仓位：100% 满仓（默认/止盈/黄金补仓区）→ 70% 趋势转多 → 50% 强趋势
W_MOM = 60          # 动量 / 收益差窗口（约 3 个月）
W_MA = 60           # 牛熊分界均线
W_MAF = 20          # 快均线
W_PCT = 750         # 分位数滚动窗口（约 3 年）
MIN_PCT = 250       # 分位最少样本
ENTRY_MOM = 0.05    # 减仓入场动量门槛
STRONG_IN = 0.10    # 强趋势进入（→50%）
STRONG_OUT = 0.05   # 强趋势退出（←70%）
CONFIRM_DAYS = 3    # 入场连续确认天数
COOLDOWN_DAYS = 10  # 回补后冷却天数
PCT_HI, PCT_LO, PCT_MID = 0.90, 0.10, 0.50


def _sma(a, i, w):
    if i < w - 1:
        return None
    return sum(a[i - w + 1:i + 1]) / w


def _ret(a, i, w):
    return None if i < w else a[i] / a[i - w] - 1


def _pct_rank(win, x):
    vals = [v for v in win if v is not None]
    if not vals:
        return None
    return sum(1 for v in vals if v <= x) / len(vals)


def compute_panel(data: dict) -> dict:
    """由 {dates,growth,dividend} 计算跷跷板面板指标与建议红利仓位序列。

    与前端 rotation.html 完全同口径（参数见上方常量），返回：
    {"dates", "diff", "pct", "w", "switches", "cur": {...}}
    """
    dates, g, d = data["dates"], data["growth"], data["dividend"]
    n = len(dates)
    diff = [None] * n
    pct = [None] * n
    bull = [False] * n
    mom_g = [None] * n
    mom_d = [None] * n
    ma60 = [None] * n
    ma20 = [None] * n

    for i in range(n):
        rg, rd = _ret(g, i, W_MOM), _ret(d, i, W_MOM)
        mom_g[i], mom_d[i] = rg, rd
        if rg is not None and rd is not None:
            diff[i] = rg - rd
            lo = max(0, i - W_PCT + 1)
            if (i - lo + 1) >= MIN_PCT or len([x for x in diff[lo:i + 1] if x is not None]) >= MIN_PCT:
                pct[i] = _pct_rank(diff[lo:i + 1], diff[i])
        ma60[i] = _sma(g, i, W_MA)
        ma20[i] = _sma(g, i, W_MAF)
        bull[i] = bool(ma60[i] and ma20[i] and g[i] > ma60[i] and ma20[i] > ma60[i])

    # 四档状态机（滞回 + 确认 + 冷却 + 止盈锁定）
    w = [1.0] * n
    switches = []
    tp = strong = False
    wcur, confirm, cooldown, bear = 1.0, 0, 0, 0
    for i in range(n):
        p = pct[i]
        if p is not None and p >= PCT_HI:
            tp = True
        elif p is not None and p <= PCT_MID:
            tp = False
        if not bull[i]:
            strong = False
        elif mom_g[i] is not None and mom_g[i] >= STRONG_IN:
            strong = True
        elif mom_g[i] is not None and mom_g[i] < STRONG_OUT:
            strong = False
        entry = bull[i] and mom_g[i] is not None and mom_g[i] >= ENTRY_MOM
        confirm = confirm + 1 if entry else 0
        bear = bear + 1 if not bull[i] else 0
        if cooldown > 0:
            cooldown -= 1
        prev = wcur
        reason = ""
        if tp:
            wcur = 1.0
            if prev < 1:
                reason = f"收益差分位 {p*100:.0f}% ≥ 90%，分化极致 → 止盈回补红利至满仓"
        elif wcur == 1.0:
            if confirm >= CONFIRM_DAYS and cooldown == 0:
                wcur = 0.7
                reason = (f"趋势转多确认：收盘>MA60 + MA20>MA60 + 60日动量 {mom_g[i]*100:.1f}% ≥5%，"
                          f"连续{CONFIRM_DAYS}日 → 红利减至70%")
        else:
            if bear >= 2:
                wcur = 1.0
                cooldown = COOLDOWN_DAYS
                reason = f"创业板连续2日失守多头结构 → 回补红利至满仓（冷却{COOLDOWN_DAYS}日）"
            elif strong and wcur != 0.5:
                wcur = 0.5
                reason = f"强趋势：60日动量 {mom_g[i]*100:.1f}% ≥10% → 红利减至50%"
            elif not strong and wcur == 0.5:
                wcur = 0.7
                reason = "60日动量回落至 5% 以下 → 红利回升至70%"
        if wcur != prev and reason:
            switches.append({"date": dates[i], "from": prev, "to": wcur, "pct": p, "reason": reason})
        w[i] = wcur

    i = n - 1
    cur = {
        "date": dates[i],
        "growth": g[i], "dividend": d[i], "ratio": g[i] / d[i],
        "diff": diff[i], "pct": pct[i], "bull": bull[i],
        "ma60": ma60[i], "ma20": ma20[i],
        "mom_g": mom_g[i], "mom_d": mom_d[i],
        "w": w[i],
        "last_switch": switches[-1] if switches else None,
        "switches": switches,
    }
    return {"dates": dates, "diff": diff, "pct": pct, "w": w,
            "ma60": ma60, "ma20": ma20, "mom_g": mom_g, "cur": cur}
