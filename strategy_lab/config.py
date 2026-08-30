# -*- coding: utf-8 -*-
"""配置管理：funds.json / .env 加载与保存、Fund 数据类、默认参数"""
from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUTPUT_DIR = os.path.join(BASE_DIR, "output")
WEB_DIR = os.path.join(BASE_DIR, "web")
FUNDS_PATH = os.path.join(BASE_DIR, "funds.json")
ENV_PATH = os.path.join(BASE_DIR, ".env")

# 回测口径常量（严格对应《红利策略报告》）
INIT_CASH = 1_000_000.0      # 初始资金 100 万
FEE = 0.001                   # 买卖各 0.1% 成本
RF_ANNUAL = 0.02              # 夏普无风险利率 2%

# 按标的类型默认的数据供应商链（可被 funds.json 或环境变量 PROVIDER_ORDER 覆盖）
DEFAULT_PROVIDER_ORDER = {
    "index": ["eastmoney", "csindex", "tencent", "akshare", "tdx"],
    "etf": ["tdx", "eastmoney", "tencent", "akshare"],
    "fund": ["akshare", "eastmoney"],
}


@dataclass
class Fund:
    code: str
    name: str
    kind: str = "index"                # "index" | "etf" | "fund"(场外基金)
    market: str = "SH"                 # "SH" | "SZ"
    enabled: bool = True
    rsi_buy: float = 45.0
    rsi_sell: float = 65.0
    ladder: list = field(default_factory=lambda: [-5.0, -6.5, -8.0, -9.5, -11.0])   # 相对年线的阶梯百分比
    boll_params: dict = field(default_factory=lambda: {"period": 20, "k": 2})
    dividends: Optional[list] = None   # [{"date":"YYYY-MM-DD","cash_per_unit":0.05}]
    splits: Optional[list] = None      # [{"date":"YYYY-MM-DD","ratio":2.0}]
    provider_order: Optional[list] = None

    # 仓位资金管理（每基金单独设置）
    position_amount: float = 10000.0   # 仓位金额（元），默认 10000
    position_ratio: float = 1.0        # 浮动仓位比例 0~1，默认 100%
    mult_mode: str = "none"            # 倍率模式："none"|"buy"(越买越多)|"sell"(越卖越多)|"both"
    mult_factor: float = 1.0           # 倍率系数 >= 1（最大加码倍数上限）

    # 实时股息率：跟踪的中证指数代码（如 000922 中证红利 / H30269 红利低波 / 932305 智选高股息）
    index_code: Optional[str] = None

    def base_amount(self) -> float:
        """实际可动用资金 = 仓位金额 × 浮动仓位比例"""
        return round(self.position_amount * self.position_ratio, 2)

    def resolved_provider_order(self) -> list:
        if self.provider_order:
            return self.provider_order
        env_order = os.environ.get("PROVIDER_ORDER", "")
        if env_order:
            return [x.strip() for x in env_order.split(",") if x.strip()]
        return DEFAULT_PROVIDER_ORDER.get(self.kind, DEFAULT_PROVIDER_ORDER["index"])


def _default_funds() -> list:
    """默认基金清单：932305 智选高股息（主标的）+ 报告中的 515080 / 512890（用于校验）"""
    return [
        Fund(
            code="932305", name="中证智选高股息指数(智选高股息)", kind="index", market="SH",
            rsi_buy=45.0, rsi_sell=65.0,
            ladder=[-5.0, -6.5, -8.0, -9.5, -11.0],
            index_code="932305",
        ),
        Fund(
            code="515080", name="中证红利ETF", kind="etf", market="SH",
            rsi_buy=45.0, rsi_sell=60.0,
            ladder=[-5.0, -6.5, -8.0, -9.5, -11.0],
            index_code="000922",
        ),
        Fund(
            code="512890", name="红利低波ETF", kind="etf", market="SH",
            rsi_buy=45.0, rsi_sell=65.0,
            ladder=[-2.0, -3.0, -4.0, -5.0, -6.0],
            splits=[{"date": "2021-10-25", "ratio": 2.0}],
            index_code="H30269",
        ),
    ]


MULT_MODES = ("none", "buy", "sell", "both")


def validate_position(amount: float, ratio: float, mult_mode: str, mult_factor: float) -> str | None:
    """校验仓位资金参数，返回错误信息；合法则返回 None。"""
    if amount is None or amount <= 0:
        return "仓位金额必须大于 0"
    if ratio is None or ratio <= 0 or ratio > 1:
        return "浮动仓位比例必须在 (0, 1] 之间（如 1.0 或 0.6）"
    if mult_mode not in MULT_MODES:
        return f"倍率模式必须为 {'/'.join(MULT_MODES)} 之一"
    if mult_factor is None or mult_factor < 1:
        return "倍率系数必须 >= 1"
    return None


def load_funds(path: str = FUNDS_PATH) -> list:
    if not os.path.exists(path):
        funds = _default_funds()
        save_funds(funds, path)
        return funds
    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)
    funds = []
    for item in raw:
        known = {k: v for k, v in item.items() if k in Fund.__dataclass_fields__}
        funds.append(Fund(**known))
    return funds


def save_funds(funds: list, path: str = FUNDS_PATH) -> None:
    """原子写：先写临时文件再 rename，避免写一半损坏 funds.json"""
    atomic_write_json(path, [asdict(x) for x in funds], indent=2)


def load_env(path: str = ENV_PATH) -> dict:
    """手工解析 .env（KEY=VALUE），不引入第三方依赖"""
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def ensure_dirs() -> None:
    for d in (DATA_DIR, OUTPUT_DIR):
        os.makedirs(d, exist_ok=True)


def atomic_replace(src: str, dst: str, max_wait: float = 15.0) -> None:
    """原子替换目标文件（Windows 下目标被占用时 os.replace 抛 PermissionError(WinError 5)）。

    策略：先快速重试 os.replace（应对杀软扫描/网页读取等瞬时占用）；重试 3 次后
    交替尝试 shutil.copyfile 直写兜底（rename 被拒但目标可写时立即成功，避免长等待）；
    持续失败则在 max_wait 内循环，超时抛原始异常。
    """
    import shutil
    deadline = time.time() + max_wait
    last = None
    attempt = 0
    while True:
        attempt += 1
        try:
            os.replace(src, dst)
            return
        except OSError as e:
            last = e
        if attempt >= 3:
            try:
                shutil.copyfile(src, dst)
                safe_unlink(src)      # copyfile 不移动源文件，成功即清理临时文件
                return
            except OSError:
                pass
        if time.time() >= deadline:
            break
        time.sleep(min(0.2 * attempt, 1.0))
    raise last


def safe_unlink(path: str) -> None:
    """尽力删除临时文件，绝不抛错。

    WorkBuddy 沙箱会拦截 os.remove 并尝试移入回收站（Windows 沙箱回收站不可用会
    fail-closed 抛 OSError），这里多次尝试后静默降级，临时文件残留也无妨，绝不掩盖
    原始错误。
    """
    for _ in range(3):
        try:
            if os.path.exists(path):
                os.remove(path)
            return
        except OSError:
            time.sleep(0.2)


def atomic_write_json(path: str, obj, indent: int | None = None) -> None:
    """原子写 JSON：写临时文件 → 原子替换；异常时尽力清理临时文件并重抛原始异常。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            json.dump(obj, fp, ensure_ascii=False, indent=indent)
        atomic_replace(tmp, path)
    except Exception:
        safe_unlink(tmp)
        raise
