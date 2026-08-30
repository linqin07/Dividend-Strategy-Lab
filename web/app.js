/* 红利策略实验室 · 前端逻辑（前后端分离）
 * 数据一律通过接口获取：GET /api/codes、/api/backtest/{code}、/api/signal/{code}、/api/yields、/api/funds ...
 * 接口地址由 window.API_BASE 决定（同源部署留空；前后端分离部署时填后端地址）。
 * 后端不可用时（如 GitHub Pages 纯静态部署）自动回退读取 output/*.json。
 */
"use strict";

/* ================= 工具 ================= */
const $ = (id) => document.getElementById(id);

/** 后端 API 基址：同源部署为空，分离部署时在 index.html 设置 window.API_BASE */
const API_BASE = (typeof window !== "undefined" && (window.API_BASE || "")) || "";
/** 拼接接口地址（支持绝对地址与以 / 开头的路径） */
function apiUrl(path) {
  const base = String(API_BASE).replace(/\/+$/, "");
  return base + (path.startsWith("/") ? path : "/" + path);
}

async function fetchJSON(url, opts) {
  const res = await fetch(url, Object.assign({ cache: "no-store" }, opts));
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      // FastAPI 用 detail，旧版自研服务用 error
      if (body && (body.detail || body.error)) detail = body.detail || body.error;
    } catch (e) { /* 非 JSON 错误体，保持默认文案 */ }
    throw new Error(detail);
  }
  return res.json();
}

/** 取数统一入口：有后端走接口，无后端回退静态文件 */
async function fetchData(apiPath, staticPath) {
  if (S.serveMode) return fetchJSON(apiUrl(apiPath));
  return fetchJSON(staticPath);
}

function toast(msg, isErr) {
  const el = $("toast");
  el.textContent = msg;
  el.className = "toast" + (isErr ? " toast-error" : "");
  el.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.hidden = true; }, 3200);
}

const pct = (x) => (x == null || isNaN(x)) ? "--" : (x * 100).toFixed(2) + "%";
const num = (x, d) => (x == null || isNaN(x)) ? "--" : Number(x).toLocaleString("zh-CN",
  { minimumFractionDigits: d == null ? 2 : d, maximumFractionDigits: d == null ? 2 : d });
const money = (x) => (x == null || isNaN(x)) ? "--" : "¥" + Math.round(x).toLocaleString("zh-CN");
const upDownCls = (x) => x > 0 ? "v-up" : (x < 0 ? "v-down" : "");

const UP = "#d93838", DOWN = "#0c9668";   // 红涨绿跌
const PALETTE = ["#2f6fed", "#d93838", "#0c9668", "#c27803", "#7a5af8", "#0e7490"];

/** TTM 股息率 = 最近12个月每股分红合计 ÷ 最新收盘价（无分红数据返回 null） */
function calcTtmDividendYield(bt) {
  if (!bt) return null;
  const divs = bt.dividends || [];
  const daily = bt.daily || [];
  if (!divs.length || !daily.length) return null;
  const last = daily[daily.length - 1];
  const lastDate = last[0], price = last[4];
  if (!price || price <= 0) return null;
  const d = new Date(lastDate + "T00:00:00");
  d.setFullYear(d.getFullYear() - 1);
  const cutoff = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
  let sum = 0;
  for (const x of divs) {
    if (x.date >= cutoff && x.date <= lastDate) sum += Number(x.cash_per_unit) || 0;
  }
  return sum > 0 ? sum / price : null;
}

/* ================= 指标（与后端 indicators.py 镜像） ================= */

/** ISO 年-周（%G-%V 口径） */
function isoWeekKey(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  const dayNum = (d.getDay() + 6) % 7;                 // 周一=0
  d.setDate(d.getDate() - dayNum + 3);                 // 本周四
  const isoYear = d.getFullYear();
  const jan4 = new Date(isoYear, 0, 4);
  const j4day = (jan4.getDay() + 6) % 7;
  jan4.setDate(jan4.getDate() - j4day + 3);            // 该年第1个周四
  const week = 1 + Math.round((d - jan4) / (7 * 864e5));
  return isoYear + "-" + String(week).padStart(2, "0");
}

/** 拆分抹平：拆分日之前价格 / ratio（仅指标计算用） */
function splitAdjustRows(daily, splits) {
  const sps = (splits || []).slice().sort((a, b) => a.date < b.date ? -1 : 1);
  return daily.map((r) => {
    let f = 1;
    for (const s of sps) if (r[0] < s.date) f *= Number(s.ratio);
    return [r[0], r[1] / f, r[2] / f, r[3] / f, r[4] / f, r[5]];
  });
}

/** 日线 → 周线（close 取周末值） */
function toWeekly(daily) {
  const map = new Map();
  for (const r of daily) {
    const k = isoWeekKey(r[0]);
    if (!map.has(k)) map.set(k, { date: r[0], close: r[4] });
    else {
      const cur = map.get(k);
      if (r[0] >= cur.date) { cur.date = r[0]; cur.close = r[4]; }
    }
  }
  return [...map.values()];
}

/** 日线 → 周K（聚合 OHLCV：开=周一开，收=周末收，高低=区间极值，量=累加） */
function toWeeklyBars(daily) {
  const map = new Map();
  for (const r of daily) {
    const k = isoWeekKey(r[0]);
    const b = map.get(k);
    if (!b) {
      // r = [date, open, high, low, close, volume]
      map.set(k, { date: r[0], open: r[1], high: r[2], low: r[3], close: r[4], volume: r[5] });
    } else {
      b.high = Math.max(b.high, r[2]);
      b.low = Math.min(b.low, r[3]);
      b.volume += r[5] || 0;
      if (r[0] >= b.date) { b.date = r[0]; b.close = r[4]; }
    }
  }
  return [...map.values()].map((b) => [b.date, b.open, b.high, b.low, b.close, b.volume]);
}

/* ---------- RSI：主体计算与平滑环节分离 ----------
 * rsiSeries = 涨跌幅序列 → smoothSeries（独立平滑，方式/周期可配） → RSI 公式
 * 默认 wilder + 平滑周期跟随 RSI 周期，与历史实现逐点一致。
 */

/** 平滑环节：对涨/跌幅度序列做平滑，返回等长数组（未达最小周期处为 null） */
function smoothSeries(vals, period, method) {
  const n = vals.length;
  const out = new Array(n).fill(null);
  if (n === 0 || period <= 0) return out;
  const m = (method || "wilder").toLowerCase();

  // 注意：序列第 0 项无前值（涨跌幅为 0），平滑一律从第 1 项开始，
  // 否则初值被 0 污染会与历史 Wilder 实现产生偏差。
  if (m === "none") {                       // 不做平滑：直接用单期涨跌幅
    for (let i = 1; i < n; i++) out[i] = vals[i];
    return out;
  }
  if (m === "sma") {                        // 简单移动平均，min_periods = period
    let sum = 0;
    for (let i = 0; i < n; i++) {
      sum += vals[i] || 0;
      if (i >= period) sum -= vals[i - period] || 0;
      if (i >= period) out[i] = sum / period;
    }
    return out;
  }
  // wilder（alpha=1/period，与 pandas ewm(com=period-1) 等价）/ ema（alpha=2/(period+1)）
  const a = (m === "ema") ? 2 / (period + 1) : 1 / period;
  let avg, seen = 0;
  for (let i = 1; i < n; i++) {
    const v = vals[i] || 0;
    avg = (avg === undefined) ? v : (1 - a) * avg + a * v;
    seen++;
    if (seen >= period) out[i] = avg;
  }
  return out;
}

