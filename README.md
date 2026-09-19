# 红利策略实验室 · 基金测算系统

基于《公开版-红利策略详细操作与回测分析报告》实现的基金/指数买卖点测算系统。
核心规则：**周线 RSI(14) Wilder 择时**——周五收盘确认信号，下一交易日开盘执行，空仓↔持仓两态切换。

## 功能

- 📊 **页面展示**：信号横幅、6 策略指标卡片、K线+交易点位、周 RSI、净值曲线、交易明细
- 🔴 **手动回测**：页面一键回测（后台任务 + 进度提示），或 CLI 批量回测
- 🧩 **基金管理**：页面新增/移除基金，自定义 RSI 买卖阈值；默认标的 `932305` 中证智选高股息
- 📧 **邮件推送**：SMTP（QQ 邮箱授权码等），红买绿卖 HTML 表格
- 🤖 **GitHub Actions**：每日自动刷新行情与回测（页面每天更新）+ 每周五 17:30 信号邮件推送 + 发布静态页面
- 🔌 **数据源降级链**：eastmoney → csindex（中证官网）→ tencent → akshare → tdx，本地 JSON 缓存兜底

## 快速开始

```bash
pip install -r requirements.txt

python run.py init                 # 初始化 funds.json / .env.example
python run.py serve                # 启动 FastAPI 服务，打开 http://127.0.0.1:8000
```

页面右上角「立即回测」生成当前标的的全部策略结果；「基金管理」增删基金。
支持 `python run.py serve --port 9000 --host 0.0.0.0 [--reload]`。

### 前后端分离架构

后端 FastAPI 提供 JSON 接口，前端 `web/` 只通过接口取数：

| 接口 | 说明 |
|---|---|
| `GET /api/ping` | 服务状态 + 策略清单（前端探测后端） |
| `GET /api/codes` | 可用标的列表（含是否已有回测结果） |
| `GET /api/backtest/{code}` | 已生成的回测结果（策略指标/交易明细/净值曲线） |
| `POST /api/backtest` | 触发回测（异步，返回 job_id） |
| `GET /api/signal/{code}` | 最新信号（默认读缓存，`?force=1` 实时重算） |
| `POST /api/refresh` | 刷新行情缓存（异步） |
| `GET /api/job/{job_id}` | 任务状态与结果 |
| `GET /api/yields` | 实时股息率汇总（`?force=1` 绕过短缓存） |
| `GET/POST/PUT/DELETE /api/funds[/{code}]` | 标的配置增删改查 |

- 交互式接口文档：`http://127.0.0.1:8000/docs`
- 前后端分离部署：页面设置 `window.API_BASE = "http://后端地址"` 即可指向独立后端
- 无后端时（如 GitHub Pages 纯静态部署）页面自动回退读取 `output/*.json`

### CLI 用法

```bash
python run.py backtest --all                      # 全部标的回测（默认 2022-01-01 起）
python run.py backtest --code 515080 --start 2022-01-01
python run.py signal --all                        # 计算最新周信号
python run.py signal --all --notify --force       # 强刷数据并发送邮件
python run.py yields                              # 汇总当前基金的实时股息率
```

## 邮件推送配置

复制 `.env.example` 为 `.env` 并填写：

```
SMTP_HOST=smtp.qq.com
SMTP_PORT=465
SMTP_USER=your_account@qq.com
SMTP_PASS=你的授权码（非登录密码）
MAIL_TO=receiver@example.com
```

> 465 走 SSL，587 自动 STARTTLS。配置缺失只告警、不阻塞计算。

## GitHub Actions

只剩两个工作流，职责不重叠：

**`refresh-and-deploy.yml`** —— 把「刷新数据」和「发布页面」合成一条流水线

| 触发 | 时间（北京时间） | 说明 |
|---|---|---|
| push 到 master | 代码提交后 | 重算 → 发布 |
| schedule | 每天 00:13 | 午夜刷新（拿到上一交易日收盘数据） |
| schedule | 工作日 16:35 | 收盘后刷新（拿到当日数据） |
| 手动 dispatch | — | 可勾选「跳过数据校验」 |

**`weekly-signal.yml`** —— 只负责信号邮件，不碰数据

