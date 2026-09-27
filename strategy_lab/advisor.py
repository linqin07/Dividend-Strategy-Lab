# -*- coding: utf-8 -*-
"""AI 加减仓顾问：结合本实验室自有策略信号 + 通用资产配置策略，调用 DeepSeek 生成持仓建议。

数据源（全部来自 output/ 本地缓存，不发额外网络请求）：
  output/{code}_signal.json   各标的周线 RSI 信号
  output/yields.json          实时股息率汇总
  output/rotation.json        创业板/红利跷跷板面板（含当前配置建议）

接口：
  build_strategy_context()                    汇总策略上下文（纯文本）
  recommend(holdings, cash, risk_level, ...)  调用 DeepSeek，返回结构化建议 dict
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime

import requests

from strategy_lab.config import OUTPUT_DIR, load_env, load_funds

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
REQUEST_TIMEOUT = 300   # 秒：深度推理 + 长输出，放宽超时

SYSTEM_PROMPT = """你是一名严谨的中国市场基金/ETF 资产配置顾问，服务对象是一名长期执行"红利低波 + 周线 RSI 择时"策略的个人投资者。

你会收到两部分输入：
1.【策略上下文】：来自"红利策略实验室"的量化信号（周线 RSI 状态机、阶梯补仓参数、实时股息率、创业板/红利跷跷板面板）。
2.【用户持仓】：分账户的持仓明细（市值/成本/盈亏）与现金金额、风险偏好。

请综合以下策略思想给出加减仓建议：
- 本实验室自有规则：周线 RSI(14) Wilder 状态机（RSI<buy 阈值买入、>sell 阈值卖出、中间持有不动）；跌破年线阶梯补仓；跷跷板面板的 红利/创业板/纳指 配置比例；高股息率区间加仓、低股息率区间谨慎。
- 通用配置原则：核心-卫星结构（红利低波为核心仓）；单一标的不超过总资产 20%；单一行业/主题不超过 30%；现金/货基保留 5%~15% 机动仓位；深亏且基本面未变的宽基/行业 ETF 用定投或阶梯补仓摊薄而非一次性加仓；QDII 注意溢价与汇率风险；退市风险/基本面恶化的个股果断处理；同质化持仓（多只跟踪同一板块）合并降维。
- 仓位管理：先定总仓位，再分标的；给出具体金额（人民币元），金额取整到百元。
- 强调纪律：不追高、不满仓、不杠杆；所有建议需可执行。