/**
 * RSI 主体：涨跌幅 → 平滑（独立） → RS → RSI
 * @param closes  收盘价序列
 * @param period  RSI 周期（同时决定默认平滑周期）
 * @param method 平滑方式：wilder(默认) | sma | ema | none
 * @param smoothPeriod 平滑周期，留空/<=0 时跟随 RSI 周期（保持历史行为）
 */
function rsiSeries(closes, period, method, smoothPeriod) {
  const n = closes.length;
  const out = new Array(n).fill(null);
  if (n < 2 || period <= 0) return out;
  const sp = (smoothPeriod && smoothPeriod > 0) ? smoothPeriod : period;

  // 1) 主体：涨跌幅序列（第 0 项无前值，记 0）
  const gains = new Array(n).fill(0), losses = new Array(n).fill(0);
  for (let i = 1; i < n; i++) {
    const d = (closes[i] - closes[i - 1]) || 0;
    gains[i] = Math.max(d, 0);
    losses[i] = Math.max(-d, 0);
  }
  // 2) 平滑（独立环节，可单独配置方式与周期，不影响上面主体计算）
  const avgG = smoothSeries(gains, sp, method);
  const avgL = smoothSeries(losses, sp, method);
  // 3) RSI 公式
  for (let i = 1; i < n; i++) {
    if (avgG[i] == null || avgL[i] == null) continue;
    out[i] = (avgL[i] === 0) ? 100 : 100 - 100 / (1 + avgG[i] / avgL[i]);
  }
  return out;
}

/** 简单滚动均线（null 补齐） */
function rollMA(vals, period) {
  const out = new Array(vals.length).fill(null);
  let sum = 0;
  for (let i = 0; i < vals.length; i++) {
    sum += vals[i];
    if (i >= period) sum -= vals[i - period];
    if (i >= period - 1) out[i] = sum / period;
  }
  return out;
}

/* ================= 全局状态 ================= */
const S = {
  serveMode: false,     // 后端 API 是否可用（在线模式）
  funds: [],            // 后端返回的基金配置
  codes: [],            // 可用标的（含名称）
  code: null,           // 当前选中
  bt: null,             // 当前回测 JSON
  sig: null,            // 当前信号 JSON
  strategyId: null,     // 当前标注策略
  editingCode: null,    // 正在编辑的基金编码（null=新增）
  charts: {},
  period: "week",       // 主图与 RSI 副图周期："day" | "week"（默认周K，与信号口径一致）
  rsiCfg: null,         // RSI 参数（日/周各自独立），见 defaultRsiCfg()
};

/* ---------- RSI 参数配置（渲染层，可按日/周分别保存） ---------- */
const RSI_LINE_COLORS = ["#2f6fed", "#7a5af8", "#c27803"];         // 蓝 / 紫 / 橙
const RSI_LINE_TYPES = ["solid", "solid", "solid"];                // 三条曲线均为实线，靠颜色区分
const SMOOTH_METHODS = [
  { v: "wilder", t: "Wilder（默认）" },
  { v: "sma", t: "SMA 简单均线" },
  { v: "ema", t: "EMA 指数均线" },
  { v: "none", t: "不平滑" },
];

/** 默认配置：周线三条线全开（含新增 RSI24），日线默认仅第一条，保持默认行为不变 */
function defaultRsiCfg() {
  return {
    // 周K：阈值 null = 跟随该标的的信号参数（932305 为 45/65，515080 为 45/60）
    week: { lines: [{ p: 14, on: true }, { p: 24, on: true }, { p: 6, on: true }],
            method: "wilder", sp: null, buy: null, sell: null },
    // 日K：日线噪声大，默认用更极端的 30/70（与周K 明显区分，可自行改）
    day: { lines: [{ p: 14, on: true }, { p: 24, on: false }, { p: 6, on: false }],
           method: "wilder", sp: null, buy: 30, sell: 70 },
  };
}

/** 当前周期的 RSI 配置 */
function rsiCfg() {
  if (!S.rsiCfg) S.rsiCfg = defaultRsiCfg();
  return S.rsiCfg[S.period] || S.rsiCfg.week;
}

/** 当前周期生效的买卖阈值：未自定义时，周K 取标的信号参数，日K 取 30/70 */
function effThresholds(cfg) {
  const p = (S.bt && S.bt.params) || {};
  const isWeek = S.period === "week";
  const defBuy = isWeek ? (p.rsi_buy != null ? p.rsi_buy : 45) : 30;
  const defSell = isWeek ? (p.rsi_sell != null ? p.rsi_sell : 65) : 70;
  return {
    buy: cfg.buy != null ? cfg.buy : defBuy,
    sell: cfg.sell != null ? cfg.sell : defSell,
    custom: cfg.buy != null || cfg.sell != null,
  };
}

/* ================= 初始化 ================= */
async function init() {
  S.rsiCfg = defaultRsiCfg();
  await detectMode();
  await buildTabs();
  bindEvents();
  renderPeriodSegs();          // 日K/周K 切换标签
  if (S.codes.length) await selectCode(S.codes[0].code);
  else $("emptyState").hidden = false;
}

async function detectMode() {
  try {
    const p = await fetchJSON(apiUrl("/api/ping"));
    if (p && p.ok) {
      S.serveMode = true;
      $("modeBadge").textContent = "已连接接口";
      $("modeBadge").className = "badge badge-serve";
      $("btnBacktest").hidden = false;
      $("btnFunds").hidden = false;
      $("btnRefresh").hidden = false;
      try {
        const f = await fetchJSON(apiUrl("/api/funds"));
        S.funds = (f.funds || []).filter((x) => x.enabled !== false);
      } catch (e) { /* ignore */ }
    }
  } catch (e) { /* 后端不可用 → 静态回退模式 */ }
}

async function buildTabs() {
  const found = [];
  if (S.serveMode) {
    // 接口模式：/api/codes 返回可用标的（含是否已有回测结果）
    try {
      const r = await fetchJSON(apiUrl("/api/codes"));
      for (const c of r.codes || []) found.push({ code: c.code, name: c.name });
    } catch (e) { /* ignore */ }
  } else {
    try {
      const s = await fetchJSON("output/summary.json");
      for (const r of s.rows || []) {
        if (!found.find((x) => x.code === r.code)) found.push({ code: r.code, name: r.name });
      }
    } catch (e) { /* ignore */ }
  }
  // 基金配置补充（接口模式下后端返回的已启用标的）
  for (const f of S.funds) {
    if (!found.find((x) => x.code === f.code)) found.push({ code: f.code, name: f.name });
  }
  // 兜底（静态模式下尝试已知标的）
  for (const c of ["932305", "515080", "512890"]) {
    if (!found.find((x) => x.code === c)) {
      try {
        const b = await fetchJSON(`output/${c}_backtest.json`);
        if (b && b.strategies) found.push({ code: c, name: b.name || c });
      } catch (e) { /* ignore */ }
    }
  }
  S.codes = found;
}

