# -*- coding: utf-8 -*-
"""SMTP 邮件推送（smtplib + email.mime）。配置缺失/发送失败仅告警，不阻塞主流程。"""
from __future__ import annotations

import smtplib
import sys
from datetime import datetime
from email.mime.text import MIMEText

REQUIRED_KEYS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "MAIL_TO")


def send_email(subject: str, body_html: str, env: dict) -> tuple[bool, str]:
    """返回 (成功?, 说明)。SSL(465) 或 STARTTLS(587) 自动选择。"""
    missing = [k for k in REQUIRED_KEYS if not env.get(k)]
    if missing:
        return False, f"邮件配置缺失：{','.join(missing)}（请在 .env 中填写后重试）"
    host = env["SMTP_HOST"]
    port = int(env["SMTP_PORT"])
    user = env["SMTP_USER"]
    pwd = env["SMTP_PASS"]
    to_list = [x.strip() for x in env["MAIL_TO"].split(",") if x.strip()]

    msg = MIMEText(body_html, "html", "utf-8")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(to_list)
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls()
        try:
            server.login(user, pwd)
            server.sendmail(user, to_list, msg.as_string())
        finally:
            server.quit()
        return True, f"已发送至 {', '.join(to_list)}"
    except Exception as e:
        return False, f"发送失败：{e}"


def build_email(signal_rows: list) -> tuple:
    """信号汇总邮件：主题 + HTML 正文（红涨绿跌遵循A股惯例）"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    acted = [r for r in signal_rows if r.get("action") in ("买入", "卖出")]
    subject = "【策略信号】" + ("；".join(
        f"{r['name']} {r['action']}（RSI {r['rsi']}）" for r in acted) or "本周无买卖信号")

    rows_html = ""
    for r in signal_rows:
        if r.get("error"):
            color, badge, action = "#999", "错误", r["error"]
            state = "-"
            rsi = "-"
        else:
            state = r["state"]
            rsi = r["rsi"]
            if r["action"] == "买入":
                color, badge = "#c62828", "买入"
            elif r["action"] == "卖出":
                color, badge = "#1b5e20", "卖出"
            else:
                color, badge = "#555", "观望"
            action = r.get("note", "")
        amt = r.get("suggested_amount")
        if amt is not None:
            over = r.get("over_position")
            amount_html = f"¥{amt:,.0f}"
            if over:
                amount_html += ' <span style="color:#c62828;font-size:11px;">⚠超仓</span>'
            if r.get("multiplier", 1.0) > 1.0:
                amount_html += f'<br><span style="color:#999;font-size:11px;">×{r["multiplier"]:.2f}</span>'
        else:
            amount_html = "-"
        rows_html += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;">{r.get('name','')}<br>
              <span style="color:#999;font-size:12px;">{r.get('code','')}</span></td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;">{rsi}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;">{state}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;">
              <span style="color:{color};font-weight:bold;">{badge}</span></td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;text-align:right;white-space:nowrap;">{amount_html}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #eee;font-size:12px;">{action}</td>
        </tr>"""

    body = f"""
    <div style="font-family:'Microsoft YaHei',sans-serif;max-width:640px;margin:0 auto;">
      <h2 style="color:#1a237e;">红利策略 · 每周信号推送</h2>
      <p style="color:#666;">{now} 自动生成 ｜ 规则：周线RSI(14)状态机，周五收盘确认，下一交易日开盘执行</p>
      <table style="border-collapse:collapse;width:100%;background:#fff;">
        <tr style="background:#1a237e;color:#fff;">
          <th style="padding:10px 12px;text-align:left;">标的</th>
          <th style="padding:10px 12px;">周RSI</th>
          <th style="padding:10px 12px;">状态</th>
          <th style="padding:10px 12px;">建议</th>
          <th style="padding:10px 12px;">建议金额</th>
          <th style="padding:10px 12px;text-align:left;">说明</th>
        </tr>
        {rows_html}
      </table>
      <p style="color:#999;font-size:12px;margin-top:16px;">
        口径：不复权实际盘面价；RSI 45买 / 持仓超卖线全卖；重复同向信号忽略。<br>
        建议金额 = 仓位金额 × 浮动仓位比例 × 倍率（倍率按 RSI 信号强弱线性加码，模式可在页面「基金管理」中设置）。<br>
        本邮件为历史规则回测研究，不构成投资建议。
      </p>
    </div>"""
    return subject, body
