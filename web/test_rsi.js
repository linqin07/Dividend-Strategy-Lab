/* 对拍：前端 JS 周RSI 算法 vs 后端 Python 计算结果 */
const fs = require("fs");
const path = require("path");

function isoWeekKey(dateStr) {
  const d = new Date(dateStr + "T00:00:00");
  const dayNum = (d.getDay() + 6) % 7;
  d.setDate(d.getDate() - dayNum + 3);
  const isoYear = d.getFullYear();
  const jan4 = new Date(isoYear, 0, 4);
  const j4day = (jan4.getDay() + 6) % 7;
  jan4.setDate(jan4.getDate() - j4day + 3);
  const week = 1 + Math.round((d - jan4) / (7 * 864e5));
  return isoYear + "-" + String(week).padStart(2, "0");
}
function splitAdjustRows(daily, splits) {
  const sps = (splits || []).slice().sort((a, b) => (a.date < b.date ? -1 : 1));
  return daily.map((r) => {
    let f = 1;
    for (const s of sps) if (r[0] < s.date) f *= Number(s.ratio);
    return [r[0], r[1] / f, r[2] / f, r[3] / f, r[4] / f, r[5]];
  });
}
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
function rsiWilder(closes, period) {
  const n = closes.length;
  const out = new Array(n).fill(null);
  if (n < period + 1) return out;
  const a = 1 / period;
  let avgG, avgL, seen = 0;
  for (let i = 1; i < n; i++) {
    const d = closes[i] - closes[i - 1];
    const g = Math.max(d, 0), l = Math.max(-d, 0);
    avgG = avgG === undefined ? g : (1 - a) * avgG + a * g;
    avgL = avgL === undefined ? l : (1 - a) * avgL + a * l;
    seen++;
    if (seen >= period) out[i] = avgL === 0 ? 100 : 100 - 100 / (1 + avgG / avgL);
  }
  return out;
}

for (const code of ["932305", "515080", "512890"]) {
  const bt = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "output", `${code}_backtest.json`), "utf8"));
  const sig = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "output", `${code}_signal.json`), "utf8"));
  const adj = splitAdjustRows(bt.daily, bt.splits);
  const wk = toWeekly(adj);
  const rsi = rsiWilder(wk.map((x) => x.close), 14);
  const last = rsi[rsi.length - 1];
  const ok = Math.abs(last - sig.rsi) < 0.05;
  console.log(`${code}: JS周RSI=${last.toFixed(2)}  后端=${sig.rsi}  周数=${wk.length}  ${ok ? "PASS" : "FAIL"}`);
}