/* ================= 标的切换 ================= */
async function selectCode(code) {
  S.code = code;
  document.querySelectorAll(".fund-tab").forEach((el) =>
    el.classList.toggle("active", el.dataset.code === code));
  $("emptyState").hidden = true;
  $("mainContent").hidden = true;
  toast(`加载 ${code} 回测数据...`);
  try {
    // 接口优先：GET /api/backtest/{code}；后端不可用时回退 output/*.json
    S.bt = await fetchData(`/api/backtest/${code}`, `output/${code}_backtest.json`);
  } catch (e) {
    S.bt = null;
  }
  try {
    // 接口优先：GET /api/signal/{code}（后端默认读缓存，?force=1 实时重算）
    S.sig = await fetchData(`/api/signal/${code}`, `output/${code}_signal.json`);
  } catch (e) {
    S.sig = null;
    if (S.serveMode) {  // 缓存缺失时实时计算
      try { S.sig = await fetchJSON(apiUrl(`/api/signal/${code}?force=1`)); } catch (e2) { /* ignore */ }
    }
  }
  if (!S.bt && !S.sig) {
    $("emptyState").hidden = false;
    $("emptyTip").innerHTML = S.serveMode
      ? `${code} 暂无回测结果，点击右上角「立即回测」生成。`
      : `${code} 暂无回测结果。请运行 <code>python run.py backtest --code ${code}</code> 生成。`;
    renderSignal(null);
    return;
  }
  $("mainContent").hidden = false;
  renderTabs();
  renderSignal(S.sig);
  if (S.bt && S.bt.strategies) {
    S.strategyId = S.strategyId && S.bt.strategies.find((x) => x.id === S.strategyId)
      ? S.strategyId : (S.bt.strategies[0] && S.bt.strategies[0].id);
    $("btStart").value = S.bt.start || "2022-01-01";
    $("btMeta").textContent =
      `${S.bt.start || ""} ~ ${S.bt.end || ""} · 数据源 ${S.bt.provider || "--"} · 计算于 ${S.bt.computed_at || "--"}`;
    // 标的 TTM 股息率（新增指标，与策略无关的标的属性）
    const dy = calcTtmDividendYield(S.bt);
    $("btYield").textContent = dy != null
      ? `股息率(TTM): ${(dy * 100).toFixed(2)}%`
      : (S.bt.dividends && S.bt.dividends.length ? "股息率(TTM): --" : "股息率(TTM): 无分红数据");
    renderStrategySelect();
    renderMetricCards();
    renderPeriodSegs();       // 周期标签（含当前参数摘要）
    renderRsiSettings();      // RSI 参数设置项（按当前周期载入）
    renderBollSettings();     // BOLL 参数设置项（按当前周期载入）
    renderKline();            // 首屏核心：仅渲染默认展开的 K 线图
    refreshRenderedPanels();  // 已展开过的懒加载面板随标的重绘（保持数据新鲜）
  }
}

function renderTabs() {
  const nav = $("fundTabs");
  nav.innerHTML = "";
  for (const c of S.codes) {
    const el = document.createElement("button");
    el.className = "fund-tab" + (c.code === S.code ? " active" : "");
    el.dataset.code = c.code;
    el.innerHTML = `<span>${c.name}</span><span class="code">${c.code}</span>`;
    el.onclick = () => { if (S.code !== c.code) selectCode(c.code); };
    nav.appendChild(el);
  }
}

/* ================= 信号横幅 ================= */
function renderSignal(sig) {
  const b = $("signalBanner");
  if (!sig || sig.error) {
    b.hidden = !sig;
    if (sig && sig.error) {
      b.hidden = false;
      b.className = "signal-banner signal-hold";
      $("sigState").textContent = "--";
      $("sigAction").textContent = "信号获取失败";
      $("sigNote").textContent = sig.error;
    }
    return;
  }
  b.hidden = false;
  const cls = sig.action === "买入" ? "signal-buy" : sig.action === "卖出" ? "signal-sell" : "signal-hold";
  b.className = "signal-banner " + cls;
  $("sigState").textContent = `当前${sig.state}`;
  $("sigAction").textContent = sig.action === "观望" ? "持币观望" : `建议${sig.action}`;
  $("sigNote").textContent = sig.note || "";
  $("sigRsi").textContent = `周RSI: ${sig.rsi != null ? sig.rsi.toFixed(1) : "--"}`;
  const dy = calcTtmDividendYield(S.bt);
  $("sigDiv").textContent = dy != null
    ? `股息率(TTM): ${(dy * 100).toFixed(2)}%`
    : (S.bt && S.bt.dividends && S.bt.dividends.length ? "股息率(TTM): --" : "股息率(TTM): 无分红数据");
  $("sigWeek").textContent = `信号周: ${sig.week_end || "--"}`;
  $("sigExec").textContent = sig.next_exec_date
    ? `执行日: ${sig.next_exec_date}（${sig.exec_note || "开盘执行"}）` : (sig.exec_note || "");
  $("sigProvider").textContent = `数据源: ${sig.provider || "--"}`;
  $("sigTime").textContent = `计算于 ${sig.computed_at || "--"}`;
  $("sigStale").hidden = !sig.stale;
  // 建议金额
  const amt = $("sigAmount");
  if (sig.suggested_amount != null) {
    let txt = `建议${sig.action} ¥${Math.round(sig.suggested_amount).toLocaleString("zh-CN")}`;
    if (sig.multiplier && sig.multiplier > 1) txt += `（×${sig.multiplier.toFixed(2)}）`;
    if (sig.over_position) txt += " ⚠超过仓位金额";
    amt.textContent = txt;
    amt.className = "sig-amount" + (sig.over_position ? " warn" : "");
  } else {
    amt.textContent = "";
    amt.className = "sig-amount";
  }
}

/* ================= 面板折叠 + 懒加载（优化首屏加载） ================= */
/* 默认只展开核心面板；其余面板首次展开时才渲染对应图表/请求数据 */
const PANEL_LAZY = {
  yield: renderYieldPanel,
  rsi: renderRsi,
  boll: renderBoll,
  equity: renderEquity,
  trades: renderTrades,
};
const _panelRendered = {};   // 已懒渲染过的面板 id（展开后不再重复创建，但随标的切换刷新）

function bindPanelToggles() {
  document.querySelectorAll(".panel[data-collapsible]").forEach((panel) => {
    const head = panel.querySelector(".panel-head");
    head.addEventListener("click", (e) => {
      if (e.target.closest("button, input, select, label")) return;  // 工具栏交互不触发折叠
      togglePanel(panel.id);
    });
    head.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") { e.preventDefault(); togglePanel(panel.id); }
    });
  });
}

function togglePanel(id) {
  const panel = document.getElementById(id);
  if (!panel) return;
  const willCollapse = !panel.classList.contains("collapsed");
  panel.classList.toggle("collapsed", willCollapse);
  const head = panel.querySelector(".panel-head");
  if (head) head.setAttribute("aria-expanded", String(!willCollapse));
  if (willCollapse) return;   // 折叠：仅隐藏内容
  // 展开：首次展开才执行懒渲染
  const lazy = panel.dataset.lazy;
  if (lazy && !_panelRendered[id] && PANEL_LAZY[lazy]) {
    _panelRendered[id] = true;
    PANEL_LAZY[lazy]();
  }
  // 容器从隐藏恢复后，面板内已初始化的 echarts 实例重算尺寸
  Object.values(S.charts).forEach((c) => { try { c && c.resize(); } catch (err) { /* ignore */ } });
}

/** 切换标的后，重绘已展开过的懒加载面板，保持内容与当前标的一致 */
function refreshRenderedPanels() {
  Object.keys(_panelRendered).forEach((id) => {
    const panel = document.getElementById(id);
    if (panel && !panel.classList.contains("collapsed") && PANEL_LAZY[panel.dataset.lazy]) {
      PANEL_LAZY[panel.dataset.lazy]();
    }
  });
}

/* ---------- BOLL 布林带参数（渲染层，按日/周独立保存） ---------- */
function defaultBollCfg() {
  return { week: { period: 20, k: 2 }, day: { period: 20, k: 2 } };
}
function bollCfg() {
  if (!S.bollCfg) S.bollCfg = defaultBollCfg();
  return S.bollCfg[S.period] || S.bollCfg.week;
}

/**
 * BOLL 布林带：中轨 = period 简单均线，上/下轨 = 中轨 ± k×总体标准差（与报告 BOLL(20,2) 口径一致）
 */
