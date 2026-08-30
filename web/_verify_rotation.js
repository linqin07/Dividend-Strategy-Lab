const fs = require("fs"), vm = require("vm");
const html = fs.readFileSync("web/rotation.html", "utf8");
const marker = "use strict";
const js = html.split(marker)[1].split("</script>")[0].replace(/^";/, '"use strict";');
const sandbox = {
  console, Math, Date, fetch: async () => ({ ok: false }),
  document: { getElementById: () => ({ set onclick(v) {}, style: {}, classList: { add() {} } }), write: () => {} },
};
vm.createContext(sandbox);
vm.runInContext(js, sandbox);
const DATA = sandbox.genSeries();
const R = sandbox.computeMetrics(DATA.dates, DATA.growth, DATA.dividend, DATA.ratio, 0.3, 0.7, 0.001);
console.log("比值范围:", Math.min(...DATA.ratio).toFixed(3), "~", Math.max(...DATA.ratio).toFixed(3), "| 首日:", DATA.ratio[0].toFixed(3), "末值:", R.curRatio.toFixed(3));
console.log("≤0.3:", DATA.ratio.filter(r=>r<=0.3).length, "天 | ≥0.7:", DATA.ratio.filter(r=>r>=0.7).length, "天");
console.log("调仓:", R.turns, "| 胜率:", (R.winRate*100).toFixed(0)+"%", "| 年化:", (R.ann*100).toFixed(1)+"%", "| 回撤:", (R.mdd*100).toFixed(1)+"%", "| 夏普:", R.sharpe.toFixed(2), "| 超额:", (R.excess*100).toFixed(1)+"%");
console.log("触发:", R.switches.map(s=>s.date+"→"+(s.to==="growth"?"创业板":"红利")+"@"+s.ratio.toFixed(2)).join(" | ") || "无",
  "| 当前:", R.curPos, "| 上次:", R.lastSig, "| 持续:", R.holdDays, "天");
