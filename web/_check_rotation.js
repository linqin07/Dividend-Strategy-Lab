
"use strict";
/* ================= 工具 ================= */
const $ = (id) => document.getElementById(id);
function fmtPct(x, d) { return (x == null || !isFinite(x)) ? "--" : (x * 100).toFixed(d == null ? 2 : d) + "%"; }
function fmtNum(x, d) { return (x == null || !isFinite(x)) ? "--" : x.toFixed(d == null ? 2 : d); }

/* 固定种子伪随机：模拟兜底数据可复现 */
let _seed = 20260830;
function srand() {
  _seed |= 0; _seed = (_seed + 0x6D2B79F5) | 0;
  let t = Math.imul(_seed ^ (_seed >>> 15), 1 | _seed);
  t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}
function randn() {
  let u = 0, v = 0;
  while (u === 0) u = srand();
  while (v === 0) v = srand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

/* ================= 一、数据层 ================= */
/* 模拟兜底序列：创业板先强后熊再复苏、红利稳步，保证四档信号均可演示 */
function genDates(from, to) {
  const out = [], d = new Date(from), end = new Date(to);
  while (d <= end) {
    const w = d.getDay();
    if (w !== 0 && w !== 6) out.push(d.toISOString().slice(0, 10));
    d.setDate(d.getDate() + 1);
  }
  return out;
}
function genSeries() {
  _seed = 20260830;
  const dates = genDates("2021-09-22", "2026-09-18");
  const n = dates.length;
  const growth = new Array(n), dividend = new Array(n);
  growth[0] = dividend[0] = 1000;
  const SEG = [[0, 0.35, 0.30], [0.35, 0.62, -0.75], [0.62, 0.85, 0.55], [0.85, 1.0, -0.35]];
  const annG = (i) => {
    const f = i / n;
    for (const [a, b, r] of SEG) if (f >= a && f < b) return Math.pow(1 + r, 1 / 252) - 1;
    return Math.pow(1.05, 1 / 252) - 1;
  };
  const annD = Math.pow(1.07, 1 / 252) - 1;
  const volG = 0.16 / Math.sqrt(252), volD = 0.05 / Math.sqrt(252);
  for (let i = 1; i < n; i++) {
    growth[i] = growth[i - 1] * (1 + annG(i) + volG * randn());
    dividend[i] = dividend[i - 1] * (1 + annD + volD * randn());
  }
  return { dates, growth, dividend, asof: "内置模拟", providers: null, stale: false, _mock: true };
}

/* 三级回退：FastAPI 接口 → 静态 output/rotation.json → 模拟序列 */
async function loadData() {
  const candidates = ["/api/rotation/data", "../output/rotation.json", "/output/rotation.json", "output/rotation.json"];
  for (let ci = 0; ci < candidates.length; ci++) {
    try {
      const r = await fetch(candidates[ci], { cache: "no-store" });
      if (!r.ok) continue;
      const j = await r.json();
      if (j && Array.isArray(j.dates) && Array.isArray(j.growth) && Array.isArray(j.dividend)
          && j.dates.length > 250) {
        const badge = $("srcBadge");
        const prov = j.providers ? `创业板=${j.providers.growth} 红利=${j.providers.dividend}` : "";
        if (ci === 0) {
          badge.textContent = `真实数据 · ${j.asof || ""} ${prov}`;
        } else {
          badge.textContent = `真实数据(静态缓存) · ${j.asof || ""} ${prov}`;
        }
        badge.classList.add(j.stale ? "stale" : "live");
        if (j.stale) badge.textContent = "⚠ " + badge.textContent + "（含缓存兜底）";
        return j;
      }
    } catch (e) { /* 尝试下一来源 */ }
  }
  const badge = $("srcBadge");
  badge.textContent = "数据源：内置模拟序列（未检测到后端/缓存数据）";
  return genSeries();
}

/* ================= 二、指标计算 ================= */
const W_MOM = 60;        // 动量/收益差窗口（约 3 个月）
const W_MA = 60;         // 牛熊分界均线
const W_MAF = 20;        // 快均线
const W_PCT = 750;       // 分位数滚动窗口（约 3 年）
const MIN_PCT = 250;     // 分位最少样本
const STRONG_MOM = 0.10; // 强趋势动量阈值
const PCT_HI = 0.90, PCT_LO = 0.10;
const COST = 0.001;      // 调仓成本（单次）

function sma(a, i, w) { if (i < w - 1) return null; let s = 0; for (let k = i - w + 1; k <= i; k++) s += a[k]; return s / w; }
function ret(a, i, w) { return i >= w ? a[i] / a[i - w] - 1 : null; }

function buildIndicators(g, d) {
  const n = g.length;
  const diff = new Array(n).fill(null), pct = new Array(n).fill(null);
  const bull = new Array(n).fill(false), strong = new Array(n).fill(false);
  const ma60 = new Array(n).fill(null), ma20 = new Array(n).fill(null);
  const momG = new Array(n).fill(null), momD = new Array(n).fill(null);
  for (let i = 0; i < n; i++) {
    const rg = ret(g, i, W_MOM), rd = ret(d, i, W_MOM);
    momG[i] = rg; momD[i] = rd;
    if (rg != null && rd != null) {
      diff[i] = rg - rd;
      const lo = Math.max(0, i - W_PCT + 1);
      const win = [];
      for (let k = lo; k <= i; k++) if (diff[k] != null) win.push(diff[k]);
      if (win.length >= MIN_PCT) {
        let cnt = 0;
        for (const v of win) if (v <= diff[i]) cnt++;
        pct[i] = cnt / win.length;
      }
    }
    ma60[i] = sma(g, i, W_MA); ma20[i] = sma(g, i, W_MAF);
    bull[i] = ma60[i] != null && ma20[i] != null && g[i] > ma60[i] && ma20[i] > ma60[i];
    strong[i] = bull[i] && rg != null && rg >= STRONG_MOM;
  }
  return { diff, pct, bull, strong, ma60, ma20, momG, momD };
}

/* ================= 三、四档仓位状态机 =================
 * 满仓红利100%（默认/止盈锁定/黄金补仓区）→ 趋势确认70% → 强趋势50%
 * 防抖设计：入场连续3日确认、回补后10日冷却、强趋势10%/5%滞回带、
 * 止盈状态锁定至分位回落至50%中枢（Wind 实测口径） */
const ENTRY_MOM = 0.05;      // 减仓入场动量门槛（60日）
const STRONG_IN = 0.10;      // 强趋势进入（→50%）
const STRONG_OUT = 0.05;     // 强趋势退出（←70%）
const CONFIRM_DAYS = 3;      // 入场连续确认天数
const COOLDOWN_DAYS = 10;    // 回补后冷却天数
const TP_ON = 0.90, TP_OFF = 0.50;

function runStrategy(ind) {
  const n = ind.diff.length;
  const w = new Array(n).fill(1.0);
  const switches = [];
  let tp = false, strong = false, wcur = 1.0, confirm = 0, cooldown = 0, bear = 0;
  for (let i = 0; i < n; i++) {
    const p = ind.pct[i], mom = ind.momG[i];
    if (p != null && p >= TP_ON) tp = true;
    else if (p != null && p <= TP_OFF) tp = false;
    if (!ind.bull[i]) strong = false;
    else if (mom != null && mom >= STRONG_IN) strong = true;
    else if (mom != null && mom < STRONG_OUT) strong = false;
    const entry = ind.bull[i] && mom != null && mom >= ENTRY_MOM;
    confirm = entry ? confirm + 1 : 0;
    bear = ind.bull[i] ? 0 : bear + 1;
    if (cooldown > 0) cooldown--;
    const prev = wcur;
    let reason = "";
    if (tp) {
      wcur = 1.0;
      if (prev < 1) reason = `收益差分位 ${fmtPct(p, 1)} ≥ 90%，分化极致 → 止盈回补红利至满仓（分位回落至50%中枢前锁定不再减仓）`;
    } else if (wcur === 1.0) {
      if (confirm >= CONFIRM_DAYS && cooldown === 0) {
        wcur = 0.7;
        reason = `趋势转多确认：收盘>MA60 + MA20>MA60 + 60日动量 ${fmtPct(mom, 1)} ≥5%，连续${CONFIRM_DAYS}日 → 红利减至70%`;
      }
    } else {
      if (bear >= 2) {
        wcur = 1.0; cooldown = COOLDOWN_DAYS;
        reason = `创业板连续2日失守多头结构 → 回补红利至满仓（冷却${COOLDOWN_DAYS}日防假突破反复）`;
      } else if (strong && wcur !== 0.5) {
        wcur = 0.5;
        reason = `强趋势：60日动量 ${fmtPct(mom, 1)} ≥10% → 红利减至50%`;
      } else if (!strong && wcur === 0.5) {
        wcur = 0.7;
        reason = "60日动量回落至 5% 以下 → 红利回升至70%";
      }
    }
    if (wcur !== prev && reason) switches.push({ idx: i, from: prev, to: wcur, pct: p, reason });
    w[i] = wcur;
  }
  return { w, switches };
}

/* 组合净值：红利仓位 w，剩余 (1-w) 配创业板；仓位变化日计成本 */
function computeNav(g, d, w) {
  const n = g.length;
  const nav = new Array(n).fill(1), navD = new Array(n).fill(1), navB = new Array(n).fill(1), navG = new Array(n).fill(1);
  for (let i = 1; i < n; i++) {
    const rg = g[i] / g[i - 1] - 1, rd = d[i] / d[i - 1] - 1;
    let r = w[i] * rd + (1 - w[i]) * rg;
    if (w[i] !== w[i - 1]) r -= COST;
    nav[i] = nav[i - 1] * (1 + r);
    navD[i] = navD[i - 1] * (1 + rd);
    navG[i] = navG[i - 1] * (1 + rg);
    navB[i] = navB[i - 1] * (1 + 0.5 * rd + 0.5 * rg);
  }
  return { nav, navD, navB, navG };
}

function perfStats(nav) {
  const n = nav.length, years = (n - 1) / 252;
  const ann = Math.pow(nav[n - 1] / nav[0], 1 / years) - 1;
  let peak = -1e18, mdd = 0;
  for (const v of nav) { peak = Math.max(peak, v); mdd = Math.max(mdd, (peak - v) / peak); }
  const rets = [];
  for (let i = 1; i < n; i++) rets.push(nav[i] / nav[i - 1] - 1);
  const mean = rets.reduce((a, b) => a + b, 0) / rets.length;
  const sd = Math.sqrt(rets.reduce((a, b) => a + (b - mean) ** 2, 0) / rets.length) * Math.sqrt(252);
  return { ann, mdd, sharpe: sd > 0 ? (ann - 0.02) / sd : 0 };
}

function computeAll(DATA) {
  const { dates, growth: g, dividend: d } = DATA;
  const n = dates.length;
  const ind = buildIndicators(g, d);
  const { w, switches } = runStrategy(ind);
  switches.forEach((s) => { s.date = dates[s.idx]; });
  const { nav, navD, navB, navG } = computeNav(g, d, w);
  const st = perfStats(nav), stD = perfStats(navD);
  // 减仓段胜率：每个 w<1 区间相对满仓红利的超额 > 0 记胜
  const segs = [];
  let start = 0;
  for (const s of switches) { segs.push([start, s.idx]); start = s.idx; }
  segs.push([start, n - 1]);
  const trimSegs = segs.filter(([a, b]) => w[Math.min(a + 1, n - 1)] < 1 && b - a > 5);
  const wins = trimSegs.filter(([a, b]) => (nav[b] / nav[a]) >= (navD[b] / navD[a])).length;
  const winRate = trimSegs.length ? wins / trimSegs.length : null;
  const lastSw = switches.length ? switches[switches.length - 1] : null;
  const holdDays = n - 1 - (lastSw ? lastSw.idx : 0);
  const i = n - 1;
  return {
    dates, g, d, ind, w, switches, nav, navD, navB, navG,
    ann: st.ann, mdd: st.mdd, sharpe: st.sharpe,
    annD: stD.ann, excess: st.ann - stD.ann,
    turns: switches.length, winRate,
    curW: w[i], curPct: ind.pct[i], curDiff: ind.diff[i],
    curBull: ind.bull[i], curStrong: ind.strong[i],
    ma60: ind.ma60[i], ma20: ind.ma20[i], momG: ind.momG[i], momD: ind.momD[i],
    lastSig: lastSw ? lastSw.date : "回测起点", holdDays,
    ratio: g[i] / d[i], curReason: lastSw ? lastSw.reason : "回测起点默认满仓红利",
  };
}

/* ================= 四、渲染 ================= */
let charts = {};
function ensureChart(id) { if (!charts[id]) charts[id] = echarts.init($(id)); return charts[id]; }
const UP = "#d93838", DOWN = "#0c9668", HOLD = "#c27803", BLUE = "#2f6fed", GRAY = "#93a1b3";

function renderDash(R, DATA) {
  const w = R.curW;
  $("curPos").textContent = Math.round(w * 100) + "%";
  const state = w >= 1 ? "full" : (w >= 0.7 ? "trim" : "attack");
  $("stateDot").className = "dot " + state;
  const stateTxt = w >= 1
    ? (R.curPct != null && R.curPct >= PCT_HI ? "💰 止盈回补 · 满仓红利"
      : (R.curPct != null && R.curPct <= PCT_LO ? "🛡 满仓红利 · 黄金补仓区" : "🛡 满仓红利 · 持有"))
    : (w >= 0.7 ? "⚖ 趋势转多 · 红利减至70%" : "⚔ 强趋势 · 红利减至50%");
  $("stateTxt").textContent = stateTxt;
  $("stateTxt").className = "state-txt " + state;
  $("posFill").style.left = ((w - 0.5) / 0.5 * 100) + "%";

  const freed = Math.round((1 - w) * 100);
  $("advice").textContent = w >= 1
    ? (R.curPct != null && R.curPct >= PCT_HI
      ? "操作参考：成长/红利分化已到极致，若前期减过仓，现在把创业板盈利落袋、回补红利至满仓。"
      : (R.curPct != null && R.curPct <= PCT_LO
        ? "操作参考：创业板深度熊市、红利极端跑赢。持仓不动吃股息；有新增资金（工资/分红到账）可在此区域加码红利，等待风格再平衡。"
        : "操作参考：创业板趋势未确认（熊多惯例），红利满仓持有，不追成长反弹。"))
    : `操作参考：创业板趋势${w <= 0.5 ? "强劲" : "转多"}确认，可将 ${freed}% 红利仓位换入创业板（或宽基成长）参与跷跷板上行段；分位触及 90% 立即回补。`;
  $("sigMeta").innerHTML = `上次仓位变化：<b>${R.lastSig}</b>　·　当前仓位已持续 <b>${R.holdDays}</b> 个交易日`;
  $("asofHint").textContent = DATA.asof && DATA.asof !== "内置模拟" ? `数据截至 ${R.dates[R.dates.length - 1]} · 生成于 ${DATA.asof}` : `数据截至 ${R.dates[R.dates.length - 1]}（模拟序列）`;

  const dm = [
    { k: "60日收益差(创-红)", v: fmtPct(R.curDiff), c: R.curDiff >= 0 ? "up" : "down", s: "创业板60日涨幅 − 红利60日涨幅" },
    { k: "收益差分位(近3年)", v: R.curPct != null ? fmtPct(R.curPct, 1) : "--", c: R.curPct != null && R.curPct >= 0.9 ? "up" : (R.curPct != null && R.curPct <= 0.1 ? "down" : "plain"), s: "≥90% 止盈回补 / ≤10% 黄金补仓区" },
    { k: "创业板 vs MA60", v: R.ma60 ? ((R.g[R.g.length - 1] > R.ma60 ? "+" : "") + fmtPct(R.g[R.g.length - 1] / R.ma60 - 1, 1)) : "--", c: R.g[R.g.length - 1] > R.ma60 ? "up" : "down", s: `MA60=${R.ma60 ? R.ma60.toFixed(0) : "--"} 牛熊分界` },
    { k: "创业板60日动量", v: fmtPct(R.momG), c: R.momG >= 0 ? "up" : "down", s: "≥10% 记强趋势" },
    { k: "红利60日动量", v: fmtPct(R.momD), c: R.momD >= 0 ? "up" : "down", s: "底仓自身走势" },
    { k: "创业板/红利 比值", v: fmtNum(R.ratio, 3), c: "plain", s: "历史摆动区间约 0.3~0.7" },
  ];
  $("dashMetrics").innerHTML = dm.map((m) =>
    `<div class="m-card"><div class="k">${m.k}</div><div class="v ${m.c}">${m.v}</div><div class="s">${m.s}</div></div>`).join("");

  const chk = (ok, txt) => `<li class="${ok ? "ok" : "no"}">${ok ? "✔" : "✘"} ${txt}</li>`;
  $("reasonList").innerHTML = [
    chk(R.g[R.g.length - 1] > R.ma60, `创业板收盘站上 MA60（<b>${R.g[R.g.length - 1].toFixed(0)}</b> vs <b>${R.ma60 ? R.ma60.toFixed(0) : "--"}</b>）`),
    chk(R.ma20 > R.ma60, `MA20 > MA60 均线多头（<b>${R.ma20 ? R.ma20.toFixed(0) : "--"}</b> vs <b>${R.ma60 ? R.ma60.toFixed(0) : "--"}</b>）`),
    chk(R.momG != null && R.momG >= ENTRY_MOM, `入场动量 ≥ 5%（当前 <b>${fmtPct(R.momG, 1)}</b>，需连续3日确认）`),
    chk(R.momG != null && R.momG >= STRONG_IN, `强趋势动量 ≥ 10% → 触发 50% 档（当前 <b>${fmtPct(R.momG, 1)}</b>）`),
    chk(R.curPct != null && R.curPct >= TP_ON, `收益差分位 ≥ 90% 止盈回补（当前 <b>${R.curPct != null ? fmtPct(R.curPct, 1) : "--"}</b>，回落至50%中枢解除）`),
    chk(R.curPct != null && R.curPct <= PCT_LO, `收益差分位 ≤ 10% 黄金补仓区（当前 <b>${R.curPct != null ? fmtPct(R.curPct, 1) : "--"}</b>）`),
  ].join("");
}

function renderDiffChart(R) {
  const c = ensureChart("chartDiff");
  const trimPts = [], addPts = [];
  for (const s of R.switches) {
    const p = { value: [s.date, R.ind.diff[s.idx]], name: s.to < 1 ? "减红利" : "回补红利" };
    (s.to < 1 ? trimPts : addPts).push(p);
  }
  c.setOption({
    animation: false, backgroundColor: "transparent",
    tooltip: { trigger: "axis" },
    legend: { top: 0, textStyle: { color: GRAY }, data: ["60日收益差", "分位数(右轴)", "减红利", "回补红利"] },
    grid: { left: 56, right: 52, top: 34, bottom: 44 },
    xAxis: { type: "category", data: R.dates, axisLabel: { color: GRAY }, axisLine: { lineStyle: { color: "#c6d2e2" } } },
    yAxis: [
      { scale: true, axisLabel: { color: GRAY, formatter: (v) => (v * 100).toFixed(0) + "%" }, splitLine: { lineStyle: { color: "#eef2f7" } } },
      { scale: false, min: 0, max: 1, axisLabel: { color: GRAY, formatter: (v) => (v * 100).toFixed(0) + "%" }, splitLine: { show: false } },
    ],
    dataZoom: [
      { type: "inside", xAxisIndex: 0, start: 0, end: 100 },
      { type: "slider", xAxisIndex: 0, bottom: 4, height: 16, borderColor: "#c6d2e2" },
    ],
    series: [
      {
        name: "60日收益差", type: "line", data: R.ind.diff, showSymbol: false,
        lineStyle: { color: BLUE, width: 1.6 },
        areaStyle: { color: "rgba(47,111,237,.08)" },
      },
      {
        name: "分位数(右轴)", type: "line", yAxisIndex: 1, data: R.ind.pct, showSymbol: false,
        lineStyle: { color: HOLD, width: 1.3, type: "dashed" },
        markLine: {
          symbol: "none", silent: true,
          data: [
            { yAxis: 0.9, lineStyle: { color: UP, type: "dashed" }, label: { formatter: "90% 止盈回补线", color: UP, position: "insideEndTop" } },
            { yAxis: 0.1, lineStyle: { color: DOWN, type: "dashed" }, label: { formatter: "10% 黄金补仓线", color: DOWN, position: "insideEndBottom" } },
          ],
        },
      },
      { name: "减红利", type: "scatter", data: trimPts, symbol: "triangle", symbolSize: 11, itemStyle: { color: UP }, z: 5 },
      { name: "回补红利", type: "scatter", data: addPts, symbol: "path://M0,0L10,0L5,8Z", symbolSize: 11, itemStyle: { color: DOWN }, z: 5 },
    ],
  }, true);
}

function renderPosChart(R) {
  const c = ensureChart("chartPos");
  c.setOption({
    animation: false, backgroundColor: "transparent",
    tooltip: { trigger: "axis", valueFormatter: (v) => (v * 100).toFixed(0) + "%" },
    grid: { left: 56, right: 20, top: 16, bottom: 44 },
    xAxis: { type: "category", data: R.dates, axisLabel: { color: GRAY }, axisLine: { lineStyle: { color: "#c6d2e2" } } },
    yAxis: { min: 0.4, max: 1.05, axisLabel: { color: GRAY, formatter: (v) => (v * 100).toFixed(0) + "%" }, splitLine: { lineStyle: { color: "#eef2f7" } } },
    dataZoom: [
      { type: "inside", xAxisIndex: 0, start: 0, end: 100 },
      { type: "slider", xAxisIndex: 0, bottom: 4, height: 16, borderColor: "#c6d2e2" },
    ],
    series: [{
      name: "建议红利仓位", type: "line", data: R.w, step: "end", showSymbol: false,
      lineStyle: { color: BLUE, width: 1.8 },
      areaStyle: {
        color: {
          type: "linear", x: 0, y: 0, x2: 0, y2: 1,
          colorStops: [{ offset: 0, color: "rgba(12,150,104,.25)" }, { offset: 1, color: "rgba(217,56,56,.15)" }],
        },
      },
    }],
  }, true);
}

function renderNavChart(R) {
  const c = ensureChart("chartNav");
  const line = (name, data, color, wdt) => ({ name, type: "line", data, showSymbol: false, lineStyle: { color, width: wdt || 1.6 } });
  c.setOption({
    animation: false, backgroundColor: "transparent",
    tooltip: { trigger: "axis", valueFormatter: (v) => v.toFixed(3) },
    legend: { top: 0, textStyle: { color: GRAY }, data: ["跷跷板策略", "满仓红利", "50/50等权", "满仓创业板"] },
    grid: { left: 56, right: 20, top: 34, bottom: 44 },
    xAxis: { type: "category", data: R.dates, axisLabel: { color: GRAY }, axisLine: { lineStyle: { color: "#c6d2e2" } } },
    yAxis: { scale: true, axisLabel: { color: GRAY, formatter: (v) => v.toFixed(1) }, splitLine: { lineStyle: { color: "#eef2f7" } } },
    dataZoom: [
      { type: "inside", xAxisIndex: 0, start: 0, end: 100 },
      { type: "slider", xAxisIndex: 0, bottom: 4, height: 16, borderColor: "#c6d2e2" },
    ],
    series: [
      line("跷跷板策略", R.nav, BLUE, 2.4),
      line("满仓红利", R.navD, DOWN, 1.4),
      line("50/50等权", R.navB, HOLD, 1.2),
      line("满仓创业板", R.navG, UP, 1.2),
    ],
  }, true);
}

function renderBtMetrics(R) {
  const cards = [
    { k: "策略年化", v: fmtPct(R.ann), c: R.ann >= 0 ? "up" : "down", s: `满仓红利年化 ${fmtPct(R.annD)}` },
    { k: "超额收益(vs满仓红利)", v: fmtPct(R.excess), c: R.excess >= 0 ? "up" : "down", s: "年化口径" },
    { k: "最大回撤", v: fmtPct(R.mdd), c: "down", s: "策略净值峰谷最大跌幅" },
    { k: "夏普比率", v: fmtNum(R.sharpe, 2), c: "plain", s: "年化，无风险 2%" },
    { k: "仓位变化次数", v: R.turns + " 次", c: "plain", s: "近五年信号切换" },
    { k: "减仓段胜率", v: R.winRate != null ? fmtPct(R.winRate) : "--", c: R.winRate != null && R.winRate >= 0.5 ? "up" : "down", s: "减仓区间跑赢满仓红利占比" },
  ];
  $("btMetrics").innerHTML = cards.map((m) =>
    `<div class="m-card"><div class="k">${m.k}</div><div class="v ${m.c}">${m.v}</div><div class="s">${m.s}</div></div>`).join("");
}

function renderTable(R) {
  $("turnCount").textContent = R.turns;
  const rows = R.switches.slice().reverse().map((s) => {
    const tagCls = s.to >= 1 ? "full" : (s.to >= 0.7 ? "trim" : "attack");
    const tag = `<span class="tag ${tagCls}">${Math.round(s.to * 100)}%</span>`;
    const chg = `${Math.round(s.from * 100)}% → ${Math.round(s.to * 100)}%`;
    return `<tr>
      <td>${s.date}</td>
      <td>${tag}</td>
      <td>${chg}</td>
      <td>${s.pct != null ? fmtPct(s.pct, 1) : "--"}</td>
      <td style="font-family:inherit;color:var(--txt2);white-space:normal">${s.reason}</td>
    </tr>`;
  });
  $("tblBody").innerHTML = rows.length ? rows.join("") :
    `<tr><td colspan="5" style="text-align:center;color:var(--txt3)">近五年未发生仓位变化</td></tr>`;
}

/* ================= 主流程 ================= */
let DATA = null;
async function init() {
  DATA = await loadData();
  const R = computeAll(DATA);
  renderDash(R, DATA);
  renderDiffChart(R);
  renderPosChart(R);
  renderNavChart(R);
  renderBtMetrics(R);
  renderTable(R);
  window._R = R;
  window.addEventListener("resize", () => { Object.values(charts).forEach((c) => c.resize()); });
}
init();