function bollSeries(closes, period, k) {
  const n = closes.length;
  const mid = rollMA(closes, period);
  const upper = new Array(n).fill(null), lower = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    if (mid[i] == null) continue;
    let m = 0, v = 0;
    for (let j = i - period + 1; j <= i; j++) m += closes[j];
    m /= period;
    for (let j = i - period + 1; j <= i; j++) v += (closes[j] - m) ** 2;
    const sd = Math.sqrt(v / period);          // 总体标准差（ddof=0）
    upper[i] = m + k * sd;
    lower[i] = m - k * sd;
  }
  return { mid, upper, lower };
}

/* ================= 周期切换（日K/周K）与 RSI 参数设置 ================= */
/** 渲染多个同步的 日K/周K Tab（主图 / RSI 副图 / BOLL 各一处） */
function renderPeriodSegs() {
  const html = [["day", "日K"], ["week", "周K"]].map(([p, t]) =>
    `<button type="button" class="seg-btn${S.period === p ? " active" : ""}" data-period="${p}">${t}</button>`
  ).join("");
  for (const id of ["periodSegKline", "periodSegRsi", "periodSegBoll"]) {
    const el = $(id);
    if (!el) continue;
    el.innerHTML = html;
    el.querySelectorAll(".seg-btn").forEach((b) => { b.onclick = () => setPeriod(b.dataset.period); });
  }
  const sum = $("rsiSummary");
  if (sum) {
    const cfg = rsiCfg();
    const on = cfg.lines.filter((l) => l.on);
    const spTxt = cfg.sp ? `平滑周期 ${cfg.sp}` : "平滑周期跟随曲线";
    const mTxt = (SMOOTH_METHODS.find((m) => m.v === cfg.method) || {}).t || cfg.method;
    const th = effThresholds(cfg);
    sum.textContent = `${S.period === "week" ? "周K" : "日K"} · ${on.length ? "RSI " + on.map((l) => l.p).join("/") : "未启用曲线"}`
      + ` · ${mTxt} · ${spTxt} · 阈值 ${th.buy}/${th.sell}`;
  }
  const bsum = $("bollSummary");
  if (bsum) {
    const b = bollCfg();
    bsum.textContent = `${S.period === "week" ? "周K" : "日K"} · BOLL(${b.period}, ${b.k})`;
  }
}

/** 切换周期：主图 / RSI / BOLL 同步重算，参数按周期独立 */
function setPeriod(p) {
  if (S.period === p || !S.bt) return;
  S.period = p;
  renderPeriodSegs();
  renderRsiSettings();                              // 载入该周期独立保存的 RSI 参数
  renderBollSettings();                             // 载入该周期独立保存的 BOLL 参数
  renderKline();                                    // 主图同步重算
  if (_panelRendered["panelRsi"]) renderRsi();      // RSI 面板若已展开则重算
  if (_panelRendered["panelBoll"]) renderBoll();    // BOLL 面板若已展开则重算
}

/** RSI 参数设置区（周期/开关/平滑方式与平滑周期），改动后实时重算 */
function renderRsiSettings() {
  const box = $("rsiSettings");
  if (!box) return;
  const cfg = rsiCfg();
  const isWeek = S.period === "week";
  const params = (S.bt && S.bt.params) || {};
  const th = effThresholds(cfg);
  const thTip = isWeek
    ? `默认跟随本标的信号参数 ${params.rsi_buy}/${params.rsi_sell}`
    : "日K 默认为 30/70（与周K 差异化）";
  const lines = cfg.lines.map((L, i) => `
    <label class="rs-line" title="第 ${i + 1} 条 RSI 曲线">
      <input type="checkbox" data-line="${i}" ${L.on ? "checked" : ""}>
      <span class="rs-dot" style="background:${RSI_LINE_COLORS[i]}"></span>
      RSI <input type="number" class="num-in" data-p="${i}" min="2" max="100" step="1" value="${L.p}">
    </label>`).join("");
  const opts = SMOOTH_METHODS.map((m) =>
    `<option value="${m.v}"${cfg.method === m.v ? " selected" : ""}>${m.t}</option>`).join("");
  box.innerHTML = `
    <div class="rs-row"><span class="rs-k">曲线</span>${lines}</div>
    <div class="rs-row">
      <span class="rs-k">平滑</span>
      <select id="rsiMethod" class="sel-in">${opts}</select>
      <label class="rs-inline">平滑周期
        <input type="number" id="rsiSmoothP" class="num-in" min="0" max="200" step="1"
               value="${cfg.sp || ""}" placeholder="跟随曲线周期">
      </label>
      <span class="meta-text">留空或 0 = 各曲线用自身周期</span>
    </div>
    <div class="rs-row">
      <span class="rs-k">阈值</span>
      <label class="rs-inline">买入
        <input type="number" id="rsiBuy" class="num-in" min="0" max="100" step="1" value="${th.buy}">
      </label>
      <label class="rs-inline">卖出
        <input type="number" id="rsiSell" class="num-in" min="0" max="100" step="1" value="${th.sell}">
      </label>
      <button type="button" id="rsiThReset" class="btn btn-mini" ${th.custom ? "" : "disabled"}
              title="${thTip}">恢复默认</button>
      <span class="meta-text">${thTip}${th.custom ? "（当前已自定义）" : ""}；日K/周K 各自独立保存</span>
    </div>`;
  box.querySelectorAll("input[data-line]").forEach((el) => {
    el.onchange = () => {
      cfg.lines[+el.dataset.line].on = el.checked;
      renderRsi(); renderPeriodSegs();
    };
  });
  box.querySelectorAll("input[data-p]").forEach((el) => {
    el.onchange = () => {
      let v = Math.round(Number(el.value));
      if (!isFinite(v) || v < 2) v = 2;
      if (v > 100) v = 100;
      el.value = v;
      cfg.lines[+el.dataset.p].p = v;
      renderRsi(); renderPeriodSegs();
    };
  });
  $("rsiMethod").onchange = (e) => { cfg.method = e.target.value; renderRsi(); renderPeriodSegs(); };
  $("rsiSmoothP").onchange = (e) => {
    const v = Number(e.target.value);
    cfg.sp = (isFinite(v) && v > 0) ? Math.round(v) : null;
    e.target.value = cfg.sp || "";
    renderRsi(); renderPeriodSegs();
  };
  const clampTh = (v) => {
    let x = Number(v);
    if (!isFinite(x)) return null;
    if (x < 0) x = 0;
    if (x > 100) x = 100;
    return Math.round(x * 10) / 10;
  };
  $("rsiBuy").onchange = (e) => {
    const v = clampTh(e.target.value);
    cfg.buy = v;
    e.target.value = cfg.buy != null ? cfg.buy : effThresholds(cfg).buy;
    renderRsi(); renderRsiSettings(); renderPeriodSegs();
  };
  $("rsiSell").onchange = (e) => {
    const v = clampTh(e.target.value);
    cfg.sell = v;
    e.target.value = cfg.sell != null ? cfg.sell : effThresholds(cfg).sell;
    renderRsi(); renderRsiSettings(); renderPeriodSegs();
  };
  $("rsiThReset").onclick = () => { cfg.buy = null; cfg.sell = null; renderRsiSettings(); renderRsi(); renderPeriodSegs(); };
}

/* ================= 策略选择 / 指标卡片 ================= */
function renderStrategySelect() {
  const sel = $("strategySelect");
  sel.innerHTML = "";
  for (const st of S.bt.strategies) {
    const o = document.createElement("option");
    o.value = st.id; o.textContent = st.name;
    sel.appendChild(o);
  }
  sel.value = S.strategyId;
}