| 触发 | 时间（北京时间） | 说明 |
|---|---|---|
| schedule | 周五 17:30 | 计算最新信号 → 发送邮件 |
| 手动 dispatch | — | 随时测试邮件推送是否正常 |

cron 一律按 **UTC** 计算，所以文件里写的是 `13 16 * * *` = 北京时间次日 00:13、
`30 9 * * 5` = 北京时间周五 17:30；两个工作流均设 `TZ: Asia/Shanghai`，
保证 `computed_at`、缓存新鲜度判断都用北京时间。二者都不向仓库提交任何数据（见下节）。

首次使用需在 **Settings → Secrets and variables → Actions** 添加 `SMTP_HOST / SMTP_PORT / SMTP_USER / SMTP_PASS / MAIL_TO`；在 **Settings → Pages** 选择 Source 为 "GitHub Actions"。

### 数据为什么不进 git

`output/`（回测与信号结果）和 `data/`（行情缓存）都是**可再生的派生产物**：每次运行都整份重写，
时间戳必然变化，提交它们会与 CI 反复互相覆盖并产生 git 冲突。现在二者都已加入 `.gitignore`：

- **部署时现场生成**：工作流执行 `backtest --all --force` + `signal --all --force`，
  组装 `web/ + output/` 后直接发布 Pages，**全程不向仓库提交任何数据**；
- **本地无需拉取**：跑 `python run.py serve` 前执行一次 `python run.py backtest --all --force` 即可，
  `data/` 与 `output/` 目录会自动重建（缓存缺失时会重新联网抓取）。
- **仓库只保留代码与配置**：`funds.json` 是唯一的标的配置真源，必须提交。

### 数据源异常时的行为

部署前会跑 `scripts/check_output_freshness.py`：若**全部标的**都取不到新行情（数据源整体故障），
则中止本次部署，线上继续保留上一次成功发布的结果，不会被陈旧缓存覆盖。
如需在数据源异常时仍要发布代码改动，手动触发时勾选 `skip_freshness_check`。

## 六种策略

1. 纯 RSI 首次建仓（报告主策略）
2. 年初满仓 + RSI 全仓滚动
3. 年初满仓 + RSI 半仓滚动（50% 固定 + 50% 滚动）
4. 年线阶梯建仓 + RSI 滚动
5. 年线阶梯建仓 + 布林带滚动
6. 买入持有（基准）

新增策略：在 `strategy_lab/strategies/` 新建文件实现 `Strategy.plan()`，在 `REGISTRY` 注册一行即可，页面自动展示。

## 回测口径

- 信号周五收盘确认，**下一交易日开盘成交**；不复权实际盘面价
- 买卖各 **0.1%** 成本；初始资金 **100 万**
- 持仓期分红计入现金、空仓期无分红、再买入时复投；拆分按份额×ratio 处理
- 指标：累计收益、几何年化、最大回撤、夏普（月度年化，无风险 2%）、卡玛、平均仓位

## 目录结构

```
run.py                    CLI 入口（backtest 支持 --force 强制刷新行情）
scripts/
  check_output_freshness.py  校验 output/ 数据新鲜度（部署前闸门）
strategy_lab/
  config.py               基金配置/常量
  indicators.py           周RSI/MA/BOLL/拆分抹平
  datasource/             5 级数据源降级 + 本地缓存
  strategies/             策略注册表 + 6 策略实现
  backtest/               事件驱动回测引擎 + 指标
  signal.py               最新周信号（推送/横幅共用）
  notify.py               SMTP 邮件
  api.py                  FastAPI 服务（/api/* 接口 + 托管 web/）
  jobs.py                 后台任务管理（异步回测/刷新 + 进度）
  datasource/dividend_yield.py  实时股息率（中证官网估值 + 动态TTM兜底）
  server.py               旧版 http.server 服务（已由 api.py 取代，保留备用）
web/                      前端单页（ECharts，全部数据通过接口获取）
output/                   回测/信号 JSON（运行时生成，git 忽略；接口读取，无后端时页面直接 fetch）
data/                     行情缓存（运行时生成，git 忽略）
.github/workflows/        CI：refresh-and-deploy.yml（刷新数据 + 发布）、weekly-signal.yml（周五邮件）
```

## 免责声明

本项目为历史规则回测研究工具，输出不构成投资建议。