输出要求：只输出一个 JSON 对象（不要 markdown 代码块包裹），结构如下：
{
  "summary": "一句话总体结论（50字内）",
  "overall": {
    "current_position_pct": 用户当前总仓位百分比的数字估计,
    "target_position_pct": 建议目标总仓位百分比的数字,
    "cash_advice": "现金/货基安排建议（50字内）"
  },
  "actions": [
    {
      "code": "标的代码（无代码则留空字符串）",
      "name": "标的名称（与输入一致）",
      "action": "加仓|减仓|持有|清仓|定投|转出",
      "amount": "建议金额或数量描述，如 '加仓 ¥2,000' / '分3批减仓至 ¥20,000'",
      "reason": "一句话理由（60字内，引用数据）"
    }
  ],
  "risks": ["风险提示1", "风险提示2"],
  "detail_md": "详细的分账户说明（Markdown 格式，可用 ### 分账户小标题、**加粗**、- 列表；涵盖：总仓位规划、每账户处理思路、同质化持仓合并建议、执行节奏）"
}
actions 必须覆盖用户每一只持仓（不可遗漏），同类小仓位可合并建议但也要单列一行。"""


# ---------- 策略上下文 ----------
def _load_output(name: str):
    fp = os.path.join(OUTPUT_DIR, name)
    if not os.path.exists(fp):
        return None
    try:
        with open(fp, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def build_strategy_context() -> str:
    """汇总实验室自有策略信号为纯文本上下文（各环节失败均降级跳过，不阻断）。"""
    parts: list[str] = []
    today = datetime.now().strftime("%Y-%m-%d %H:%M")
    parts.append(f"【生成时间】{today}")

    # 1) 各标的周线 RSI 信号 + 仓位参数
    funds = load_funds()
    lines = []
    for f in funds:
        if not f.enabled:
            continue
        sig = _load_output(f"{f.code}_signal.json")
        if not sig or sig.get("error"):
            continue
        lines.append(
            f"- {sig.get('code')} {sig.get('name')}: 周RSI={sig.get('rsi')} "
            f"状态={sig.get('state')} 本周建议={sig.get('action')}（{sig.get('note')}）"
            f" 买入阈值{sig.get('params', {}).get('rsi_buy')} 卖出阈值{sig.get('params', {}).get('rsi_sell')} "
            f"单次仓位金额¥{sig.get('params', {}).get('position_amount', 0):,.0f}"
        )
    if lines:
        parts.append("【本实验室周线RSI信号（截至最近计算）】\n" + "\n".join(lines))

    # 2) 实时股息率
    yd = _load_output("yields.json")
    if yd and yd.get("rows"):
        rows = []
        for r in yd["rows"]:
            dy2 = r.get("dy2") if r.get("dy2") is not None else r.get("ttm_dy")
            if dy2 is None:
                continue
            rows.append(f"- {r.get('code')} {r.get('name')}: 滚动股息率(TTM)={dy2*100:.2f}%"
                        f"（数据日期 {r.get('date')}）")
        if rows:
            parts.append("【实时股息率（高股息=估值低区域，可分批加仓；低股息=偏贵，谨慎追高）】\n"
                         + "\n".join(rows))

    # 3) 跷跷板面板当前配置
    try:
        rot = _load_output("rotation.json")
        if rot and rot.get("dates"):
            from strategy_lab.rotation import compute_panel
            panel = compute_panel(rot)
            cur = panel.get("cur") or {}
            alloc = cur.get("alloc") or {}
            last = cur.get("last_switch") or {}
            parts.append(
                "【创业板/红利跷跷板面板】\n"
                f"- 当前区域：{cur.get('zone_name')}（创红比={cur.get('ratio')}）"
                f" VXN={cur.get('vxn')} VXN触发={cur.get('vxn_hit')}\n"
                f"- 面板建议配置：红利 {alloc.get('div', 0)*100:.0f}% / "
                f"创业板 {alloc.get('gem', 0)*100:.0f}% / 纳指 {alloc.get('ndx', 0)*100:.0f}%\n"
                f"- 最近一次切换：{last.get('date', '-')} {last.get('reason', '')}"
            )
    except Exception:
        pass

    # 4) 策略规则速览
    parts.append(
        "【实验室策略规则速览】\n"
        "- 周线 RSI(14) Wilder 状态机：RSI<买入阈值→空仓转全仓买入；RSI>卖出阈值→持仓转全仓卖出；中间区间不操作。\n"
        "- 跌破年线阶梯补仓：各标设定有 -5%/-6.5%/-8%/-9.5%/-11% 等阶梯（512890 为 -2%~-6%），逐档加码。\n"
        "- 单次仓位金额默认 ¥10,000/标的，由 funds.json 的 position_amount 控制。"
    )
    return "\n\n".join(parts)


# ---------- DeepSeek 调用 ----------
def resolve_api_key(explicit: str | None = None) -> str:
    """Key 优先级：请求显式传入 > 环境变量 DEEPSEEK_API_KEY > .env 文件。"""
    key = (explicit or "").strip()
    if key:
        return key
    key = (os.environ.get("DEEPSEEK_API_KEY") or "").strip()
    if key:
        return key
    return (load_env().get("DEEPSEEK_API_KEY") or "").strip()


def _holdings_text(holdings: list[dict], cash: float, risk_level: str,
                   extra: str | None) -> str:
    lines = [f"【风险偏好】{risk_level}",
             f"【可用现金】¥{cash:,.2f}"]
    lines.append("【持仓明细】（账户 | 名称 | 代码 | 持仓市值元 | 成本 | 现价 | 数量 | 累计盈亏元 | 持有收益率%）")
    for h in holdings:
        def _fmt(v):
            if v in (None, ""):
                return "-"
            try:
                return f"{float(v):,.2f}"
            except (TypeError, ValueError):
                return str(v)
        pct = h.get("pct")
        pct_txt = f"{pct:+.2f}%" if isinstance(pct, (int, float)) else "-"
        lines.append("- {} | {} | {} | {} | {} | {} | {} | {} | {}".format(
            h.get("account", "-"), h.get("name", "-"), h.get("code", "-"),
            _fmt(h.get("amount")), _fmt(h.get("cost")), _fmt(h.get("price")),
            _fmt(h.get("qty")), _fmt(h.get("profit")), pct_txt))
    if extra:
        lines.append(f"【用户补充说明】{extra}")
    return "\n".join(lines)


def _parse_reply(content: str) -> dict:
    """解析 DeepSeek 返回：优先按 JSON 解析，失败则降级为纯文本建议。"""
    text = (content or "").strip()
    # 剥离可能的 ```json ... ``` 包裹
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            data["_format"] = "json"
            return data
    except json.JSONDecodeError:
        pass
    # JSON 截断兜底：尝试回溯到最后完整节点再补闭合
    try:
        patched = _patch_truncated_json(text)
        if isinstance(patched, dict) and (patched.get("summary") or patched.get("actions") or patched.get("detail_md")):
            patched["_format"] = "json"
            patched["_patched"] = True
            return patched
    except Exception:
        pass
    return {"_format": "text", "summary": "AI 返回为非结构化文本", "detail_md": content or ""}


def _patch_truncated_json(text: str):
    """对截断的 JSON 做尽力修复：回溯到最后一个"完整安全点"，再闭合剩余括号。

    安全点定义为处理完该字符后 in_str==False 的位置（字符串/括号闭合处），
    因此截断点永远落在结构完整处，无需补引号。
    """
    depth_stack = []
    in_str = False
    esc = False
    last_safe = -1
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
                last_safe = i
            continue
        if ch == '"':
            in_str = True
        elif ch in "{[":
            depth_stack.append(ch)
        elif ch in "}]":
            if depth_stack:
                depth_stack.pop()
            last_safe = i
    if not depth_stack and not in_str:
        return json.loads(text)
    # 回退到最后一个安全点（丢掉其后可能残缺的字段），再闭合未关闭的括号
    cut = text[:last_safe + 1] if last_safe >= 0 else ""
    cut = cut.rstrip().rstrip(",")          # 去掉尾部悬空逗号
    # 截断点可能落在 "key" / "key": 的悬空键上，剥掉后才能合法闭合
    cut = re.sub(r',?\s*"[^"]*"\s*:\s*$', "", cut)
    cut = re.sub(r',\s*"[^"]*"\s*$', "", cut)
    cut = cut.rstrip().rstrip(",")
    if not cut:
        raise json.JSONDecodeError("无可解析内容", text, 0)
    opened = []
    for ch in cut:
        if ch in "{[":
            opened.append(ch)
        elif ch in "}]":
            if opened:
                opened.pop()
    fixed = cut + "".join("]" if c == "[" else "}" for c in reversed(opened))
    return json.loads(fixed)


def recommend(holdings: list[dict], cash: float = 0.0, risk_level: str = "稳健",
              extra: str | None = None, api_key: str | None = None) -> dict:
    """调用 DeepSeek 生成加减仓建议。返回 {advice: {...}, context, model}。"""
    key = resolve_api_key(api_key)
    if not key:
        raise RuntimeError(
            "未配置 DeepSeek API Key：请在页面填入，或在项目根目录 .env 中加入 "
            "DEEPSEEK_API_KEY=sk-xxx（或设置环境变量 DEEPSEEK_API_KEY）")

    context = build_strategy_context()
    user_msg = (context + "\n\n" +
                _holdings_text(holdings or [], cash or 0.0, risk_level, extra) +
                "\n\n请严格按系统要求的 JSON 结构输出建议，覆盖全部持仓。")

    resp = requests.post(
        DEEPSEEK_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": DEEPSEEK_MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "temperature": 1.0,
            "max_tokens": 8000,
            "response_format": {"type": "json_object"},
        },
        timeout=REQUEST_TIMEOUT,
    )
    if resp.status_code == 401:
        raise RuntimeError("DeepSeek API Key 无效（401），请检查密钥")
    if resp.status_code == 402:
        raise RuntimeError("DeepSeek 账户余额不足（402），请充值后重试")
    if resp.status_code == 429:
        raise RuntimeError("DeepSeek 请求过于频繁/限流（429），请稍后重试")
    resp.raise_for_status()
    data = resp.json()
    content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")
    usage = data.get("usage") or {}
    advice = _parse_reply(content)
    return {"advice": advice, "model": DEEPSEEK_MODEL,
            "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens", "total_tokens")},
            "context_chars": len(context)}