function renderMetricCards() {
  const wrap = $("metricCards");
  wrap.innerHTML = "";
  let bestIdx = -1, bestRet = -Infinity;
  S.bt.strategies.forEach((st, i) => {
    const m = st.metrics || {};
    if (m.cumulative_return != null && m.cumulative_return > bestRet) { bestRet = m.cumulative_return; bestIdx = i; }
  });
  S.bt.strategies.forEach((st, i) => {
    const m = st.metrics || {};
    const card = document.createElement("div");
    card.className = "mcard" + (i === bestIdx ? " best" : "");
    const ret = m.cumulative_return;
    card.innerHTML = `
      <h3>${st.name}${i === bestIdx ? '<span class="mcard-best-tag">区间最优</span>' : ""}</h3>
      <div class="mgrid">
        <div class="mitem"><span class="k">累计收益</span>
          <span class="v ${upDownCls(ret)}">${pct(ret)}</span></div>
        <div class="mitem"><span class="k">年化收益</span>
          <span class="v ${upDownCls(m.ann_return)}">${pct(m.ann_return)}</span></div>
        <div class="mitem"><span class="k">最大回撤</span>
          <span class="v v-down">${m.max_drawdown != null ? (m.max_drawdown * 100).toFixed(2) + "%" : "--"}</span></div>
        <div class="mitem"><span class="k">夏普比率</span>
          <span class="v">${num(m.sharpe)}</span></div>
        <div class="mitem"><span class="k">卡玛比率</span>
          <span class="v">${num(m.calmar)}</span></div>
        <div class="mitem"><span class="k">平均仓位</span>
          <span class="v">${pct(m.avg_position)}</span></div>
      </div>`;
    card.onclick = () => { $("strategySelect").value = st.id; onStrategyChange(st.id); };
    wrap.appendChild(card);
  });
}

/* ================= 实时股息率汇总（新增面板） ================= */
const KIND_LABEL = { index: "指数", etf: "ETF", fund: "场外基金" };
const YIELD_SRC_LABEL = { csindex: "中证官网", dynamic: "动态TTM", local: "本地回测" };

/** 主股息率：滚动TTM(dy2) 优先，动态TTM 兜底 */
function mainYield(row) {
  if (row.dy2 != null) return row.dy2;
  if (row.ttm_dy != null) return row.ttm_dy;
  return null;
}

function yieldStatsHTML(s) {
  const cards = [];
  const avg = s.avg_dy2;
  const prem = avg != null ? avg - (s.rf_annual || 0.02) : null;
  cards.push({ k: "启用基金", v: `${s.total} 只`, sub: `有数据 ${s.with_yield} 只` });
  cards.push({ k: "平均滚动股息率", v: avg != null ? (avg * 100).toFixed(2) + "%" : "--",
    sub: prem != null ? `较无风险利率(${((s.rf_annual || 0.02) * 100).toFixed(0)}%)溢价 ${(prem * 100).toFixed(2)}%` : "" });
  cards.push({ k: "最高", v: s.max ? (s.max.dy * 100).toFixed(2) + "%" : "--", sub: s.max ? s.max.name : "" });
  cards.push({ k: "最低", v: s.min ? (s.min.dy * 100).toFixed(2) + "%" : "--", sub: s.min ? s.min.name : "" });
  return cards.map((c) => `
    <div class="ystat">
      <div class="ystat-k">${c.k}</div>
      <div class="ystat-v">${c.v}</div>
      ${c.sub ? `<div class="ystat-sub">${c.sub}</div>` : ""}
    </div>`).join("");
}

function yieldRowHTML(r) {
  const dy1 = r.dy1 != null ? (r.dy1 * 100).toFixed(2) + "%" : "--";
  const dy2 = mainYield(r);
  const dy2txt = dy2 != null ? `<span class="v ${upDownCls(dy2 - 0.02)}">${(dy2 * 100).toFixed(2)}%</span>` : "--";
  const pe = r.pe2 != null ? num(r.pe2, 2) : "--";
  const idx = r.index_code ? `<span class="mono">${r.index_code}</span>` : "--";
  // 获取失败时给出可读提示（多为官网接口间歇性断连），而非空白 "--"
  const err = r.error ? String(r.error) : "";
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const srcCell = r.source
    ? YIELD_SRC_LABEL[r.source]
    : (err ? `<span class="yield-err" title="${esc(err)}">⚠ 获取失败</span>` : "--");
  return `<tr${err ? ` title="${esc(err + "（可点右上角「刷新」重试）")}"` : ""}>
    <td>${r.name}<span class="td-code">${r.code}</span></td>
    <td>${KIND_LABEL[r.kind] || r.kind || "--"}</td>
    <td>${idx}</td>
    <td class="num">${dy1}</td>
    <td class="num">${dy2txt}</td>
    <td class="num">${pe}</td>
    <td>${r.date || "--"}</td>
    <td>${srcCell}</td>
  </tr>`;
}

async function renderYieldPanel(force) {
  const table = document.querySelector("#yieldTable tbody");
  table.innerHTML = `<tr><td colspan="8" style="color:#93a1b3">加载实时股息率中...</td></tr>`;
  $("yieldStats").innerHTML = "";
  $("yieldNote").textContent = "";
  try {
    if (S.serveMode) {
      const s = await fetchJSON(apiUrl("/api/yields" + (force ? "?force=1" : "")));
      $("yieldMeta").textContent =
        `数据源：中证指数官网估值（股息率1=静态 / 股息率2=近12个月滚动TTM），无官网数据时按分红动态计算 · 计算于 ${s.computed_at || "--"}`;
      $("btnYieldRefresh").hidden = false;
      $("yieldStats").innerHTML = yieldStatsHTML(s);
      table.innerHTML = (s.rows || []).map(yieldRowHTML).join("") ||
        `<tr><td colspan="8" style="color:#93a1b3">暂无基金配置</td></tr>`;
      $("yieldNote").innerHTML = s.avg_dy2 != null && s.avg_dy2 > (s.rf_annual || 0.02)
        ? `<span class="yield-note-hi">📌 当前红利组合平均滚动股息率 ${(s.avg_dy2 * 100).toFixed(2)}%，高于无风险利率 ${((s.rf_annual || 0.02) * 100).toFixed(0)}%，分红现金回报具备吸引力；股息率会随价格波动，请结合回测指标综合判断。</span>`
        : "当前红利组合股息率低于无风险利率，分红吸引力一般。";
    } else {
      // 静态模式：从本地回测 JSON 计算各标的 TTM 股息率（降级展示）
      const rows = [];
      for (const c of S.codes) {
        try {
          const b = await fetchData(`/api/backtest/${c.code}`, `output/${c.code}_backtest.json`);
          const dy = calcTtmDividendYield(b);
          rows.push({ name: c.name, code: c.code, kind: b.kind, index_code: null,
            dy1: null, dy2: null, ttm_dy: dy, date: b.end || "", source: "local" });
        } catch (e) { /* 无回测数据跳过 */ }
      }
      $("yieldMeta").textContent = "静态预览模式：仅展示本地回测数据的 TTM 股息率；启动 python run.py serve 后可获取中证官网实时股息率";
      $("btnYieldRefresh").hidden = true;
      const valid = rows.filter((r) => r.ttm_dy != null);
      const avg = valid.length ? valid.reduce((a, r) => a + r.ttm_dy, 0) / valid.length : null;
      $("yieldStats").innerHTML = [
        { k: "本地标的", v: `${rows.length} 只`, sub: `有股息率 ${valid.length} 只` },
        { k: "平均TTM股息率", v: avg != null ? (avg * 100).toFixed(2) + "%" : "--", sub: "基于本地回测分红数据" },
      ].map((c) => `<div class="ystat"><div class="ystat-k">${c.k}</div><div class="ystat-v">${c.v}</div>${c.sub ? `<div class="ystat-sub">${c.sub}</div>` : ""}</div>`).join("");
      table.innerHTML = rows.map(yieldRowHTML).join("") ||
        `<tr><td colspan="8" style="color:#93a1b3">暂无本地回测数据</td></tr>`;
      $("yieldNote").innerHTML = "💡 提示：启动 <code>python run.py serve</code> 后，本面板将自动切换为各基金跟踪指数的官方实时股息率。";
    }
  } catch (e) {
    table.innerHTML = `<tr><td colspan="8" style="color:#d93838">股息率加载失败：${e.message}</td></tr>`;
  }
}

