/* AI 加减仓顾问 · 前端逻辑
 * 持仓数据保存在浏览器 localStorage；生成建议时优先走本地后端 /api/advisor/recommend，
 * 后端不在线时回退为浏览器直连 DeepSeek（仅持仓明细，无实验室策略信号上下文）。
 */
"use strict";

const $ = (id) => document.getElementById(id);

/* ================= 预置持仓（2026-09-25 四账户截图，代码已联网核实） =================
 * pct = 截图中的持有收益率；场外基金收益率的成本口径为 市值-盈亏。
 * 注意：券商账户 159280 名称截图模糊（互联网ETF），代码待核对。
 */
const DEFAULT_HOLDINGS = [
  // —— 券商账户（总资产 528,872.69 = 市值 239,510.80 + 现金 289,361.89）——
  { account: "券商账户", name: "恒指科技ETF",      code: "513180", qty: 6300,  price: 0.549, cost: 0.793,  profit: -1537.31, pct: -30.77 },
  { account: "券商账户", name: "白云机场",         code: "600004", qty: 6000,  price: 7.580, cost: 9.503,  profit: -11540.21, pct: -20.24 },
  { account: "券商账户", name: "上海机场",         code: "600009", qty: 1300,  price: 22.460, cost: 30.663, profit: -10663.50, pct: -26.75 },
  { account: "券商账户", name: "长江电力",         code: "600900", qty: 2200,  price: 28.360, cost: 26.625, profit: 3817.35, pct: 6.52 },
  { account: "券商账户", name: "金财互联",         code: "002530", qty: 1700,  price: 7.030, cost: 8.050,  profit: -1733.34, pct: -12.67 },
  { account: "券商账户", name: "互联网ETF",        code: "159280", qty: 19000, price: 0.666, cost: 0.979,  profit: -5947.67, pct: -31.97 },
  { account: "券商账户", name: "旅游ETF",          code: "159766", qty: 7700,  price: 0.543, cost: 0.700,  profit: -1205.40, pct: -22.38 },
  { account: "券商账户", name: "医药ETF",          code: "512983", qty: 32800, price: 0.439, cost: 0.544,  profit: -3458.30, pct: -19.37 },
  { account: "券商账户", name: "恒生医药ETF华夏",  code: "159892", qty: 68800, price: 0.811, cost: 0.827,  profit: -1126.75, pct: -1.98 },
  // —— 场内ETF账户（总市值 67,517.20）——
  { account: "场内ETF账户", name: "中概互联网ETF易方达", code: "513050", qty: 42000, price: 1.025, cost: 1.284, profit: -10868.73, pct: -20.16 },
  { account: "场内ETF账户", name: "传媒ETF广发",        code: "512980", qty: 23500, price: 0.802, cost: 0.831, profit: -668.95, pct: -3.43 },
  { account: "场内ETF账户", name: "消费ETF汇添富",      code: "159928", qty: 8700,  price: 0.646, cost: 1.644, profit: -8680.96, pct: -60.70 },
  // —— 广发基金账户（总资产 188,970.21，收益率来自 09-24 截图；<2000 元持仓已按用户要求移除：广发军工联接C）——
  { account: "广发基金", name: "广发恒生科技ETF联接(QDII)F",     code: "022005", amount: 76345.94, profit: -20986.06, pct: -21.55 },
  { account: "广发基金", name: "广发中证智选高股息策略ETF联接A", code: "025682", amount: 66965.11, profit: -461.69, pct: -0.70 },
  { account: "广发基金", name: "广发中证红利ETF联接A",           code: "021399", amount: 37771.50, profit: 983.29, pct: 2.67 },
  { account: "广发基金", name: "广发中证传媒ETF联接F",           code: "021952", amount: 3154.26,  profit: -45.74, pct: -1.73 },
  { account: "广发基金", name: "广发中证智选高股息策略ETF联接C", code: "025683", amount: 2593.80,  profit: 67.99, pct: 2.69 },
  { account: "广发基金", name: "广发全球医疗保健指数(QDII)A",    code: "000369", amount: 2136.80,  profit: 36.80, pct: 1.75 },
  // —— 支付宝基金账户（<2000 元持仓已按用户要求移除：创金合信主题精选C / 摩根标普500 A、C / 中信保诚）——
  { account: "支付宝基金", name: "嘉实恒生港股通新经济指数(LOF)C", code: "006614", amount: 38480.51, profit: -6614.93, pct: -14.67 },
  { account: "支付宝基金", name: "华夏中证全指证券公司ETF联接C",   code: "007993", amount: 7250.17,  profit: -293.52, pct: -4.05 },
  { account: "支付宝基金", name: "民生加银城镇化混合C",            code: "009706", amount: 3561.70,  profit: -438.30, pct: -11.85 },
];

