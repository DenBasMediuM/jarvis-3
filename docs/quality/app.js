/* GitHub Pages viewer for Jarvis quality snapshot (data.json). */
const DATA_URL = "./data.json";
const MASTERS_COLLAPSE_KEY = "jarvis.pages.masters.collapsed";
const SORT_OVERVIEW_KEY = "jarvis.pages.sort.overview";
const SORT_MASTERS_KEY = "jarvis.pages.sort.masters";
const SORT_SUMMARY_KEY = "jarvis.pages.sort.summary";

const SORT_NUMERIC = new Set([
  "oid",
  "total",
  "wait",
  "diag",
  "rework",
  "calls",
  "kpi",
  "mgr",
  "count",
]);

let DATA = null;
let chartMasters = null;
let chartKpi = null;
let chartDays = null;
let floatTipEl = null;
let floatTipAnchor = null;
let floatTipHideTimer = null;
let tipsBound = false;
let overviewSort = null;
let mastersSort = { key: "kpi", dir: "asc" };
let summarySort = { key: "kpi", dir: "desc" };

const $ = (sel, root = document) => root.querySelector(sel);

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmtDays(v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  return String(Math.round(Number(v) * 10) / 10);
}

function fmtDate(s) {
  if (!s) return "—";
  const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return `${m[3]}.${m[2]}.${m[1]}`;
  return String(s).slice(0, 19).replace("T", " ");
}

function dayClass(v, warn, bad) {
  if (v == null) return "";
  const n = Number(v);
  if (n >= bad) return "day-bad";
  if (n >= warn) return "day-warn";
  return "";
}

function kpiTone(v) {
  if (v == null || Number.isNaN(Number(v))) return "muted";
  if (v >= 70) return "good";
  if (v >= 40) return "mid";
  return "bad";
}

function kpiClass(v) {
  const t = kpiTone(v);
  return t === "muted" ? "muted" : `kpi-${t}`;
}

function heatStyle(kpi) {
  if (kpi == null || Number.isNaN(Number(kpi))) return "";
  const raw = Math.max(0, Math.min(100, Number(kpi))) / 100;
  const t = Math.pow(raw, 1.65);
  const hue = Math.round(t * 118);
  const sat = Math.round(62 - 8 * t);
  const light = Math.round(44 + 4 * t);
  const alpha = (0.28 + 0.22 * (1 - t)).toFixed(3);
  return `background-color: hsla(${hue}, ${sat}%, ${light}%, ${alpha})`;
}

function avg(nums) {
  const vals = nums.filter((n) => n != null && !Number.isNaN(Number(n))).map(Number);
  if (!vals.length) return null;
  return Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10;
}

function loadSort(key) {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed?.key && (parsed.dir === "asc" || parsed.dir === "desc")) return parsed;
  } catch {
    /* ignore */
  }
  return null;
}

function saveSort(key, sort) {
  try {
    if (!sort) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(sort));
  } catch {
    /* ignore */
  }
}

function orderSortValue(row, key) {
  switch (key) {
    case "oid":
      return Number(row.order_id) || 0;
    case "status":
      return String(row.status || "").toLowerCase();
    case "engineer":
      return String(row.engineer || row.master_name || "").toLowerCase();
    case "device":
      return String(row.device || "").toLowerCase();
    case "total":
      return row.total_days == null ? -1 : Number(row.total_days);
    case "wait":
      return row.wait_master_days == null ? -1 : Number(row.wait_master_days);
    case "diag":
      return row.diag_days == null ? -1 : Number(row.diag_days);
    case "rework":
      if (row.rework_kpi == null) return 101;
      return Number(row.rework_kpi);
    case "calls":
      return row.calls_kpi == null ? -1 : Number(row.calls_kpi);
    case "kpi":
      return row.order_kpi == null ? -1 : Number(row.order_kpi);
    case "mgr":
      return row.manager_no_answer_missed ? 1 : 0;
    default:
      return "";
  }
}

function sortOrders(rows, sort) {
  if (!sort?.key || !rows?.length) return rows || [];
  const dir = sort.dir === "desc" ? -1 : 1;
  const key = sort.key;
  return [...rows].sort((a, b) => {
    const va = orderSortValue(a, key);
    const vb = orderSortValue(b, key);
    if (typeof va === "number" && typeof vb === "number") {
      if (va === vb) return Number(b.order_id) - Number(a.order_id);
      return (va - vb) * dir;
    }
    const cmp = String(va).localeCompare(String(vb), "ru", { sensitivity: "base" });
    if (cmp === 0) return Number(b.order_id) - Number(a.order_id);
    return cmp * dir;
  });
}

