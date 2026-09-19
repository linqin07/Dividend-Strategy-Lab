# -*- coding: utf-8 -*-
"""校验 output/ 下的回测结果是否为最新有效数据。

判定基准是 funds.json 中「已启用」的标的清单，逐个检查对应文件 —— 而不是只看
output/ 里已存在的文件，否则拉取失败的标的会被整份漏掉（曾出现 4 个标的只成功
2 个、却仍判为通过的情况）。以下情况均计为失败：

  * output/{code}_backtest.json 不存在（无行情时 run_fund_backtest 直接返回、不落盘）
  * 文件不是合法 JSON
  * 文件里带 error 字段
  * stale=True，即所有在线数据源都失败、只能用本地缓存兜底

退出码：
  0  数据可用 —— 个别标的失败只告警，其余标的照常发布（尽量让页面每天都有更新）
  1  失败标的超过半数 —— 中止部署，线上继续保留上一次成功发布的结果

用途：refresh-and-deploy.yml 在组装静态站点前的闸门。本地也可直接运行自检：
  python scripts/check_output_freshness.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
FUNDS_PATH = os.path.join(BASE_DIR, "funds.json")


def _enabled_funds() -> list:
    """读取 funds.json 中已启用的标的（与回测/信号的实际范围保持一致）"""
    if not os.path.exists(FUNDS_PATH):
        return []
    with open(FUNDS_PATH, "r", encoding="utf-8") as f:
        funds = json.load(f)
    return [x for x in funds if x.get("enabled", True)]


def _check_one(fund: dict) -> tuple:
    """返回 (是否通过, 说明文本)"""
    code = fund.get("code", "?")
    path = os.path.join(OUTPUT_DIR, f"{code}_backtest.json")

    if not os.path.exists(path):
        return False, "缺少回测结果文件（该标的未取到行情）"

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return False, f"文件解析失败：{e}"

    if data.get("error"):
        return False, f"回测报错：{data['error']} {data.get('errors') or ''}".strip()

    bars = data.get("daily") or []
    last = bars[-1][0] if bars else None
    if not last:
        return False, "回测结果中没有日线数据"

    lag = (dt.date.today() - dt.date.fromisoformat(last)).days
    detail = f"最新K线={last} 距今{lag}天 provider={data.get('provider')}"

    if data.get("stale"):
        return False, f"{detail}；所有在线数据源失败，仅用本地缓存兜底"
    if lag > 10:
        return True, f"{detail}；⚠ 距今超过 10 天（长假属正常，否则检查数据源）"
    return True, detail


def main() -> int:
    today = dt.date.today()
    print(f"数据新鲜度校验 · {today}")

    funds = _enabled_funds()
    if not funds:
        print("  [FAIL] funds.json 不存在或没有已启用的标的")
        return 1

    failed = []
    for fund in funds:
        ok, detail = _check_one(fund)
        print(f"  [{'OK' if ok else 'FAIL'}] {fund.get('code')} {fund.get('name', '')}: {detail}")
        if not ok:
            failed.append(str(fund.get("code")))

    total = len(funds)
    print(f"----- 通过 {total - len(failed)}/{total} -----")

    # 严格多数失败 = 数据源整体不可用，此时用残缺或陈旧数据部署没有意义；
    # 少数标的失败则放行，其余标的仍能正常更新到页面上。
    if len(failed) * 2 > total:
        print(f"失败标的超过半数（{len(failed)}/{total}）：{'、'.join(failed)}")
        print("中止部署，线上继续保留上一次成功发布的结果")
        return 1

    if failed:
        print(f"警告：以下标的本次未取到新行情，页面上会缺少它们的数据：{'、'.join(failed)}")
    else:
        print("全部标的数据新鲜度校验通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