const LS_HOLDINGS = "dsa_advisor_holdings_v3";   // v3: 嘉实改C类006614、创金合信=主题精选003625、移除<2000元持仓
const LS_KEY = "dsa_advisor_key";

let holdings = loadHoldings();

function loadHoldings() {
  try {
    const raw = localStorage.getItem(LS_HOLDINGS);
    if (raw) {
      const arr = JSON.parse(raw);
      if (Array.isArray(arr) && arr.length) return arr;
    }
  } catch (e) { /* 忽略坏数据 */ }
  return JSON.parse(JSON.stringify(DEFAULT_HOLDINGS));
}
function saveHoldings() {
  try { localStorage.setItem(LS_HOLDINGS, JSON.stringify(holdings)); } catch (e) { /* 私隐模式等 */ }
}

/* ================= 工具 ================= */
function fmtMoney(v) {
  if (v === null || v === undefined || v === "" || isNaN(Number(v))) return "--";
  return Number(v).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
function effAmount(h) {
  if (h.amount !== undefined && h.amount !== null && h.amount !== "") return Number(h.amount) || 0;
  const p = Number(h.price) || 0, q = Number(h.qty) || 0;
  return p * q;
}
function esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function effPct(h) {
  if (h.pct !== undefined && h.pct !== null && h.pct !== "" && !isNaN(Number(h.pct))) return Number(h.pct);
  const a = effAmount(h), p = Number(h.profit) || 0;
  const base = a - p;                       // 成本口径：市值 - 累计盈亏
  return base > 0 ? (p / base * 100) : null;
}

/* ================= 持仓表格 ================= */
function renderTable() {
  const tb = $("holdBody");
  tb.innerHTML = "";
  holdings.forEach((h, i) => {
    const pct = effPct(h);
    const pctTxt = pct === null ? "--" : (pct >= 0 ? "+" : "") + pct.toFixed(2) + "%";
    const pctCls = pct === null ? "" : (pct >= 0 ? "v-up" : "v-down");
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td class="txt-cell"><input class="hold-in" data-i="${i}" data-k="account" value="${esc(h.account)}"></td>
      <td class="txt-cell"><input class="hold-in" data-i="${i}" data-k="name" value="${esc(h.name)}"></td>
      <td class="code-cell"><input class="hold-in" data-i="${i}" data-k="code" value="${esc(h.code)}"></td>
      <td class="num-cell"><input class="hold-num" data-i="${i}" data-k="amount" value="${h.amount ?? ""}" placeholder="自动=现价×数量"></td>
      <td class="num-cell"><input class="hold-num" data-i="${i}" data-k="cost" value="${h.cost ?? ""}"></td>
      <td class="num-cell"><input class="hold-num" data-i="${i}" data-k="price" value="${h.price ?? ""}"></td>
      <td class="num-cell"><input class="hold-num" data-i="${i}" data-k="qty" value="${h.qty ?? ""}"></td>
      <td class="num-cell"><input class="hold-num" data-i="${i}" data-k="profit" value="${h.profit ?? ""}"></td>
      <td class="num ${pctCls}" style="min-width:76px">${pctTxt}</td>
      <td class="op-cell"><button class="btn-danger-link" data-del="${i}">删除</button></td>`;
    tb.appendChild(tr);
  });
  tb.querySelectorAll("input").forEach(inp => {
    inp.addEventListener("input", () => {
      const i = Number(inp.dataset.i), k = inp.dataset.k;
      const v = inp.value.trim();
      holdings[i][k] = (v === "") ? null : (["amount", "cost", "price", "qty", "profit"].includes(k) ? Number(v) || 0 : v);
      saveHoldings();
      renderSummary();
    });
  });
  tb.querySelectorAll("[data-del]").forEach(btn => {
    btn.addEventListener("click", () => {
      holdings.splice(Number(btn.dataset.del), 1);
      saveHoldings(); renderTable(); renderSummary();
    });
  });
}

/* ================= 汇总 ================= */
function renderSummary() {
  const cash = Number($("inCash").value) || 0;
  let mv = 0, profit = 0;
  const byAccount = {};
  holdings.forEach(h => {
    const a = effAmount(h);
    mv += a;
    profit += Number(h.profit) || 0;
    const acc = h.account || "未分组";
    byAccount[acc] = (byAccount[acc] || 0) + a;
  });
  const total = mv + cash;
  const pct = total > 0 ? (mv / total * 100) : 0;
  const accChips = Object.entries(byAccount)
    .map(([k, v]) => `${esc(k)} ¥${fmtMoney(v)}`).join(" · ");
  $("sumGrid").innerHTML = `
    <div class="ystat"><div class="ystat-k">总资产（含现金）</div><div class="ystat-v">¥${fmtMoney(total)}</div></div>
    <div class="ystat"><div class="ystat-k">持仓市值合计</div><div class="ystat-v">¥${fmtMoney(mv)}</div></div>
    <div class="ystat"><div class="ystat-k">现金</div><div class="ystat-v">¥${fmtMoney(cash)}</div></div>
    <div class="ystat"><div class="ystat-k">当前总仓位</div><div class="ystat-v">${pct.toFixed(1)}%</div>
      <div class="ystat-sub">${accChips}</div></div>
    <div class="ystat"><div class="ystat-k">累计盈亏</div>
      <div class="ystat-v ${profit >= 0 ? "v-up" : "v-down"}">${profit >= 0 ? "+" : ""}¥${fmtMoney(profit)}</div></div>
    <div class="ystat"><div class="ystat-k">持仓笔数</div><div class="ystat-v">${holdings.length}</div></div>`;
}

/* ================= 建议生成 ================= */
function collectPayload() {
  const cash = Number($("inCash").value) || 0;
  const rows = holdings
    .filter(h => h.name || h.code || effAmount(h) > 0)
    .map(h => ({
      account: h.account || "", name: h.name || "", code: h.code || "",
      amount: effAmount(h), cost: h.cost ?? null, price: h.price ?? null,
      qty: h.qty ?? null, profit: h.profit ?? null, pct: effPct(h),
    }));
  return {
    holdings: rows, cash,
    risk_level: $("inRisk").value || "稳健",
    extra: $("inExtra").value.trim() || null,
    api_key: ($("inKey").value.trim()) || null,
  };
}

function setStatus(html) { $("aiStatus").innerHTML = html; }

async function detectServe() {
  try {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 3000);
    const r = await fetch("api/ping", { cache: "no-store", signal: ctl.signal });
    clearTimeout(t);
    return r.ok;
  } catch (e) { return false; }
}

/* 浏览器直连 DeepSeek（后端不在线时的兜底；实验室信号上下文不可用） */
async function directDeepSeek(payload) {
  const key = payload.api_key;
  if (!key) throw new Error("后端不在线，且页面未填 DeepSeek API Key。请填入 Key，或运行 python run.py serve 后重试。");
  const lines = payload.holdings.map(h =>
    `- ${h.account} | ${h.name} | ${h.code || "-"} | 市值¥${fmtMoney(h.amount)} | 成本${h.cost ?? "-"} | 现价${h.price ?? "-"} | 数量${h.qty ?? "-"} | 累计盈亏¥${fmtMoney(h.profit)} | 收益率${h.pct != null ? h.pct + "%" : "-"}`);
  const user = `你是中国市场基金/ETF资产配置顾问。请结合通用资产配置策略（核心-卫星、单一标的≤20%、行业≤30%、现金5%~15%、深亏宽基分批定投摊薄、QDII溢价风险、同质化持仓合并）给出加减仓建议。
风险偏好：${payload.risk_level}
可用现金：¥${fmtMoney(payload.cash)}
${payload.extra ? "补充说明：" + payload.extra : ""}
持仓明细：
${lines.join("\n")}

只输出 JSON：{"summary":"一句话结论","overall":{"current_position_pct":数字,"target_position_pct":数字,"cash_advice":"现金安排"},"actions":[{"code":"","name":"","action":"加仓|减仓|持有|清仓|定投|转出","amount":"金额","reason":"理由"}],"risks":["风险"],"detail_md":"Markdown详细说明"}
actions 必须覆盖全部持仓。金额取整到百元。`;
  const r = await fetch("https://api.deepseek.com/chat/completions", {
    method: "POST",
    headers: { "Authorization": "Bearer " + key, "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "deepseek-chat",
      messages: [
        { role: "system", content: "你是一名严谨的中国市场基金/ETF资产配置顾问，只输出 JSON。" },
        { role: "user", content: user },
      ],
      temperature: 1.0, max_tokens: 8000,
      response_format: { type: "json_object" },
    }),
  });
  if (r.status === 401) throw new Error("DeepSeek API Key 无效（401）");
  if (r.status === 402) throw new Error("DeepSeek 账户余额不足（402）");
  if (!r.ok) throw new Error("DeepSeek 调用失败：HTTP " + r.status);
  const data = await r.json();
  const content = (data.choices || [{}])[0].message?.content || "";
  let advice;
  try { advice = JSON.parse(content.trim().replace(/^```json?/, "").replace(/```$/, "").trim()); }
  catch (e) { advice = { _format: "text", summary: "AI 返回为非结构化文本", detail_md: content }; }
  return { advice, model: "deepseek-chat", mode: "direct" };
}

async function generate() {
  const payload = collectPayload();
  if (!payload.holdings.length) { alert("请先录入至少一条持仓"); return; }
  // Key 记住（仅本机 localStorage）
  try { localStorage.setItem(LS_KEY, payload.api_key || ""); } catch (e) { /* ignore */ }

  $("btnGo").disabled = true;
  setStatus('<span class="spinner-inline"></span>正在调用 DeepSeek 分析（约 30~120 秒，请勿关闭页面）...');
  $("advicePanel").hidden = true;

  try {
    let result, mode;
    const serve = await detectServe();
    if (serve) {
      const r = await fetch("api/advisor/recommend", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) {
        let detail = "HTTP " + r.status;
        try { const b = await r.json(); detail = b.detail || detail; } catch (e) { /* ignore */ }
        throw new Error(detail);
      }
      result = await r.json(); mode = "serve";
    } else {
      result = await directDeepSeek(payload);
    }
    renderAdvice(result.advice, result, mode);
    setStatus("✅ 建议已生成");
  } catch (e) {
    setStatus("");
    alert("生成失败：" + (e.message || e));
  } finally {
    $("btnGo").disabled = false;
  }
}

/* ================= 结果渲染 ================= */
function miniMarkdown(md) {
  const lines = esc(md).split(/\r?\n/);
  const out = [];
  let inList = false;
  for (const ln of lines) {
    const t = ln.trim();
    let html = t
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
    const h = t.match(/^(#{1,4})\s+(.*)$/);
    if (h) {
      if (inList) { out.push("</ul>"); inList = false; }
      const lv = Math.min(h[1].length + 2, 5);
      out.push(`<h${lv}>${h[2]}</h${lv}>`);
      continue;
    }
    if (/^[-*]\s+/.test(t)) {
      if (!inList) { out.push("<ul>"); inList = true; }
      out.push(`<li>${html.replace(/^[-*]\s+/, "")}</li>`);
      continue;
    }
    if (inList) { out.push("</ul>"); inList = false; }
    if (t) out.push(`<p>${html}</p>`);
  }
  if (inList) out.push("</ul>");
  return out.join("");
}

function renderAdvice(advice, result, mode) {
  $("advicePanel").hidden = false;
  const usage = result.usage ? ` · tokens ${result.usage.total_tokens ?? "-"}` : "";
  $("adviceMeta").textContent =
    `${result.model || "deepseek-chat"} · ${mode === "serve" ? "含实验室策略信号" : "浏览器直连（无实验室信号上下文）"}${usage}`;

  const parts = [];
  // 总结论
  parts.push(`<div class="advice-summary">
    <div class="sum-title">总体结论</div>
    <div class="sum-text">${esc(advice.summary || "--")}</div>
  </div>`);
  // 总仓位
  const ov = advice.overall || {};
  const curPct = ov.current_position_pct != null ? Number(ov.current_position_pct) : null;
  const tgtPct = ov.target_position_pct != null ? Number(ov.target_position_pct) : null;
  parts.push(`<div class="advice-overall">
    <div class="ystat"><div class="ystat-k">当前总仓位（AI 估计）</div>
      <div class="ystat-v">${curPct != null ? curPct + "%" : "--"}</div></div>
    <div class="ystat"><div class="ystat-k">建议目标总仓位</div>
      <div class="ystat-v">${tgtPct != null ? tgtPct + "%" : "--"}</div></div>
    <div class="ystat"><div class="ystat-k">现金安排</div>
      <div class="ystat-v small">${esc(ov.cash_advice || "--")}</div></div>
  </div>`);
  // 明细表
  const acts = Array.isArray(advice.actions) ? advice.actions : [];
  if (acts.length) {
    parts.push(`<div class="table-wrap"><table>
      <thead><tr><th>标的</th><th>建议</th><th>金额/数量</th><th>理由</th></tr></thead><tbody>`);
    for (const a of acts) {
      const act = String(a.action || "");
      const tagCls = "act-" + esc(act);
      parts.push(`<tr>
        <td>${esc(a.name || "")}${a.code ? ` <span class="td-code">${esc(a.code)}</span>` : ""}</td>
        <td><span class="act-tag ${tagCls}">${esc(act)}</span></td>
        <td class="mono">${esc(a.amount || "")}</td>
        <td style="white-space:normal;min-width:220px">${esc(a.reason || "")}</td>
      </tr>`);
    }
    parts.push("</tbody></table></div>");
  }
  // 风险
  const risks = Array.isArray(advice.risks) ? advice.risks : [];
  if (risks.length) {
    parts.push(`<div class="risk-box"><h3>⚠️ 风险提示</h3><ul class="risk-list">` +
      risks.map(r => `<li>${esc(r)}</li>`).join("") + `</ul></div>`);
  }
  // 详细说明
  if (advice.detail_md) {
    parts.push(`<div class="md-body">${miniMarkdown(advice.detail_md)}</div>`);
  }
  $("adviceBody").innerHTML = parts.join("");
  $("advicePanel").scrollIntoView({ behavior: "smooth" });
}

/* ================= 初始化 ================= */
function init() {
  // 恢复记住的 Key
  try {
    const k = localStorage.getItem(LS_KEY);
    if (k) $("inKey").value = k;
  } catch (e) { /* ignore */ }

  $("inCash").addEventListener("input", renderSummary);
  $("btnAddRow").addEventListener("click", () => {
    holdings.push({ account: "", name: "", code: "", amount: null, cost: null, price: null, qty: null, profit: null });
    saveHoldings(); renderTable();
  });
  $("btnResetDemo").addEventListener("click", () => {
    if (!confirm("将覆盖当前持仓为示例数据（2026-09-25 四账户截图），确认？")) return;
    holdings = JSON.parse(JSON.stringify(DEFAULT_HOLDINGS));
    saveHoldings(); renderTable(); renderSummary();
  });
  $("btnClearRows").addEventListener("click", () => {
    if (!confirm("确认清空全部持仓行？")) return;
    holdings = []; saveHoldings(); renderTable(); renderSummary();
  });
  $("btnGo").addEventListener("click", generate);

  renderTable();
  renderSummary();
}
init();