function summarySortValue(g, key) {
  switch (key) {
    case "name":
      return String(g.name || "").toLowerCase();
    case "count":
      return Number(g.count) || 0;
    case "kpi":
      return g.avgKpi == null ? -1 : Number(g.avgKpi);
    case "total":
      return g.avgTotal == null ? -1 : Number(g.avgTotal);
    case "wait":
      return g.avgWait == null ? -1 : Number(g.avgWait);
    case "diag":
      return g.avgDiag == null ? -1 : Number(g.avgDiag);
    case "rework":
      return g.avgRework == null ? 101 : Number(g.avgRework);
    case "calls":
      return g.avgCalls == null ? -1 : Number(g.avgCalls);
    default:
      return "";
  }
}

function sortSummaryGroups(groups, sort) {
  if (!sort?.key || !groups?.length) return groups || [];
  const dir = sort.dir === "desc" ? -1 : 1;
  const key = sort.key;
  return [...groups].sort((a, b) => {
    const va = summarySortValue(a, key);
    const vb = summarySortValue(b, key);
    if (typeof va === "number" && typeof vb === "number") {
      if (va === vb) return String(a.name).localeCompare(String(b.name), "ru");
      return (va - vb) * dir;
    }
    const cmp = String(va).localeCompare(String(vb), "ru", { sensitivity: "base" });
    if (cmp === 0) return (b.count || 0) - (a.count || 0);
    return cmp * dir;
  });
}

function cycleSort(current, key) {
  if (current?.key === key) {
    const firstDir = SORT_NUMERIC.has(key) ? "desc" : "asc";
    if (current.dir === firstDir) {
      return { key, dir: current.dir === "asc" ? "desc" : "asc" };
    }
    return null;
  }
  return { key, dir: SORT_NUMERIC.has(key) ? "desc" : "asc" };
}

function updateSortIndicators(table, sort) {
  if (!table) return;
  table.querySelectorAll("thead th[data-col]").forEach((th) => {
    const key = th.getAttribute("data-col");
    const mark = th.querySelector(".th-sort");
    const active = sort && sort.key === key;
    th.classList.toggle("is-sorted", !!active);
    if (mark) mark.textContent = active ? (sort.dir === "asc" ? "▲" : "▼") : "▲";
  });
}

function bindTableSort(table, getSort, setSort, onChange) {
  if (!table) return;
  updateSortIndicators(table, getSort());
  if (table.dataset.sortBound === "1") return;
  table.dataset.sortBound = "1";
  // Делегирование: клик по любой части заголовка (label/стрелка).
  table.tHead?.addEventListener("click", (e) => {
    const th = e.target.closest?.("th[data-col]");
    if (!th || !table.contains(th)) return;
    e.preventDefault();
    const key = th.getAttribute("data-col");
    if (!key) return;
    const next = cycleSort(getSort(), key);
    setSort(next);
    updateSortIndicators(table, next);
    onChange();
  });
}

function masterHeaderHtml() {
  const cols = [
    ["oid", "№"],
    ["status", "Статус"],
    ["device", "Устройство"],
    ["total", "Всего дн"],
    ["wait", "До мастера"],
    ["diag", "До диагн."],
    ["rework", "Дораб."],
    ["calls", "Звонки"],
    ["kpi", "KPI"],
    ["mgr", "Мен."],
  ];
  return cols
    .map(
      ([key, label]) =>
        `<th data-col="${key}"><div class="th-inner"><span class="th-label">${label}</span><span class="th-sort" aria-hidden="true">▲</span></div></th>`,
    )
    .join("");
}

function tipLi(text, tone) {
  return `<li class="${tone ? `is-${tone}` : ""}">${esc(text)}</li>`;
}

