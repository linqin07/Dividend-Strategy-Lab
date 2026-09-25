# -*- coding: utf-8 -*-
"""邮件报告：图表生成 + HTML 正文组装

供 run.py signal --notify 使用，产出三类内容：
  1. 每只标的的周线 RSI(14) 曲线图（PNG，内嵌 cid）
  2. 风格轮动 & 纳指波动监控面板（创红比区间 + 三资产配置两张图）
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


# ---------------------------------------------------------------- 风格轮动面板
def render_rotation_diff_chart(data: dict, panel: dict) -> bytes | None:
    """创红比 x = 创业板指/中证红利 走势（含 0.60/0.35 区间边界线）"""
    plt = _mpl()
    if plt is None:
        return None
    dates, ratio = panel["dates"], panel["ratio"]
    xs = list(range(len(dates)))
    fig, ax = plt.subplots(figsize=(7.2, 3.0))
    ax.plot(xs, ratio, color=BLUE, linewidth=1.4, label="GEM / Dividend ratio (x)")
    ax.axhline(0.60, color=GREEN, linewidth=0.9, linestyle="--")
    ax.axhline(0.35, color=RED, linewidth=0.9, linestyle="--")
    ax.axhspan(0.35, 0.60, color="#93a1b3", alpha=0.10)
    ax.text(len(xs) - 1, 0.605, "watch dividend", fontsize=8, color=GREEN, ha="right")
    ax.text(len(xs) - 1, 0.355, "watch growth", fontsize=8, color=RED, ha="right")
    ax.set_ylabel("Ratio (x)", color=BLUE, fontsize=9)
    ax.grid(True, color="#eef2f7", linewidth=0.8)
    ax.set_title("ChiNext / Dividend ratio & style zones (0.35 / 0.60)",
                 fontsize=11, color="#1f2733")
    step = max(1, len(xs) // 6)
    ax.set_xticks(xs[::step])
    ax.set_xticklabels([dates[i][2:] for i in xs[::step]], fontsize=8, color=GRAY)
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    return _png(fig)


def render_rotation_pos_chart(panel: dict) -> bytes | None:
    """三资产配置堆叠面积图（红利 / 创业板 / 纳指）"""
    plt = _mpl()
    if plt is None:
        return None
    dates, w = panel["dates"], panel["w"]
    xs = list(range(len(dates)))
    div = [v * 100 for v in w["div"]]
    gem = [v * 100 for v in w["gem"]]
    ndx = [v * 100 for v in w["ndx"]]
    fig, ax = plt.subplots(figsize=(7.2, 2.2))
    ax.stackplot(xs, div, gem, ndx,
                 colors=[GREEN, RED, BLUE], alpha=0.65,
                 labels=["Dividend", "ChiNext", "NDX100"])
    ax.set_ylim(0, 100)
    ax.set_ylabel("Allocation (%)", fontsize=9)
    ax.grid(True, color="#eef2f7", linewidth=0.8, axis="y")
    ax.set_title("Signal-driven allocation (dividend / growth / NASDAQ)",
                 fontsize=10, color="#1f2733")
    step = max(1, len(xs) // 6)
    ax.set_xticks(xs[::step])
    ax.set_xticklabels([dates[i][2:] for i in xs[::step]], fontsize=8, color=GRAY)
    ax.legend(loc="lower left", fontsize=8, frameon=False, ncol=3)
    return _png(fig)


# ---------------------------------------------------------------- HTML 正文
def _fmt_pct(x, d=2) -> str:
    return "--" if x is None else f"{x * 100:.{d}f}%"


def _zone_style(zone: str | None) -> tuple:
    """返回 (颜色, 区间徽章, 一句话建议)"""
    if zone == "dividend":
        return GREEN, "观察中证红利", "创红比站上 0.60，成长拥挤、红利性价比占优，红利底仓 60%"
    if zone == "growth":
        return RED, "观察创业板", "创红比跌破 0.35，成长极度低估，向创业板倾斜至 60%"
    return "#555555", "中性", "0.35~0.60 中性区，均衡配置等待边界信号"


def _rotation_block(panel: dict, images: dict) -> str:
    cur = panel["cur"]
    alloc = cur["alloc"]
    color, badge, advice = _zone_style(cur.get("zone"))
    last = cur.get("last_switch")
    last_txt = (f"{last['date']}：{last['reason']}" if last
                else "近五年无区间边界穿越")

    vxn = cur.get("vxn")
    vxn_hit = cur.get("vxn_hit")
    vxn_color = RED if vxn_hit else "#93a1b3"
    vxn_txt = f"已触发（VXN {vxn:.2f} &gt; 30，纳指加仓至 40%）" if vxn_hit \
        else f"未触发（VXN {vxn:.2f} &lt; 30）"

    prem = cur.get("premium") or {}
    p1, p3 = prem.get("513100"), prem.get("513300")
    worst = max(p1 or 0, p3 or 0)
    prem_color = RED if worst >= 0.10 else (YELLOW if worst >= 0.05 else GREEN)
    prem_txt = (f"513100 {p1 * 100:+.2f}% / 513300 {p3 * 100:+.2f}%"
                if (p1 is not None and p3 is not None) else "--")
    prem_state = ("严重溢价：暂缓买入纳指ETF" if worst >= 0.10
                  else ("高溢价观察：暂缓买入纳指ETF" if worst >= 0.05
                        else "溢价正常，可按配置买入"))

    def cell(k, v, c="#1f2733", s=""):
        return (f'<td style="padding:8px 6px;text-align:center;border:1px solid #e3e8ef;">'
                f'<div style="font-size:11px;color:#5c6b7f;">{k}</div>'
                f'<div style="font-size:15px;font-weight:700;color:{c};'
                f'font-family:Consolas,monospace;">{v}</div>'
                f'<div style="font-size:10px;color:#93a1b3;">{s}</div></td>')

    metrics = (
        cell("创红比 x", f"{cur['ratio']:.4f}" if cur.get("ratio") else "--", BLUE, "创业板指/中证红利")
        + cell("当前区间", badge, color, "0.35 / 0.60 边界")
        + cell("红利仓位", f"{alloc['div'] * 100:.0f}%", GREEN, "底仓")
        + cell("创业板仓位", f"{alloc['gem'] * 100:.0f}%", RED, "成长弹性")
        + cell("纳指仓位", f"{alloc['ndx'] * 100:.0f}%", BLUE, "海外分散")
        + cell("VXN", f"{vxn:.2f}" if vxn is not None else "--", vxn_color, vxn_txt)
        + cell("纳指ETF溢价", prem_txt, prem_color, prem_state)
    )

    imgs = ""
    for cid, title in (("rot_diff", "创红比 x 与风格区间"), ("rot_pos", "三资产配置走势")):
        if cid in images:
            imgs += (f'<div style="margin-top:12px;">'
                     f'<div style="font-size:11px;color:#93a1b3;margin-bottom:4px;">{title}</div>'
                     f'<img src="cid:{cid}" style="width:100%;max-width:680px;'
                     f'border:1px solid #e3e8ef;border-radius:8px;display:block;"></div>')

    return f"""
    <tr><td style="padding:0 0 14px;">
      <div style="border:1px solid #e3e8ef;border-radius:10px;overflow:hidden;">
        <div style="background:#2f6fed;color:#fff;padding:10px 14px;font-size:14px;font-weight:700;">
          风格轮动 &amp; 纳指波动监控
          <span style="float:right;font-weight:400;font-size:11px;">{cur['date']} 收盘</span>
        </div>
        <div style="padding:12px 14px;background:#fff;">
          <div style="font-size:16px;font-weight:700;color:{color};">{badge}</div>
          <div style="font-size:13px;color:#1f2733;margin-top:6px;">{advice}</div>
          <table style="width:100%;border-collapse:collapse;margin-top:12px;background:#f7f9fc;">
            <tr>{metrics}</tr>
          </table>
          <div style="font-size:11px;color:#93a1b3;margin-top:10px;">
            最近一次信号变化：{last_txt}
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

    rotation: compute_panel() 的结果（可为 None，则不展示风格轮动区块）
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
             text-decoration:none;font-weight:600;">电脑版 · 风格轮动看板</a>
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
          风格轮动看板：创红比（创业板指/中证红利）&gt;0.60 观察中证红利、&lt;0.35 观察创业板；
          VXN&gt;30 触发大笔买入纳斯达克（纳指加仓至 40%）；纳指ETF溢价 &gt;5% 预警、&gt;10% 暂缓买入。<br>
          本邮件为历史规则回测研究，不构成投资建议。
        </div>
      </div>
    </td></tr>
  </table>
</div>"""
    return subject, body