function renderYieldPanelError(msg) {
  const table = document.querySelector("#yieldTable tbody");
  table.innerHTML = `<tr><td colspan="8" style="color:#d93838">${msg}</td></tr>`;
}

/* ================= 图表 ================= */
function ensureChart(id) {
  if (typeof echarts === "undefined") {
    const el = $(id);
    el.innerHTML = '<div class="chart-placeholder">ECharts 加载失败（检查网络后刷新页面）</div>';
    return null;
  }
  if (!S.charts[id]) S.charts[id] = echarts.init($(id));
  return S.charts[id];
}

function renderCharts() {
  renderKline();
  renderRsi();
  renderEquity();
}

function renderKline() {
  const c = ensureChart("chartKline");
  if (!c) return;
  const isWeek = S.period === "week";
  // K线展示实际盘面价（不做拆分抹平）；周K 由日线聚合 OHLCV
  const bars = isWeek ? toWeeklyBars(S.bt.daily || []) : (S.bt.daily || []);
  const dates = bars.map((r) => r[0]);
  const k = bars.map((r) => [r[1], r[4], r[3], r[2]]);   // [open, close, low, high]
  const vol = bars.map((r) => r[5]);
  const maPeriod = isWeek ? 50 : 250;                    // 周K 取 50 周 ≈ 250 交易日
  const maName = `MA${maPeriod}`;
  const ma = rollMA(bars.map((r) => r[4]), maPeriod);
  const up = bars.map((r) => r[4] >= r[1]);

  const st = S.bt.strategies.find((x) => x.id === S.strategyId);
  const buys = [], sells = [];
  if (st) {
    // 周K 模式下把成交日期映射到所属周，才能落在周K坐标上
    const weekAnchor = new Map();
    if (isWeek) bars.forEach((b) => weekAnchor.set(isoWeekKey(b[0]), b[0]));
    for (const t of st.trades || []) {
      // ECharts 散点系列数据项须为 {value:[x,y]}（category 轴 x 用日期字符串匹配），
      // 自定义 coord 字段不会被渲染——买卖点位此前不显示即因此。
      const x = isWeek ? (weekAnchor.get(isoWeekKey(t.date)) || t.date) : t.date;
      const pt = { value: [x, t.price], reason: t.reason || "" };
      (t.side === "买入" ? buys : sells).push(pt);
    }
  }

  c.setOption({
    animation: false,
    backgroundColor: "transparent",
    tooltip: { trigger: "axis", axisPointer: { type: "cross" } },
    legend: { top: 0, data: [maName, "买入", "卖出"] },
    grid: [
      { left: 64, right: 20, top: 34, height: "58%" },
      { left: 64, right: 20, top: "76%", height: "14%" },
    ],
    xAxis: [
      { type: "category", data: dates, boundaryGap: true,
        axisLine: { lineStyle: { color: "#c6d2e2" } }, axisLabel: { color: "#93a1b3" } },
      { type: "category", gridIndex: 1, data: dates, axisLabel: { show: false }, axisTick: { show: false } },
    ],
    yAxis: [
      { scale: true, axisLabel: { color: "#93a1b3" }, splitLine: { lineStyle: { color: "#eef2f7" } } },
      { gridIndex: 1, axisLabel: { show: false }, splitLine: { show: false } },
    ],
    dataZoom: [
      { type: "inside", xAxisIndex: [0, 1], start: 55, end: 100 },
      { type: "slider", xAxisIndex: [0, 1], bottom: 2, height: 16, borderColor: "#e3e8ef" },
    ],
    series: [
      {
        name: "K线", type: "candlestick", data: k,
        itemStyle: { color: UP, color0: DOWN, borderColor: UP, borderColor0: DOWN },
      },
      { name: maName, type: "line", data: ma, smooth: true, showSymbol: false,
        lineStyle: { color: "#c27803", width: 1.5 } },
      {
        name: "成交量", type: "bar", xAxisIndex: 1, yAxisIndex: 1, data: vol.map((v, i) => ({
          value: v, itemStyle: { color: up[i] ? "rgba(217,56,56,.45)" : "rgba(12,150,104,.45)" },
        })),
      },
      {
        name: "买入", type: "scatter", data: buys, symbol: "triangle", symbolSize: 11,
        itemStyle: { color: UP }, z: 5,
        tooltip: { formatter: (p) => `${p.data.value[0]} 买入<br/>价 ${p.data.value[1]}<br/>${p.data.reason || ""}` },
      },
      {
        name: "卖出", type: "scatter", data: sells, symbol: "path://M0,0L10,0L5,8Z", symbolSize: 11,
        itemStyle: { color: DOWN }, z: 5,
        tooltip: { formatter: (p) => `${p.data.value[0]} 卖出<br/>价 ${p.data.value[1]}<br/>${p.data.reason || ""}` },
      },
    ],
  }, true);
}

function renderRsi() {
  const c = ensureChart("chartRsi");
  if (!c) return;
  const isWeek = S.period === "week";
  const unit = isWeek ? "周" : "日";
  // 拆分抹平仅用于指标计算（避免份额拆分造成的假缺口干扰 RSI）
  const adj = splitAdjustRows(S.bt.daily || [], S.bt.splits);
  const src = isWeek ? toWeekly(adj) : adj.map((r) => ({ date: r[0], close: r[4] }));
  const closes = src.map((x) => x.close);
  const dates = src.map((x) => x.date);
  // 买卖阈值：日K/周K 各自独立（周K 默认跟随标的信号参数，日K 默认 30/70）
  const th = effThresholds(rsiCfg());
  const buy = th.buy, sell = th.sell;
  const cfg = rsiCfg();

  const series = [];
  cfg.lines.forEach((L, i) => {
    if (!L.on) return;
    series.push({
      name: `${unit}RSI(${L.p})`, type: "line",
      data: rsiSeries(closes, L.p, cfg.method, cfg.sp),
      showSymbol: false,
      lineStyle: { color: RSI_LINE_COLORS[i], width: i === 0 ? 1.8 : 1.3,
                   type: RSI_LINE_TYPES[i] || "solid" },
      itemStyle: { color: RSI_LINE_COLORS[i] },
      // 主曲线（第 0 条）加淡色填充，便于区分
      areaStyle: i === 0 ? { color: "rgba(47,111,237,.08)" } : undefined,
    });
  });
  // 阈值辅助系列：买卖阈值虚线与中间区间是公共参考（与显示哪条曲线无关），
  // 单独挂在一个不可见 series 上，保证即使 RSI(14) 关闭、只剩 RSI(6)/RSI(24) 也始终显示。
  series.push({
    name: "", type: "line", data: dates.map(() => null),
    showSymbol: false, silent: true, legendHoverLink: false,
    lineStyle: { width: 0 }, itemStyle: { color: "transparent" },
    tooltip: { show: false },
    markLine: {
      symbol: "none", silent: true,
      data: [
        { yAxis: buy, lineStyle: { color: UP, type: "dashed" },
          label: { formatter: `买入阈值 ${buy}`, position: "insideStartTop", color: UP } },
        { yAxis: sell, lineStyle: { color: DOWN, type: "dashed" },
          label: { formatter: `卖出阈值 ${sell}`, position: "insideEndBottom", color: DOWN } },
        { yAxis: 50, lineStyle: { color: "#c6d2e2" }, label: { show: false } },
      ],
    },
    markArea: {
      silent: true,
      itemStyle: { color: "rgba(147,161,179,.10)" },
      data: [[{ yAxis: buy }, { yAxis: sell }]],
    },
  });
  c.setOption({
    animation: false,
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" },
    legend: { top: 0, data: series.filter((s) => s.name).map((s) => s.name), textStyle: { fontSize: 12 } },
    grid: { left: 48, right: 20, top: 34, bottom: 48 },
    xAxis: { type: "category", data: dates,
      axisLine: { lineStyle: { color: "#c6d2e2" } }, axisLabel: { color: "#93a1b3" } },
    yAxis: { min: 0, max: 100, axisLabel: { color: "#93a1b3" },
      splitLine: { lineStyle: { color: "#eef2f7" } } },
    dataZoom: [
      { type: "inside", xAxisIndex: 0, start: 55, end: 100 },   // 图内滚轮缩放 / 按住拖拽平移
      { type: "slider", xAxisIndex: 0, bottom: 4, height: 16, borderColor: "#e3e8ef", start: 55, end: 100 },
    ],
    series,
  }, true);
}

