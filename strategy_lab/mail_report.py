# -*- coding: utf-8 -*-
"""邮件报告：图表生成 + HTML 正文组装

供 run.py signal --notify 使用，产出三类内容：
  1. 每只标的的周线 RSI(14) 曲线图（PNG，内嵌 cid）
  2. 创业板/红利跷跷板面板（收益差分位 + 建议红利仓位两张图）
  3. 美化后的 HTML 邮件正文（表格布局 + 内联样式，兼容常见邮件客户端）

图内文字统一用英文：CI（ubuntu）通常没有中文字体，避免乱码方块；
中文说明全部放在 HTML 正文中。
"""
from __future__ import annotations

import io
from datetime import datetime

# 图表配色（A股惯例：涨红跌绿）
RED = "#d93838"
GREEN = "#0c9668"
YELLOW = "#c27803"
BLUE = "#2f6fed"
GRAY = "#93a1b3"

# 线上页面入口（邮件快捷按钮）
SITE_DESKTOP = "https://linqin07.github.io/Dividend-Strategy-Lab/rotation.html"
SITE_MOBILE = "https://linqin07.github.io/Dividend-Strategy-Lab/m.html"


def _mpl():
    """按需导入 matplotlib（未安装则返回 None，邮件自动降级为无图）"""
    try:
        import matplotlib
        matplotlib.use("Agg")           # 无 GUI 环境必须切 Agg
        import matplotlib.pyplot as plt
        return plt
    except Exception:
        return None


def _png(fig) -> bytes | None:
    import matplotlib.pyplot as plt
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------- 周线 RSI(14)
def weekly_rsi_series(fund, weeks: int = 120) -> dict | None:
    """计算基金周线 RSI(14) 序列（用于画图）。失败返回 None。"""
    try:
        from strategy_lab.datasource import get_daily
        from strategy_lab.indicators import rsi_wilder, split_adjusted, to_weekly
        from strategy_lab.signal import _two_years_ago

        daily, _meta = get_daily(fund, start=_two_years_ago())
        if daily is None or not len(daily):
            return None
        weekly = to_weekly(split_adjusted(daily, fund.splits or []))
        rsi = rsi_wilder(weekly["close"], 14)
        ds = [x.strftime("%Y-%m-%d") for x in weekly["date"]]
        rs = [None if rsi.isna().iloc[i] else round(float(rsi.iloc[i]), 2)
              for i in range(len(ds))]
        return {"dates": ds[-weeks:], "rsi": rs[-weeks:],
                "buy": fund.rsi_buy, "sell": fund.rsi_sell}
    except Exception:
        return None