function buildCallsTip(r) {
  const inOk = r.calls_inbound_ok ?? r.calls_inbound ?? 0;
  const inFail = r.calls_inbound_fail ?? 0;
  const outOk = r.calls_outbound_ok ?? 0;
  const outFail = r.calls_outbound_fail ?? 0;
  const missed = r.calls_missed ?? r.calls_missed_total ?? 0;
  const missUnrec = r.calls_missed_unrecovered ?? 0;
  const missRec = r.calls_missed_recovered ?? 0;
  const preOk = r.calls_pre_inbound_ok ?? 0;
  const preSame = r.calls_pre_miss_same_day ?? 0;
  const preBefore = r.calls_pre_miss_before_visit ?? 0;
  const preUntil = r.calls_pre_miss_until_visit ?? 0;
  const kpi = r.calls_kpi != null ? Number(r.calls_kpi) : null;
  const tone = kpiTone(kpi);

  const preItems = [];
  if (preOk) preItems.push(tipLi(`Приняли входящий: ${preOk} — норма, без штрафа`, "good"));
  if (preSame) {
    preItems.push(
      tipLi(`Не взяли, но в тот же день связались: ${preSame}`, "mid"),
    );
  }
  if (preBefore) preItems.push(tipLi(`Связались позже, но до сдачи: ${preBefore}`, "mid"));
  if (preUntil) {
    preItems.push(tipLi(`До сдачи так и не связались: ${preUntil}`, "bad"));
  }

  const postItems = [];
  if (missUnrec) postItems.push(tipLi(`Пропущенный без перезвона в тот же день: ${missUnrec}`, "bad"));
  if (missRec) postItems.push(tipLi(`Пропущенный, перезвонили в тот же день: ${missRec}`, "good"));
  if (r.callback_same_day) {
    postItems.push(tipLi(`Дней с перезвоном в тот же день: ${r.callback_same_day}`));
  }

  const score =
    kpi == null
      ? `<div class="float-tip-score is-muted">Нет данных</div>
         <p class="float-tip-note">В ленте нет звонков для оценки коммуникации.</p>`
      : `<div class="float-tip-score is-${tone}"><span>${kpi}</span><small>/ 100</small></div>`;

  return `
    <div class="float-tip-head">Коммуникация</div>
    ${score}
    <div class="float-tip-block">
      <div class="float-tip-label">Звонки по заказу</div>
      <ul>
        <li>Исходящие: <strong>${outOk}</strong> успешных · <strong>${outFail}</strong> неуспешных</li>
        <li>Входящие: <strong>${inOk}</strong> успешных · <strong>${inFail}</strong> неуспешных${
          missed ? ` · пропущено <strong>${missed}</strong>` : ""
        }</li>
      </ul>
    </div>
    ${
      preItems.length
        ? `<div class="float-tip-block"><div class="float-tip-label">До создания заказа</div><ul>${preItems.join("")}</ul></div>`
        : ""
    }
    ${
      postItems.length
        ? `<div class="float-tip-block"><div class="float-tip-label">После создания заказа</div><ul>${postItems.join("")}</ul></div>`
        : ""
    }
    ${
      kpi != null && !preItems.length && !postItems.length
        ? `<p class="float-tip-note">Особых проблем с дозвоном не зафиксировано — оценка по успешности звонков.</p>`
        : ""
    }
  `;
}

function buildReworkTip(r) {
  const rwN = Number(r.rework_count || 0);
  const rwKpi = r.rework_kpi != null ? Number(r.rework_kpi) : null;
  if (rwN <= 0 || rwKpi == null) {
    return `
      <div class="float-tip-head">Доработки</div>
      <div class="float-tip-score is-good"><span>—</span></div>
      <p class="float-tip-note">Приёмов на доработку не было.</p>
    `;
  }
  const tone = kpiTone(rwKpi);
  const diag = r.rework_diag_days;
  const repair = r.rework_repair_days;
  const total = r.rework_total_days;
  const since = fmtDate(r.last_rework_at || r.rework_last_accepted_at);
  const why = [];
  if (rwN === 1) why.push(tipLi("Первая доработка: −20 к оценке", "mid"));
  else why.push(tipLi(`${rwN} приёма на доработку: −20 за первую и −25 за каждую следующую`, "bad"));
  if (repair == null) {
    why.push(tipLi("Ремонт после доработки ещё не начат — долгая диагностика штрафуется сильнее", "bad"));
  } else if (Number(diag) >= 7 || Number(repair) >= 7 || Number(total) >= 10) {
    why.push(tipLi("Долгий цикл после последней доработки снижает оценку", "mid"));
  }
  return `
    <div class="float-tip-head">Доработки</div>
    <div class="float-tip-score is-${tone}"><span>${rwKpi}</span><small>/ 100</small></div>
    <div class="float-tip-block">
      <div class="float-tip-label">Сводка</div>
      <ul>
        <li>Приёмов на доработку: <strong>${rwN}</strong></li>
        <li>Последний приём: <strong>${esc(since)}</strong></li>
      </ul>
    </div>
    <div class="float-tip-block">
      <div class="float-tip-label">С последней доработки</div>
      <ul>
        <li>Диагностика: <strong>${diag == null ? "—" : `${fmtDays(diag)} дн`}</strong></li>
        <li>Ремонт: <strong>${repair == null ? "ещё не начат" : `${fmtDays(repair)} дн`}</strong></li>
        <li>Всего: <strong>${total == null ? "—" : `${fmtDays(total)} дн`}</strong></li>
      </ul>
    </div>
    ${
      why.length
        ? `<div class="float-tip-block"><div class="float-tip-label">Что влияет на оценку</div><ul>${why.join("")}</ul></div>`
        : ""
    }
  `;
}

function buildOrderKpiTip(r) {
  const kpi = r.order_kpi != null ? Number(r.order_kpi) : null;
  const tone = kpiTone(kpi);
  const parts = Array.isArray(r.order_kpi_parts) ? r.order_kpi_parts : [];
  const score =
    kpi == null
      ? `<div class="float-tip-score is-muted">Нет данных</div>`
      : `<div class="float-tip-score is-${tone}"><span>${kpi}</span><small>/ 100</small></div>`;
  const rows = parts
    .map((p) => {
      const pt = kpiTone(p.score);
      const detail = String(p.detail || "").trim();
      return `<li class="is-${pt}"><strong>${esc(p.label)}</strong> → <strong>${
        p.score
      }/100</strong>${
        detail ? ` <span class="float-tip-muted">(${esc(detail)})</span>` : ""
      } · вес ${p.weight_pct ?? "—"}%</li>`;
    })
    .join("");
  return `
    <div class="float-tip-head">Итоговый KPI</div>
    ${score}
    <div class="float-tip-block">
      <div class="float-tip-label">Оценка компонентов (не «количество»)</div>
      <ul>${rows || "<li>Недостаточно данных для оценки</li>"}</ul>
    </div>
    <p class="float-tip-note">В «Дораб.» и «Звонки» число — балл 0–100, не счётчик. «Мен.» не входит. Нет звонков — веса перенормируются.</p>
  `;
}

