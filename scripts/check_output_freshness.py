# -*- coding: utf-8 -*-
"""校验 output/*_backtest.json 是否为有效的最新行情结果。

用途：GitHub Actions 每日刷新跑完后调用，若在线数据源全部失败（stale=True，
即只用了本地缓存兜底）或无数据，则以退出码 1 中止提交，避免把陈旧数据推上去
覆盖页面。本地也可直接 `python scripts/check_output_freshness.py` 自检。
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")


def main() -> int:
    today = dt.date.today()
    print(f"刷新日期: {today}")
    files = sorted(glob.glob(os.path.join(OUTPUT_DIR, "*_backtest.json")))
    if not files:
        print("  [FAIL] output/ 下没有回测结果文件")
        return 1

    failed = []
    for p in files:
        name = os.path.basename(p)
        with open(p, "r", encoding="utf-8") as f:
            d = json.load(f)
        if d.get("error"):
            print(f"  [FAIL] {name}: {d.get('error')} {d.get('errors') or ''}")
            failed.append(name)
            continue
        bars = d.get("daily") or []
        last = bars[-1][0] if bars else None
        lag = (today - dt.date.fromisoformat(last)).days if last else None
        print(f"  [OK] {name}: 最新K线={last} 距今={lag}天 "
              f"provider={d.get('provider')} stale={d.get('stale')}")
        if d.get("stale"):
            print(f"  [FAIL] {name}: 所有在线数据源失败，仅使用本地缓存")
            failed.append(name)
        elif lag is not None and lag > 7:
            print(f"  [WARN] {name}: 最新K线距今 {lag} 天（节假日属正常，否则检查数据源）")

    # 全部标的都失败 = 网络/数据源整体不可用，中止提交避免用缓存覆盖页面；
    # 个别标的失败则放行，其余标的仍能正常更新。
    if failed and len(failed) == len(files):
        print("全部标的行情拉取失败，中止提交（页面继续沿用上一次结果）")
        return 1
    if failed:
        print(f"警告：{len(failed)}/{len(files)} 个标的未取到新行情（沿用旧数据）：{', '.join(failed)}")
    print("数据新鲜度校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