def render_rsi_chart(fund) -> bytes | None:
    """周线 RSI(14) 曲线图 PNG（含买卖阈值线与触发点）"""
    plt = _mpl()
    if plt is None:
        return None
    s = weekly_rsi_series(fund)
    if not s or not s["rsi"]:
        return None

    fig, ax = plt.subplots(figsize=(6.6, 2.5))
    xs = list(range(len(s["dates"])))
    ys = [v for v in s["rsi"]]
    ax.plot(xs, ys, color=BLUE, linewidth=1.6, label="RSI(14)")
    ax.axhline(s["buy"], color=GREEN, linestyle="--", linewidth=1.0,
               label=f"Buy {s['buy']:.0f}")
    ax.axhline(s["sell"], color=RED, linestyle="--", linewidth=1.0,
               label=f"Sell {s['sell']:.0f}")
    ax.fill_between(xs, 0, s["buy"], color=GREEN, alpha=0.07)
    ax.fill_between(xs, s["sell"], 100, color=RED, alpha=0.07)
    ax.set_ylim(0, 100)
    ax.set_ylabel("RSI(14)")
    ax.grid(True, color="#eef2f7", linewidth=0.8)
    ax.set_title(f"{fund.code} Weekly RSI(14)", fontsize=11, color="#1f2733")

    # 标出穿越阈值的点
    valid = [(i, v) for i, v in enumerate(ys) if v is not None]
    for i in range(1, len(valid)):
        pi, pv = valid[i - 1]
        ci, cv = valid[i]
        if pv >= s["buy"] > cv:      # 跌破买入线
            ax.scatter([ci], [cv], marker="^", s=42, color=GREEN, zorder=5)
        if pv <= s["sell"] < cv:     # 升破卖出线
            ax.scatter([ci], [cv], marker="v", s=42, color=RED, zorder=5)

    last = valid[-1][1] if valid else None
    if last is not None:
        ax.annotate(f"{last:.1f}", xy=(valid[-1][0], last),
                    xytext=(6, 0), textcoords="offset points",
                    fontsize=9, fontweight="bold", color="#1f2733")

    step = max(1, len(xs) // 6)
    ax.set_xticks(xs[::step])
    ax.set_xticklabels([s["dates"][i][2:] for i in xs[::step]], fontsize=8, color=GRAY)
    ax.legend(loc="upper left", fontsize=8, frameon=False, ncol=3)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    return _png(fig)


# ---------------------------------------------------------------- 跷跷板面板
def render_rotation_diff_chart(data: dict, panel: dict) -> bytes | None:
    """60日收益差 + 滚动分位（双轴，含 90%/10% 参考线）"""
    plt = _mpl()
    if plt is None:
        return None
    dates, diff, pct = panel["dates"], panel["diff"], panel["pct"]
    xs = list(range(len(dates)))
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.plot(xs, [None if v is None else v * 100 for v in diff],
            color=BLUE, linewidth=1.4, label="60D return gap (GEM - Dividend)")
    ax.axhline(0, color="#c6d2e2", linewidth=0.8)
    ax.set_ylabel("Return gap (%)", color=BLUE, fontsize=9)
    ax.grid(True, color="#eef2f7", linewidth=0.8)
    ax.set_title("ChiNext vs Dividend · 60D return gap & 3Y percentile",
                 fontsize=11, color="#1f2733")

    ax2 = ax.twinx()
    ax2.plot(xs, [None if v is None else v * 100 for v in pct],
             color=YELLOW, linewidth=1.2, linestyle="--", label="Percentile (3Y)")
    ax2.axhline(90, color=RED, linewidth=0.9, linestyle=":")
    ax2.axhline(10, color=GREEN, linewidth=0.9, linestyle=":")
    ax2.set_ylim(0, 100)
    ax2.set_ylabel("Percentile (%)", color=YELLOW, fontsize=9)

    step = max(1, len(xs) // 6)
    ax.set_xticks(xs[::step])
    ax.set_xticklabels([dates[i][2:] for i in xs[::step]], fontsize=8, color=GRAY)
    h1, l1 = ax.get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    ax.legend(h1 + h2, l1 + l2, loc="upper left", fontsize=8, frameon=False, ncol=2)
    return _png(fig)


def render_rotation_pos_chart(panel: dict) -> bytes | None:
    """建议红利仓位阶梯图"""
    plt = _mpl()
    if plt is None:
        return None
    dates, w = panel["dates"], panel["w"]
    xs = list(range(len(dates)))
    fig, ax = plt.subplots(figsize=(7.2, 1.9))
    ax.step(xs, [v * 100 for v in w], where="post", color=BLUE, linewidth=1.6)
    ax.fill_between(xs, [v * 100 for v in w], 100, step="post",
                    color=GREEN, alpha=0.10, label="Switched to ChiNext")
    ax.fill_between(xs, 0, [v * 100 for v in w], step="post",
                    color=GREEN, alpha=0.22, label="Dividend position")
    ax.set_ylim(0, 105)
    ax.set_ylabel("Dividend %", fontsize=9)
    ax.grid(True, color="#eef2f7", linewidth=0.8)
    ax.set_title("Suggested dividend position (100% / 70% / 50%)",
                 fontsize=10, color="#1f2733")
    step = max(1, len(xs) // 6)
    ax.set_xticks(xs[::step])
    ax.set_xticklabels([dates[i][2:] for i in xs[::step]], fontsize=8, color=GRAY)
    ax.legend(loc="lower left", fontsize=8, frameon=False, ncol=2)
    return _png(fig)


# ---------------------------------------------------------------- HTML 正文
def _fmt_pct(x, d=2) -> str:
    return "--" if x is None else f"{x * 100:.{d}f}%"


def _pos_style(w: float) -> tuple:
    """返回 (颜色, 徽章文案, 一句话建议)"""
    if w >= 1:
        return GREEN, "满仓红利", "创业板未形成多头结构，红利满仓持有吃股息"
    if w >= 0.7:
        return YELLOW, "减仓至 70%", "创业板趋势转多，减 30% 仓位参与成长弹性"
    return RED, "减仓至 50%", "创业板强趋势主升，红利降至半仓"


def _rotation_block(panel: dict, images: dict) -> str:
    cur = panel["cur"]
    w = cur["w"]
    color, badge, advice = _pos_style(w)
    last = cur.get("last_switch")
    last_txt = (f"{last['date']}：{last['reason']}" if last
                else "回测起点以来未发生仓位变化")
    golden = cur["pct"] is not None and cur["pct"] <= 0.10
    tpzone = cur["pct"] is not None and cur["pct"] >= 0.90

    tip = ""
    if golden:
        tip = ('<div style="margin-top:8px;padding:8px 10px;background:#eafaf2;'
               'border-left:3px solid #0c9668;color:#0c9668;font-size:12px;">'
               '黄金补仓区：创业板深度熊市、红利极端跑赢，可用新增资金（工资/分红）加码红利。</div>')
    elif tpzone:
        tip = ('<div style="margin-top:8px;padding:8px 10px;background:#fdecec;'
               'border-left:3px solid #d93838;color:#c62828;font-size:12px;">'
               '分化极致区：成长/红利分化已到历史极端，若有减仓应先落袋回补红利。</div>')

    def cell(k, v, c="#1f2733", s=""):
        return (f'<td style="padding:8px 6px;text-align:center;border:1px solid #e3e8ef;">'
                f'<div style="font-size:11px;color:#5c6b7f;">{k}</div>'
                f'<div style="font-size:15px;font-weight:700;color:{c};'
                f'font-family:Consolas,monospace;">{v}</div>'
                f'<div style="font-size:10px;color:#93a1b3;">{s}</div></td>')

    above = ("+" + f"{(cur['growth'] / cur['ma60'] - 1) * 100:.1f}%"
             if cur["ma60"] and cur["growth"] > cur["ma60"]
             else (f"{(cur['growth'] / cur['ma60'] - 1) * 100:.1f}%" if cur["ma60"] else "--"))
    metrics = (
        cell("建议红利仓位", f"{w * 100:.0f}%", color, badge)
        + cell("60日收益差", _fmt_pct(cur["diff"], 1),
               RED if (cur["diff"] or 0) >= 0 else GREEN, "创业板−红利")
        + cell("收益差分位", "--" if cur["pct"] is None else f"{cur['pct'] * 100:.0f}%",
               BLUE, "近3年滚动")
        + cell("创业板 vs MA60", above,
               RED if (cur["ma60"] and cur["growth"] > cur["ma60"]) else GREEN,
               "多头" if cur["bull"] else "空头")
        + cell("创业板60日动量", _fmt_pct(cur["mom_g"], 1),
               RED if (cur["mom_g"] or 0) >= 0 else GREEN, "≥10% 强趋势")
        + cell("创业板/红利比值", f"{cur['ratio']:.3f}", "#1f2733", "区间约0.3~0.7")
    )

    imgs = ""
    for cid, title in (("rot_diff", "60日收益差 & 分位数"), ("rot_pos", "建议红利仓位走势")):
        if cid in images:
            imgs += (f'<div style="margin-top:12px;">'
                     f'<div style="font-size:11px;color:#93a1b3;margin-bottom:4px;">{title}</div>'
                     f'<img src="cid:{cid}" style="width:100%;max-width:680px;'
                     f'border:1px solid #e3e8ef;border-radius:8px;display:block;"></div>')

    return f"""
    <tr><td style="padding:0 0 14px;">
      <div style="border:1px solid #e3e8ef;border-radius:10px;overflow:hidden;">
        <div style="background:#2f6fed;color:#fff;padding:10px 14px;font-size:14px;font-weight:700;">
          创业板-红利跷跷板 · 红利补仓/减仓参考
          <span style="float:right;font-weight:400;font-size:11px;">{cur['date']} 收盘</span>
        </div>
        <div style="padding:12px 14px;background:#fff;">
          <div style="font-size:34px;font-weight:800;color:{color};
                      font-family:Consolas,monospace;line-height:1.1;">{w * 100:.0f}%</div>
          <div style="font-size:12px;color:#5c6b7f;margin-top:2px;">建议红利仓位 · {badge}</div>
          <div style="font-size:13px;color:#1f2733;margin-top:8px;">{advice}</div>
          {tip}
          <table style="width:100%;border-collapse:collapse;margin-top:12px;background:#f7f9fc;">
            <tr>{metrics}</tr>
          </table>
          <div style="font-size:11px;color:#93a1b3;margin-top:10px;">
            最近一次仓位变化：{last_txt}
          </div>
          {imgs}
        </div>
      </div>
    </td></tr>"""


def _signal_card(r: dict, images: dict) -> str:
    code = r.get("code", "")
    if r.get("error"):
        right = f'<span style="color:#999;">{r["error"]}</span>'
        rsi_txt, state, note = "--", "-", ""
    else:
        state = r.get("state", "-")
        rsi_txt = "--" if r.get("rsi") is None else f"{r['rsi']:.1f}"
        note = r.get("note", "")
        if r["action"] == "买入":
            color, badge = RED, "买入"
        elif r["action"] == "卖出":
            color, badge = GREEN, "卖出"
        else:
            color, badge = "#555555", "观望"
        amt = r.get("suggested_amount")
        amt_html = (f"建议金额 <b style=\"color:#1f2733;\">¥{amt:,.0f}</b>" if amt is not None
                    else "本周期无操作")
        if amt is not None and r.get("over_position"):
            amt_html += ' <span style="color:#d93838;font-size:11px;">⚠超仓</span>'
        if r.get("multiplier", 1.0) > 1.0:
            amt_html += f' <span style="color:#93a1b3;font-size:11px;">×{r["multiplier"]:.2f}</span>'
        right = (f'<span style="display:inline-block;padding:2px 10px;border-radius:999px;'
                 f'background:{color};color:#fff;font-size:12px;font-weight:700;">{badge}</span>'
                 f'<div style="font-size:12px;color:#5c6b7f;margin-top:4px;">{amt_html}</div>')

    img = ""
    cid = f"rsi_{code}"
    if cid in images:
        img = (f'<div style="margin-top:10px;"><img src="cid:{cid}" '
               f'style="width:100%;max-width:640px;border:1px solid #e3e8ef;'
               f'border-radius:8px;display:block;"></div>')

    return f"""
    <tr><td style="padding:0 0 12px;">
      <div style="border:1px solid #e3e8ef;border-radius:10px;background:#fff;">
        <table style="width:100%;border-collapse:collapse;">
          <tr>
            <td style="padding:12px 14px;width:130px;vertical-align:middle;">
              <div style="font-size:14px;font-weight:700;color:#1f2733;">{r.get('name','')}</div>
              <div style="font-size:11px;color:#93a1b3;">{code} · {state}</div>
            </td>
            <td style="padding:12px 6px;width:80px;text-align:center;vertical-align:middle;">
              <div style="font-size:11px;color:#5c6b7f;">周RSI14</div>
              <div style="font-size:26px;font-weight:800;color:#2f6fed;
                          font-family:Consolas,monospace;line-height:1.1;">{rsi_txt}</div>
            </td>
            <td style="padding:12px 14px;text-align:right;vertical-align:middle;">{right}</td>
          </tr>
        </table>
        <div style="padding:0 14px 12px;font-size:12px;color:#5c6b7f;">{note}</div>
        {img}
      </div>
    </td></tr>"""


def build_email(signal_rows: list, rotation: dict | None = None,
                images: dict | None = None) -> tuple:
    """组装邮件（主题 + HTML 正文）。

    rotation: compute_panel() 的结果（可为 None，则不展示跷跷板区块）
    images:   {cid: png bytes}，内嵌到正文对应位置
    """
    images = images or {}
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    acted = [r for r in signal_rows if r.get("action") in ("买入", "卖出")]
    subject = "【策略信号】" + ("；".join(
        f"{r['name']} {r['action']}（周RSI {r['rsi']}）" for r in acted) or "今日无买卖信号")

    cards = "".join(_signal_card(r, images) for r in signal_rows)
    rot_block = _rotation_block(rotation, images) if rotation else ""

    body = f"""
<div style="background:#f5f7fa;padding:16px 0;font-family:'Microsoft YaHei',
            'PingFang SC','Segoe UI',sans-serif;">
  <table role="presentation" style="width:100%;max-width:720px;margin:0 auto;
         border-collapse:collapse;">
    <tr><td style="padding:0 12px;">
      <div style="background:#1a237e;border-radius:10px 10px 0 0;padding:16px 18px;">
        <div style="color:#fff;font-size:18px;font-weight:700;letter-spacing:.5px;">
          红利策略实验室 · 工作日信号简报</div>
        <div style="color:#b9c4e8;font-size:12px;margin-top:4px;">
          {now} 自动生成 ｜ 规则：周线 RSI(14) 状态机，每个工作日收盘后推送，信号触发则下一交易日开盘执行</div>
      </div>

      <div style="background:#fff;padding:14px 18px;border-left:1px solid #e3e8ef;
                  border-right:1px solid #e3e8ef;">
        <div style="font-size:13px;color:#1f2733;margin-bottom:10px;">
          快速查看线上看板（点击直达）：
          <a href="{SITE_DESKTOP}" style="display:inline-block;margin:2px 6px 0 0;padding:5px 12px;
             background:#2f6fed;color:#fff;border-radius:6px;font-size:12px;
             text-decoration:none;font-weight:600;">电脑版 · 跷跷板面板</a>
          <a href="{SITE_MOBILE}" style="display:inline-block;margin:2px 0 0;padding:5px 12px;
             background:#0c9668;color:#fff;border-radius:6px;font-size:12px;
             text-decoration:none;font-weight:600;">手机版 · 全部标的</a>
        </div>
      </div>

      <table role="presentation" style="width:100%;border-collapse:collapse;
             background:#fff;border-left:1px solid #e3e8ef;border-right:1px solid #e3e8ef;">
        {rot_block}
        <tr><td style="padding:0 0 8px;font-size:13px;font-weight:700;color:#1a237e;">
          标的信号（周线 RSI(14)）</td></tr>
        {cards}
      </table>

      <div style="background:#fafbfd;border:1px solid #e3e8ef;border-radius:0 0 10px 10px;
                  padding:12px 18px;">
        <div style="font-size:11px;color:#93a1b3;line-height:1.7;">
          口径：不复权实际盘面价；RSI 45 买 / 持仓超卖线全卖；重复同向信号忽略。<br>
          建议金额 = 仓位金额 × 浮动仓位比例 × 倍率（倍率按 RSI 信号强弱线性加码）。<br>
          跷跷板面板：60日收益差近3年分位 ≥90% 止盈回补红利、≤10% 黄金补仓区；
          趋势过滤 MA20/MA60 + 60日动量（5% 入场 / 10% 强趋势），3日确认、10日冷却。<br>
          本邮件为历史规则回测研究，不构成投资建议。
        </div>
      </div>
    </td></tr>
  </table>
</div>"""
    return subject, body