function tipCell(innerHtml, tipHtml, extraClass = "") {
  // div, не span: в подсказке есть блочные теги — span ломает DOM таблицы.
  return `<div class="tip-anchor ${extraClass}" tabindex="0">${innerHtml}<div class="tip-content" hidden>${tipHtml}</div></div>`;
}

function ensureFloatTip() {
  if (floatTipEl) return floatTipEl;
  floatTipEl = document.createElement("div");
  floatTipEl.className = "float-tip";
  floatTipEl.hidden = true;
  floatTipEl.setAttribute("role", "tooltip");
  document.body.appendChild(floatTipEl);
  floatTipEl.addEventListener("mouseenter", () => {
    if (floatTipHideTimer) {
      clearTimeout(floatTipHideTimer);
      floatTipHideTimer = null;
    }
  });
  floatTipEl.addEventListener("mouseleave", () => hideFloatTipSoon());
  return floatTipEl;
}

function positionFloatTip(anchor) {
  const tip = ensureFloatTip();
  const rect = anchor.getBoundingClientRect();
  const pad = 10;
  const tipW = tip.offsetWidth || 320;
  const tipH = tip.offsetHeight || 180;
  let left = rect.left + rect.width / 2 - tipW / 2;
  left = Math.max(pad, Math.min(left, window.innerWidth - tipW - pad));
  let top = rect.bottom + 8;
  if (top + tipH > window.innerHeight - pad && rect.top > tipH + 16) {
    top = rect.top - tipH - 8;
  }
  tip.style.left = `${Math.round(left)}px`;
  tip.style.top = `${Math.round(top)}px`;
}

function showFloatTip(anchor) {
  const content = anchor.querySelector(".tip-content");
  if (!content) return;
  if (floatTipHideTimer) {
    clearTimeout(floatTipHideTimer);
    floatTipHideTimer = null;
  }
  const tip = ensureFloatTip();
  tip.innerHTML = content.innerHTML;
  tip.hidden = false;
  floatTipAnchor = anchor;
  positionFloatTip(anchor);
}

function hideFloatTipSoon() {
  if (floatTipHideTimer) clearTimeout(floatTipHideTimer);
  floatTipHideTimer = setTimeout(() => {
    if (!floatTipEl) return;
    floatTipEl.hidden = true;
    floatTipEl.innerHTML = "";
    floatTipAnchor = null;
    floatTipHideTimer = null;
  }, 120);
}

function bindTips() {
  if (tipsBound) return;
  tipsBound = true;
  document.addEventListener("mouseover", (e) => {
    const a = e.target.closest?.(".tip-anchor");
    if (!a) return;
    if (floatTipAnchor === a && floatTipEl && !floatTipEl.hidden) return;
    showFloatTip(a);
  });
  document.addEventListener("mouseout", (e) => {
    const a = e.target.closest?.(".tip-anchor");
    if (!a) return;
    const related = e.relatedTarget;
    if (related && (a.contains(related) || floatTipEl?.contains(related))) return;
    hideFloatTipSoon();
  });
  document.addEventListener("focusin", (e) => {
    const a = e.target.closest?.(".tip-anchor");
    if (a) showFloatTip(a);
  });
  document.addEventListener("scroll", () => {
    if (floatTipAnchor && floatTipEl && !floatTipEl.hidden) positionFloatTip(floatTipAnchor);
  }, true);
}

function groupByMaster(orders) {
  const map = new Map();
  for (const o of orders || []) {
    const name = String(o.engineer || o.master_name || "").trim();
    if (!name || name === "—" || name.toLowerCase() === "без мастера") continue;
    if (!map.has(name)) map.set(name, []);
    map.get(name).push(o);
  }
  return [...map.entries()]
    .map(([name, rows]) => {
      const avgKpi = avg(rows.map((r) => r.order_kpi));
      return {
        name,
        rows,
        count: rows.length,
        avgKpi: avgKpi == null ? null : Math.round(avgKpi),
        avgTotal: avg(rows.map((r) => r.total_days)),
        avgWait: avg(rows.map((r) => r.wait_master_days)),
        avgDiag: avg(rows.map((r) => r.diag_days)),
        avgRework: avg(rows.filter((r) => Number(r.rework_count) > 0).map((r) => r.rework_kpi)),
        avgCalls: avg(rows.map((r) => r.calls_kpi)),
      };
    })
    .sort((a, b) => (b.avgKpi ?? -1) - (a.avgKpi ?? -1) || b.count - a.count);
}

