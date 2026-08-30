# -*- coding: utf-8 -*-
"""统一 CLI 入口：serve / backtest / signal / init
用法：
  python run.py init
  python run.py serve [--port 8000]
  python run.py backtest [--code 932305] [--all] [--start 2022-01-01] [--end 2026-08-21]
  python run.py signal [--all] [--notify]
"""
from __future__ import annotations

import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(prog="run.py", description="基金/指数策略测算系统")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="初始化 funds.json/.env.example/目录")
    p_init.set_defaults(func=_cmd_init)

    p_serve = sub.add_parser("serve", help="启动 FastAPI 服务（前端页面 + JSON API）")
    p_serve.add_argument("--port", type=int, default=8000)
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--reload", action="store_true", help="开发模式：代码变更自动重启")
    p_serve.set_defaults(func=_cmd_serve)

    p_bt = sub.add_parser("backtest", help="手动回测")
    p_bt.add_argument("--code", default="932305", help="标的编码（默认 932305）")
    p_bt.add_argument("--all", action="store_true", help="对 funds.json 全部标的回测")
    p_bt.add_argument("--start", default="2022-01-01")
    p_bt.add_argument("--end", default=None)
    p_bt.set_defaults(func=_cmd_backtest)

    p_sig = sub.add_parser("signal", help="计算最新周信号（可选邮件推送）")
    p_sig.add_argument("--all", action="store_true", help="全部标的")
    p_sig.add_argument("--code", default=None, help="指定标的（默认仅主标的932305）")
    p_sig.add_argument("--notify", action="store_true", help="发送邮件推送")
    p_sig.add_argument("--force", action="store_true", help="强制刷新行情缓存")
    p_sig.set_defaults(func=_cmd_signal)

    p_yd = sub.add_parser("yields", help="汇总当前基金的实时股息率（中证官网估值，动态TTM兜底）")
    p_yd.set_defaults(func=_cmd_yields)

    args = ap.parse_args()
    args.func(args)


def _cmd_init(args):
    from strategy_lab.config import ensure_dirs, load_funds, save_funds, BASE_DIR
    import os
    ensure_dirs()
    load_funds()   # 不存在则生成默认
    env_example = os.path.join(BASE_DIR, ".env.example")
    if not os.path.exists(env_example):
        with open(env_example, "w", encoding="utf-8") as f:
            f.write(_ENV_TEMPLATE)
    print("初始化完成：funds.json / data / output / .env.example")


def _cmd_serve(args):
    """启动 FastAPI 服务（前后端分离：web/ 静态页 + /api/* 接口）"""
    from strategy_lab.api import serve
    serve(port=args.port, host=args.host, reload=args.reload)
    serve(port=args.port)


def _cmd_backtest(args):
    from strategy_lab.config import ensure_dirs, load_funds
    from strategy_lab.report import run_fund_backtest, write_summary
    ensure_dirs()
    funds = load_funds()
    if args.all:
        targets = [f for f in funds if f.enabled]
    else:
        targets = [f for f in funds if f.code == args.code]
        if not targets:
            targets = [f for f in funds if f.code == "932305"] or funds[:1]
    results = []
    for f in targets:
        print(f"回测 {f.code} {f.name}（{args.start} ~ {args.end or '最新'}）...")
        r = run_fund_backtest(f, start=args.start, end=args.end)
        results.append(r)
        for s in r.get("strategies", []):
            m = s.get("metrics") or {}
            print(f"  {s['name']:18s} 累计{m.get('cumulative_return',0)*100:8.2f}%  "
                  f"回撤{m.get('max_drawdown',0)*100:7.2f}%  夏普{m.get('sharpe',0):5.2f}")
    write_summary(targets, results)
    print("完成。结果已写入 output/")


def _cmd_signal(args):
    import os
    from strategy_lab.config import ensure_dirs, load_funds, load_env
    from strategy_lab.signal import latest_signal
    from strategy_lab.report import write_signal_json, write_summary
    from strategy_lab.notify import build_email, send_email
    ensure_dirs()
    funds = load_funds()
    if args.all:
        targets = [f for f in funds if f.enabled]
    elif args.code:
        targets = [f for f in funds if f.code == args.code]
    else:
        targets = [f for f in funds if f.code == "932305"] or funds[:1]

    rows = []
    for f in targets:
        sig = latest_signal(f, force=args.force)
        rows.append(sig)
        write_signal_json(f, sig)
        state = sig.get("state", "-")
        amt = sig.get("suggested_amount")
        amt_txt = "" if amt is None else f" 建议金额=¥{amt:,.0f}" + (
            " ⚠超仓" if sig.get("over_position") else "")
        print(f"{f.code} {f.name}: 周RSI={sig.get('rsi')} 状态={state} "
              f"建议={sig.get('action')}{amt_txt} （{sig.get('note')}）")

    if args.notify:
        # .env 优先，缺失项用环境变量补齐（GitHub Actions Secrets 走环境变量）
        env = load_env()
        for k in ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "MAIL_TO"):
            if os.environ.get(k):
                env[k] = os.environ[k]
        subject, body = build_email(rows)
        ok, msg = send_email(subject, body, env)
        print(("✅ " if ok else "⚠️ ") + msg)
    print("信号结果已写入 output/")


def _cmd_yields(args):
    """汇总当前基金的实时股息率（中证官网估值，动态TTM兜底）"""
    from strategy_lab.datasource.dividend_yield import summarize_yields
    s = summarize_yields()
    print(f"实时股息率汇总（共 {s['total']} 只启用基金，{s['with_yield']} 只有数据）")
    print(f"平均滚动股息率: {(s['avg_dy2'] or 0)*100:.2f}%  |  "
          f"最高: {s['max']['name'] if s['max'] else '-'} {(s['max']['dy'] if s['max'] else 0)*100:.2f}%  |  "
          f"最低: {s['min']['name'] if s['min'] else '-'} {(s['min']['dy'] if s['min'] else 0)*100:.2f}%")
    print(f"{'编码':<8}{'名称':<18}{'指数':<8}{'静态股息率':<10}{'滚动股息率(TTM)':<14}{'数据日期':<12}来源")
    for r in s["rows"]:
        dy1 = f"{r['dy1']*100:.2f}%" if r["dy1"] is not None else "--"
        dy2 = f"{r['dy2']*100:.2f}%" if r["dy2"] is not None else (
            f"{r['ttm_dy']*100:.2f}%" if r["ttm_dy"] is not None else "--")
        src = {"csindex": "中证官网", "dynamic": "动态TTM"}.get(r["source"], "--")
        print(f"{r['code']:<8}{r['name'][:16]:<18}{str(r['index_code'] or ''):<8}"
              f"{dy1:<10}{dy2:<14}{str(r['date'] or ''):<12}{src}")


_ENV_TEMPLATE = """# SMTP 邮件推送配置（QQ邮箱示例：smtp.qq.com / 465 / 授权码）
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=your_account@qq.com
SMTP_PASS=你的授权码（非登录密码）
MAIL_TO=receiver@example.com

# 数据源顺序覆盖（可选，逗号分隔；CI 中建议去掉 tdx）
# PROVIDER_ORDER=eastmoney,csindex,tencent,akshare
"""


if __name__ == "__main__":
    main()
