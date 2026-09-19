# -*- coding: utf-8 -*-
"""SMTP 邮件推送（smtplib + email.mime）。配置缺失/发送失败仅告警，不阻塞主流程。

多收件人：MAIL_TO / MAIL_CC / MAIL_BCC 均可用「英文逗号、中文逗号、分号或空白」分隔，
例如 MAIL_TO=a@qq.com,b@163.com,c@126.com
- MAIL_TO  必填，收件人（所有收件人互相可见）
- MAIL_CC  可选，抄送
- MAIL_BCC 可选，密送（不会出现在邮件头里，适合不想互相暴露邮箱的场合）
"""
from __future__ import annotations

import re
import smtplib
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# 邮件正文（含跷跷板面板与图表占位）由 mail_report 组装，此处保持 import 路径不变
from strategy_lab.mail_report import build_email   # noqa: F401

REQUIRED_KEYS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "MAIL_TO")

# 分隔符：英文/中文逗号、英文/中文分号、空白、换行
_ADDR_SPLIT = re.compile(r"[,，;；\s]+")


def parse_addrs(raw: str | None) -> list:
    """把配置字符串拆成邮箱列表（去空、去重复、保持顺序）"""
    if not raw:
        return []
    out = []
    for x in _ADDR_SPLIT.split(str(raw)):
        x = x.strip()
        if x and x not in out:
            out.append(x)
    return out


def _build_msg(subject: str, body_html: str, sender: str, to_list: list,
               cc_list: list, images: dict | None = None):
    """构造邮件对象：无图走 MIMEText；有图走 multipart/related + cid 内嵌"""
    if not images:
        msg = MIMEText(body_html, "html", "utf-8")
    else:
        msg = MIMEMultipart("related")
        msg.attach(MIMEText(body_html, "html", "utf-8"))
        for cid, data in images.items():
            img = MIMEImage(data, _subtype="png")
            img.add_header("Content-ID", f"<{cid}>")
            img.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
            msg.attach(img)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)
    return msg


def send_email(subject: str, body_html: str, env: dict,
               images: dict | None = None) -> tuple[bool, str]:
    """返回 (成功?, 说明)。SSL(465) 或 STARTTLS(587) 自动选择。

    MAIL_TO 支持多个地址（逗号分隔）；MAIL_CC / MAIL_BCC 可选。
    images: {cid: png 字节}，正文用 <img src="cid:xxx"> 引用，随邮件内嵌发送。
    """
    missing = [k for k in REQUIRED_KEYS if not env.get(k)]
    if missing:
        return False, f"邮件配置缺失：{','.join(missing)}（请在 .env 中填写后重试）"
    host = env["SMTP_HOST"]
    port = int(env["SMTP_PORT"])
    user = env["SMTP_USER"]
    pwd = env["SMTP_PASS"]
    to_list = parse_addrs(env["MAIL_TO"])
    cc_list = parse_addrs(env.get("MAIL_CC"))
    bcc_list = parse_addrs(env.get("MAIL_BCC"))
    if not to_list:
        return False, "MAIL_TO 无有效收件人（请用逗号分隔多个邮箱）"
    # 实际投递名单 = 收件人 + 抄送 + 密送（密送不写入邮件头）
    rcpt_list = list(dict.fromkeys(to_list + cc_list + bcc_list))

    msg = _build_msg(subject, body_html, user, to_list, cc_list, images)
    try:
        if port == 465:
            server = smtplib.SMTP_SSL(host, port, timeout=20)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
            server.starttls()
        try:
            server.login(user, pwd)
            server.sendmail(user, rcpt_list, msg.as_string())
        finally:
            server.quit()
        detail = f"已发送至 {', '.join(to_list)}"
        if cc_list:
            detail += f"；抄送 {', '.join(cc_list)}"
        if bcc_list:
            detail += f"；密送 {len(bcc_list)} 人"
        return True, detail
    except Exception as e:
        return False, f"发送失败：{e}"

# 注：旧版 build_email 已于此处移除，现统一由 strategy_lab.mail_report.build_email 提供
#     （支持跷跷板面板 + 图表内嵌），上方 import 已重导出，调用方无需改动。