function orderRowHtml(r, { engineer = true } = {}) {
  const oid = esc(r.order_id || "");
  const link = r.url
    ? `<a href="${esc(r.url)}" target="_blank" rel="noopener">${oid}</a>`
    : oid;
  const kpi = r.order_kpi != null ? Number(r.order_kpi) : null;
  const eng = engineer ? `<td>${esc(r.engineer || r.master_name || "—")}</td>` : "";

  const rwN = Number(r.rework_count || 0);
  const rwKpi = r.rework_kpi != null ? Number(r.rework_kpi) : null;
  const rwInner =
    rwN > 0 && rwKpi != null
      ? `<span class="${kpiClass(rwKpi)}">${rwKpi}</span>`
      : `<span class="muted">—</span>`;
  const rework = tipCell(rwInner, buildReworkTip(r));

  const callsKpi = r.calls_kpi != null ? Number(r.calls_kpi) : null;
  const callsInner =
    callsKpi == null
      ? `<span class="muted">—</span>`
      : `<span class="${kpiClass(callsKpi)}">${callsKpi}</span>`;
  const calls = tipCell(callsInner, buildCallsTip(r));

  const orderInner =
    kpi == null
      ? `<span class="muted">—</span>`
      : `<span class="${kpiClass(kpi)}">${kpi}</span>`;
  const orderKpi = tipCell(orderInner, buildOrderKpiTip(r));

  const mgr = r.manager_no_answer_missed
    ? `<span class="flag" title="После согласования неуспешный исходящий">статус?</span>`
    : `<span class="muted">—</span>`;

  return `<tr>
    <td>${link}</td>
    <td title="${esc(r.status || "")}">${esc(r.status || "—")}</td>
    ${eng}
    <td title="${esc(r.device || "")}" style="${heatStyle(kpi)}">${esc((r.device || "—").slice(0, 32))}</td>
    <td class="${dayClass(r.total_days, 7, 14)}" title="Принят: ${esc(fmtDate(r.accepted_at))}">${fmtDays(r.total_days)}</td>
    <td class="${dayClass(r.wait_master_days, 2, 5)}">${fmtDays(r.wait_master_days)}</td>
    <td class="${dayClass(r.diag_days, 3, 7)}" title="${esc(r.agreement_source || "")}">${fmtDays(r.diag_days)}</td>
    <td>${rework}</td>
    <td>${calls}</td>
    <td>${orderKpi}</td>
    <td>${mgr}</td>
  </tr>`;
}

const OVERVIEW_COLS = `
  <colgroup>
    <col class="c-oid" /><col class="c-status" /><col class="c-eng" /><col class="c-device" />
    <col class="c-num" /><col class="c-num" /><col class="c-num" />
    <col class="c-kpi" /><col class="c-kpi" /><col class="c-kpi" /><col class="c-mgr" />
  </colgroup>`;

const MASTER_COLS = `
  <colgroup>
    <col class="c-oid" /><col class="c-status" /><col class="c-device" />
    <col class="c-num" /><col class="c-num" /><col class="c-num" />
    <col class="c-kpi" /><col class="c-kpi" /><col class="c-kpi" /><col class="c-mgr" />
  </colgroup>`;

function renderOverview() {
  const tbody = $("#tbody-overview");
  const table = tbody?.closest("table");
  if (table && !table.querySelector("colgroup")) {
    table.insertAdjacentHTML("afterbegin", OVERVIEW_COLS);
  }
  if (table) {
    bindTableSort(
      table,
      () => overviewSort,
      (s) => {
        overviewSort = s;
        saveSort(SORT_OVERVIEW_KEY, s);
      },
      () => renderOverview(),
    );
  }
  const orders = DATA?.orders || [];
  if (!orders.length) {
    tbody.innerHTML = `<tr><td colspan="11" class="muted">Нет данных. Обновите из CRM локально и сделайте git push.</td></tr>`;
    return;
  }
  const sorted = overviewSort ? sortOrders(orders, overviewSort) : orders;
  tbody.innerHTML = sorted.map((r) => orderRowHtml(r)).join("");
  updateSortIndicators(table, overviewSort);
}

function loadCollapsedMasters() {
  try {
    return new Set(JSON.parse(localStorage.getItem(MASTERS_COLLAPSE_KEY) || "[]"));
  } catch {
    return new Set();
  }
}

function saveCollapsedMasters(set) {
  try {
    localStorage.setItem(MASTERS_COLLAPSE_KEY, JSON.stringify([...set]));
  } catch {
    /* ignore */
  }
}