/* ================= BOLL 布林带（价格通道） ================= */
function renderBollSettings() {
  const box = $("bollSettings");
  if (!box) return;
  const cfg = bollCfg();
  box.innerHTML = `
    <div class="rs-row">
      <span class="rs-k">参数</span>
      <label class="rs-inline">周期
        <input type="number" id="bollPeriod" class="num-in" min="2" max="250" step="1" value="${cfg.period}">
      </label>
      <label class="rs-inline">倍数 K
        <input type="number" id="bollK" class="num-in" min="0.1" max="5" step="0.1" value="${cfg.k}">
      </label>
      <span class="meta-text">中轨 = ${cfg.period} 周期均线，上/下轨 = 中轨 ± K×标准差；日K/周K 各自独立保存</span>
    </div>`;
  $("bollPeriod").onchange = (e) => {
    let v = Math.round(Number(e.target.value));
    if (!isFinite(v) || v < 2) v = 2;
    if (v > 250) v = 250;
    e.target.value = v;
    cfg.period = v;
    renderBoll(); renderPeriodSegs();
  };
  $("bollK").onchange = (e) => {
    let v = Number(e.target.value);
    if (!isFinite(v) || v < 0.1) v = 0.1;
    if (v > 5) v = 5;
    v = Math.round(v * 10) / 10;
    e.target.value = v;
    cfg.k = v;
    renderBoll(); renderPeriodSegs();
  };
}

function renderBoll() {
  const c = ensureChart("chartBoll");
  if (!c) return;
  const isWeek = S.period === "week";
  // 布林带与 RSI 同为指标：用拆分抹平序列（避免份额拆分假缺口），按当前周期取收盘价
  const adj = splitAdjustRows(S.bt.daily || [], S.bt.splits);
  const src = isWeek ? toWeekly(adj) : adj.map((r) => ({ date: r[0], close: r[4] }));
  const dates = src.map((x) => x.date);
  const closes = src.map((x) => x.close);
  const cfg = bollCfg();
  const { mid, upper, lower } = bollSeries(closes, cfg.period, cfg.k);
  const priceColor = "#5c6b7f", midColor = "#2f6fed", bandColor = "#c27803";

  c.setOption({
    animation: false,
    backgroundColor: "transparent",
    tooltip: { trigger: "axis" },
    legend: { top: 0, data: ["收盘价", `中轨MA${cfg.period}`, "上轨", "下轨"], textStyle: { fontSize: 12 } },
    grid: { left: 60, right: 20, top: 34, bottom: 48 },
    xAxis: { type: "category", data: dates,
      axisLine: { lineStyle: { color: "#c6d2e2" } }, axisLabel: { color: "#93a1b3" } },
    yAxis: { scale: true, axisLabel: { color: "#93a1b3" },
      splitLine: { lineStyle: { color: "#eef2f7" } } },
    dataZoom: [
      { type: "inside", xAxisIndex: 0, start: 55, end: 100 },   // 图内滚轮缩放 / 按住拖拽平移
      { type: "slider", xAxisIndex: 0, bottom: 4, height: 16, borderColor: "#e3e8ef", start: 55, end: 100 },
    ],
    series: [
      {
        name: "收盘价", type: "line", data: closes, showSymbol: false,
        lineStyle: { color: priceColor, width: 1.2 },
      },
      {
        name: `中轨MA${cfg.period}`, type: "line", data: mid, showSymbol: false,
        lineStyle: { color: midColor, width: 1.6 },
      },
      {
        name: "上轨", type: "line", data: upper, showSymbol: false,
        lineStyle: { color: bandColor, width: 1.2, type: "dashed" },
      },
      {
        name: "下轨", type: "line", data: lower, showSymbol: false,
        lineStyle: { color: bandColor, width: 1.2, type: "dashed" },
      },
    ],
  }, true);
}

function renderEquity() {
  const c = ensureChart("chartEquity");
  if (!c) return;
  const initCash = (S.bt.params || {}).init_cash || 1e6;
  const series = S.bt.strategies.map((st, i) => {
    const eq = st.equity_curve || [];
    return {
      name: st.name, type: "line", showSymbol: false, smooth: false,
      data: eq.map((r) => [r[0], +(r[1] / initCash).toFixed(4)]),
      lineStyle: { width: i === 0 ? 2.4 : 1.6, color: PALETTE[i % PALETTE.length] },
      itemStyle: { color: PALETTE[i % PALETTE.length] },
      emphasis: { focus: "series" },
    };
  });
  c.setOption({
    animation: false,
    backgroundColor: "transparent",
    tooltip: { trigger: "axis", valueFormatter: (v) => num(v) },
    legend: { top: 0, type: "scroll", textStyle: { fontSize: 12 } },
    grid: { left: 56, right: 20, top: 36, bottom: 48 },
    xAxis: { type: "time", axisLabel: { color: "#93a1b3" } },
    yAxis: { scale: true, axisLabel: { color: "#93a1b3", formatter: (v) => v.toFixed(1) },
      splitLine: { lineStyle: { color: "#eef2f7" } } },
    dataZoom: [{ type: "slider", bottom: 4, height: 16, borderColor: "#e3e8ef", start: 0, end: 100 }],
    series,
  }, true);
}