function renderMasters() {
  const root = $("#masters-root");
  const groups = groupByMaster(DATA?.orders || []);
  if (!groups.length) {
    root.innerHTML = `<div class="empty">Нет данных по мастерам.</div>`;
    return;
  }
  const collapsed = loadCollapsedMasters();
  root.innerHTML = `
    <div class="masters-toolbar">
      <button type="button" data-masters-action="expand">Развернуть все</button>
      <button type="button" data-masters-action="collapse">Свернуть все</button>
    </div>
    ${groups
      .map((g) => {
        const key = g.name;
        const isCol = collapsed.has(key);
        const rows = (mastersSort ? sortOrders(g.rows, mastersSort) : g.rows)
          .map((r) => orderRowHtml(r, { engineer: false }))
          .join("");
        return `<article class="master-card${isCol ? " is-collapsed" : ""}" data-master="${esc(key)}">
          <button type="button" class="master-card-head" aria-expanded="${!isCol}">
            <span class="master-chevron" aria-hidden="true">▾</span>
            <h3>${esc(g.name)}
              <span class="meta-bits">KPI ${g.avgKpi ?? "—"} · ${g.count} зак.</span>
            </h3>
          </button>
          <div class="master-card-body">
            <div class="table-wrap">
              <table class="qtable master-table">
                ${MASTER_COLS}
                <thead><tr>${masterHeaderHtml()}</tr></thead>
                <tbody>${rows}</tbody>
              </table>
            </div>
          </div>
        </article>`;
      })
      .join("")}
  `;

  root.querySelectorAll(".master-table").forEach((table) => {
    // Сортировка общая для всех таблиц мастеров.
    table.dataset.sortBound = "";
    bindTableSort(
      table,
      () => mastersSort,
      (s) => {
        mastersSort = s || { key: "kpi", dir: "asc" };
        saveSort(SORT_MASTERS_KEY, mastersSort);
      },
      () => renderMasters(),
    );
  });

  root.querySelectorAll(".master-card-head").forEach((btn) => {
    btn.addEventListener("click", () => {
      const card = btn.closest(".master-card");
      const name = card?.getAttribute("data-master");
      if (!card || !name) return;
      const next = !card.classList.contains("is-collapsed");
      card.classList.toggle("is-collapsed", next);
      btn.setAttribute("aria-expanded", String(!next));
      const set = loadCollapsedMasters();
      if (next) set.add(name);
      else set.delete(name);
      saveCollapsedMasters(set);
    });
  });
  root.querySelectorAll("[data-masters-action]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const action = btn.getAttribute("data-masters-action");
      const cards = [...root.querySelectorAll(".master-card")];
      const set = new Set();
      cards.forEach((card) => {
        const name = card.getAttribute("data-master");
        const collapse = action === "collapse";
        card.classList.toggle("is-collapsed", collapse);
        card.querySelector(".master-card-head")?.setAttribute("aria-expanded", String(!collapse));
        if (collapse && name) set.add(name);
      });
      saveCollapsedMasters(set);
    });
  });
}

function kpiBarColor(kpi) {
  if (kpi == null) return "rgba(93,107,124,0.35)";
  if (kpi >= 70) return "rgba(15,110,86,0.78)";
  if (kpi >= 40) return "rgba(196,92,38,0.72)";
  return "rgba(161,40,40,0.72)";
}

function renderSummary() {
  const groups = groupByMaster(DATA?.orders || []);
  const table = $("#table-summary");
  const tbody = $("#tbody-summary");
  if (table) {
    bindTableSort(
      table,
      () => summarySort,
      (s) => {
        summarySort = s;
        saveSort(SORT_SUMMARY_KEY, s);
      },
      () => renderSummary(),
    );
  }
  const sortedGroups = summarySort ? sortSummaryGroups(groups, summarySort) : groups;
  if (!sortedGroups.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="muted">Нет данных</td></tr>`;
  } else {
    tbody.innerHTML = sortedGroups
      .map(
        (g) => `<tr>
        <td>${esc(g.name)}</td>
        <td>${g.count}</td>
        <td class="${kpiClass(g.avgKpi)}">${g.avgKpi ?? "—"}</td>
        <td>${fmtDays(g.avgTotal)}</td>
        <td>${fmtDays(g.avgWait)}</td>
        <td>${fmtDays(g.avgDiag)}</td>
        <td>${g.avgRework == null ? "—" : fmtDays(g.avgRework)}</td>
        <td>${g.avgCalls == null ? "—" : fmtDays(g.avgCalls)}</td>
      </tr>`,
      )
      .join("");
  }
  updateSortIndicators(table, summarySort);
  if (typeof Chart === "undefined") return;
  const canvas = $("#chart-masters");
  const wrap = canvas?.closest(".chart-wrap");
  if (!canvas) return;
  if (chartMasters) chartMasters.destroy();

  // График: слабее сверху → сильнее снизу (независимо от сортировки таблицы).
  const rows = [...groups].sort((a, b) => (a.avgKpi ?? -1) - (b.avgKpi ?? -1));
  if (wrap) wrap.style.setProperty("--summary-n", String(Math.max(rows.length, 8)));

  chartMasters = new Chart(canvas, {
    type: "bar",
    data: {
      labels: rows.map((g) => g.name),
      datasets: [
        {
          label: "Средний KPI",
          data: rows.map((g) => g.avgKpi),
          backgroundColor: rows.map((g) => kpiBarColor(g.avgKpi)),
          borderRadius: 6,
          borderSkipped: false,
          barThickness: 18,
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      layout: { padding: { right: 36 } },
      scales: {
        x: {
          min: 0,
          max: 100,
          grid: { color: "rgba(28,36,48,0.06)" },
          ticks: { stepSize: 20 },
          title: { display: true, text: "Средний KPI (0–100)" },
        },
        y: {
          grid: { display: false },
          ticks: { font: { size: 12, weight: "600" } },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title(items) {
              const i = items[0]?.dataIndex;
              return i == null ? "" : rows[i]?.name || "";
            },
            label(ctx) {
              const g = rows[ctx.dataIndex];
              if (!g) return "";
              return [
                `KPI: ${g.avgKpi ?? "—"}`,
                `Заказов: ${g.count}`,
                `Всего дн (ср.): ${fmtDays(g.avgTotal)}`,
                `Звонки (ср.): ${g.avgCalls == null ? "—" : fmtDays(g.avgCalls)}`,
                `Дораб. (ср.): ${g.avgRework == null ? "—" : fmtDays(g.avgRework)}`,
              ];
            },
          },
        },
        datalabels: undefined,
      },
    },
    plugins: [
      {
        id: "kpiValueLabels",
        afterDatasetsDraw(chart) {
          const { ctx } = chart;
          const meta = chart.getDatasetMeta(0);
          ctx.save();
          ctx.font = "600 12px IBM Plex Sans, system-ui, sans-serif";
          ctx.fillStyle = "#1c2430";
          meta.data.forEach((bar, i) => {
            const g = rows[i];
            if (!g || g.avgKpi == null) return;
            const { x, y } = bar.tooltipPosition();
            ctx.textBaseline = "middle";
            ctx.fillText(String(g.avgKpi), x + 8, y);
          });
          ctx.restore();
        },
      },
    ],
  });
}

function renderDynamics() {
  const days = DATA?.daily_stats || [];
  const empty = $("#dynamics-empty");
  const body = $("#dynamics-body");
  if (!days.length) {
    empty.hidden = false;
    body.hidden = true;
    return;
  }
  empty.hidden = true;
  body.hidden = false;
  $("#dynamics-meta").textContent = `Точек: ${days.length} · с ${fmtDate(days[0].day)} по ${fmtDate(
    days[days.length - 1].day,
  )}`;
  if (typeof Chart === "undefined") return;
  const labels = days.map((d) => {
    const m = String(d.day || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m ? `${m[3]}.${m[2]}` : d.day;
  });
  const series = (key) => days.map((d) => (d[key] == null ? null : Number(d[key])));
  if (chartKpi) chartKpi.destroy();
  if (chartDays) chartDays.destroy();
  const opts = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { position: "bottom", labels: { boxWidth: 12, usePointStyle: true } },
    },
    scales: {
      x: { grid: { color: "rgba(28,36,48,0.05)" } },
      y: { grid: { color: "rgba(28,36,48,0.06)" } },
    },
  };
  chartKpi = new Chart($("#chart-kpi"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "KPI",
          data: series("avg_order_kpi"),
          borderColor: "#0f6e56",
          backgroundColor: "rgba(15,110,86,0.12)",
          fill: true,
          tension: 0.3,
          spanGaps: true,
          pointRadius: 4,
        },
        {
          label: "Звонки",
          data: series("avg_calls_kpi"),
          borderColor: "#1a5f8a",
          tension: 0.3,
          spanGaps: true,
          pointRadius: 4,
        },
        {
          label: "Дораб.",
          data: series("avg_rework_kpi"),
          borderColor: "#c45c26",
          tension: 0.3,
          spanGaps: true,
          pointRadius: 4,
        },
      ],
    },
    options: { ...opts, scales: { ...opts.scales, y: { ...opts.scales.y, min: 0, max: 100 } } },
  });
  chartDays = new Chart($("#chart-days"), {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          label: "Всего дн",
          data: series("avg_total_days"),
          borderColor: "#a12828",
          tension: 0.3,
          spanGaps: true,
          pointRadius: 4,
        },
        {
          label: "До мастера",
          data: series("avg_wait_master_days"),
          borderColor: "#a15c12",
          tension: 0.3,
          spanGaps: true,
          pointRadius: 4,
        },
        {
          label: "До диагн.",
          data: series("avg_diag_days"),
          borderColor: "#5d6b7c",
          tension: 0.3,
          spanGaps: true,
          pointRadius: 4,
        },
      ],
    },
    options: opts,
  });
}

function sevLabel(s) {
  return ({ critical: "крит.", high: "высок.", medium: "средн." }[s] || s || "—");
}

function renderAnalysis() {
  const a = DATA?.analysis;
  const empty = $("#analysis-empty");
  const root = $("#analysis-root");
  if (!a || !a.orders_count) {
    empty.hidden = false;
    root.hidden = true;
    root.innerHTML = "";
    return;
  }
  empty.hidden = true;
  root.hidden = false;
  const p = a.portfolio || {};
  const bands = p.kpi_bands || {};
  const dyn = a.dynamics || {};
  const focus = (a.focus_areas || [])
    .map(
      (f) => `<div class="focus is-${esc(f.severity || "")}">
      <strong>${esc(f.title)}</strong> [${esc(sevLabel(f.severity))}]
      <div class="muted">${esc(f.detail || "")}</div>
      <ul>${(f.actions || []).map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
    </div>`,
    )
    .join("");
  const urgent = (a.urgent || [])
    .slice(0, 30)
    .map((u, i) => {
      const link = u.url
        ? `<a href="${esc(u.url)}" target="_blank" rel="noopener">№${esc(u.order_id)}</a>`
        : `№${esc(u.order_id)}`;
      return `<article class="urgent is-${esc(u.severity || "")}">
        <h4>${i + 1}. ${link} · ${esc(sevLabel(u.severity))} · KPI ${esc(u.order_kpi ?? "—")} · ${esc(u.total_days ?? "—")} дн</h4>
        <div class="muted">${esc(u.engineer || "—")} · ${esc(u.status || "—")} · ${esc(u.device || "—")}</div>
        <ul>${(u.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>
        <ul>${(u.actions || []).map((r) => `<li>→ ${esc(r)}</li>`).join("")}</ul>
      </article>`;
    })
    .join("");
  root.innerHTML = `
    <div class="analysis-hero">
      <div>
        <div class="score-num">${esc(a.health?.score ?? "—")}</div>
        <span class="score-label">${esc(a.health?.label || "—")}</span>
      </div>
      <div>
        <p><strong>${esc(a.headline || "")}</strong></p>
        <p class="muted">${esc(a.health?.summary || "")}</p>
        <p class="muted">Собран: ${esc(fmtDate(a.generated_at))} · срочных ${esc(a.urgent_total ?? (a.urgent || []).length)}</p>
      </div>
    </div>
    <div class="card">
      <h3>Портфель</h3>
      <div class="metrics">
        ${[
          ["KPI", p.avg_order_kpi],
          ["Звонки", p.avg_calls_kpi],
          ["Дораб.", p.avg_rework_kpi],
          ["Всего дн", p.avg_total_days],
          ["≥70", bands.good],
          ["40–69", bands.mid],
          ["<40", bands.bad],
          ["≥45 дн", p.long_orders_45d],
        ]
          .map(
            ([l, v]) =>
              `<div class="metric"><span>${esc(l)}</span><strong>${
                v == null ? "—" : esc(typeof v === "number" ? Math.round(v * 10) / 10 : v)
              }</strong></div>`,
          )
          .join("")}
      </div>
    </div>
    <div class="card">
      <h3>Динамика</h3>
      <ul>${(dyn.narrative || []).map((n) => `<li>${esc(n)}</li>`).join("") || "<li>—</li>"}</ul>
    </div>
    <div class="card"><h3>Зоны внимания</h3>${focus || '<p class="muted">—</p>'}</div>
    <div class="card">
      <h3>Что хорошо</h3>
      <ul>${(a.positives || []).map((x) => `<li>${esc(x)}</li>`).join("") || "<li>—</li>"}</ul>
    </div>
    <div class="card"><h3>Срочные (топ)</h3>${urgent || '<p class="muted">Нет</p>'}</div>
  `;
}

function setTab(id) {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.tab === id);
  });
  document.querySelectorAll(".panel").forEach((panel) => {
    const on = panel.id === `panel-${id}`;
    panel.classList.toggle("is-active", on);
    panel.hidden = !on;
  });
  if (id === "masters") renderMasters();
  if (id === "summary") renderSummary();
  if (id === "dynamics") renderDynamics();
  if (id === "analysis") renderAnalysis();
}

async function boot() {
  bindTips();
  overviewSort = loadSort(SORT_OVERVIEW_KEY) || { key: "kpi", dir: "asc" };
  mastersSort = loadSort(SORT_MASTERS_KEY) || { key: "kpi", dir: "asc" };
  summarySort = loadSort(SORT_SUMMARY_KEY) || { key: "kpi", dir: "desc" };
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.addEventListener("click", () => setTab(btn.dataset.tab));
  });
  try {
    const res = await fetch(`${DATA_URL}?t=${Date.now()}`);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    DATA = await res.json();
    const n = DATA.counts?.orders ?? DATA.orders?.length ?? 0;
    $("#export-meta").innerHTML = DATA.exported_at
      ? `Снимок: <strong>${esc(fmtDate(DATA.exported_at))}</strong><br />заказов: ${esc(n)}`
      : `data.json пустой · заказов: ${esc(n)}`;
    renderOverview();
  } catch (err) {
    $("#export-meta").textContent = `Ошибка загрузки: ${err.message || err}`;
    $("#tbody-overview").innerHTML = `<tr><td colspan="11" class="muted">Не удалось загрузить data.json</td></tr>`;
  }
}

boot();