/* ================= 交易明细 ================= */
function renderTrades() {
  const st = S.bt.strategies.find((x) => x.id === S.strategyId);
  const tbody = document.querySelector("#tradesTable tbody");
  tbody.innerHTML = "";
  const trades = st ? (st.trades || []) : [];
  $("tradesTitle").textContent = `交易明细 · ${st ? st.name : ""}`;
  $("tradesCount").textContent = `共 ${trades.length} 笔`;
  for (const t of trades) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${t.date}</td>
      <td class="${t.side === "买入" ? "side-buy" : "side-sell"}">${t.side}</td>
      <td class="num">${num(t.price, 3)}</td>
      <td class="num">${num(t.shares, 0)}</td>
      <td class="num">${money(t.amount)}</td>
      <td class="num">${money(t.fee)}</td>
      <td class="reason">${t.reason || ""}</td>
      <td class="num">${money(t.equity)}</td>`;
    tbody.appendChild(tr);
  }
}

function onStrategyChange(id) {
  S.strategyId = id;
  if (S.bt && S.bt.strategies) {
    renderKline();
    // 交易明细面板已展开过则同步刷新
    if (_panelRendered["panelTrades"]) renderTrades();
  }
}

/* ================= serve 模式交互 ================= */
function bindEvents() {
  bindPanelToggles();
  $("strategySelect").onchange = (e) => onStrategyChange(e.target.value);
  $("btnBacktest").onclick = runBacktest;
  $("btnRefresh").onclick = refreshData;
  $("btnFunds").onclick = openFundModal;
  $("btnYieldRefresh").onclick = () => renderYieldPanel(true);
  $("fundModalClose").onclick = closeFundModal;
  $("fundModal").addEventListener("click", (e) => { if (e.target === $("fundModal")) closeFundModal(); });
  $("fundForm").onsubmit = submitFund;
  $("fundCancelBtn").onclick = resetFundForm;
  window.addEventListener("resize", () => {
    Object.values(S.charts).forEach((c) => c && c.resize());
  });
}

async function runBacktest() {
  if (!S.serveMode) return;
  const start = $("btStart").value || "2022-01-01";
  const end = $("btEnd").value || null;
  try {
    const r = await fetchJSON(apiUrl("/api/backtest"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: S.code, start, end }),
    });
    await pollJob(r.job_id, async (job) => {
      await selectCode(S.code);   // 重新拉取 output JSON
      toast(`${S.code} 回测完成`);
    });
  } catch (e) {
    toast("回测失败：" + e.message, true);
  }
}

async function refreshData() {
  if (!S.serveMode) return;
  try {
    const r = await fetchJSON(apiUrl("/api/refresh"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: S.code }),
    });
    await pollJob(r.job_id, async () => {
      toast("行情缓存已更新");
      await selectCode(S.code);
    });
  } catch (e) {
    toast("刷新失败：" + e.message, true);
  }
}

function pollJob(jobId, onDone) {
  return new Promise((resolve, reject) => {
    const bar = $("jobBar"), text = $("jobText");
    bar.hidden = false;
    const tick = async () => {
      let job;
      try {
        job = await fetchJSON(apiUrl(`/api/job/${jobId}`));
      } catch (e) {
        bar.hidden = true;
        reject(e);
        return;
      }
      text.textContent = job.progress || job.description || "执行中...";
      if (job.status === "done") {
        bar.hidden = true;
        await onDone(job);
        resolve();
      } else if (job.status === "error") {
        bar.hidden = true;
        toast("任务失败：" + (job.error || "").split("\n")[0], true);
        reject(new Error(job.error));
      } else {
        setTimeout(tick, 1000);
      }
    };
    tick();
  });
}

/* ---------- 基金管理 ---------- */
async function openFundModal() {
  $("fundModal").hidden = false;
  await loadFundTable();
}

function closeFundModal() { $("fundModal").hidden = true; }

async function loadFundTable() {
  const tbody = document.querySelector("#fundTable tbody");
  tbody.innerHTML = "<tr><td colspan='8' style='color:#93a1b3'>加载中...</td></tr>";
  try {
    const r = await fetchJSON(apiUrl("/api/funds"));
    S.funds = r.funds || [];
    tbody.innerHTML = "";
    for (const f of S.funds) {
      const tr = document.createElement("tr");
      const modeTxt = ({ none: "无", buy: "越买越多", sell: "越卖越多", both: "双向" })[f.mult_mode] || f.mult_mode;
      const posTxt = `¥${Math.round(f.position_amount).toLocaleString("zh-CN")} · ${Math.round(f.position_ratio * 100)}% · ×${f.mult_factor}` +
        (f.mult_mode !== "none" ? `(${modeTxt})` : "");
      tr.innerHTML = `
        <td>${f.code}</td><td>${f.name}</td>
        <td>${({ index: "指数", etf: "ETF", fund: "场外基金" })[f.kind] || f.kind}</td>
        <td class="num">${f.rsi_buy}</td><td class="num">${f.rsi_sell}</td>
        <td class="mono">${f.index_code || "--"}</td>
        <td class="pos">${posTxt}</td>
        <td>
          <button class="btn-link" data-edit="${f.code}">编辑</button>
          <button class="btn-danger-link" data-code="${f.code}">移除</button>
        </td>`;
      tbody.appendChild(tr);
    }
    tbody.querySelectorAll(".btn-danger-link").forEach((btn) => {
      btn.onclick = async () => {
        if (!confirm(`确认移除基金 ${btn.dataset.code}？`)) return;
        try {
          await fetchJSON(apiUrl(`/api/funds/${btn.dataset.code}`), { method: "DELETE" });
          toast("已移除");
          await loadFundTable();
          await buildTabs();
          renderTabs();
        } catch (e) { toast("移除失败：" + e.message, true); }
      };
    });
    tbody.querySelectorAll(".btn-link[data-edit]").forEach((btn) => {
      btn.onclick = () => openEditFund(btn.dataset.edit);
    });
  } catch (e) {
    tbody.innerHTML = `<tr><td colspan='8' style='color:#d93838'>加载失败：${e.message}</td></tr>`;
  }
}

function openEditFund(code) {
  const f = S.funds.find((x) => x.code === code);
  if (!f) return;
  S.editingCode = code;
  const form = $("fundForm");
  form.code.value = f.code;
  form.code.disabled = true;
  form.name.value = f.name || "";
  form.kind.value = f.kind || "index";
  form.rsi_buy.value = f.rsi_buy;
  form.rsi_sell.value = f.rsi_sell;
  form.index_code.value = f.index_code || "";
  form.position_amount.value = f.position_amount;
  form.position_ratio.value = Math.round((f.position_ratio || 1) * 100);
  form.mult_mode.value = f.mult_mode || "none";
  form.mult_factor.value = f.mult_factor;
  $("fundFormTitle").textContent = `编辑基金 ${code}`;
  $("fundSubmitBtn").textContent = "保存";
  $("fundCancelBtn").hidden = false;
}

function resetFundForm() {
  S.editingCode = null;
  const form = $("fundForm");
  form.reset();
  form.code.disabled = false;
  form.kind.value = "index";
  form.index_code.value = "";
  form.position_amount.value = 10000;
  form.position_ratio.value = 100;
  form.mult_mode.value = "none";
  form.mult_factor.value = 1;
  $("fundFormTitle").textContent = "新增基金";
  $("fundSubmitBtn").textContent = "添加";
  $("fundCancelBtn").hidden = true;
}

async function submitFund(e) {
  e.preventDefault();
  const btn = e.target.querySelector('button[type="submit"]');
  if (btn.disabled) return;            // 防止重复提交
  const fd = new FormData(e.target);
  const body = {
    code: fd.get("code").trim(), name: fd.get("name").trim() || undefined,
    kind: fd.get("kind"),
    index_code: (fd.get("index_code") || "").trim() || undefined,
    rsi_buy: Number(fd.get("rsi_buy")), rsi_sell: Number(fd.get("rsi_sell")),
    position_amount: Number(fd.get("position_amount")),
    position_ratio: Number(fd.get("position_ratio")) / 100,
    mult_mode: fd.get("mult_mode"),
    mult_factor: Number(fd.get("mult_factor")),
  };
  if (!S.editingCode && !/^\d{6}$/.test(body.code)) {
    toast("编码须为 6 位数字", true);
    return;
  }
  btn.disabled = true;
  try {
    if (S.editingCode) {
      // 编辑模式：编码不可改，其余字段走 PUT
      const patch = { ...body };
      delete patch.code;
      await fetchJSON(apiUrl(`/api/funds/${S.editingCode}`), {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      toast(`已保存 ${S.editingCode}`);
      resetFundForm();
    } else {
      await fetchJSON(apiUrl("/api/funds"), {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      toast(`已添加 ${body.code}`);
      resetFundForm();
    }
    await loadFundTable();
    await buildTabs();
    renderTabs();
  } catch (err) {
    toast((S.editingCode ? "保存" : "添加") + "失败：" + err.message, true);
  } finally {
    btn.disabled = false;
  }
}

/* ================= 启动 ================= */
window.addEventListener("DOMContentLoaded", init);
