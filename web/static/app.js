const state = {
  conversationId: null,
  charts: [],
};

const $ = (sel) => document.querySelector(sel);
const messagesEl = $("#messages");

const PROCESSES_TAB_KEY = "jarvis.processes.tab";
let processesTab = "upsell";

function showView(view, opts = {}) {
  const resolved = view === "vyrobotka" ? "processes" : view;
  document.querySelectorAll(".nav-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.view === resolved);
  });
  document.querySelectorAll(".nav-sub-btn").forEach((b) => {
    const on =
      resolved === "processes" &&
      b.getAttribute("data-processes-tab") === (opts.processesTab || processesTab);
    b.classList.toggle("is-active", on);
  });
  document.querySelectorAll(".nav-group").forEach((g) => {
    g.classList.toggle("is-open", g.getAttribute("data-nav-group") === resolved);
  });
  document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
  const el = $(`#view-${resolved}`);
  if (el) el.classList.add("active");
  document.querySelector(".app")?.classList.toggle("app--quality", resolved === "quality");
  document.querySelector(".app")?.classList.toggle(
    "app--vyrobotka",
    resolved === "processes",
  );
  document.querySelector(".app")?.classList.toggle("app--processes", resolved === "processes");
  if (resolved === "quality") {
    // Сначала показать вкладку, потом мерить столбцы (display:none даёт width=0).
    requestAnimationFrame(() => {
      initQualityTabs();
      initQualityColResize();
      loadQualityOrders().then((sync) => {
        initQualityColResize();
        if (sync?.status === "running") startQualityPoll();
      });
    });
  } else {
    stopQualityPoll();
  }
  if (resolved === "processes") {
    if (opts.processesTab) setProcessesTab(opts.processesTab);
    else initProcessesTabs();
    requestAnimationFrame(() => {
      initVyrobotkaSplits();
      loadVyrobotkaStats().then((sync) => {
        if (sync?.status === "running") startVyrobotkaPoll();
        resizeVyrobotkaCharts();
      });
    });
  } else {
    stopVyrobotkaPoll();
    stopVyrobotkaVerifyPoll();
  }
  if (resolved === "vitrine-users") {
    loadVitrineUsers();
  }
  if (resolved === "updates") {
    loadUpdatesStatus();
    startUpdatesPoll();
  } else {
    stopUpdatesPoll();
  }
}

function setProcessesTab(tab) {
  const id = tab === "debt" ? "debt" : "upsell";
  processesTab = id;
  try {
    localStorage.setItem(PROCESSES_TAB_KEY, id);
  } catch {
    /* ignore */
  }
  const root = $("#view-processes");
  if (!root) return;
  root.querySelectorAll(".quality-tab[data-processes-tab]").forEach((btn) => {
    const on = btn.getAttribute("data-processes-tab") === id;
    btn.classList.toggle("is-active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  document.querySelectorAll(".nav-sub-btn[data-processes-tab]").forEach((btn) => {
    btn.classList.toggle("is-active", btn.getAttribute("data-processes-tab") === id);
  });
  const upsell = $("#vyrobotka-upsell-body");
  const debt = $("#vyrobotka-debt-body");
  const empty = $("#vyrobotka-empty");
  const hasData = !(empty && !empty.hidden);
  if (upsell) upsell.hidden = !(hasData && id === "upsell");
  if (debt) debt.hidden = !(hasData && id === "debt");
  if (id === "debt") {
    requestAnimationFrame(() => resizeVyrobotkaCharts());
  }
}

function initProcessesTabs() {
  const root = $("#view-processes");
  if (!root) return;
  if (!root.dataset.processesTabsReady) {
    root.dataset.processesTabsReady = "1";
    root.querySelectorAll(".quality-tab[data-processes-tab]").forEach((btn) => {
      btn.addEventListener("click", () => setProcessesTab(btn.getAttribute("data-processes-tab")));
    });
  }
  let saved = "upsell";
  try {
    saved = localStorage.getItem(PROCESSES_TAB_KEY) || "upsell";
  } catch {
    saved = "upsell";
  }
  setProcessesTab(saved);
}

document.querySelectorAll(".nav-btn[data-view]").forEach((btn) => {
  btn.addEventListener("click", () => showView(btn.dataset.view));
});
document.querySelectorAll(".nav-sub-btn[data-view]").forEach((btn) => {
  btn.addEventListener("click", () =>
    showView(btn.dataset.view, { processesTab: btn.getAttribute("data-processes-tab") }),
  );
});

$("#quality-back-btn")?.addEventListener("click", () => showView("chat"));
$("#vyrobotka-back-btn")?.addEventListener("click", () => showView("chat"));

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function inlineMarkdown(text) {
  let s = escapeHtml(text);
  s = s.replace(/`([^`]+)`/g, "<code>$1</code>");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  s = s.replace(/(?<!\*)\*([^*\n]+)\*(?!\*)/g, "<em>$1</em>");
  return s;
}

function isTableSeparator(line) {
  return /^\s*\|?[\s:|-]+\|\s*$/.test(line) || /^\s*\|?(?:\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$/.test(line);
}

function parseTableRow(line) {
  let s = line.trim();
  if (s.startsWith("|")) s = s.slice(1);
  if (s.endsWith("|")) s = s.slice(0, -1);
  return s.split("|").map((c) => c.trim());
}

function renderMarkdown(src, { stripTables = false } = {}) {
  // Drop fake chart image refs the model sometimes invents
  let text = String(src || "")
    .replace(/!\[[^\]]*]\(\s*charts?\[[^\]]*]\s*\)/gi, "")
    .replace(/!\[[^\]]*]\(\s*charts\/[^\)]*\)/gi, "")
    .trim();

  const lines = text.split(/\r?\n/);
  const out = [];
  let i = 0;
  let para = [];

  const flushPara = () => {
    if (!para.length) return;
    const body = para.map(inlineMarkdown).join("<br>");
    out.push(`<p>${body}</p>`);
    para = [];
  };

  while (i < lines.length) {
    const line = lines[i];

    // Markdown table
    if (
      line.includes("|") &&
      i + 1 < lines.length &&
      isTableSeparator(lines[i + 1])
    ) {
      flushPara();
      if (stripTables) {
        i += 2;
        while (i < lines.length && lines[i].includes("|") && lines[i].trim()) i += 1;
        continue;
      }
      const header = parseTableRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) {
        if (isTableSeparator(lines[i])) {
          i += 1;
          continue;
        }
        rows.push(parseTableRow(lines[i]));
        i += 1;
      }
      const thead = `<tr>${header.map((c) => `<th>${inlineMarkdown(c)}</th>`).join("")}</tr>`;
      const tbody = rows
        .map((r) => {
          const cells = header.map((_, idx) => r[idx] ?? "");
          return `<tr>${cells.map((c) => `<td>${inlineMarkdown(c)}</td>`).join("")}</tr>`;
        })
        .join("");
      out.push(
        `<div class="md-table-wrap"><table class="md-table"><thead>${thead}</thead><tbody>${tbody}</tbody></table></div>`
      );
      continue;
    }

    // Headings
    const hm = /^(#{1,3})\s+(.+)$/.exec(line.trim());
    if (hm) {
      flushPara();
      const level = hm[1].length;
      out.push(`<h${level + 2} class="md-h">${inlineMarkdown(hm[2])}</h${level + 2}>`);
      i += 1;
      continue;
    }

    // Horizontal rule
    if (/^\s*-{3,}\s*$/.test(line)) {
      flushPara();
      out.push("<hr class='md-hr' />");
      i += 1;
      continue;
    }

    // Blank line → new paragraph
    if (!line.trim()) {
      flushPara();
      i += 1;
      continue;
    }

    // Unordered list
    if (/^\s*[-*•]\s+/.test(line)) {
      flushPara();
      const items = [];
      while (i < lines.length && /^\s*[-*•]\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*[-*•]\s+/, ""));
        i += 1;
      }
      out.push(`<ul>${items.map((it) => `<li>${inlineMarkdown(it)}</li>`).join("")}</ul>`);
      continue;
    }

    para.push(line);
    i += 1;
  }
  flushPara();
  return out.join("") || (stripTables ? "" : `<p>${escapeHtml(text)}</p>`);
}

function renderStructuredTable(table) {
  const wrap = document.createElement("div");
  wrap.className = "md-table-wrap structured-table";
  if (table.title) {
    const title = document.createElement("div");
    title.className = "md-table-title";
    title.textContent = table.title;
    wrap.appendChild(title);
  }
  const el = document.createElement("table");
  el.className = "md-table";
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  (table.columns || []).forEach((c) => {
    const th = document.createElement("th");
    th.textContent = c;
    hr.appendChild(th);
  });
  thead.appendChild(hr);
  el.appendChild(thead);
  const tbody = document.createElement("tbody");
  (table.rows || []).forEach((row) => {
    const tr = document.createElement("tr");
    (table.columns || []).forEach((_, idx) => {
      const td = document.createElement("td");
      td.textContent = row[idx] ?? "";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  el.appendChild(tbody);
  if (table.footer?.length) {
    const tfoot = document.createElement("tfoot");
    const tr = document.createElement("tr");
    (table.columns || []).forEach((_, idx) => {
      const td = document.createElement("td");
      td.textContent = table.footer[idx] ?? "";
      tr.appendChild(td);
    });
    tfoot.appendChild(tr);
    el.appendChild(tfoot);
  }
  wrap.appendChild(el);
  return wrap;
}

function fmtMoney(n) {
  const num = Number(n) || 0;
  return num.toLocaleString("ru-RU", {
    maximumFractionDigits: 2,
    minimumFractionDigits: Number.isInteger(num) ? 0 : 2,
  });
}

function computeCashJournal(journal) {
  let cash = Number(journal.opening_cash) || 0;
  let card = Number(journal.opening_card) || 0;
  for (const line of journal.lines || []) {
    if (line.is_checkpoint) continue;
    const a = Math.abs(Number(line.amount) || 0);
    switch (line.action) {
      case "cash_out":
        cash -= a;
        break;
      case "cash_in":
        cash += a;
        break;
      case "card_out":
        card -= a;
        break;
      case "card_in":
        card += a;
        break;
      case "cash_to_card":
        cash -= a;
        card += a;
        break;
      case "card_to_cash":
        card -= a;
        cash += a;
        break;
      default:
        break;
    }
  }
  return { cash, card };
}

function applyWidgetLine(cash, card, line) {
  const a = Math.abs(Number(line.amount) || 0);
  switch (line.action) {
    case "cash_out":
      return { cash: cash - a, card };
    case "cash_in":
      return { cash: cash + a, card };
    case "card_out":
      return { cash, card: card - a };
    case "card_in":
      return { cash, card: card + a };
    case "cash_to_card":
      return { cash: cash - a, card: card + a };
    case "card_to_cash":
      return { cash: cash + a, card: card - a };
    default:
      return { cash, card };
  }
}

function parseBalanceCheckpoint(raw) {
  const body = String(raw || "")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  const cashRe = /касс?[аыу]?\s*[:\-–—]\s*([\d\s.,]+)/i;
  const factRe = /касс?[аыу]?\s+факт\s*:?\s*([\d\s.,]+)/i;
  const cardRe = /карт[аыу]?\s*[:\-–—]\s*([\d\s.,]+)/i;
  const cashM = body.match(cashRe);
  const factM = cashM ? null : body.match(factRe);
  const cardM = body.match(cardRe);
  let rest = body;
  if (cashM) rest = rest.replace(cashRe, " ");
  else if (factM) rest = rest.replace(factRe, " ");
  if (cardM) rest = rest.replace(cardRe, " ");
  rest = rest.replace(/\s+/g, " ").trim();
  rest = rest.replace(/(?:грн|uah|₴)\.?\s*$/i, "").trim();
  if (rest || (!cashM && !factM && !cardM)) return null;
  const out = {};
  const cashVal = cashM ? cashM[1] : factM ? factM[1] : null;
  if (cashVal) {
    const v = parseMoneyLoose(cashVal);
    if (v != null) out.written_cash = Math.abs(v);
  }
  if (cardM) {
    const v = parseMoneyLoose(cardM[1]);
    if (v != null) out.written_card = Math.abs(v);
  }
  return Object.keys(out).length ? out : null;
}

function parseMoneyLoose(raw) {
  const s = String(raw || "")
    .replace(/\u00a0/g, " ")
    .replace(/\s/g, "")
    .replace(",", ".")
    .replace(/[^\d.+-]/g, "");
  const m = s.match(/^([+-]?)(\d+(?:\.\d+)?)/);
  if (!m) return null;
  return (m[1] === "-" ? -1 : 1) * parseFloat(m[2]);
}

function isQuoteLine(raw) {
  const s = String(raw || "")
    .replace(/[\u200e\u200f\u202a-\u202e\u2066-\u2069\ufeff]/g, "")
    .replace(/\u00a0/g, " ")
    .trim();
  return /^>/.test(s);
}

function ensureLineMeta(data) {
  for (const line of data.lines || []) {
    if (!line.is_quote && isQuoteLine(line.raw)) {
      line.is_quote = true;
      line.action = "ignore";
    }
    if (!line.is_checkpoint && !line.is_quote) {
      const cp = parseBalanceCheckpoint(line.raw);
      if (cp) {
        line.is_checkpoint = true;
        line.action = "ignore";
        line.order_id = null;
        if (cp.written_cash != null) line.written_cash = cp.written_cash;
        if (cp.written_card != null) line.written_card = cp.written_card;
      }
    }
  }
}

function enrichCheckpoints(data) {
  ensureLineMeta(data);
  let cash = Number(data.opening_cash) || 0;
  let card = Number(data.opening_card) || 0;
  for (const line of data.lines || []) {
    if (line.is_checkpoint) {
      line.calc_cash = cash;
      line.calc_card = card;
      if (line.written_cash != null) {
        line.cash_match = Math.abs(cash - Number(line.written_cash)) <= 1;
      }
      if (line.written_card != null) {
        line.card_match = Math.abs(card - Number(line.written_card)) <= 1;
      }
      continue;
    }
    ({ cash, card } = applyWidgetLine(cash, card, line));
  }
}

function checkpointLineHtml(line) {
  const parts = [];
  if (line.written_cash != null) {
    const ok = line.cash_match !== false;
    if (ok) {
      parts.push(`Касса: ${fmtMoney(line.written_cash)} = расчёт ${fmtMoney(line.calc_cash)} ✓`);
    } else {
      const delta = Number(line.calc_cash) - Number(line.written_cash);
      const sign = delta > 0 ? "+" : "−";
      parts.push(
        `Касса: написано ${fmtMoney(line.written_cash)}, расчёт ${fmtMoney(line.calc_cash)} ✗ (Δ ${sign}${fmtMoney(Math.abs(delta))})`
      );
    }
  }
  if (line.written_card != null) {
    const ok = line.card_match !== false;
    if (ok) {
      parts.push(`Карта: ${fmtMoney(line.written_card)} = расчёт ${fmtMoney(line.calc_card)} ✓`);
    } else {
      const delta = Number(line.calc_card) - Number(line.written_card);
      const sign = delta > 0 ? "+" : "−";
      parts.push(
        `Карта: написано ${fmtMoney(line.written_card)}, расчёт ${fmtMoney(line.calc_card)} ✗ (Δ ${sign}${fmtMoney(Math.abs(delta))})`
      );
    }
  }
  return parts.join(" · ");
}

const CJ_ACTION_ICONS = {
  cash_in: `<svg viewBox="0 0 32 32" aria-hidden="true"><ellipse cx="16" cy="22" rx="9" ry="6" fill="#c4a574" stroke="#8a6b3d" stroke-width="1.2"/><path d="M10 18c0-5 2.5-10 6-10s6 5 6 10" fill="#d4b896" stroke="#8a6b3d" stroke-width="1.2"/><circle cx="24" cy="10" r="6" fill="#2e7d32"/><path d="M24 7v6M21 10h6" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>`,
  cash_out: `<svg viewBox="0 0 32 32" aria-hidden="true"><ellipse cx="16" cy="22" rx="9" ry="6" fill="#c4a574" stroke="#8a6b3d" stroke-width="1.2"/><path d="M10 18c0-5 2.5-10 6-10s6 5 6 10" fill="#d4b896" stroke="#8a6b3d" stroke-width="1.2"/><circle cx="24" cy="10" r="6" fill="#c62828"/><path d="M21 10h6" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>`,
  card_in: `<svg viewBox="0 0 32 32" aria-hidden="true"><rect x="4" y="10" width="20" height="14" rx="2" fill="#5c6bc0" stroke="#3949ab" stroke-width="1.2"/><path d="M4 15h20" stroke="#fff" stroke-width="2"/><rect x="7" y="19" width="6" height="2.5" rx="0.5" fill="#c5cae9"/><circle cx="24" cy="10" r="6" fill="#1565c0"/><path d="M24 7v6M21 10h6" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>`,
  card_out: `<svg viewBox="0 0 32 32" aria-hidden="true"><rect x="4" y="10" width="20" height="14" rx="2" fill="#8e24aa" stroke="#6a1b9a" stroke-width="1.2"/><path d="M4 15h20" stroke="#fff" stroke-width="2"/><rect x="7" y="19" width="6" height="2.5" rx="0.5" fill="#e1bee7"/><circle cx="24" cy="10" r="6" fill="#ad1457"/><path d="M21 10h6" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>`,
  cash_to_card: `<svg viewBox="0 0 32 32" aria-hidden="true"><ellipse cx="9" cy="22" rx="6" ry="4.5" fill="#c4a574" stroke="#8a6b3d" stroke-width="1"/><path d="M5.5 19c0-3.5 1.6-7 3.5-7s3.5 3.5 3.5 7" fill="#d4b896" stroke="#8a6b3d" stroke-width="1"/><path d="M15 16h4M17.5 13.5L21 16l-3.5 2.5" fill="none" stroke="#1565c0" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><rect x="20" y="12" width="10" height="8" rx="1.2" fill="#5c6bc0" stroke="#3949ab" stroke-width="1"/><path d="M20 15h10" stroke="#fff" stroke-width="1.4"/></svg>`,
  card_to_cash: `<svg viewBox="0 0 32 32" aria-hidden="true"><rect x="2" y="12" width="10" height="8" rx="1.2" fill="#5c6bc0" stroke="#3949ab" stroke-width="1"/><path d="M2 15h10" stroke="#fff" stroke-width="1.4"/><path d="M13 16h4M15.5 13.5L19 16l-3.5 2.5" fill="none" stroke="#2e7d32" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/><ellipse cx="24" cy="22" rx="6" ry="4.5" fill="#c4a574" stroke="#8a6b3d" stroke-width="1"/><path d="M20.5 19c0-3.5 1.6-7 3.5-7s3.5 3.5 3.5 7" fill="#d4b896" stroke="#8a6b3d" stroke-width="1"/></svg>`,
  ignore: `<svg viewBox="0 0 32 32" aria-hidden="true"><path d="M10 10l12 12M22 10L10 22" stroke="#c62828" stroke-width="3.2" stroke-linecap="round"/></svg>`,
};

const CJ_LAST_CASHBOX_KEY = "jarvis_cj_last_cashbox_id";
const CJ_LAST_CARD_CASHBOX_KEY = "jarvis_cj_last_card_cashbox_id";

function getLastCashboxId(preferCard = false) {
  try {
    const key = preferCard ? CJ_LAST_CARD_CASHBOX_KEY : CJ_LAST_CASHBOX_KEY;
    return localStorage.getItem(key) || "";
  } catch {
    return "";
  }
}

function setLastCashboxId(id, preferCard = false) {
  try {
    if (!id) return;
    const key = preferCard ? CJ_LAST_CARD_CASHBOX_KEY : CJ_LAST_CASHBOX_KEY;
    localStorage.setItem(key, String(id));
  } catch {
    /* ignore */
  }
}

function pickPaymentCashbox(cashboxes, formSelected, { preferCard = false } = {}) {
  const list = cashboxes || [];
  const last = getLastCashboxId(preferCard);
  if (last && list.some((b) => String(b.id) === String(last))) return String(last);
  if (preferCard) {
    const cardBox = list.find((b) => /карт/i.test(String(b.name || "")));
    if (cardBox) return String(cardBox.id);
  }
  if (formSelected && list.some((b) => String(b.id) === String(formSelected))) {
    return String(formSelected);
  }
  return list[0] ? String(list[0].id) : "";
}

function isPartsAttachLine(line) {
  if (!line || line.action !== "cash_out" || !line.order_id) return false;
  if (line.is_breakdown_total) return false;
  const raw = String(line.raw || line.note || "").trim();
  const core = raw.replace(/^зч\.?\s+/i, "").trim();
  const oid = String(line.order_id).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const n = core.toLowerCase().replace(/ё/g, "е");
  if (/(^|\s)(зп|зарплат\w*)(\s|$)/.test(n)) return false;
  // «123956 -256 …» / «123959 -427 зч»
  if (new RegExp(`^${oid}\\s*[-−–]\\s*\\d+(?:[.,]\\d+)?\\b`).test(core)) {
    return true;
  }
  // «122114 - помпа - 1500»
  if (new RegExp(`^${oid}\\s*[-−–]\\s*.+\\s*[-−–]\\s*\\d+(?:[.,]\\d+)?\\s*$`).test(core)) {
    return true;
  }
  // «121985 - Шлейфы , датчики, 2000»
  if (new RegExp(`^${oid}\\s*[-−–]\\s*.+,\\s*\\d+(?:[.,]\\d+)?\\s*$`).test(core)) {
    return true;
  }
  return false;
}

function importableCashJournalLines(lines) {
  return (lines || []).filter((l) => {
    if (l.posted) return false;
    if (l.is_quote || l.is_checkpoint || l.is_breakdown_total) return false;
    const amt = Math.abs(Number(l.amount) || 0);
    if (amt <= 0) return false;
    if (isPartsAttachLine(l)) return true;
    if (l.is_breakdown) return false;
    if ((l.action === "cash_in" || l.action === "card_in") && l.order_id) return true;
    if (l.action === "cash_out" && !l.order_id) return true;
    return false;
  });
}

function closeCashImportModal() {
  document.getElementById("cj-import-modal")?.remove();
}

function guessCategoryId(categories, note) {
  const n = String(note || "").toLowerCase();
  const rules = [
    [/такси|бензин|логістик|логистик|почт/, /логистик|почт|транспорт/i],
    [/зп|зарплат/, /зарплат/i],
    [/аренда|оренда/, /аренд/i],
    [/смс|телефон|связь|зв.язок/, /телефон|смс|связ|телефони/i],
  ];
  for (const [noteRe, catRe] of rules) {
    if (!noteRe.test(n)) continue;
    const hit = categories.find((c) => catRe.test(c.name || ""));
    if (hit) return String(hit.id);
  }
  return "";
}

function guessContractorId(contractors, note) {
  const n = String(note || "").toLowerCase();
  const hit = contractors.find((c) => {
    const name = String(c.name || "").toLowerCase();
    return name && n.includes(name);
  });
  return hit ? String(hit.id) : "";
}

async function openCashImportFlow(lines, { onUpdate } = {}) {
  const queue = importableCashJournalLines(lines);
  if (!queue.length) {
    alert(
      "Нет строк для внесения: «в кассу»/«в карту» с квитанцией, «из кассы» без заказа (расход) или «из кассы» с номером (привязка запчасти)."
    );
    return;
  }
  await runCashImportStep(queue, 0, { onUpdate });
}

async function runCashImportStep(queue, index, { onUpdate } = {}) {
  closeCashImportModal();
  if (index >= queue.length) {
    alert("Готово: очередь внесения завершена.");
    return;
  }
  const line = queue[index];
  const overlay = document.createElement("div");
  overlay.id = "cj-import-modal";
  overlay.className = "cj-import-overlay";
  const card = document.createElement("div");
  card.className = "cj-import-card";
  const loadingLabel =
    isPartsAttachLine(line)
      ? `Загрузка квитанции №${line.order_id} (запчасть)…`
      : line.action === "cash_out"
        ? "Загрузка формы расхода…"
        : `Загрузка квитанции №${line.order_id}…`;
  card.innerHTML = `<div class="cj-import-loading">${loadingLabel}</div>`;
  overlay.appendChild(card);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeCashImportModal();
  });
  document.body.appendChild(overlay);

  let preview;
  try {
    const resp = await fetch("/api/cash-journal/import/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        order_id: line.order_id ? String(line.order_id) : null,
        amount: Number(line.amount),
        action: line.action,
        line_id: line.id,
        cashbox_id: getLastCashboxId() || null,
        note: line.raw || line.note || "",
      }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || data.error || resp.statusText);
    preview = data;
  } catch (err) {
    card.innerHTML = `<div class="cj-import-error">Ошибка: ${err.message || err}</div>
      <div class="cj-import-actions"></div>`;
    const actionsEl = card.querySelector(".cj-import-actions");
    addImportBtn(actionsEl, "Закрыть", "is-muted", closeCashImportModal);
    addImportBtn(actionsEl, "Пропустить", "is-skip", () =>
      runCashImportStep(queue, index + 1, { onUpdate })
    );
    return;
  }

  if (preview.kind === "cashbox_expense") {
    await renderCashExpenseImport(card, {
      queue,
      index,
      line,
      preview,
      onUpdate,
    });
    return;
  }

  if (preview.kind === "parts_attach") {
    await renderPartsAttachImport(card, {
      queue,
      index,
      line,
      preview,
      onUpdate,
    });
    return;
  }

  await renderCashPaymentImport(card, {
    queue,
    index,
    line,
    preview,
    onUpdate,
  });
}

function addImportBtn(parent, label, cls, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = `cj-import-btn ${cls || ""}`;
  b.textContent = label;
  b.addEventListener("click", onClick);
  parent.appendChild(b);
  return b;
}

function wireSearchCombo(card, {
  combo,
  items,
  getSelected,
  setSelected,
  disabled,
  onPick,
}) {
  const root = card.querySelector(`[data-combo="${combo}"]`);
  if (!root || disabled) return;
  const input = root.querySelector(".cj-combo-input");
  const list = root.querySelector(".cj-combo-list");
  if (!input || !list) return;

  const hide = () => list.classList.add("is-hidden");
  const showFiltered = (q) => {
    const qq = String(q || "")
      .trim()
      .toLowerCase();
    const filtered = items.filter(
      (c) => !qq || String(c.name || "").toLowerCase().includes(qq)
    );
    if (!filtered.length) {
      list.innerHTML = `<li class="cj-combo-empty">Ничего не найдено</li>`;
    } else {
      const selected = String(getSelected() || "");
      list.innerHTML = filtered
        .slice(0, 100)
        .map((c) => {
          const id = String(c.id);
          const active = id === selected ? " is-active" : "";
          return `<li class="cj-combo-item${active}" role="option" data-id="${escapeHtml(id)}">${escapeHtml(c.name || id)}</li>`;
        })
        .join("");
    }
    list.classList.remove("is-hidden");
  };

  const applyPick = (id, label) => {
    setSelected(id || "");
    if (label != null) input.value = label;
    hide();
    onPick?.(id || "");
  };

  const pickExact = (text) => {
    const t = String(text || "").trim().toLowerCase();
    if (!t) {
      applyPick("", "");
      return;
    }
    const match = items.find((c) => String(c.name || "").toLowerCase() === t);
    if (match) applyPick(String(match.id), match.name || String(match.id));
    else setSelected("");
  };

  input.addEventListener("focus", () => showFiltered(input.value));
  input.addEventListener("input", () => {
    setSelected("");
    showFiltered(input.value);
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      hide();
      input.blur();
    } else if (e.key === "Enter") {
      e.preventDefault();
      const first = list.querySelector(".cj-combo-item");
      if (first && !list.classList.contains("is-hidden")) {
        applyPick(first.dataset.id || "", first.textContent || "");
      } else {
        pickExact(input.value);
        hide();
      }
    }
  });
  list.addEventListener("mousedown", (e) => {
    const li = e.target.closest(".cj-combo-item[data-id]");
    if (!li) return;
    e.preventDefault();
    applyPick(li.dataset.id || "", li.textContent || "");
  });
  input.addEventListener("blur", () => {
    setTimeout(() => {
      if (!getSelected()) pickExact(input.value);
      if (getSelected()) {
        const name =
          items.find((c) => String(c.id) === String(getSelected()))?.name || "";
        if (name) input.value = name;
      }
      hide();
    }, 120);
  });
}

async function renderCashPaymentImport(card, { queue, index, line, preview, onUpdate }) {
  const order = preview.order || {};
  const pay = order.payment || {};
  const form = preview.payment_form || {};
  const cashboxes = form.cashboxes || [];
  const preferCard = line.action === "card_in";
  let step = "preview";
  let selectedCashbox = pickPaymentCashbox(cashboxes, form.selected_cashbox_id, {
    preferCard,
  });

  function render() {
    const feedHtml = (order.live_feed || [])
      .slice(0, 30)
      .map(
        (f) =>
          `<div class="cj-feed-row"><span class="cj-feed-date">${escapeHtml(f.date || "")}</span>
           <span class="cj-feed-author">${escapeHtml(f.author || "")}</span>
           <span class="cj-feed-text">${escapeHtml(f.text || "")}</span></div>`
      )
      .join("");
    const boxOpts = cashboxes
      .map((b) => {
        const bal = b.total_uah != null ? ` (${fmtMoney(b.total_uah)})` : "";
        const sel = String(b.id) === String(selectedCashbox) ? " selected" : "";
        return `<option value="${escapeHtml(String(b.id))}"${sel}>${escapeHtml(b.name || b.id)}${escapeHtml(bal)}</option>`;
      })
      .join("");
    const headTitle = preferCard ? "Внесение в базу · на карту" : "Внесение в базу · в кассу";
    const boxTitle = preferCard ? "Карта (касса CRM)" : "Касса";

    card.innerHTML = `
      <div class="cj-import-head">
        <strong>${headTitle}</strong>
        <span>${index + 1} / ${queue.length}</span>
      </div>
      <div class="cj-import-line">${escapeHtml(line.raw || line.note || "")} → <b>${fmtMoney(line.amount)}</b></div>
      <div class="cj-import-section">
        <div class="cj-import-sec-title">Оплата
          <a href="${escapeHtml(order.url || "#")}" target="_blank" rel="noopener">№${escapeHtml(order.order_id || "")}</a>
        </div>
        <div class="cj-pay-grid">
          <div><span>Форма оплаты</span><strong>${escapeHtml(pay.payment_method || "—")}</strong></div>
          <div><span>Стоимость ремонта</span><strong>${fmtMoney(pay.repair_cost)}</strong></div>
          <div><span>Оплачено</span><strong>${fmtMoney(pay.paid)}</strong></div>
          <div><span>Предоплата</span><strong>${fmtMoney(pay.prepay)}</strong></div>
          <div><span>Итого к оплате</span><strong>${fmtMoney(pay.due)}</strong></div>
          <div><span>Сумма из журнала</span><strong>${fmtMoney(preview.amount)}</strong></div>
        </div>
      </div>
      <div class="cj-import-section">
        <div class="cj-import-sec-title">Живая лента</div>
        <div class="cj-feed">${feedHtml || "<em>пусто</em>"}</div>
      </div>
      <div class="cj-import-section${step === "cashbox" || step === "done" ? "" : " is-hidden"}">
        <div class="cj-import-sec-title">${boxTitle}</div>
        <select class="cj-cashbox-select">${boxOpts}</select>
      </div>
      <div class="cj-import-status" data-status></div>
      <div class="cj-import-actions"></div>
    `;

    const actionsEl = card.querySelector(".cj-import-actions");
    const statusEl = card.querySelector("[data-status]");
    card.querySelector(".cj-cashbox-select")?.addEventListener("change", (e) => {
      selectedCashbox = e.target.value;
    });

    addImportBtn(actionsEl, "Закрыть", "is-muted", closeCashImportModal);

    if (step === "preview") {
      addImportBtn(actionsEl, "Пропустить", "is-skip", () =>
        runCashImportStep(queue, index + 1, { onUpdate })
      );
      addImportBtn(actionsEl, "Принять оплату", "is-primary", () => {
        step = "cashbox";
        render();
      });
    } else if (step === "cashbox") {
      addImportBtn(actionsEl, "Пропустить", "is-skip", () =>
        runCashImportStep(queue, index + 1, { onUpdate })
      );
      const acceptBtn = addImportBtn(actionsEl, "Принять", "is-success", async () => {
        if (!selectedCashbox) {
          statusEl.textContent = preferCard ? "Выберите карту/кассу" : "Выберите кассу";
          return;
        }
        acceptBtn.disabled = true;
        statusEl.textContent = "Отправка в CRM…";
        try {
          const resp = await fetch("/api/cash-journal/import/accept", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              kind: "client_order_cash_in",
              order_id: String(line.order_id),
              amount: Number(preview.amount || line.amount),
              cashbox_id: String(selectedCashbox),
              currency_id: String(form.currency_id || "3"),
              form_act: form.form_act || "pay_for_repair_form",
              transaction_type: String(form.transaction_type || "2"),
              order_kind: form.order_kind || "repair",
              line_id: line.id,
            }),
          });
          const data = await resp.json().catch(() => ({}));
          if (!resp.ok) throw new Error(data.detail || data.error || resp.statusText);
          setLastCashboxId(selectedCashbox, preferCard);
          line.posted = true;
          step = "done";
          statusEl.textContent = data.crm?.msg || "Оплата внесена.";
          onUpdate?.();
          render();
        } catch (err) {
          acceptBtn.disabled = false;
          statusEl.textContent = `Ошибка: ${err.message || err}`;
        }
      });
    } else if (step === "done") {
      addImportBtn(actionsEl, "Следующая", "is-primary", () =>
        runCashImportStep(queue, index + 1, { onUpdate })
      );
    }
  }

  render();
}

async function renderCashExpenseImport(card, { queue, index, line, preview, onUpdate }) {
  const form = preview.expense_form || {};
  const cashboxes = form.cashboxes || [];
  const categories = form.categories || [];
  let selectedCashbox =
    getLastCashboxId() ||
    form.selected_cashbox_id ||
    cashboxes[0]?.id ||
    "";
  if (
    selectedCashbox &&
    !cashboxes.some((b) => String(b.id) === String(selectedCashbox))
  ) {
    selectedCashbox = form.selected_cashbox_id || cashboxes[0]?.id || "";
  }
  let selectedCategory = guessCategoryId(categories, preview.note || line.raw);
  let contractors = [];
  let selectedContractor = "";
  let comment = preview.note || line.raw || line.note || "";
  let step = "form"; // form | done
  let loadingContractors = false;

  async function loadContractors(categoryId) {
    contractors = [];
    selectedContractor = "";
    if (!categoryId) return;
    loadingContractors = true;
    render();
    try {
      const resp = await fetch(
        `/api/cash-journal/import/contractors?category_id=${encodeURIComponent(categoryId)}`
      );
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.detail || data.error || resp.statusText);
      contractors = data.contractors || [];
      selectedContractor = guessContractorId(contractors, comment);
    } catch (err) {
      contractors = [];
      card.querySelector("[data-status]") &&
        (card.querySelector("[data-status]").textContent = `Ошибка контрагентов: ${err.message || err}`);
    } finally {
      loadingContractors = false;
      render();
    }
  }

  function render() {
    const boxOpts = cashboxes
      .map((b) => {
        const bal = b.total_uah != null ? ` (${fmtMoney(b.total_uah)})` : "";
        const sel = String(b.id) === String(selectedCashbox) ? " selected" : "";
        return `<option value="${escapeHtml(String(b.id))}"${sel}>${escapeHtml(b.name || b.id)}${escapeHtml(bal)}</option>`;
      })
      .join("");
    const selectedCategoryName =
      categories.find((c) => String(c.id) === String(selectedCategory))?.name || "";
    const selectedContractorName =
      contractors.find((c) => String(c.id) === String(selectedContractor))?.name || "";
    const categoryDisabled = step === "done";
    const contractorDisabled = step === "done" || loadingContractors || !contractors.length;

    card.innerHTML = `
      <div class="cj-import-head">
        <strong>Внесение в базу · расход</strong>
        <span>${index + 1} / ${queue.length}</span>
      </div>
      <div class="cj-import-line">${escapeHtml(line.raw || line.note || "")} → <b>${fmtMoney(line.amount)}</b></div>
      <div class="cj-import-section">
        <div class="cj-import-sec-title">С кассы</div>
        <select class="cj-cashbox-select" data-field="cashbox" ${step === "done" ? "disabled" : ""}>${boxOpts}</select>
      </div>
      <div class="cj-import-section">
        <div class="cj-import-sec-title">Статья</div>
        <div class="cj-combo" data-combo="category">
          <input type="text" class="cj-combo-input" data-field="category-query"
            placeholder="Начните вводить статью…"
            value="${escapeHtml(selectedCategoryName)}"
            autocomplete="off"
            ${categoryDisabled ? "disabled" : ""} />
          <ul class="cj-combo-list is-hidden" role="listbox"></ul>
        </div>
      </div>
      <div class="cj-import-section">
        <div class="cj-import-sec-title">Контрагент ${loadingContractors ? "(загрузка…)" : ""}</div>
        <div class="cj-combo" data-combo="contractor">
          <input type="text" class="cj-combo-input" data-field="contractor-query"
            placeholder="${contractors.length ? "Начните вводить имя…" : "Сначала выберите статью"}"
            value="${escapeHtml(selectedContractorName)}"
            autocomplete="off"
            ${contractorDisabled ? "disabled" : ""} />
          <ul class="cj-combo-list is-hidden" role="listbox"></ul>
        </div>
      </div>
      <div class="cj-import-section">
        <div class="cj-import-sec-title">Примечание</div>
        <textarea class="cj-import-comment" data-field="comment" rows="2" ${step === "done" ? "disabled" : ""}>${escapeHtml(comment)}</textarea>
      </div>
      <div class="cj-import-status" data-status></div>
      <div class="cj-import-actions"></div>
    `;

    const actionsEl = card.querySelector(".cj-import-actions");
    const statusEl = card.querySelector("[data-status]");

    card.querySelector('[data-field="cashbox"]')?.addEventListener("change", (e) => {
      selectedCashbox = e.target.value;
    });
    wireSearchCombo(card, {
      combo: "category",
      items: categories,
      getSelected: () => selectedCategory,
      setSelected: (id) => {
        selectedCategory = id;
      },
      disabled: categoryDisabled,
      onPick: (id) => {
        if (id) loadContractors(id);
        else {
          contractors = [];
          selectedContractor = "";
          render();
        }
      },
    });
    wireSearchCombo(card, {
      combo: "contractor",
      items: contractors,
      getSelected: () => selectedContractor,
      setSelected: (id) => {
        selectedContractor = id;
      },
      disabled: contractorDisabled,
    });
    card.querySelector('[data-field="comment"]')?.addEventListener("input", (e) => {
      comment = e.target.value;
    });

    addImportBtn(actionsEl, "Закрыть", "is-muted", closeCashImportModal);

    if (step === "form") {
      addImportBtn(actionsEl, "Пропустить", "is-skip", () =>
        runCashImportStep(queue, index + 1, { onUpdate })
      );
      const issueBtn = addImportBtn(actionsEl, "Выдать", "is-success", async () => {
        if (!selectedCashbox) {
          statusEl.textContent = "Выберите кассу";
          return;
        }
        if (!selectedCategory) {
          statusEl.textContent = "Выберите статью";
          return;
        }
        if (!selectedContractor) {
          statusEl.textContent = "Выберите контрагента";
          return;
        }
        issueBtn.disabled = true;
        statusEl.textContent = "Отправка в CRM…";
        try {
          const resp = await fetch("/api/cash-journal/import/accept", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              kind: "cashbox_expense",
              amount: Number(preview.amount || line.amount),
              cashbox_id: String(selectedCashbox),
              category_id: String(selectedCategory),
              contractor_id: String(selectedContractor),
              comment: comment || "",
              currency_id: String(form.currency_id || "3"),
              line_id: line.id,
            }),
          });
          const data = await resp.json().catch(() => ({}));
          if (!resp.ok) throw new Error(data.detail || data.error || resp.statusText);
          setLastCashboxId(selectedCashbox);
          line.posted = true;
          step = "done";
          statusEl.textContent = data.crm?.msg || "Расход проведён.";
          onUpdate?.();
          render();
        } catch (err) {
          issueBtn.disabled = false;
          statusEl.textContent = `Ошибка: ${err.message || err}`;
        }
      });
    } else if (step === "done") {
      addImportBtn(actionsEl, "Следующая", "is-primary", () =>
        runCashImportStep(queue, index + 1, { onUpdate })
      );
    }
  }

  render();
  if (selectedCategory) {
    await loadContractors(selectedCategory);
  }
}

async function renderPartsAttachImport(card, { queue, index, line, preview, onUpdate }) {
  const order = preview.order || {};
  const payment = order.payment || {};
  let step = "preview"; // preview | done

  function render() {
    const statusLine = preview.will_change_status
      ? `${escapeHtml(preview.current_status_name || preview.current_status_id || "—")} → <b>${escapeHtml(preview.target_status_name || "В процессе ремонта")}</b> (потом вернём)`
      : `Уже «${escapeHtml(preview.current_status_name || preview.target_status_name || "В процессе ремонта")}» — менять не нужно`;

    card.innerHTML = `
      <div class="cj-import-head">
        <strong>Внесение в базу · запчасть</strong>
        <span>${index + 1} / ${queue.length}</span>
      </div>
      <div class="cj-import-line">${escapeHtml(line.raw || line.note || "")} → <b>${fmtMoney(Math.abs(Number(preview.amount || line.amount) || 0))}</b></div>
      <div class="cj-import-section">
        <div class="cj-import-sec-title">Квитанция №${escapeHtml(String(preview.order_id || line.order_id || ""))}</div>
        <div class="cj-import-meta">
          <div>Статус: ${statusLine}</div>
          <div>Товар: <b>${escapeHtml(preview.product_title || "Запчасти.")}</b></div>
          <div>Поставщик: <b>${escapeHtml(preview.supplier_name || "prom.ua")}</b></div>
          <div>Цена: <b>${fmtMoney(Math.abs(Number(preview.amount || line.amount) || 0))}</b></div>
          <div>Оплата в CRM: ремонт ${fmtMoney(payment.repair_cost)} · оплачено ${fmtMoney(payment.paid)} · к оплате ${fmtMoney(payment.due)}</div>
        </div>
      </div>
      <div class="cj-import-status" data-status></div>
      <div class="cj-import-actions"></div>
    `;

    const actionsEl = card.querySelector(".cj-import-actions");
    const statusEl = card.querySelector("[data-status]");
    addImportBtn(actionsEl, "Закрыть", "is-muted", closeCashImportModal);

    if (step === "preview") {
      addImportBtn(actionsEl, "Пропустить", "is-skip", () =>
        runCashImportStep(queue, index + 1, { onUpdate })
      );
      const goBtn = addImportBtn(actionsEl, "Привязать запчасть", "is-success", async () => {
        goBtn.disabled = true;
        statusEl.textContent = "Привязка в CRM (статус → заказ → оприходование)…";
        try {
          const resp = await fetch("/api/cash-journal/import/accept", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              kind: "parts_attach",
              order_id: String(preview.order_id || line.order_id),
              amount: Math.abs(Number(preview.amount || line.amount) || 0),
              note: preview.note || line.raw || line.note || "",
              line_id: line.id,
            }),
          });
          const data = await resp.json().catch(() => ({}));
          if (!resp.ok) throw new Error(data.detail || data.error || resp.statusText);
          line.posted = true;
          step = "done";
          const so = data.supplier_order_id ? ` · ЗП №${data.supplier_order_id}` : "";
          statusEl.textContent =
            (data.crm && (data.crm.msg || data.crm.message)) ||
            `Запчасть оприходована${so}.`;
          onUpdate?.();
          render();
        } catch (err) {
          goBtn.disabled = false;
          statusEl.textContent = `Ошибка: ${err.message || err}`;
        }
      });
    } else if (step === "done") {
      addImportBtn(actionsEl, "Следующая", "is-primary", () =>
        runCashImportStep(queue, index + 1, { onUpdate })
      );
    }
  }

  render();
}

function renderCashJournal(journal) {
  const root = document.createElement("div");
  root.className = "cash-journal";
  const data = {
    opening_cash: journal.opening_cash,
    opening_card: journal.opening_card,
    lines: (journal.lines || []).map((l) => ({ ...l })),
  };

  const title = document.createElement("div");
  title.className = "cash-journal-title";
  title.textContent = journal.title || "Сведение кассы";
  root.appendChild(title);

  const opening = document.createElement("div");
  opening.className = "cash-journal-opening";
  root.appendChild(opening);

  const summary = document.createElement("div");
  summary.className = "cash-journal-summary";
  root.appendChild(summary);

  const toolbar = document.createElement("div");
  toolbar.className = "cash-journal-toolbar";
  const importBtn = document.createElement("button");
  importBtn.type = "button";
  importBtn.className = "cj-import-open";
  importBtn.textContent = "Внести в базу";
  importBtn.addEventListener("click", () =>
    openCashImportFlow(data.lines, { onUpdate: renderLines })
  );
  toolbar.appendChild(importBtn);
  root.appendChild(toolbar);

  const head = document.createElement("div");
  head.className = "cj-cols-head";
  head.innerHTML = `<span>№</span><span>Текст</span><span>Сумма</span>`;
  root.appendChild(head);

  const list = document.createElement("div");
  list.className = "cash-journal-lines";
  root.appendChild(list);

  const actions = journal.actions || [
    { id: "cash_in", label: "в кассу" },
    { id: "cash_out", label: "из кассы" },
    { id: "card_in", label: "в карту" },
    { id: "card_out", label: "из карты" },
    { id: "cash_to_card", label: "из кассы в карту" },
    { id: "card_to_cash", label: "из карты в кассу" },
    { id: "ignore", label: "игнорировать транзакцию" },
  ];

  function refreshSummary() {
    enrichCheckpoints(data);
    const tot = computeCashJournal(data);
    opening.textContent = `Начальные балансы: Касса: ${fmtMoney(data.opening_cash)} | Карта: ${fmtMoney(data.opening_card)}`;
    summary.innerHTML = `
      <div class="cj-pill"><span>Касса</span><strong>${fmtMoney(data.opening_cash)}</strong><em>→</em><strong>${fmtMoney(tot.cash)}</strong></div>
      <div class="cj-pill"><span>Карта</span><strong>${fmtMoney(data.opening_card)}</strong><em>→</em><strong>${fmtMoney(tot.card)}</strong></div>
    `;
  }

  function renderLines() {
    enrichCheckpoints(data);
    list.innerHTML = "";
    data.lines.forEach((line, idx) => {
      const mismatch =
        line.is_checkpoint &&
        (line.cash_match === false || line.card_match === false);
      const row = document.createElement("div");
      row.className = `cash-journal-line${
        line.is_checkpoint
          ? ` is-checkpoint${mismatch ? " is-mismatch" : " is-match"}`
          : line.is_breakdown_total
            ? " is-breakdown is-breakdown-total"
            : line.is_breakdown
              ? " is-breakdown"
              : line.is_quote
                ? " is-quote"
                : line.action === "ignore"
                  ? " is-ignored"
                  : ""
      }${line.posted ? " is-posted" : ""}`;

      const num = document.createElement("div");
      num.className = "cj-num";
      num.textContent = String(idx + 1);

      const main = document.createElement("div");
      main.className = "cj-main";

      const text = document.createElement("div");
      text.className = "cj-text";
      if (line.is_checkpoint) {
        const badge = document.createElement("span");
        badge.className = "cj-checkpoint-badge";
        badge.textContent = "сверка";
        text.appendChild(badge);
      } else if (line.is_breakdown_total) {
        const badge = document.createElement("span");
        badge.className = "cj-breakdown-badge is-total";
        badge.textContent = "итог ЗЧ";
        text.appendChild(badge);
      } else if (line.is_breakdown) {
        const badge = document.createElement("span");
        badge.className = "cj-breakdown-badge";
        badge.textContent = "ЗЧ";
        text.appendChild(badge);
      } else if (line.is_quote) {
        const badge = document.createElement("span");
        badge.className = "cj-quote-badge";
        badge.textContent = "цитата";
        text.appendChild(badge);
      }
      let label = line.raw || line.note || "";
      const oid = line.order_id ? String(line.order_id) : "";
      if (oid && !String(label).includes(oid)) {
        label = `${oid} ${label}`.trim();
      }
      const labelNode = document.createTextNode(label);
      text.appendChild(labelNode);
      if (line.posted) text.appendChild(document.createTextNode(" ✓ внесено"));
      main.appendChild(text);

      if (line.is_checkpoint) {
        const cp = document.createElement("div");
        cp.className = "cj-checkpoint";
        cp.textContent = checkpointLineHtml(line);
        main.appendChild(cp);
      }

      if (!line.is_checkpoint) {
        const btns = document.createElement("div");
        btns.className = "cj-actions";
        actions.forEach((act) => {
          const b = document.createElement("button");
          b.type = "button";
          b.className = `cj-btn cj-btn-icon${line.action === act.id ? " active" : ""}`;
          b.title = act.label;
          b.setAttribute("aria-label", act.label);
          b.disabled = !!line.posted;
          b.innerHTML = CJ_ACTION_ICONS[act.id] || "";
          b.addEventListener("click", () => {
            data.lines[idx].action = act.id;
            renderLines();
            refreshSummary();
          });
          btns.appendChild(b);
        });
        main.appendChild(btns);
      }

      const sum = document.createElement("div");
      sum.className = "cj-sum";
      sum.textContent = line.is_checkpoint ? "—" : fmtMoney(line.amount);

      row.appendChild(num);
      row.appendChild(main);
      row.appendChild(sum);
      list.appendChild(row);
    });
  }

  renderLines();
  refreshSummary();
  return root;
}

function addBubble(role, text, extras = {}) {
  const el = document.createElement("div");
  el.className = `bubble ${role}`;
  const body = document.createElement("div");
  body.className = "bubble-body";
  const hasCashJournal = !!extras.cash_journals?.length;
  const hasStructuredTables = !!extras.tables?.length && !hasCashJournal;
  if (role === "assistant") {
    body.innerHTML = renderMarkdown(text, {
      stripTables: hasStructuredTables || hasCashJournal,
    });
  } else {
    body.textContent = text;
  }
  el.appendChild(body);
  if (hasCashJournal) {
    extras.cash_journals.forEach((journal) => {
      el.appendChild(renderCashJournal(journal));
    });
  } else if (hasStructuredTables) {
    extras.tables.forEach((table) => {
      el.appendChild(renderStructuredTable(table));
    });
  }
  if (extras.meta) {
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = extras.meta;
    el.appendChild(meta);
  }
  if (extras.charts?.length) {
    extras.charts.forEach((chart) => {
      const wrap = document.createElement("div");
      wrap.className = "chart-wrap";
      const canvas = document.createElement("canvas");
      canvas.height = 220;
      wrap.appendChild(canvas);
      el.appendChild(wrap);
      const palette = [
        "rgba(15, 110, 86, 0.75)",
        "rgba(198, 40, 40, 0.65)",
        "rgba(21, 101, 192, 0.7)",
        "rgba(245, 124, 0, 0.7)",
        "rgba(123, 31, 162, 0.65)",
        "rgba(0, 121, 107, 0.7)",
        "rgba(69, 90, 100, 0.7)",
        "rgba(46, 125, 50, 0.7)",
        "rgba(239, 108, 0, 0.7)",
        "rgba(84, 110, 122, 0.7)",
      ];
      requestAnimationFrame(() => {
        const datasets = (chart.datasets || []).map((ds, i) => {
          const fallback = palette[i % palette.length];
          return {
            ...ds,
            backgroundColor: ds.backgroundColor || fallback,
            borderColor: ds.borderColor || fallback,
            borderWidth: ds.borderWidth ?? 1.5,
            fill: ds.fill ?? (chart.type === "line" ? true : undefined),
            tension: ds.tension,
          };
        });
        // eslint-disable-next-line no-new
        new Chart(canvas, {
          type: chart.type || "bar",
          data: {
            labels: chart.labels || [],
            datasets,
          },
          options: {
            responsive: true,
            maintainAspectRatio: true,
            plugins: {
              title: {
                display: !!chart.title,
                text: chart.title || "",
                font: { size: 14, weight: "600" },
              },
              legend: {
                display: datasets.length > 1 || (chart.labels || []).length > 6,
                position: "bottom",
              },
              tooltip: {
                callbacks: {
                  label(ctx) {
                    const v = ctx.parsed.y ?? ctx.parsed;
                    const num = Number(v);
                    return `${ctx.dataset.label || ""}: ${num.toLocaleString("ru-RU")}`;
                  },
                },
              },
            },
            scales: {
              x: {
                ticks: {
                  maxRotation: 45,
                  minRotation: 0,
                  autoSkip: true,
                  maxTicksLimit: 16,
                },
              },
              y: {
                beginAtZero: true,
                ticks: {
                  callback(v) {
                    return Number(v).toLocaleString("ru-RU");
                  },
                },
              },
            },
          },
        });
      });
    });
  }
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

$("#chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#chat-input");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  addBubble("user", text);
  const btn = $("#send-btn");
  btn.disabled = true;
  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        message: text,
        conversation_id: state.conversationId,
      }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Ошибка чата");
    state.conversationId = data.conversation_id;
    const tools = (data.tool_traces || []).map((t) => t.tool).join(", ");
    addBubble("assistant", data.message, {
      meta: tools ? `инструменты: ${tools}` : null,
      charts: data.charts || [],
      tables: data.tables || [],
      cash_journals: data.cash_journals || [],
    });
  } catch (err) {
    addBubble("assistant", String(err.message || err));
  } finally {
    btn.disabled = false;
    input.focus();
  }
});

async function loadSettings() {
  const res = await fetch("/api/settings");
  const data = await res.json();
  const form = $("#llm-form");
  form.llm_base_url.value = data.llm_base_url || "";
  form.llm_api_key.value = data.llm_api_key || "";
  form.llm_model.value = data.llm_model || "";
}

$("#llm-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const status = $("#llm-status");
  status.textContent = "Сохраняю...";
  const res = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      llm_base_url: form.llm_base_url.value,
      llm_api_key: form.llm_api_key.value,
      llm_model: form.llm_model.value,
    }),
  });
  if (!res.ok) {
    status.className = "status err";
    status.textContent = "Не удалось сохранить";
    return;
  }
  status.className = "status ok";
  status.textContent = "Сохранено";
  await loadSettings();
});

function fieldInput(field, value) {
  if (field.type === "checkbox") {
    return `<div class="checkbox-row">
      <input type="checkbox" name="${field.key}" ${value ? "checked" : ""} />
      <span>${field.label}</span>
    </div>`;
  }
  if (field.type === "textarea") {
    return `<label>
      ${field.label}
      <textarea name="${field.key}" rows="6" placeholder="${escapeHtml(field.placeholder || "")}">${escapeHtml(
        value ?? "",
      )}</textarea>
      ${field.help ? `<span class="field-help">${field.help}</span>` : ""}
    </label>`;
  }
  return `<label>
    ${field.label}
    <input name="${field.key}" type="${field.type}" value="${escapeHtml(value ?? "")}" placeholder="${escapeHtml(
      field.placeholder || "",
    )}" />
    ${field.help ? `<span class="field-help">${field.help}</span>` : ""}
  </label>`;
}

async function loadModules() {
  const res = await fetch("/api/modules");
  const data = await res.json();
  const root = $("#modules-list");
  root.innerHTML = "";
  for (const mod of data.modules) {
    const card = document.createElement("div");
    card.className = "module-card";
    card.innerHTML = `
      <h2>${mod.name}</h2>
      <p class="desc">${mod.description}</p>
      <form data-module="${mod.id}">
        ${mod.settings
          .map((f) => fieldInput(f, mod.values?.[f.key]))
          .join("")}
        <div class="actions">
          <button type="submit">Сохранить</button>
          ${
            mod.id === "gincore"
              ? `<button type="button" class="secondary" data-test="gincore">Проверить вход</button>`
              : ""
          }
          ${
            mod.id === "vyrobotka"
              ? `<button type="button" class="secondary" data-test="vyrobotka">Проверить подключение</button>`
              : ""
          }
        </div>
        <p class="status" data-status></p>
      </form>
    `;
    root.appendChild(card);
  }

  root.querySelectorAll("form[data-module]").forEach((form) => {
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const moduleId = form.dataset.module;
      const status = form.querySelector("[data-status]");
      const values = {};
      for (const el of form.elements) {
        if (!el.name) continue;
        if (el.type === "checkbox") values[el.name] = el.checked;
        else values[el.name] = el.value;
      }
      status.textContent = "Сохраняю...";
      const res = await fetch(`/api/modules/${moduleId}/settings`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ values }),
      });
      const data = await res.json();
      if (!res.ok) {
        status.className = "status err";
        status.textContent = data.detail || "Ошибка";
        return;
      }
      status.className = "status ok";
      status.textContent = "Сохранено";
    });
  });

  root.querySelectorAll('[data-test="gincore"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const status = btn.closest("form").querySelector("[data-status]");
      status.textContent = "Проверяю вход в Gincore...";
      const res = await fetch("/api/modules/gincore/test", { method: "POST" });
      const data = await res.json();
      if (data.ok) {
        status.className = "status ok";
        status.textContent = `Вход успешен${data.result?.title ? ": " + data.result.title : ""}`;
      } else {
        status.className = "status err";
        status.textContent = data.error || "Ошибка входа";
      }
    });
  });

  root.querySelectorAll('[data-test="vyrobotka"]').forEach((btn) => {
    btn.addEventListener("click", async () => {
      const status = btn.closest("form").querySelector("[data-status]");
      status.className = "status";
      status.textContent = "Проверяю доступ к Google Таблице…";
      try {
        const res = await fetch("/api/modules/vyrobotka/test", { method: "POST" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok || !data.ok) {
          throw new Error(data.error || data.detail || res.statusText || "Нет доступа");
        }
        const names = (data.sheets || []).map((s) => s.title).filter(Boolean);
        status.className = "status ok";
        status.textContent = [
          "Подключение есть.",
          `Таблица: «${data.title || "—"}».`,
          `ID: ${data.spreadsheet_id || "—"}.`,
          `Листов: ${data.sheets_count ?? names.length}.`,
          names.length ? `Вкладки: ${names.slice(0, 10).join(", ")}${names.length > 10 ? "…" : ""}.` : "",
          data.client_email ? `Аккаунт: ${data.client_email}.` : "",
        ]
          .filter(Boolean)
          .join(" ");
      } catch (err) {
        status.className = "status err";
        status.textContent = `Нет подключения: ${err.message || err}`;
      }
    });
  });
}

let qualityPollTimer = null;

function fmtDays(v) {
  if (v == null || v === "") return "—";
  return String(v);
}

function dayClass(v, warnAt, badAt) {
  if (v == null) return "quality-muted";
  const n = Number(v);
  if (Number.isNaN(n)) return "";
  if (badAt != null && n >= badAt) return "quality-bad";
  if (warnAt != null && n >= warnAt) return "quality-warn";
  return "";
}

function formatSyncStatus(sync) {
  if (!sync) return "—";
  const st = sync.status || "idle";
  const msg = sync.message || "";
  if (st === "running") {
    const done = sync.done || 0;
    const total = sync.total || 0;
    return `Обновление… ${done}/${total}${msg ? " · " + msg : ""}`;
  }
  if (st === "error") return `Ошибка: ${msg || "неизвестно"}`;
  return msg || "Готово (данные из локального кэша)";
}

const QUALITY_COL_WIDTHS_KEY = "jarvis.quality.colWidths";
const QUALITY_COL_MIN = 52;
const QUALITY_COL_MAX = 480;
/** Базовые ширины — если в localStorage нет ключа или данные битые. */
const QUALITY_COL_DEFAULTS = {
  oid: 78,
  status: 150,
  engineer: 170,
  device: 170,
  total: 78,
  wait: 88,
  diag: 82,
  rework: 68,
  calls: 68,
  kpi: 64,
  mgr: 58,
  feed: 78,
};
let qualityColResizeReady = false;
let qualityTextMeasureCtx = null;

function qualityColKeys(table) {
  return [...table.querySelectorAll("colgroup col[data-col]")].map((c) =>
    c.getAttribute("data-col")
  );
}

function sanitizeQualityColWidths(raw, keys) {
  if (!raw || typeof raw !== "object") return {};
  const keySet = keys && keys.length ? new Set(keys) : null;
  const out = {};
  for (const [k, v] of Object.entries(raw)) {
    if (keySet && !keySet.has(k)) continue;
    const n = Math.round(Number(v));
    if (!Number.isFinite(n) || n < QUALITY_COL_MIN) continue;
    out[k] = Math.min(QUALITY_COL_MAX, n);
  }
  // Если почти всё «схлопнуто» — считаем кэш битым (после смены набора колонок).
  const vals = Object.values(out);
  if (vals.length >= 3) {
    const tiny = vals.filter((w) => w <= 64).length;
    if (tiny >= Math.ceil(vals.length * 0.6)) return {};
  }
  return out;
}

function loadQualityColWidths(keys) {
  try {
    const raw = localStorage.getItem(QUALITY_COL_WIDTHS_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw);
    const clean = sanitizeQualityColWidths(parsed, keys);
    // Перезаписать, если вычистили устаревшие/битые ключи.
    if (
      parsed &&
      typeof parsed === "object" &&
      JSON.stringify(parsed) !== JSON.stringify(clean)
    ) {
      if (Object.keys(clean).length) saveQualityColWidths(clean);
      else localStorage.removeItem(QUALITY_COL_WIDTHS_KEY);
    }
    return clean;
  } catch {
    return {};
  }
}

function saveQualityColWidths(map) {
  try {
    const table = $("#quality-table");
    const keys = table ? qualityColKeys(table) : Object.keys(map || {});
    const clean = sanitizeQualityColWidths(map, keys);
    if (!Object.keys(clean).length) {
      localStorage.removeItem(QUALITY_COL_WIDTHS_KEY);
      return;
    }
    localStorage.setItem(QUALITY_COL_WIDTHS_KEY, JSON.stringify(clean));
  } catch {
    /* ignore */
  }
}

function resolveQualityColWidths(table, override) {
  const keys = qualityColKeys(table);
  const saved = loadQualityColWidths(keys);
  const map = {};
  keys.forEach((key) => {
    const fromOverride = override && override[key] != null ? Number(override[key]) : 0;
    const fromSaved = saved[key] != null ? Number(saved[key]) : 0;
    const fromDefault = QUALITY_COL_DEFAULTS[key] || 96;
    const w = fromOverride >= QUALITY_COL_MIN
      ? fromOverride
      : fromSaved >= QUALITY_COL_MIN
        ? fromSaved
        : fromDefault;
    map[key] = Math.min(QUALITY_COL_MAX, Math.round(w));
  });
  return map;
}

function measureQualityColWidths(table) {
  const map = {};
  table.querySelectorAll("thead th[data-col]").forEach((th) => {
    const key = th.getAttribute("data-col");
    const w = Math.round(th.getBoundingClientRect().width);
    if (key && w >= QUALITY_COL_MIN) map[key] = Math.min(QUALITY_COL_MAX, w);
  });
  return map;
}

function applyQualityColWidths(widths) {
  const table = $("#quality-table");
  if (!table) return;
  const map = resolveQualityColWidths(
    table,
    widths && Object.keys(widths).length ? widths : null,
  );
  let sum = 0;
  qualityColKeys(table).forEach((key) => {
    const col = table.querySelector(`colgroup col[data-col="${key}"]`);
    const th = table.querySelector(`thead th[data-col="${key}"]`);
    const w = map[key] || QUALITY_COL_DEFAULTS[key] || 96;
    if (col) {
      col.style.width = `${w}px`;
      col.style.minWidth = `${w}px`;
    }
    if (th) {
      th.style.width = `${w}px`;
      th.style.minWidth = `${w}px`;
      th.style.maxWidth = `${w}px`;
    }
    sum += w;
  });
  table.style.width = sum > 0 ? `${sum}px` : "";
}

function setQualityColWidth(table, key, widthPx) {
  const w = Math.max(QUALITY_COL_MIN, Math.min(QUALITY_COL_MAX, Math.round(widthPx)));
  const col = table.querySelector(`colgroup col[data-col="${key}"]`);
  const th = table.querySelector(`thead th[data-col="${key}"]`);
  if (col) {
    col.style.width = `${w}px`;
    col.style.minWidth = `${w}px`;
  }
  if (th) {
    th.style.width = `${w}px`;
    th.style.minWidth = `${w}px`;
    th.style.maxWidth = `${w}px`;
  }
  let sum = 0;
  qualityColKeys(table).forEach((k) => {
    const c = table.querySelector(`colgroup col[data-col="${k}"]`);
    const cw = parseInt(c?.style.width || "0", 10);
    sum += cw >= QUALITY_COL_MIN ? cw : Math.round(
      table.querySelector(`thead th[data-col="${k}"]`)?.getBoundingClientRect().width || 80
    );
  });
  table.style.width = `${sum}px`;
  return w;
}

function measureQualityTextWidth(text, font) {
  if (!qualityTextMeasureCtx) {
    const canvas = document.createElement("canvas");
    qualityTextMeasureCtx = canvas.getContext("2d");
  }
  qualityTextMeasureCtx.font = font;
  return qualityTextMeasureCtx.measureText(text || "").width;
}

function collectQualityColWidths(table) {
  // Только явно заданные style.width — не снимать «схлопнутые» getBoundingClientRect.
  const prev = loadQualityColWidths(qualityColKeys(table));
  const map = {};
  qualityColKeys(table).forEach((k) => {
    const c = table.querySelector(`colgroup col[data-col="${k}"]`);
    const cw = parseInt(c?.style.width || "0", 10);
    if (cw >= QUALITY_COL_MIN) map[k] = Math.min(QUALITY_COL_MAX, cw);
    else if (prev[k] >= QUALITY_COL_MIN) map[k] = prev[k];
    else if (QUALITY_COL_DEFAULTS[k]) map[k] = QUALITY_COL_DEFAULTS[k];
  });
  return map;
}

function autoFitQualityCol(table, key) {
  const keys = qualityColKeys(table);
  const idx = keys.indexOf(key);
  const th = table.querySelector(`thead th[data-col="${key}"]`);
  if (idx < 0 || !th) return;
  ensureQualityColBaseline(table);

  let maxW = QUALITY_COL_MIN;
  const inner = th.querySelector(".quality-th-inner") || th;
  const labelEl = th.querySelector(".quality-th-label") || inner;
  const thCs = getComputedStyle(inner);
  const thFont = thCs.font || `${thCs.fontWeight} ${thCs.fontSize} ${thCs.fontFamily}`;
  const thPad =
    (parseFloat(thCs.paddingLeft) || 0) + (parseFloat(thCs.paddingRight) || 0);
  const labelText = (labelEl.textContent || "").replace(/\s+/g, " ").trim();
  // Запас под маркер сортировки.
  maxW = Math.max(maxW, Math.ceil(measureQualityTextWidth(labelText, thFont) + thPad + 18));

  table.querySelectorAll(`tbody tr td:nth-child(${idx + 1})`).forEach((td) => {
    const cs = getComputedStyle(td);
    const font = cs.font || `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
    const pad = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.paddingRight) || 0);
    const text = (td.innerText || td.textContent || "").replace(/\s+/g, " ").trim();
    maxW = Math.max(maxW, Math.ceil(measureQualityTextWidth(text, font) + pad + 2));
  });

  const w = setQualityColWidth(table, key, maxW);
  const map = collectQualityColWidths(table);
  map[key] = w;
  saveQualityColWidths(map);
  applyQualityColWidths(map);
}

function ensureQualityColBaseline(table) {
  const view = $("#view-quality");
  if (view && !view.classList.contains("active")) return;
  applyQualityColWidths(loadQualityColWidths(qualityColKeys(table)));
}

function initQualityColResize() {
  const table = $("#quality-table");
  if (!table) return;
  if (!qualityColResizeReady) {
    qualityColResizeReady = true;
    const headers = [...table.querySelectorAll("thead th[data-col]")];
    headers.forEach((th, idx) => {
      // У последнего столбца ручка не нужна — иначе пустая полоса справа.
      if (idx === headers.length - 1) return;
      const inner = th.querySelector(".quality-th-inner") || th;
      if (inner.querySelector(".quality-col-grip")) return;
      const grip = document.createElement("span");
      grip.className = "quality-col-grip";
      grip.title = "Перетащите ширину · двойной клик — по содержимому";
      inner.appendChild(grip);

      const startDrag = (e) => {
        e.preventDefault();
        e.stopPropagation();
        const key = th.getAttribute("data-col");
        if (!key) return;
        ensureQualityColBaseline(table);
        const startX = e.clientX;
        const startW = th.getBoundingClientRect().width;
        let moved = false;
        grip.classList.add("is-active");
        document.body.classList.add("quality-col-resizing");

        const onMove = (ev) => {
          if (Math.abs(ev.clientX - startX) > 2) moved = true;
          setQualityColWidth(table, key, startW + (ev.clientX - startX));
        };
        const onUp = () => {
          grip.classList.remove("is-active");
          document.body.classList.remove("quality-col-resizing");
          window.removeEventListener("pointermove", onMove);
          window.removeEventListener("pointerup", onUp);
          window.removeEventListener("mousemove", onMove);
          window.removeEventListener("mouseup", onUp);
          if (moved) {
            qualityIgnoreSortClick = true;
            setTimeout(() => {
              qualityIgnoreSortClick = false;
            }, 0);
          }
          const map = collectQualityColWidths(table);
          saveQualityColWidths(map);
          applyQualityColWidths(map);
        };
        window.addEventListener("pointermove", onMove);
        window.addEventListener("pointerup", onUp);
        window.addEventListener("mousemove", onMove);
        window.addEventListener("mouseup", onUp);
      };

      grip.addEventListener("dblclick", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const key = th.getAttribute("data-col");
        if (!key) return;
        qualityIgnoreSortClick = true;
        setTimeout(() => {
          qualityIgnoreSortClick = false;
        }, 0);
        autoFitQualityCol(table, key);
      });

      if (window.PointerEvent) grip.addEventListener("pointerdown", startDrag);
      else grip.addEventListener("mousedown", startDrag);
    });
  }
  ensureQualityColBaseline(table);
}

$("#quality-cols-reset")?.addEventListener("click", () => {
  try {
    localStorage.removeItem(QUALITY_COL_WIDTHS_KEY);
  } catch {
    /* ignore */
  }
  const table = $("#quality-table");
  if (!table) return;
  const defaults = {};
  qualityColKeys(table).forEach((k) => {
    defaults[k] = QUALITY_COL_DEFAULTS[k] || 96;
  });
  applyQualityColWidths(defaults);
});

const QUALITY_SORT_KEY = "jarvis.quality.sort";
const QUALITY_SORT_NUMERIC = new Set([
  "oid",
  "total",
  "wait",
  "diag",
  "rework",
  "calls",
  "kpi",
  "mgr",
  "feed",
]);
let qualityOrdersCache = [];
let qualitySort = null; // { key, dir: 'asc'|'desc' }
let qualitySortReady = false;
let qualityIgnoreSortClick = false;

function loadQualitySort() {
  try {
    const raw = localStorage.getItem(QUALITY_SORT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (parsed?.key && (parsed.dir === "asc" || parsed.dir === "desc")) return parsed;
  } catch {
    /* ignore */
  }
  return null;
}

function saveQualitySort(sort) {
  try {
    if (!sort) localStorage.removeItem(QUALITY_SORT_KEY);
    else localStorage.setItem(QUALITY_SORT_KEY, JSON.stringify(sort));
  } catch {
    /* ignore */
  }
}

function qualitySortValue(row, key) {
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
      // Без доработок — лучше любого KPI (101): при desc сверху, при asc внизу.
      if (row.rework_kpi == null) return 101;
      return Number(row.rework_kpi);
    case "calls":
      return row.calls_kpi == null ? -1 : Number(row.calls_kpi);
    case "kpi":
      return row.order_kpi == null ? -1 : Number(row.order_kpi);
    case "mgr":
      return row.manager_no_answer_missed ? 1 : 0;
    case "feed":
      return row.has_feed ? 1 : 0;
    default:
      return "";
  }
}

function sortQualityRows(rows, sort) {
  if (!sort?.key || !rows?.length) return rows || [];
  const dir = sort.dir === "desc" ? -1 : 1;
  const key = sort.key;
  return [...rows].sort((a, b) => {
    const va = qualitySortValue(a, key);
    const vb = qualitySortValue(b, key);
    if (typeof va === "number" && typeof vb === "number") {
      if (va === vb) return Number(b.order_id) - Number(a.order_id);
      return (va - vb) * dir;
    }
    const cmp = String(va).localeCompare(String(vb), "ru", { sensitivity: "base" });
    if (cmp === 0) return Number(b.order_id) - Number(a.order_id);
    return cmp * dir;
  });
}

function updateQualitySortIndicators() {
  document.querySelectorAll("#quality-table thead th[data-col]").forEach((th) => {
    const key = th.getAttribute("data-col");
    const mark = th.querySelector(".quality-th-sort");
    const active = qualitySort && qualitySort.key === key;
    th.classList.toggle("is-sorted", !!active);
    if (mark) {
      mark.textContent = active ? (qualitySort.dir === "asc" ? "▲" : "▼") : "▲";
    }
  });
}

function initQualitySort() {
  const table = $("#quality-table");
  if (!table || qualitySortReady) {
    updateQualitySortIndicators();
    return;
  }
  qualitySortReady = true;
  qualitySort = loadQualitySort();
  if (
    qualitySort?.key &&
    !table.querySelector(`thead th[data-col="${qualitySort.key}"]`)
  ) {
    qualitySort = null;
    saveQualitySort(null);
  }

  table.querySelectorAll("thead th[data-col]").forEach((th) => {
    const inner = th.querySelector(".quality-th-inner");
    if (!inner) return;
    if (!inner.querySelector(".quality-th-label")) {
      const label = document.createElement("span");
      label.className = "quality-th-label";
      // Move existing text nodes / content except grip into label
      const grip = inner.querySelector(".quality-col-grip");
      const nodes = [...inner.childNodes].filter((n) => n !== grip);
      nodes.forEach((n) => label.appendChild(n));
      inner.insertBefore(label, grip || null);
    }
    if (!inner.querySelector(".quality-th-sort")) {
      const mark = document.createElement("span");
      mark.className = "quality-th-sort";
      mark.setAttribute("aria-hidden", "true");
      mark.textContent = "▲";
      const grip = inner.querySelector(".quality-col-grip");
      inner.insertBefore(mark, grip || null);
    }
    th.addEventListener("click", (e) => {
      if (e.target?.closest?.(".quality-col-grip")) return;
      if (document.body.classList.contains("quality-col-resizing")) return;
      if (qualityIgnoreSortClick) return;
      const key = th.getAttribute("data-col");
      if (!key) return;
      // Цикл: нет → первая → обратная → сброс.
      if (qualitySort?.key === key) {
        if (qualitySort.dir === (QUALITY_SORT_NUMERIC.has(key) ? "desc" : "asc")) {
          qualitySort = {
            key,
            dir: qualitySort.dir === "asc" ? "desc" : "asc",
          };
        } else {
          qualitySort = null;
        }
      } else {
        qualitySort = {
          key,
          dir: QUALITY_SORT_NUMERIC.has(key) ? "desc" : "asc",
        };
      }
      saveQualitySort(qualitySort);
      updateQualitySortIndicators();
      renderQualityOrders();
    });
  });
  updateQualitySortIndicators();
}

function fmtQualityDate(s) {
  if (!s) return "—";
  const m = String(s).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (m) return `${m[3]}.${m[2]}.${m[1]}`;
  return String(s);
}

function qualityKpiTone(kpi) {
  if (kpi == null) return "muted";
  if (kpi >= 70) return "good";
  if (kpi >= 40) return "mid";
  return "bad";
}

/** Фон ячейки по KPI 0–100: красный → жёлтый → зелёный. */
function qualityKpiHeatStyle(kpi) {
  if (kpi == null || Number.isNaN(Number(kpi))) return "";
  // Красная зона до ~55, жёлтая середина узкая, зелёный только у высоких.
  // t=0 → red, t=1 → green; степень >1 сильнее тянет низкие KPI к красному.
  const raw = Math.max(0, Math.min(100, Number(kpi))) / 100;
  const t = Math.pow(raw, 1.65);
  const hue = Math.round(t * 118); // 0=red … ~118=green
  const sat = Math.round(58 + 22 * (1 - t)); // насыщеннее на плохих
  const light = Math.round(44 + 4 * t);
  const alpha = (0.28 + 0.22 * (1 - t)).toFixed(3); // KPI 30 ≈ заметно красный
  return `background-color: hsla(${hue}, ${sat}%, ${light}%, ${alpha})`;
}

function qualityTipLi(text, tone) {
  return `<li class="${tone ? `is-${tone}` : ""}">${escapeHtml(text)}</li>`;
}

function buildQualityCallsTipHtml(r) {
  const inOk = r.calls_inbound_ok ?? r.calls_inbound ?? 0;
  const inFail = r.calls_inbound_fail ?? 0;
  const outOk = r.calls_outbound_ok ?? 0;
  const outFail = r.calls_outbound_fail ?? 0;
  const missed = r.calls_missed ?? 0;
  const missUnrec = r.calls_missed_unrecovered ?? 0;
  const missRec = r.calls_missed_recovered ?? 0;
  const preOk = r.calls_pre_inbound_ok ?? 0;
  const preSame = r.calls_pre_miss_same_day ?? 0;
  const preBefore = r.calls_pre_miss_before_visit ?? 0;
  const preUntil = r.calls_pre_miss_until_visit ?? 0;
  const kpi = r.calls_kpi != null ? Number(r.calls_kpi) : null;
  const tone = qualityKpiTone(kpi);

  const preItems = [];
  if (preOk) preItems.push(qualityTipLi(`Приняли входящий: ${preOk} — норма, без штрафа`, "good"));
  if (preSame) {
    preItems.push(
      qualityTipLi(
        `Не взяли, но в тот же день связались (повторный вх. или наш исходящий): ${preSame}`,
        "mid",
      ),
    );
  }
  if (preBefore) {
    preItems.push(
      qualityTipLi(`Связались позже, но до сдачи устройства: ${preBefore}`, "mid"),
    );
  }
  if (preUntil) {
    preItems.push(
      qualityTipLi(`До сдачи так и не связались: ${preUntil} — сильно снижает оценку`, "bad"),
    );
  }

  const postItems = [];
  if (missUnrec) {
    postItems.push(
      qualityTipLi(`Пропущенный без перезвона в тот же день: ${missUnrec}`, "bad"),
    );
  }
  if (missRec) {
    postItems.push(
      qualityTipLi(`Пропущенный, перезвонили в тот же день: ${missRec}`, "good"),
    );
  }
  if (r.callback_same_day) {
    postItems.push(
      qualityTipLi(`Дней, когда был перезвон в тот же день: ${r.callback_same_day}`),
    );
  }

  const score =
    kpi == null
      ? `<div class="quality-float-tip-score is-muted">Нет данных</div>
         <p class="quality-float-tip-note">В ленте нет звонков для оценки коммуникации.</p>`
      : `<div class="quality-float-tip-score is-${tone}"><span>${kpi}</span><small>/ 100</small></div>`;

  return `
    <div class="quality-float-tip-head">Коммуникация</div>
    ${score}
    <div class="quality-float-tip-block">
      <div class="quality-float-tip-label">Звонки по заказу</div>
      <ul>
        <li>Исходящие: <strong>${outOk}</strong> успешных · <strong>${outFail}</strong> неуспешных</li>
        <li>Входящие: <strong>${inOk}</strong> успешных · <strong>${inFail}</strong> неуспешных${
          missed ? ` · пропущено <strong>${missed}</strong>` : ""
        }</li>
      </ul>
    </div>
    ${
      preItems.length
        ? `<div class="quality-float-tip-block">
            <div class="quality-float-tip-label">До создания заказа</div>
            <ul>${preItems.join("")}</ul>
          </div>`
        : ""
    }
    ${
      postItems.length
        ? `<div class="quality-float-tip-block">
            <div class="quality-float-tip-label">После создания заказа</div>
            <ul>${postItems.join("")}</ul>
          </div>`
        : ""
    }
    ${
      kpi != null && !preItems.length && !postItems.length
        ? `<p class="quality-float-tip-note">Особых проблем с дозвоном не зафиксировано — оценка по успешности звонков.</p>`
        : ""
    }
  `;
}

function buildQualityReworkTipHtml(r) {
  const rwN = Number(r.rework_count || 0);
  const rwKpi = r.rework_kpi != null ? Number(r.rework_kpi) : null;
  if (rwN <= 0 || rwKpi == null) {
    return `
      <div class="quality-float-tip-head">Доработки</div>
      <div class="quality-float-tip-score is-good"><span>—</span></div>
      <p class="quality-float-tip-note">Приёмов на доработку не было.</p>
    `;
  }
  const tone = qualityKpiTone(rwKpi);
  const diag = r.rework_diag_days;
  const repair = r.rework_repair_days;
  const total = r.rework_total_days;
  const since = fmtQualityDate(r.last_rework_at);
  const why = [];
  if (rwN === 1) why.push(qualityTipLi("Первая доработка: −20 к оценке", "mid"));
  else why.push(qualityTipLi(`${rwN} приёма на доработку: −20 за первую и −25 за каждую следующую`, "bad"));
  if (repair == null) {
    why.push(
      qualityTipLi(
        "Ремонт после доработки ещё не начат — долгая диагностика штрафуется сильнее",
        "bad",
      ),
    );
  } else if (Number(diag) >= 7 || Number(repair) >= 7 || Number(total) >= 10) {
    why.push(qualityTipLi("Долгий цикл после последней доработки снижает оценку", "mid"));
  }

  return `
    <div class="quality-float-tip-head">Доработки</div>
    <div class="quality-float-tip-score is-${tone}"><span>${rwKpi}</span><small>/ 100</small></div>
    <div class="quality-float-tip-block">
      <div class="quality-float-tip-label">Сводка</div>
      <ul>
        <li>Приёмов на доработку: <strong>${rwN}</strong></li>
        <li>Последний приём: <strong>${escapeHtml(since)}</strong></li>
      </ul>
    </div>
    <div class="quality-float-tip-block">
      <div class="quality-float-tip-label">С последней доработки</div>
      <ul>
        <li>Диагностика: <strong>${diag == null ? "—" : `${fmtDays(diag)} дн`}</strong></li>
        <li>Ремонт: <strong>${
          repair == null ? "ещё не начат" : `${fmtDays(repair)} дн`
        }</strong></li>
        <li>Всего: <strong>${total == null ? "—" : `${fmtDays(total)} дн`}</strong></li>
      </ul>
    </div>
    ${
      why.length
        ? `<div class="quality-float-tip-block">
            <div class="quality-float-tip-label">Что влияет на оценку</div>
            <ul>${why.join("")}</ul>
          </div>`
        : ""
    }
  `;
}

function buildQualityOrderKpiTipHtml(r) {
  const kpi = r.order_kpi != null ? Number(r.order_kpi) : null;
  const tone = qualityKpiTone(kpi);
  const parts = Array.isArray(r.order_kpi_parts) ? r.order_kpi_parts : [];
  const score =
    kpi == null
      ? `<div class="quality-float-tip-score is-muted">Нет данных</div>`
      : `<div class="quality-float-tip-score is-${tone}"><span>${kpi}</span><small>/ 100</small></div>`;
  const rows = parts
    .map((p) => {
      const pt = qualityKpiTone(p.score);
      const detail = String(p.detail || "").trim();
      return `<li class="is-${pt}"><strong>${escapeHtml(p.label)}</strong> → <strong>${
        p.score
      }/100</strong>${
        detail ? ` <span class="quality-float-tip-muted">(${escapeHtml(detail)})</span>` : ""
      } · вес ${p.weight_pct ?? "—"}%</li>`;
    })
    .join("");
  return `
    <div class="quality-float-tip-head">Итоговый KPI</div>
    ${score}
    <div class="quality-float-tip-block">
      <div class="quality-float-tip-label">Оценка компонентов (не «количество»)</div>
      <ul>${
        rows ||
        "<li>Недостаточно данных для оценки</li>"
      }</ul>
    </div>
    <p class="quality-float-tip-note">В «Дораб.» и «Звонки» число — это балл 0–100, не счётчик. «Мен.» не входит. Нет звонков — веса перенормируются.</p>
  `;
}

let qualityFloatTipEl = null;
let qualityFloatTipAnchor = null;
let qualityFloatTipHideTimer = null;
let qualityTipsReady = false;

function ensureQualityFloatTip() {
  if (qualityFloatTipEl) return qualityFloatTipEl;
  qualityFloatTipEl = document.createElement("div");
  qualityFloatTipEl.className = "quality-float-tip";
  qualityFloatTipEl.hidden = true;
  qualityFloatTipEl.setAttribute("role", "tooltip");
  document.body.appendChild(qualityFloatTipEl);
  qualityFloatTipEl.addEventListener("mouseenter", () => {
    if (qualityFloatTipHideTimer) {
      clearTimeout(qualityFloatTipHideTimer);
      qualityFloatTipHideTimer = null;
    }
  });
  qualityFloatTipEl.addEventListener("mouseleave", () => hideQualityFloatTipSoon());
  return qualityFloatTipEl;
}

function positionQualityFloatTip(anchor) {
  const tip = ensureQualityFloatTip();
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

function showQualityFloatTip(anchor) {
  const content = anchor.querySelector(".quality-tip-content");
  if (!content) return;
  if (qualityFloatTipHideTimer) {
    clearTimeout(qualityFloatTipHideTimer);
    qualityFloatTipHideTimer = null;
  }
  const tip = ensureQualityFloatTip();
  tip.innerHTML = content.innerHTML;
  tip.hidden = false;
  qualityFloatTipAnchor = anchor;
  positionQualityFloatTip(anchor);
}

function hideQualityFloatTipSoon() {
  if (qualityFloatTipHideTimer) clearTimeout(qualityFloatTipHideTimer);
  qualityFloatTipHideTimer = setTimeout(() => {
    if (!qualityFloatTipEl) return;
    qualityFloatTipEl.hidden = true;
    qualityFloatTipEl.innerHTML = "";
    qualityFloatTipAnchor = null;
    qualityFloatTipHideTimer = null;
  }, 120);
}

function hideQualityFloatTipNow() {
  if (qualityFloatTipHideTimer) {
    clearTimeout(qualityFloatTipHideTimer);
    qualityFloatTipHideTimer = null;
  }
  if (qualityFloatTipEl) {
    qualityFloatTipEl.hidden = true;
    qualityFloatTipEl.innerHTML = "";
  }
  qualityFloatTipAnchor = null;
}

function initQualityTips() {
  if (qualityTipsReady) return;
  const table = $("#quality-table");
  if (!table) return;
  qualityTipsReady = true;
  table.addEventListener("mouseover", (e) => {
    const a = e.target.closest?.(".quality-tip-anchor");
    if (!a || !table.contains(a)) return;
    if (qualityFloatTipAnchor === a && qualityFloatTipEl && !qualityFloatTipEl.hidden) return;
    showQualityFloatTip(a);
  });
  table.addEventListener("mouseout", (e) => {
    const a = e.target.closest?.(".quality-tip-anchor");
    if (!a) return;
    const related = e.relatedTarget;
    if (related && (a.contains(related) || qualityFloatTipEl?.contains(related))) return;
    hideQualityFloatTipSoon();
  });
  table.addEventListener("focusin", (e) => {
    const a = e.target.closest?.(".quality-tip-anchor");
    if (a && table.contains(a)) showQualityFloatTip(a);
  });
  table.addEventListener("focusout", (e) => {
    const a = e.target.closest?.(".quality-tip-anchor");
    if (!a) return;
    const related = e.relatedTarget;
    if (related && (a.contains(related) || qualityFloatTipEl?.contains(related))) return;
    hideQualityFloatTipSoon();
  });
  window.addEventListener("scroll", () => hideQualityFloatTipNow(), true);
  window.addEventListener("resize", () => hideQualityFloatTipNow());
}

function buildQualityOrderRowHtml(r, { includeEngineer = true } = {}) {
  const callsKpi = r.calls_kpi != null ? Number(r.calls_kpi) : null;
  const callsCls =
    callsKpi == null
      ? "quality-muted"
      : callsKpi >= 70
        ? "is-good"
        : callsKpi >= 40
          ? "is-mid"
          : "is-bad";
  const callsTip = r.has_feed ? buildQualityCallsTipHtml(r) : "";
  const calls = r.has_feed
    ? `<span class="quality-tip-anchor quality-calls ${callsCls}" tabindex="0">${
        callsKpi == null ? "—" : callsKpi
      }<span class="quality-tip-content" hidden>${callsTip}</span></span>`
    : "…";
  const oid = escapeHtml(r.order_id || "");
  const feed = r.has_feed
    ? `<button type="button" class="quality-feed-btn" data-feed-order="${oid}" title="${escapeHtml(r.feed_synced_at || "Открыть ленту")}">открыть</button>`
    : `<button type="button" class="quality-feed-btn" disabled>нет</button>`;
  const link = r.url
    ? `<a href="${escapeHtml(r.url)}" target="_blank" rel="noopener">${oid}</a>`
    : oid;
  const mgr = r.manager_no_answer_missed
    ? `<span class="quality-mgr-flag" title="После согласования неуспешный исходящий, статус не «На согласовании»/«Не дозвонились»">статус?</span>`
    : `<span class="quality-muted">—</span>`;
  const rwN = Number(r.rework_count || 0);
  const rwKpi = r.rework_kpi != null ? Number(r.rework_kpi) : null;
  const rwCls =
    rwKpi == null
      ? "quality-muted"
      : rwKpi >= 70
        ? "is-good"
        : rwKpi >= 40
          ? "is-mid"
          : "is-bad";
  const rwTip = buildQualityReworkTipHtml(r);
  const rework =
    rwN > 0 && rwKpi != null
      ? `<span class="quality-tip-anchor quality-rework ${rwCls}" tabindex="0">${rwKpi}<span class="quality-tip-content" hidden>${rwTip}</span></span>`
      : `<span class="quality-tip-anchor quality-muted" tabindex="0">—<span class="quality-tip-content" hidden>${rwTip}</span></span>`;
  const orderKpi = r.order_kpi != null ? Number(r.order_kpi) : null;
  const orderCls =
    orderKpi == null
      ? "quality-muted"
      : orderKpi >= 70
        ? "is-good"
        : orderKpi >= 40
          ? "is-mid"
          : "is-bad";
  const orderTip = buildQualityOrderKpiTipHtml(r);
  const orderKpiCell =
    orderKpi == null
      ? `<span class="quality-tip-anchor quality-muted" tabindex="0">—<span class="quality-tip-content" hidden>${orderTip}</span></span>`
      : `<span class="quality-tip-anchor quality-order-kpi ${orderCls}" tabindex="0">${orderKpi}<span class="quality-tip-content" hidden>${orderTip}</span></span>`;
  const rowCls = r.manager_no_answer_missed ? ' class="quality-row-flag"' : "";
  const acceptedTip = r.accepted_at
    ? `Принят: ${fmtQualityDate(r.accepted_at)}`
    : "Дата приёмки неизвестна";
  const engineerCell = includeEngineer
    ? `<td>${escapeHtml(r.engineer || r.master_name || "—")}</td>`
    : "";
  return `<tr${rowCls}>
          <td>${link}</td>
          <td>${escapeHtml(r.status || "—")}</td>
          ${engineerCell}
          <td class="quality-device-cell" title="${escapeHtml(r.device || "")}" style="${qualityKpiHeatStyle(orderKpi)}">${escapeHtml((r.device || "—").slice(0, 28))}</td>
          <td class="${dayClass(r.total_days, 7, 14)}" title="${escapeHtml(acceptedTip)}">${fmtDays(r.total_days)}</td>
          <td class="${dayClass(r.wait_master_days, 2, 5)}">${fmtDays(r.wait_master_days)}</td>
          <td class="${dayClass(r.diag_days, 3, 7)}" title="${escapeHtml(r.agreement_source || "")}">${fmtDays(r.diag_days)}</td>
          <td>${rework}</td>
          <td>${calls}</td>
          <td>${orderKpiCell}</td>
          <td>${mgr}</td>
          <td>${feed}</td>
        </tr>`;
}

function qualityMasterName(row) {
  return String(row?.engineer || row?.master_name || "").trim();
}

function qualityAvg(nums) {
  const vals = nums.filter((n) => n != null && !Number.isNaN(Number(n))).map(Number);
  if (!vals.length) return null;
  return Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10;
}

function qualityMasterStats(name, rows) {
  const avgKpi = qualityAvg(rows.map((r) => r.order_kpi));
  return {
    name,
    count: rows.length,
    avgKpi: avgKpi == null ? null : Math.round(avgKpi),
    avgTotal: qualityAvg(rows.map((r) => r.total_days)),
    avgWait: qualityAvg(rows.map((r) => r.wait_master_days)),
    avgDiag: qualityAvg(rows.map((r) => r.diag_days)),
    avgRework: qualityAvg(rows.filter((r) => r.rework_kpi != null).map((r) => r.rework_kpi)),
    avgCalls: qualityAvg(rows.map((r) => r.calls_kpi)),
    rows,
  };
}

function groupQualityByMaster(rows) {
  const map = new Map();
  for (const r of rows || []) {
    const key = qualityMasterName(r);
    // Пустой мастер / «—» — не отдельный мастер, в срезы не включаем.
    if (!key || key === "—" || key.toLowerCase() === "без мастера") continue;
    if (!map.has(key)) map.set(key, []);
    map.get(key).push(r);
  }
  return [...map.entries()]
    .map(([name, list]) => qualityMasterStats(name, list))
    .sort((a, b) => {
      const ka = a.avgKpi == null ? -1 : a.avgKpi;
      const kb = b.avgKpi == null ? -1 : b.avgKpi;
      if (kb !== ka) return kb - ka;
      return a.name.localeCompare(b.name, "ru");
    });
}

let qualityMastersChart = null;

function renderQualityMastersTab() {
  const root = $("#quality-masters-root");
  if (!root) return;
  initQualityTips();
  const groups = groupQualityByMaster(qualityOrdersCache);
  if (!groups.length) {
    root.innerHTML = `<div class="quality-empty">Нет данных. Нажмите «Обновить из CRM».</div>`;
    return;
  }
  root.innerHTML = groups
    .map((g) => {
      const tone = qualityKpiTone(g.avgKpi);
      const score =
        g.avgKpi == null
          ? `<span class="quality-master-kpi is-muted">—</span>`
          : `<span class="quality-master-kpi is-${tone}"><span>${g.avgKpi}</span><small>/ 100</small></span>`;
      const body = sortQualityRows(g.rows, { key: "kpi", dir: "desc" })
        .map((r) => buildQualityOrderRowHtml(r, { includeEngineer: false }))
        .join("");
      return `<article class="quality-master-card">
        <div class="quality-master-card-head">
          <h3>${escapeHtml(g.name)}</h3>
          ${score}
          <span class="quality-master-meta">KPI мастера · ${g.count} заказ${
            g.count % 10 === 1 && g.count % 100 !== 11
              ? ""
              : g.count % 10 >= 2 && g.count % 10 <= 4 && (g.count % 100 < 10 || g.count % 100 >= 20)
                ? "а"
                : "ов"
          }</span>
        </div>
        <div class="quality-table-wrap">
          <table class="quality-table">
            <thead>
              <tr>
                <th>№</th><th>Статус</th><th>Устройство</th><th>Всего дн</th>
                <th>До мастера</th><th>До диагн.</th><th>Дораб.</th><th>Звонки</th>
                <th>KPI</th><th>Мен.</th><th>Лента</th>
              </tr>
            </thead>
            <tbody>${body}</tbody>
          </table>
        </div>
      </article>`;
    })
    .join("");
  root.querySelectorAll("[data-feed-order]").forEach((btn) => {
    btn.addEventListener("click", () => openQualityFeed(btn.getAttribute("data-feed-order")));
  });
}

function renderQualitySummaryTab() {
  const tbody = $("#quality-summary-tbody");
  const canvas = $("#quality-masters-chart");
  if (!tbody) return;
  const groups = groupQualityByMaster(qualityOrdersCache);
  if (!groups.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="quality-empty">Нет данных</td></tr>`;
    if (qualityMastersChart) {
      qualityMastersChart.destroy();
      qualityMastersChart = null;
    }
    return;
  }
  tbody.innerHTML = groups
    .map((g) => {
      const tone = qualityKpiTone(g.avgKpi);
      const kpiCls =
        g.avgKpi == null ? "quality-muted" : `quality-order-kpi is-${tone}`;
      return `<tr>
        <td>${escapeHtml(g.name)}</td>
        <td>${g.count}</td>
        <td class="${kpiCls}" style="${qualityKpiHeatStyle(g.avgKpi)}">${
          g.avgKpi == null ? "—" : g.avgKpi
        }</td>
        <td class="${dayClass(g.avgTotal, 7, 14)}">${fmtDays(g.avgTotal)}</td>
        <td class="${dayClass(g.avgWait, 2, 5)}">${fmtDays(g.avgWait)}</td>
        <td class="${dayClass(g.avgDiag, 3, 7)}">${fmtDays(g.avgDiag)}</td>
        <td>${g.avgRework == null ? "—" : Math.round(g.avgRework)}</td>
        <td>${g.avgCalls == null ? "—" : Math.round(g.avgCalls)}</td>
      </tr>`;
    })
    .join("");

  if (!canvas || typeof Chart === "undefined") return;
  const wrap = canvas.parentElement;
  if (wrap) {
    wrap.style.height = `${Math.max(280, Math.min(640, 48 + groups.length * 34))}px`;
  }
  const labels = groups.map((g) => {
    const parts = g.name.split(/\s+/);
    if (parts.length >= 2) return `${parts[0]} ${parts[1][0]}.`;
    return g.name.length > 18 ? `${g.name.slice(0, 16)}…` : g.name;
  });
  const values = groups.map((g) => (g.avgKpi == null ? 0 : g.avgKpi));
  const colors = values.map((v) => {
    const t = Math.pow(Math.max(0, Math.min(100, v)) / 100, 1.65);
    const hue = Math.round(t * 118);
    return `hsla(${hue}, 58%, 42%, 0.85)`;
  });
  if (qualityMastersChart) {
    qualityMastersChart.destroy();
    qualityMastersChart = null;
  }
  qualityMastersChart = new Chart(canvas, {
    type: "bar",
    data: {
      labels,
      datasets: [
        {
          label: "Средний KPI",
          data: values,
          backgroundColor: colors,
          borderColor: colors,
          borderWidth: 0,
          borderRadius: 6,
        },
      ],
    },
    options: {
      indexAxis: "y",
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            title(items) {
              const i = items[0]?.dataIndex;
              return i == null ? "" : groups[i].name;
            },
            label(ctx) {
              const g = groups[ctx.dataIndex];
              return `KPI ${g.avgKpi ?? "—"} · заказов ${g.count}`;
            },
          },
        },
      },
      scales: {
        x: {
          min: 0,
          max: 100,
          ticks: { stepSize: 20 },
          grid: { color: "rgba(28,36,48,0.06)" },
        },
        y: {
          grid: { display: false },
          ticks: { font: { size: 11 } },
        },
      },
    },
  });
}

function renderQualityOrders() {
  const tbody = $("#quality-tbody");
  if (!tbody) return;
  hideQualityFloatTipNow();
  initQualityTips();
  const rows = sortQualityRows(qualityOrdersCache, qualitySort);
  if (!rows.length) {
    tbody.innerHTML = `<tr><td colspan="12" class="quality-empty">Нет данных. Нажмите «Обновить из CRM».</td></tr>`;
    renderQualityMastersTab();
    renderQualitySummaryTab();
    return;
  }
  tbody.innerHTML = rows.map((r) => buildQualityOrderRowHtml(r, { includeEngineer: true })).join("");
  tbody.querySelectorAll("[data-feed-order]").forEach((btn) => {
    btn.addEventListener("click", () => openQualityFeed(btn.getAttribute("data-feed-order")));
  });
  const table = $("#quality-table");
  if (table) applyQualityColWidths(loadQualityColWidths(qualityColKeys(table)));
  renderQualityMastersTab();
  renderQualitySummaryTab();
}

const QUALITY_TAB_KEY = "jarvis.quality.tab";

let qualityDailyStatsCache = [];
let qualityAnalysisCache = null;
let qualityDynamicsKpiChart = null;
let qualityDynamicsDaysChart = null;

function qualityAnalysisSeverityLabel(sev) {
  if (sev === "critical") return "критично";
  if (sev === "high") return "высокий";
  if (sev === "medium") return "средний";
  if (sev === "watch") return "наблюдение";
  return sev || "—";
}

function qualityFmtDelta(key, v) {
  if (v == null || Number.isNaN(Number(v))) return "—";
  const n = Number(v);
  const isDays = String(key).includes("days");
  const sign = n > 0 ? "+" : "";
  const unit = isDays ? " дн" : "";
  let tone = "is-flat";
  if (isDays) {
    if (n <= -1) tone = "is-up";
    else if (n >= 1) tone = "is-down";
  } else if (n >= 2) tone = "is-up";
  else if (n <= -2) tone = "is-down";
  return `<span class="quality-delta ${tone}">${sign}${n.toFixed(1)}${unit}</span>`;
}

function renderQualityAnalysisTab() {
  const empty = $("#quality-analysis-empty");
  const root = $("#quality-analysis-root");
  if (!root) return;
  const a = qualityAnalysisCache;
  if (!a || !a.orders_count) {
    if (empty) empty.hidden = false;
    root.hidden = true;
    root.innerHTML = "";
    return;
  }
  if (empty) empty.hidden = true;
  root.hidden = false;

  const health = a.health || {};
  const portfolio = a.portfolio || {};
  const bands = portfolio.kpi_bands || {};
  const dyn = a.dynamics || {};
  const deltas = dyn.deltas || {};
  const masters = a.masters || {};
  const score = health.score;
  const scoreTone =
    score == null ? "unknown" : score >= 75 ? "good" : score >= 55 ? "mid" : score >= 40 ? "tense" : "bad";

  const metric = (label, value, hint) => `
    <div class="quality-analysis-metric" title="${escapeHtml(hint || "")}">
      <span class="quality-analysis-metric-label">${escapeHtml(label)}</span>
      <strong>${value == null || value === "" ? "—" : escapeHtml(String(value))}</strong>
    </div>`;

  const fmtNum = (v, digits = 1) =>
    v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(digits);

  const narrativeHtml = (dyn.narrative || [])
    .map((t) => `<li>${escapeHtml(t)}</li>`)
    .join("");

  const deltaRows = [
    ["avg_order_kpi", "Средний KPI"],
    ["avg_calls_kpi", "Звонки"],
    ["avg_rework_kpi", "Дораб."],
    ["avg_total_days", "Всего дн"],
    ["avg_wait_master_days", "До мастера"],
    ["avg_diag_days", "До диагн."],
  ]
    .map(
      ([key, title]) =>
        `<div class="quality-analysis-delta-row"><span>${escapeHtml(title)}</span>${qualityFmtDelta(
          key,
          deltas[key],
        )}</div>`,
    )
    .join("");

  const focusHtml = (a.focus_areas || [])
    .map((f) => {
      const acts = (f.actions || [])
        .map((x) => `<li>${escapeHtml(x)}</li>`)
        .join("");
      return `
        <article class="quality-analysis-focus is-${escapeHtml(f.severity || "medium")}">
          <header>
            <h4>${escapeHtml(f.title || "Фокус")}</h4>
            <span class="quality-sev is-${escapeHtml(f.severity || "medium")}">${escapeHtml(
              qualityAnalysisSeverityLabel(f.severity),
            )}</span>
          </header>
          <p>${escapeHtml(f.detail || "")}</p>
          ${acts ? `<ul class="quality-analysis-actions">${acts}</ul>` : ""}
        </article>`;
    })
    .join("");

  const positivesHtml = (a.positives || [])
    .map((t) => `<li>${escapeHtml(t)}</li>`)
    .join("");

  const masterList = (rows, emptyText) => {
    if (!rows?.length) return `<p class="quality-muted">${escapeHtml(emptyText)}</p>`;
    return `<ul class="quality-analysis-masters">${rows
      .map(
        (m) => `<li>
          <strong>${escapeHtml(m.name || "—")}</strong>
          <span>KPI ${m.avg_kpi == null ? "—" : m.avg_kpi}</span>
          <span>${m.count || 0} зак.</span>
          <span>дораб. ${m.rework_orders || 0}</span>
          <span>${
            m.avg_total_days == null ? "—" : `${Number(m.avg_total_days).toFixed(1)} дн`
          }</span>
        </li>`,
      )
      .join("")}</ul>`;
  };

  const urgentHtml = (a.urgent || [])
    .map((u, idx) => {
      const oid = escapeHtml(u.order_id || "");
      const link = u.url
        ? `<a href="${escapeHtml(u.url)}" target="_blank" rel="noopener">№${oid}</a>`
        : `№${oid}`;
      const reasons = (u.reasons || []).map((r) => `<li>${escapeHtml(r)}</li>`).join("");
      const acts = (u.actions || []).map((r) => `<li>${escapeHtml(r)}</li>`).join("");
      const kpiTone = qualityKpiTone(u.order_kpi);
      return `
        <article class="quality-urgent-card is-${escapeHtml(u.severity || "medium")}">
          <header class="quality-urgent-head">
            <div class="quality-urgent-title">
              <span class="quality-urgent-rank">${idx + 1}</span>
              ${link}
              <span class="quality-sev is-${escapeHtml(u.severity || "medium")}">${escapeHtml(
                qualityAnalysisSeverityLabel(u.severity),
              )}</span>
              <span class="quality-urgent-score" title="Балл срочности">срочн. ${escapeHtml(
                String(u.urgency ?? "—"),
              )}</span>
            </div>
            <div class="quality-urgent-meta">
              <span class="quality-kpi-chip is-${kpiTone}">KPI ${
                u.order_kpi == null ? "—" : u.order_kpi
              }</span>
              <span>${escapeHtml(u.status || "—")}</span>
              <span>${escapeHtml(u.engineer || "—")}</span>
              <span>${escapeHtml(u.device || "—")}</span>
              <span>${u.total_days == null ? "—" : `${u.total_days} дн`}</span>
              ${u.rework_count ? `<span>дораб. ×${u.rework_count}</span>` : ""}
            </div>
          </header>
          <div class="quality-urgent-cols">
            <div>
              <h5>Почему срочно</h5>
              <ul>${reasons || "<li>—</li>"}</ul>
            </div>
            <div>
              <h5>Что сделать сейчас</h5>
              <ul class="quality-analysis-actions">${acts || "<li>—</li>"}</ul>
            </div>
          </div>
        </article>`;
    })
    .join("");

  const generated = fmtQualityDate(a.generated_at) || a.generated_at || "—";
  const dynLabel =
    dyn.points > 0
      ? `снимков: ${dyn.points}${dyn.prev_day ? ` · Δ к ${fmtQualityDate(dyn.prev_day) || dyn.prev_day}` : ""}${
          dyn.curr_day ? ` · текущий ${fmtQualityDate(dyn.curr_day) || dyn.curr_day}` : ""
        }`
      : "снимков динамики пока нет";

  root.innerHTML = `
    <section class="quality-analysis-hero is-${scoreTone}">
      <div class="quality-analysis-score">
        <span class="quality-analysis-score-num">${score == null ? "—" : score}</span>
        <span class="quality-analysis-score-den">/100</span>
        <span class="quality-analysis-score-label">${escapeHtml(health.label || "—")}</span>
      </div>
      <div class="quality-analysis-hero-text">
        <h3>Текущий анализ</h3>
        <p class="quality-analysis-headline">${escapeHtml(a.headline || "")}</p>
        <p class="quality-analysis-summary">${escapeHtml(health.summary || "")}</p>
        <p class="quality-analysis-meta">Собран: ${escapeHtml(String(generated))} · заказов ${
          a.orders_count
        } · срочных в разборе ${a.urgent_total ?? (a.urgent || []).length} · ${escapeHtml(dynLabel)}</p>
      </div>
    </section>

    <section class="quality-analysis-section">
      <h3>Портфель сейчас</h3>
      <div class="quality-analysis-metrics">
        ${metric("Средний KPI", fmtNum(portfolio.avg_order_kpi, 1))}
        ${metric("Звонки", fmtNum(portfolio.avg_calls_kpi, 1))}
        ${metric("Дораб.", fmtNum(portfolio.avg_rework_kpi, 1), "Без доработок = 100")}
        ${metric("Всего дн", fmtNum(portfolio.avg_total_days, 1))}
        ${metric("До мастера", fmtNum(portfolio.avg_wait_master_days, 1))}
        ${metric("До диагн.", fmtNum(portfolio.avg_diag_days, 1))}
        ${metric("KPI ≥70", bands.good ?? 0)}
        ${metric("KPI 40–69", bands.mid ?? 0)}
        ${metric("KPI <40", bands.bad ?? 0)}
        ${metric("Доработок", portfolio.rework_orders ?? 0)}
        ${metric("≥45 дн", portfolio.long_orders_45d ?? 0)}
        ${metric("Флаги мен.", portfolio.manager_flags ?? 0)}
        ${metric("Слабые звонки", portfolio.weak_calls ?? 0)}
        ${metric("Без мастера", portfolio.no_master_count ?? 0)}
      </div>
    </section>

    <section class="quality-analysis-section">
      <h3>Динамика к прошлому снимку</h3>
      <div class="quality-analysis-dynamics-grid">
        <div class="quality-analysis-deltas">${deltaRows}</div>
        <ul class="quality-analysis-narrative">${
          narrativeHtml || "<li>Нет изменений для комментария</li>"
        }</ul>
      </div>
    </section>

    <div class="quality-analysis-split">
      <section class="quality-analysis-section">
        <h3>Зоны внимания</h3>
        <div class="quality-analysis-focus-list">${
          focusHtml || `<p class="quality-muted">Явных зон внимания не выделено.</p>`
        }</div>
      </section>
      <section class="quality-analysis-section">
        <h3>Что уже хорошо</h3>
        <ul class="quality-analysis-positives">${positivesHtml || "<li>—</li>"}</ul>
        <h3 class="quality-analysis-subh">Мастера · лидеры</h3>
        ${masterList(masters.best, "Нет данных")}
        <h3 class="quality-analysis-subh">Мастера · слабее (от 3+ заказов)</h3>
        ${masterList(masters.worst, "Нет мастеров с 3+ заказами и KPI")}
      </section>
    </div>

    <section class="quality-analysis-section quality-analysis-urgent-section">
      <h3>Квитанции, требующие срочного внимания
        <span class="quality-analysis-count">${a.urgent_total ?? (a.urgent || []).length}</span>
      </h3>
      <p class="quality-tab-lead quality-analysis-urgent-lead">
        Топ до 30 по баллу срочности: низкий KPI, долгий цикл, доработки, флаги менеджера, слабая коммуникация.
        Для каждой — причины и конкретные действия.
      </p>
      <div class="quality-urgent-list">${
        urgentHtml || `<p class="quality-muted">Срочных квитанций сейчас нет.</p>`
      }</div>
    </section>
  `;
}

async function loadQualityAnalysis() {
  try {
    const res = await fetch("/api/quality/analysis");
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    qualityAnalysisCache = data.analysis || null;
  } catch {
    qualityAnalysisCache = null;
  }
  const active = document.querySelector(".quality-tab.is-active")?.getAttribute("data-quality-tab");
  if (active === "analysis") renderQualityAnalysisTab();
}

async function sendQualityAnalysisToTelegram() {
  const btn = $("#quality-tg-btn");
  const status = $("#quality-tg-status");
  if (btn) btn.disabled = true;
  if (status) {
    status.hidden = false;
    status.textContent = "Отправка…";
    status.classList.remove("is-error", "is-ok");
  }
  try {
    const res = await fetch("/api/quality/analysis/telegram", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail || data.error || res.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    if (status) {
      status.textContent = `Отправлено ${data.sent ?? "—"} сообщ.`;
      status.classList.add("is-ok");
    }
  } catch (err) {
    if (status) {
      status.textContent = err.message || String(err);
      status.classList.add("is-error");
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

$("#quality-tg-btn")?.addEventListener("click", () => sendQualityAnalysisToTelegram());

function fmtQualityChartDay(iso) {
  if (!iso) return "";
  const m = String(iso).match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!m) return String(iso);
  return `${m[3]}.${m[2]}`;
}

function destroyQualityDynamicsCharts() {
  if (qualityDynamicsKpiChart) {
    qualityDynamicsKpiChart.destroy();
    qualityDynamicsKpiChart = null;
  }
  if (qualityDynamicsDaysChart) {
    qualityDynamicsDaysChart.destroy();
    qualityDynamicsDaysChart = null;
  }
}

function renderQualityDynamicsTab() {
  const empty = $("#quality-dynamics-empty");
  const body = $("#quality-dynamics-body");
  const meta = $("#quality-dynamics-meta");
  const days = qualityDailyStatsCache || [];
  if (!days.length) {
    destroyQualityDynamicsCharts();
    if (empty) empty.hidden = false;
    if (body) body.hidden = true;
    return;
  }
  if (empty) empty.hidden = true;
  if (body) body.hidden = false;
  if (meta) {
    const first = days[0]?.day;
    const last = days[days.length - 1]?.day;
    meta.textContent = `Точек: ${days.length} · с ${fmtQualityDate(first)} по ${fmtQualityDate(last)} · заказов в последнем снимке: ${
      days[days.length - 1]?.orders_count ?? "—"
    }`;
  }
  if (typeof Chart === "undefined") return;
  const labels = days.map((d) => fmtQualityChartDay(d.day));
  const series = (key) => days.map((d) => (d[key] == null ? null : Number(d[key])));

  destroyQualityDynamicsCharts();
  const kpiCanvas = $("#quality-dynamics-kpi-chart");
  const daysCanvas = $("#quality-dynamics-days-chart");
  const lineOpts = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: { position: "bottom" },
      tooltip: {
        callbacks: {
          title(items) {
            const i = items[0]?.dataIndex;
            return i == null ? "" : fmtQualityDate(days[i]?.day);
          },
        },
      },
    },
    scales: {
      x: {
        ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 },
        grid: { color: "rgba(28,36,48,0.05)" },
      },
      y: {
        beginAtZero: true,
        grid: { color: "rgba(28,36,48,0.06)" },
      },
    },
  };

  if (kpiCanvas) {
    qualityDynamicsKpiChart = new Chart(kpiCanvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "KPI",
            data: series("avg_order_kpi"),
            borderColor: "#0f6e56",
            backgroundColor: "rgba(15,110,86,0.12)",
            tension: 0.25,
            spanGaps: true,
            pointRadius: 3,
          },
          {
            label: "Звонки",
            data: series("avg_calls_kpi"),
            borderColor: "#1a5f8a",
            backgroundColor: "transparent",
            tension: 0.25,
            spanGaps: true,
            pointRadius: 3,
          },
          {
            label: "Дораб.",
            data: series("avg_rework_kpi"),
            borderColor: "#c45c26",
            backgroundColor: "transparent",
            tension: 0.25,
            spanGaps: true,
            pointRadius: 3,
          },
        ],
      },
      options: {
        ...lineOpts,
        scales: {
          ...lineOpts.scales,
          y: { ...lineOpts.scales.y, min: 0, max: 100 },
        },
      },
    });
  }
  if (daysCanvas) {
    qualityDynamicsDaysChart = new Chart(daysCanvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Всего дн",
            data: series("avg_total_days"),
            borderColor: "#a12828",
            backgroundColor: "transparent",
            tension: 0.25,
            spanGaps: true,
            pointRadius: 3,
          },
          {
            label: "До мастера",
            data: series("avg_wait_master_days"),
            borderColor: "#a15c12",
            backgroundColor: "transparent",
            tension: 0.25,
            spanGaps: true,
            pointRadius: 3,
          },
          {
            label: "До диагн.",
            data: series("avg_diag_days"),
            borderColor: "#5d6b7c",
            backgroundColor: "transparent",
            tension: 0.25,
            spanGaps: true,
            pointRadius: 3,
          },
        ],
      },
      options: lineOpts,
    });
  }
}

async function loadQualityDailyStats() {
  try {
    const res = await fetch("/api/quality/daily-stats");
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    qualityDailyStatsCache = data.days || [];
  } catch {
    qualityDailyStatsCache = [];
  }
  const active = document.querySelector(".quality-tab.is-active")?.getAttribute("data-quality-tab");
  if (active === "dynamics") renderQualityDynamicsTab();
}

function setQualityTab(tab) {
  const root = $("#view-quality");
  if (!root) return;
  const id = ["overview", "masters", "summary", "dynamics", "analysis"].includes(tab)
    ? tab
    : "overview";
  // Только вкладки Качества — не трогаем панели Выработки (общий класс .quality-tab*).
  root.querySelectorAll(".quality-tab").forEach((btn) => {
    const on = btn.getAttribute("data-quality-tab") === id;
    btn.classList.toggle("is-active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  });
  root.querySelectorAll(".quality-tab-panel").forEach((panel) => {
    const on = panel.id === `quality-tab-${id}`;
    panel.classList.toggle("is-active", on);
    panel.hidden = !on;
  });
  try {
    localStorage.setItem(QUALITY_TAB_KEY, id);
  } catch {
    /* ignore */
  }
  if (id === "masters") renderQualityMastersTab();
  if (id === "summary") renderQualitySummaryTab();
  if (id === "dynamics") {
    loadQualityDailyStats().then(() => renderQualityDynamicsTab());
  }
  if (id === "analysis") {
    loadQualityAnalysis().then(() => renderQualityAnalysisTab());
  }
}

function initQualityTabs() {
  const root = $("#view-quality");
  if (!root) return;
  const tabs = root.querySelectorAll(".quality-tab");
  if (!tabs.length || tabs[0].dataset.ready) return;
  tabs.forEach((btn) => {
    btn.dataset.ready = "1";
    btn.addEventListener("click", () => setQualityTab(btn.getAttribute("data-quality-tab")));
  });
  let saved = "overview";
  try {
    saved = localStorage.getItem(QUALITY_TAB_KEY) || "overview";
  } catch {
    saved = "overview";
  }
  setQualityTab(saved);
}

async function loadQualityOrders() {
  const tbody = $("#quality-tbody");
  const statusEl = $("#quality-sync-status");
  if (!tbody) return null;
  initQualityColResize();
  initQualitySort();
  try {
    const res = await fetch("/api/quality/orders");
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    if (statusEl) statusEl.textContent = formatSyncStatus(data.sync);
    qualityOrdersCache = data.orders || [];
    if (!qualityOrdersCache.length) {
      tbody.innerHTML = `<tr><td colspan="12" class="quality-empty">Нет данных. Нажмите «Обновить из CRM».</td></tr>`;
      renderQualityMastersTab();
      renderQualitySummaryTab();
      return data.sync || null;
    }
    renderQualityOrders();
    return data.sync || null;
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="12" class="quality-empty">Ошибка: ${escapeHtml(err.message || err)}</td></tr>`;
    return null;
  }
}

function qualityFeedKindLabel(ev) {
  const kind = ev.kind || "";
  if (kind === "call") {
    const ok = ev.call_ok;
    const mark = ok === true ? "✓" : ok === false ? "✗" : "";
    const cls =
      ok === true ? "is-call-ok" : ok === false ? "is-call-fail" : "is-call";
    if (ev.call_dir === "inbound") return { label: `вх.${mark}`, cls };
    if (ev.call_dir === "outbound") return { label: `исх.${mark}`, cls };
    if (ev.call_dir === "missed") return { label: "проп.✗", cls: "is-call-fail" };
    return { label: `звонок${mark}`, cls };
  }
  if (kind === "master_changed") return { label: "мастер", cls: "is-master" };
  if (kind === "status_changed") return { label: "статус", cls: "is-status" };
  return { label: "комм.", cls: "" };
}

function closeQualityFeedModal() {
  document.getElementById("quality-feed-modal")?.remove();
}

async function openQualityFeed(orderId) {
  if (!orderId) return;
  closeQualityFeedModal();
  const overlay = document.createElement("div");
  overlay.id = "quality-feed-modal";
  overlay.className = "cj-import-overlay quality-feed-overlay";
  const card = document.createElement("div");
  card.className = "cj-import-card";
  card.innerHTML = `<div class="cj-import-loading">Загрузка ленты №${escapeHtml(orderId)}…</div>`;
  overlay.appendChild(card);
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeQualityFeedModal();
  });
  document.body.appendChild(overlay);
  try {
    const res = await fetch(`/api/quality/orders/${encodeURIComponent(orderId)}`);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    const o = data.order || {};
    const feed = o.feed || [];
    const feedHtml = feed.length
      ? feed
          .map((f) => {
            const k = qualityFeedKindLabel(f);
            return `<div class="cj-feed-row">
              <span class="cj-feed-date">${escapeHtml(f.date || f.date_iso || "")}</span>
              <span class="quality-feed-kind ${k.cls}">${escapeHtml(k.label)}</span>
              <span class="cj-feed-author">${escapeHtml(f.author || "")}</span>
              <span class="cj-feed-text">${escapeHtml(f.text || "")}</span>
            </div>`;
          })
          .join("")
      : "<em>Лента пуста</em>";
    const crm = o.url
      ? `<a href="${escapeHtml(o.url)}" target="_blank" rel="noopener">открыть в CRM</a>`
      : "";
    const m = o.metrics || {};
    const mgrFlag = m.manager_no_answer_missed
      ? `<span class="quality-mgr-flag" title="После согласования неуспешный исходящий, статус не «На согласовании»/«Не дозвонились»">статус?</span>`
      : "";
    const reworkMeta =
      Number(m.rework_count || 0) > 0
        ? `<span>Дораб.: <strong>${m.rework_kpi ?? "—"}/100</strong> · ${m.rework_count}× с ${escapeHtml(m.last_rework_at || "—")} · диаг ${fmtDays(m.rework_diag_days)} / рем ${fmtDays(m.rework_repair_days)} / всего ${fmtDays(m.rework_total_days)}</span>`
        : "";
    card.innerHTML = `
      <div class="cj-import-head">
        <strong>Лента · №${escapeHtml(o.order_id || orderId)}</strong>
        <button type="button" class="quality-back-btn" data-close>Закрыть</button>
      </div>
      <div class="quality-feed-meta">
        <span>Статус: <strong>${escapeHtml(o.status || "—")}</strong></span>
        <span>Мастер: <strong>${escapeHtml(o.engineer || "—")}</strong></span>
        <span>Устройство: <strong>${escapeHtml(o.device || "—")}</strong></span>
        <span>Принят: <strong>${escapeHtml(o.accepted_at || "—")}</strong></span>
        <span>Событий: <strong>${feed.length}</strong></span>
        <span>Кэш: <strong>${escapeHtml(o.feed_synced_at || "—")}</strong></span>
        <span>KPI: <strong>${m.order_kpi != null ? `${m.order_kpi}/100` : "—"}</strong></span>
        ${reworkMeta}
        ${mgrFlag}
        ${crm}
      </div>
      <div class="quality-feed-body"><div class="cj-feed">${feedHtml}</div></div>
    `;
    card.querySelector("[data-close]")?.addEventListener("click", closeQualityFeedModal);
  } catch (err) {
    card.innerHTML = `<div class="cj-import-error">Ошибка: ${escapeHtml(err.message || err)}</div>
      <div class="cj-import-actions"></div>`;
    const actions = card.querySelector(".cj-import-actions");
    const b = document.createElement("button");
    b.type = "button";
    b.className = "cj-import-btn is-muted";
    b.textContent = "Закрыть";
    b.addEventListener("click", closeQualityFeedModal);
    actions?.appendChild(b);
  }
}

function stopQualityPoll() {
  if (qualityPollTimer) {
    clearTimeout(qualityPollTimer);
    qualityPollTimer = null;
  }
}

/** Poll only while sync is running; stops itself when idle/error. */
function startQualityPoll() {
  stopQualityPoll();
  const tick = async () => {
    qualityPollTimer = null;
    const sync = await loadQualityOrders();
    if (sync?.status === "running") {
      qualityPollTimer = setTimeout(tick, 2000);
      return;
    }
    const btn = $("#quality-sync-btn");
    const forceBtn = $("#quality-force-btn");
    if (btn) btn.disabled = false;
    if (forceBtn) forceBtn.disabled = false;
    // После sync обновить динамику и анализ (пересобраны на сервере).
    loadQualityDailyStats();
    loadQualityAnalysis();
    const statusEl = $("#quality-sync-status");
    const msg = String(sync?.message || "");
    if (statusEl && /pages\s+\d+/i.test(msg)) {
      statusEl.textContent = `${msg} · витрина: git add/commit/push docs/quality/data.json`;
    }
  };
  qualityPollTimer = setTimeout(tick, 500);
}

async function runQualitySync(force = false) {
  const statusEl = $("#quality-sync-status");
  const btn = $("#quality-sync-btn");
  const forceBtn = $("#quality-force-btn");
  if (btn) btn.disabled = true;
  if (forceBtn) forceBtn.disabled = true;
  if (statusEl) statusEl.textContent = force ? "Полный пересбор…" : "Старт обновления…";
  try {
    const res = await fetch("/api/quality/sync", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ force: !!force }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    startQualityPoll();
  } catch (err) {
    if (statusEl) statusEl.textContent = `Ошибка: ${err.message || err}`;
    if (btn) btn.disabled = false;
    if (forceBtn) forceBtn.disabled = false;
  }
}

$("#quality-sync-btn")?.addEventListener("click", () => runQualitySync(false));
$("#quality-force-btn")?.addEventListener("click", () => {
  if (confirm("Перекачать ленту по всем заказам из списка? Это ~300 запросов к CRM (несколько минут).")) {
    runQualitySync(true);
  }
});

async function exportQualityPages() {
  const statusEl = $("#quality-sync-status");
  const btn = $("#quality-export-pages-btn");
  if (btn) btn.disabled = true;
  if (statusEl) statusEl.textContent = "Экспорт data.json…";
  try {
    const res = await fetch("/api/quality/export-pages", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    if (statusEl) {
      statusEl.textContent = `Pages: ${data.orders ?? "—"} зак. → docs/quality/data.json (сделайте git push)`;
    }
  } catch (err) {
    if (statusEl) statusEl.textContent = `Экспорт: ${err.message || err}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

$("#quality-export-pages-btn")?.addEventListener("click", () => exportQualityPages());

function renderQualityCalcResult(order) {
  const box = $("#quality-calc-result");
  if (!box) return;
  const m = order.metrics || {};
  const kpi = m.order_kpi != null ? Number(m.order_kpi) : null;
  const tone = qualityKpiTone(kpi);
  const parts = Array.isArray(m.order_kpi_parts) ? m.order_kpi_parts : [];
  const partsHtml = parts.length
    ? parts
        .map((p) => {
          const pt = qualityKpiTone(p.score);
          return `<li class="is-${pt}"><strong>${escapeHtml(p.label)}</strong> → ${
            p.score
          }/100 · вес ${p.weight_pct ?? "—"}%<br /><span class="quality-muted">${escapeHtml(
            String(p.detail || ""),
          )}</span></li>`;
        })
        .join("")
    : "<li>Нет компонентов</li>";

  const rwN = Number(m.rework_count || 0);
  const crm = order.url
    ? `<a href="${escapeHtml(order.url)}" target="_blank" rel="noopener">открыть в CRM</a>`
    : "";
  const oid = escapeHtml(order.order_id || "");

  box.hidden = false;
  if (kpi != null) {
    const t = Math.pow(Math.max(0, Math.min(100, kpi)) / 100, 1.65);
    const hue = Math.round(t * 118);
    box.style.background = `linear-gradient(135deg, hsla(${hue}, 55%, 96%, 0.95), rgba(255,255,255,0.85))`;
  } else {
    box.style.background = "";
  }

  box.innerHTML = `
    <div class="quality-calc-head">
      <strong>KPI · №${oid}</strong>
      <span class="quality-calc-score is-${tone}">${
        kpi == null ? "—" : `<span>${kpi}</span><small>/ 100</small>`
      }</span>
    </div>
    <div class="quality-calc-meta">
      <span>Статус: <strong>${escapeHtml(order.status || "—")}</strong></span>
      <span>Мастер: <strong>${escapeHtml(order.engineer || "—")}</strong></span>
      <span>Устройство: <strong>${escapeHtml(order.device || "—")}</strong></span>
      <span>Принят: <strong>${escapeHtml(fmtQualityDate(order.accepted_at) || "—")}</strong></span>
      <span>Расчёт до: <strong>${
        m.is_closed
          ? `выдачи ${escapeHtml(fmtQualityDate(m.closed_at) || m.as_of || "—")}`
          : m.is_ready
            ? `готовности ${escapeHtml(fmtQualityDate(m.ready_at || m.as_of) || "—")}`
            : escapeHtml(fmtQualityDate(m.as_of) || "сегодня")
      }</strong></span>
      <span>Событий в ленте: <strong>${order.feed_count ?? (order.feed || []).length}</strong></span>
      <span>Обновлено из CRM: <strong>${escapeHtml(order.feed_synced_at || "—")}</strong></span>
      ${
        m.manager_no_answer_missed
          ? `<span class="quality-mgr-flag">Мен.: статус?</span>`
          : ""
      }
      ${crm}
    </div>
    <div class="quality-calc-grid">
      <div class="quality-calc-card">
        <h4>Итоговый KPI</h4>
        <ul>${partsHtml}</ul>
      </div>
      <div class="quality-calc-card">
        <h4>Сроки</h4>
        <ul>
          <li>Всего в ремонте: <strong>${fmtDays(m.total_days)}</strong> дн</li>
          <li>До мастера: <strong>${fmtDays(m.wait_master_days)}</strong> дн${
            m.master_assigned_at
              ? ` <span class="quality-muted">(с ${escapeHtml(fmtQualityDate(m.master_assigned_at))})</span>`
              : ""
          }</li>
          <li>До диагн./согласования: <strong>${fmtDays(m.diag_days)}</strong> дн${
            m.agreement_at
              ? ` <span class="quality-muted">(до ${escapeHtml(fmtQualityDate(m.agreement_at))})</span>`
              : ""
          }</li>
          ${
            m.agreement_source
              ? `<li class="quality-muted">Источник согласования: ${escapeHtml(m.agreement_source)}</li>`
              : ""
          }
        </ul>
      </div>
      <div class="quality-calc-card">
        <h4>Доработки</h4>
        <ul>
          <li>Приёмов: <strong>${rwN}</strong></li>
          <li>KPI доработок: <strong>${
            m.rework_kpi == null ? "— (не было)" : `${m.rework_kpi}/100`
          }</strong></li>
          <li>Последний приём: <strong>${escapeHtml(fmtQualityDate(m.last_rework_at) || "—")}</strong></li>
          <li>С последней — диаг: <strong>${fmtDays(m.rework_diag_days)}</strong> дн</li>
          <li>С последней — ремонт: <strong>${
            m.rework_repair_days == null && rwN > 0
              ? "ещё не начат"
              : `${fmtDays(m.rework_repair_days)} дн`
          }</strong></li>
          <li>С последней — всего: <strong>${fmtDays(m.rework_total_days)}</strong> дн</li>
        </ul>
      </div>
      <div class="quality-calc-card">
        <h4>Звонки / коммуникация</h4>
        <ul>
          <li>KPI: <strong>${m.calls_kpi == null ? "—" : `${m.calls_kpi}/100`}</strong></li>
          <li>Исходящие: <strong>${m.calls_outbound_ok ?? 0}</strong> ✓ · <strong>${
            m.calls_outbound_fail ?? 0
          }</strong> ✗</li>
          <li>Входящие: <strong>${m.calls_inbound_ok ?? 0}</strong> ✓ · <strong>${
            m.calls_inbound_fail ?? 0
          }</strong> ✗ · проп. <strong>${m.calls_missed ?? 0}</strong></li>
          <li>До заказа принятые вх.: <strong>${m.calls_pre_inbound_ok ?? 0}</strong></li>
          <li>До заказа: связались в тот же день: <strong>${m.calls_pre_miss_same_day ?? 0}</strong></li>
          <li>До заказа: связались до сдачи: <strong>${m.calls_pre_miss_before_visit ?? 0}</strong></li>
          <li>До заказа: не связались до сдачи: <strong>${m.calls_pre_miss_until_visit ?? 0}</strong></li>
          <li>После: без перезвона в тот же день: <strong>${m.calls_missed_unrecovered ?? 0}</strong></li>
          <li>После: перезвонили в тот же день: <strong>${m.calls_missed_recovered ?? 0}</strong></li>
        </ul>
      </div>
    </div>
    <div class="quality-calc-actions">
      <button type="button" class="cj-import-btn is-muted" data-calc-feed="${oid}">Открыть ленту</button>
      <button type="button" class="cj-import-btn is-muted" data-calc-close>Скрыть</button>
    </div>
  `;
  box.querySelector("[data-calc-feed]")?.addEventListener("click", () => {
    openQualityFeed(order.order_id);
  });
  box.querySelector("[data-calc-close]")?.addEventListener("click", () => {
    box.hidden = true;
    box.innerHTML = "";
  });
}

async function runQualityCalc() {
  const input = $("#quality-calc-input");
  const status = $("#quality-calc-status");
  const btn = $("#quality-calc-btn");
  const box = $("#quality-calc-result");
  const raw = String(input?.value || "").trim().replace(/[^\d]/g, "");
  if (!raw) {
    if (status) {
      status.textContent = "Введите номер квитанции";
      status.classList.add("is-error");
    }
    input?.focus();
    return;
  }
  if (input) input.value = raw;
  if (status) {
    status.textContent = "Загружаю из CRM…";
    status.classList.remove("is-error");
  }
  if (btn) btn.disabled = true;
  try {
    const res = await fetch(`/api/quality/calc/${encodeURIComponent(raw)}`, {
      method: "POST",
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail || data.error || res.statusText;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    const order = data.order || {};
    if (!order.feed_count && !(order.feed || []).length && !order.accepted_at) {
      throw new Error(`По №${raw} CRM не вернул данных для расчёта`);
    }
    renderQualityCalcResult(order);
    const m = order.metrics || {};
    const asOf = m.closed_at
      ? `выдана ${fmtQualityDate(m.closed_at)}`
      : m.ready_at
        ? `готова ${fmtQualityDate(m.ready_at)}`
        : `на дату ${fmtQualityDate(m.as_of) || "сегодня"}`;
    if (status) status.textContent = `Готово · №${raw} · ${asOf}`;
  } catch (err) {
    if (box) {
      box.hidden = true;
      box.innerHTML = "";
    }
    if (status) {
      status.textContent = err.message || String(err);
      status.classList.add("is-error");
    }
  } finally {
    if (btn) btn.disabled = false;
  }
}

$("#quality-calc-btn")?.addEventListener("click", () => runQualityCalc());
$("#quality-calc-input")?.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    runQualityCalc();
  }
});

const QUALITY_PANEL_KEY = "jarvis.quality.panelCollapsed";

function applyQualityPanelCollapsed(collapsed) {
  const view = $("#view-quality");
  const btn = $("#quality-panel-toggle");
  if (!view || !btn) return;
  view.classList.toggle("is-panel-collapsed", !!collapsed);
  btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  btn.textContent = collapsed ? "Развернуть" : "Свернуть";
  try {
    localStorage.setItem(QUALITY_PANEL_KEY, collapsed ? "1" : "0");
  } catch {
    /* ignore */
  }
}

function initQualityPanelToggle() {
  const btn = $("#quality-panel-toggle");
  if (!btn || btn.dataset.ready) return;
  btn.dataset.ready = "1";
  let collapsed = false;
  try {
    collapsed = localStorage.getItem(QUALITY_PANEL_KEY) === "1";
  } catch {
    collapsed = false;
  }
  applyQualityPanelCollapsed(collapsed);
  btn.addEventListener("click", () => {
    const view = $("#view-quality");
    applyQualityPanelCollapsed(!view?.classList.contains("is-panel-collapsed"));
  });
}

/* —— Выработка —— */
let vyrobotkaSheetsCache = [];
let vyrobotkaDebtCache = {
  sheets: [],
  tickets: [],
  debt_sum: 0,
  tickets_count: 0,
  verify: null,
  daily: [],
};
let vyrobotkaMoneyChart = null;
let vyrobotkaVolumeChart = null;
let vyrobotkaDebtChart = null;
let vyrobotkaPollTimer = null;
let vyrobotkaVerifyPollTimer = null;
let vyrobotkaWindowResizeBound = false;

function formatVyrobotkaSync(sync) {
  if (!sync) return "—";
  const st = sync.status || "idle";
  if (st === "running") {
    const done = sync.done ?? 0;
    const total = sync.total ?? 0;
    const msg = sync.message ? ` · ${sync.message}` : "";
    return `Обновление… ${done}/${total}${msg}`;
  }
  if (st === "error") return `Ошибка: ${sync.message || "неизвестно"}`;
  if (sync.message) return sync.message;
  return "Готово";
}

function fmtMoneyUa(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return new Intl.NumberFormat("uk-UA", {
    maximumFractionDigits: 0,
  }).format(Number(n));
}

function fmtPct(ratio) {
  if (ratio == null || Number.isNaN(Number(ratio))) return "—";
  return `${(Number(ratio) * 100).toFixed(1)}%`;
}

function stopVyrobotkaPoll() {
  if (vyrobotkaPollTimer) {
    clearInterval(vyrobotkaPollTimer);
    vyrobotkaPollTimer = null;
  }
}

function stopVyrobotkaVerifyPoll() {
  if (vyrobotkaVerifyPollTimer) {
    clearInterval(vyrobotkaVerifyPollTimer);
    vyrobotkaVerifyPollTimer = null;
  }
}

function formatVyrobotkaVerify(verify) {
  if (!verify) return "—";
  const st = verify.status || "idle";
  if (st === "running") {
    const done = verify.done ?? 0;
    const total = verify.total ?? 0;
    const msg = verify.message ? ` · ${verify.message}` : "";
    return `Сверка… ${done}/${total}${msg}`;
  }
  if (st === "error") return `Ошибка сверки: ${verify.message || "неизвестно"}`;
  if (verify.message) return verify.message;
  return "Сверка не запускалась";
}

function vyrobotkaVerdictMeta(verdict) {
  if (verdict === "ok") return { cls: "is-verify-ok", chip: "is-ok", label: "ок" };
  if (verdict === "norm") return { cls: "is-verify-norm", chip: "is-norm", label: "норма" };
  if (verdict === "mismatch") return { cls: "is-verify-bad", chip: "is-bad", label: "расхождение" };
  if (verdict === "missing") return { cls: "is-verify-miss", chip: "is-miss", label: "нет в CRM" };
  if (verdict === "error") return { cls: "is-verify-error", chip: "is-error", label: "ошибка" };
  return { cls: "", chip: "", label: "—" };
}

/** CRM «Выдан» + долга нет → норма (таблица устарела). Работает и без перезапуска API. */
function resolveVyrobotkaDisplayVerdict(verify) {
  if (!verify) return null;
  const raw = verify.verdict || null;
  if (raw === "norm" || raw === "ok" || raw === "missing" || raw === "error") return raw;
  if (raw !== "mismatch") return raw;
  const crmStatus = String(
    verify.crm_status || verify.field_diffs?.status?.crm || ""
  )
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
  if (crmStatus !== "выдан") return raw;
  const debt = verify.crm_debt;
  if (debt == null || debt === "" || Number(debt) <= 1) return "norm";
  return raw;
}

let vyrobotkaDebtSort = { key: "verdict", dir: 1 };
let vyrobotkaUpsellSort = { key: "sheet", dir: 1 };

function vyrobotkaSheetOrder(title) {
  const i = (vyrobotkaSheetsCache || []).findIndex((s) => s.sheet_title === title);
  return i < 0 ? 99999 : i;
}

function vyrobotkaVerdictRank(verdict) {
  if (verdict === "mismatch") return 0;
  if (verdict === "missing") return 1;
  if (verdict === "error") return 2;
  if (!verdict) return 3;
  if (verdict === "norm") return 4;
  if (verdict === "ok") return 5;
  return 6;
}

function updateVyrobotkaSortHeaders(tableId, sortState, attr) {
  const table = document.getElementById(tableId);
  if (!table) return;
  table.querySelectorAll(`th[${attr}]`).forEach((th) => {
    const key = th.getAttribute(attr);
    const on = key === sortState.key;
    th.classList.toggle("is-sorted", on);
    const ind = th.querySelector(".vyrobotka-sort-ind");
    if (ind) ind.textContent = on ? (sortState.dir > 0 ? "▲" : "▼") : "";
  });
}

function initVyrobotkaTableSort() {
  const debtTable = $("#vyrobotka-debt-table");
  if (debtTable && !debtTable.dataset.sortReady) {
    debtTable.dataset.sortReady = "1";
    debtTable.querySelectorAll("th[data-debt-sort]").forEach((th) => {
      th.querySelector(".vyrobotka-th-btn")?.addEventListener("click", () => {
        const key = th.getAttribute("data-debt-sort");
        if (vyrobotkaDebtSort.key === key) vyrobotkaDebtSort.dir *= -1;
        else {
          vyrobotkaDebtSort.key = key;
          vyrobotkaDebtSort.dir = 1;
        }
        renderVyrobotkaDebt();
      });
    });
  }
  const upsellTable = $("#vyrobotka-upsell-table");
  if (upsellTable && !upsellTable.dataset.sortReady) {
    upsellTable.dataset.sortReady = "1";
    upsellTable.querySelectorAll("th[data-upsell-sort]").forEach((th) => {
      th.querySelector(".vyrobotka-th-btn")?.addEventListener("click", () => {
        const key = th.getAttribute("data-upsell-sort");
        if (vyrobotkaUpsellSort.key === key) vyrobotkaUpsellSort.dir *= -1;
        else {
          vyrobotkaUpsellSort.key = key;
          vyrobotkaUpsellSort.dir = 1;
        }
        renderVyrobotkaUpsell();
      });
    });
  }
}

function startVyrobotkaPoll() {
  stopVyrobotkaPoll();
  vyrobotkaPollTimer = setInterval(async () => {
    try {
      const res = await fetch("/api/vyrobotka/sync");
      const data = await res.json().catch(() => ({}));
      const sync = data.sync;
      const statusEl = $("#vyrobotka-sync-status");
      if (statusEl) statusEl.textContent = formatVyrobotkaSync(sync);
      if (sync?.status !== "running") {
        stopVyrobotkaPoll();
        await loadVyrobotkaStats();
      }
    } catch {
      /* ignore */
    }
  }, 900);
}

function destroyVyrobotkaCharts() {
  if (vyrobotkaMoneyChart) {
    vyrobotkaMoneyChart.destroy();
    vyrobotkaMoneyChart = null;
  }
  if (vyrobotkaVolumeChart) {
    vyrobotkaVolumeChart.destroy();
    vyrobotkaVolumeChart = null;
  }
  if (vyrobotkaDebtChart) {
    vyrobotkaDebtChart.destroy();
    vyrobotkaDebtChart = null;
  }
}

const VYROBOTKA_SPLIT_DEFAULT = 66.666;
const VYROBOTKA_SPLIT_MIN = 35;
const VYROBOTKA_SPLIT_MAX = 80;

function resizeVyrobotkaCharts() {
  requestAnimationFrame(() => {
    try {
      vyrobotkaMoneyChart?.resize();
      vyrobotkaVolumeChart?.resize();
      vyrobotkaDebtChart?.resize();
    } catch {
      /* ignore */
    }
  });
}

function setVyrobotkaSplit(splitEl, storageKey, pct) {
  if (!splitEl) return;
  const clamped = Math.min(
    VYROBOTKA_SPLIT_MAX,
    Math.max(VYROBOTKA_SPLIT_MIN, Number(pct) || VYROBOTKA_SPLIT_DEFAULT)
  );
  splitEl.style.setProperty("--vyrobotka-split", `${clamped}%`);
  try {
    localStorage.setItem(storageKey, String(clamped));
  } catch {
    /* ignore */
  }
  resizeVyrobotkaCharts();
}

function bindVyrobotkaSplit(splitId, handleId, storageKey) {
  const split = document.getElementById(splitId);
  const handle = document.getElementById(handleId);
  if (!split || !handle) return;

  let saved = VYROBOTKA_SPLIT_DEFAULT;
  try {
    const raw = localStorage.getItem(storageKey);
    if (raw != null && raw !== "") saved = Number(raw);
  } catch {
    saved = VYROBOTKA_SPLIT_DEFAULT;
  }
  setVyrobotkaSplit(split, storageKey, saved);

  if (handle.dataset.ready) return;
  handle.dataset.ready = "1";

  const apply = (pct) => setVyrobotkaSplit(split, storageKey, pct);

  const onPointerMove = (e) => {
    const rect = split.getBoundingClientRect();
    if (rect.width < 40) return;
    apply(((e.clientX - rect.left) / rect.width) * 100);
  };
  const onPointerUp = (e) => {
    handle.releasePointerCapture?.(e.pointerId);
    document.body.classList.remove("vyrobotka-resizing");
    window.removeEventListener("pointermove", onPointerMove);
    window.removeEventListener("pointerup", onPointerUp);
    resizeVyrobotkaCharts();
  };

  handle.addEventListener("pointerdown", (e) => {
    if (e.button != null && e.button !== 0) return;
    e.preventDefault();
    handle.setPointerCapture?.(e.pointerId);
    document.body.classList.add("vyrobotka-resizing");
    window.addEventListener("pointermove", onPointerMove);
    window.addEventListener("pointerup", onPointerUp);
  });

  handle.addEventListener("keydown", (e) => {
    const step = e.shiftKey ? 5 : 2;
    let cur = VYROBOTKA_SPLIT_DEFAULT;
    try {
      cur = parseFloat(getComputedStyle(split).getPropertyValue("--vyrobotka-split")) || cur;
    } catch {
      /* ignore */
    }
    if (e.key === "ArrowLeft") {
      e.preventDefault();
      apply(cur - step);
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      apply(cur + step);
    } else if (e.key === "Home") {
      e.preventDefault();
      apply(VYROBOTKA_SPLIT_DEFAULT);
    }
  });
}

function initVyrobotkaSplits() {
  bindVyrobotkaSplit(
    "vyrobotka-upsell-split",
    "vyrobotka-upsell-resizer",
    "jarvis.vyrobotka.upsellSplit"
  );
  if (!vyrobotkaWindowResizeBound) {
    vyrobotkaWindowResizeBound = true;
    window.addEventListener("resize", () => {
      if ($("#view-processes")?.classList.contains("active")) resizeVyrobotkaCharts();
    });
  }
}

function shortVyrobotkaLabel(title) {
  const t = String(title || "").replace(/^!/, "");
  const m = t.match(/^(\d{6,8})\((\d{2}-\d{2})\)$/);
  if (!m) return t;
  const head = m[1];
  const range = m[2];
  if (head.length >= 8) {
    return `${head.slice(4, 6)}.${head.slice(6, 8)}`;
  }
  // 202609(16-23) → 09/26 · 16-23
  return `${head.slice(4, 6)}/${head.slice(2, 4)} · ${range}`;
}

function vyrobotkaLineDefaults() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    layout: { padding: { top: 4, right: 4, bottom: 0, left: 0 } },
    plugins: {
      legend: {
        position: "bottom",
        labels: { boxWidth: 10, boxHeight: 10, font: { size: 11 }, padding: 14 },
      },
    },
    scales: {
      x: {
        grid: { color: "rgba(28,36,48,0.06)" },
        ticks: {
          maxRotation: 45,
          minRotation: 0,
          autoSkip: true,
          maxTicksLimit: 12,
          font: { size: 10 },
          color: "#5d6b7c",
        },
      },
    },
  };
}

function renderVyrobotkaUpsell() {
  const body = $("#vyrobotka-upsell-body");
  const meta = $("#vyrobotka-upsell-meta");
  const kpis = $("#vyrobotka-upsell-kpis");
  const tbody = $("#vyrobotka-upsell-tbody");
  const moneyCanvas = $("#vyrobotka-chart-money");
  const volumeCanvas = $("#vyrobotka-chart-volume");
  const sheets = vyrobotkaSheetsCache || [];

  if (!sheets.length) {
    if (vyrobotkaMoneyChart) {
      vyrobotkaMoneyChart.destroy();
      vyrobotkaMoneyChart = null;
    }
    if (vyrobotkaVolumeChart) {
      vyrobotkaVolumeChart.destroy();
      vyrobotkaVolumeChart = null;
    }
    return;
  }
  initVyrobotkaSplits();
  initVyrobotkaTableSort();

  const last = sheets[sheets.length - 1];
  const totalTickets = sheets.reduce((a, s) => a + (Number(s.tickets_count) || 0), 0);
  const totalUpsell = sheets.reduce((a, s) => a + (Number(s.upsell_sum) || 0), 0);
  const totalUpsellN = sheets.reduce((a, s) => a + (Number(s.upsell_count) || 0), 0);
  const totalReport = sheets.reduce((a, s) => a + (Number(s.report_sum) || 0), 0);

  if (kpis) {
    kpis.innerHTML = [
      ["Листов", String(sheets.length), `посл. ${last?.sheet_title || "—"}`],
      ["Квитанций", fmtMoneyUa(totalTickets), "все недели"],
      ["Σ досогл.", fmtMoneyUa(totalUpsell), `${totalUpsellN} шт.`],
      ["Σ в отчёте", fmtMoneyUa(totalReport), "мастера"],
      ["Посл. ср. досогл.", fmtMoneyUa(last?.avg_upsell), last?.sheet_title || ""],
      ["Посл. доля", fmtPct(last?.upsell_ratio), `${last?.upsell_count ?? 0} / ${last?.tickets_count ?? 0}`],
    ]
      .map(
        ([label, value, hint]) => `<div class="vyrobotka-kpi">
          <span class="vyrobotka-kpi-label">${escapeHtml(label)}</span>
          <span class="vyrobotka-kpi-value">${escapeHtml(value)}</span>
          <span class="vyrobotka-kpi-hint">${escapeHtml(hint)}</span>
        </div>`
      )
      .join("");
  }

  if (meta) {
    meta.textContent = `${sheets.length} недельных листов · от ${sheets[0]?.sheet_title || "—"} до ${last?.sheet_title || "—"}`;
  }

  if (tbody) {
    const tableSheets = [...sheets].sort((a, b) => {
      if (vyrobotkaUpsellSort.key === "sheet") {
        return vyrobotkaUpsellSort.dir * (vyrobotkaSheetOrder(a.sheet_title) - vyrobotkaSheetOrder(b.sheet_title));
      }
      return 0;
    });
    updateVyrobotkaSortHeaders("vyrobotka-upsell-table", vyrobotkaUpsellSort, "data-upsell-sort");
    tbody.innerHTML = tableSheets
      .map(
        (s) => `<tr>
          <td>${escapeHtml(s.sheet_title)}</td>
          <td>${fmtMoneyUa(s.avg_upsell)}</td>
          <td>${fmtMoneyUa(s.upsell_sum)}</td>
          <td>${s.upsell_count ?? 0}</td>
          <td>${fmtPct(s.upsell_ratio)}</td>
          <td>${s.tickets_count ?? 0}</td>
          <td>${fmtMoneyUa(s.report_sum)}</td>
        </tr>`
      )
      .join("");
  }

  if (typeof Chart === "undefined") return;
  destroyVyrobotkaCharts();
  const labels = sheets.map((s) => shortVyrobotkaLabel(s.sheet_title));
  const base = vyrobotkaLineDefaults();
  const line = {
    tension: 0.3,
    spanGaps: true,
    pointRadius: 2,
    pointHoverRadius: 4,
    borderWidth: 2.25,
    backgroundColor: "transparent",
  };

  if (moneyCanvas) {
    vyrobotkaMoneyChart = new Chart(moneyCanvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            ...line,
            label: "Ср. досогласование",
            data: sheets.map((s) => s.avg_upsell),
            borderColor: "#0f6e56",
          },
          {
            ...line,
            label: "Σ досогласований",
            data: sheets.map((s) => s.upsell_sum),
            borderColor: "#c45c26",
          },
          {
            ...line,
            label: "Σ в отчёте",
            data: sheets.map((s) => s.report_sum),
            borderColor: "#1a5f8a",
          },
        ],
      },
      options: {
        ...base,
        plugins: {
          ...base.plugins,
          tooltip: {
            callbacks: {
              title: (items) => sheets[items[0]?.dataIndex]?.sheet_title || "",
              label(ctx) {
                const v = ctx.parsed.y;
                return v == null ? `${ctx.dataset.label}: —` : `${ctx.dataset.label}: ${fmtMoneyUa(v)}`;
              },
            },
          },
        },
        scales: {
          ...base.scales,
          y: {
            beginAtZero: true,
            grid: { color: "rgba(28,36,48,0.07)" },
            ticks: {
              color: "#5d6b7c",
              callback: (v) => fmtMoneyUa(v),
              font: { size: 10 },
            },
          },
        },
      },
    });
  }

  if (volumeCanvas) {
    vyrobotkaVolumeChart = new Chart(volumeCanvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            ...line,
            label: "Кол-во досогл.",
            data: sheets.map((s) => s.upsell_count),
            borderColor: "#6b4f9a",
            yAxisID: "y",
          },
          {
            ...line,
            label: "Квитанций",
            data: sheets.map((s) => s.tickets_count),
            borderColor: "#5d6b7c",
            yAxisID: "y",
          },
          {
            ...line,
            label: "Доля, %",
            data: sheets.map((s) =>
              s.upsell_ratio == null ? null : Number(s.upsell_ratio) * 100
            ),
            borderColor: "#a12828",
            borderDash: [5, 4],
            yAxisID: "y1",
          },
        ],
      },
      options: {
        ...base,
        plugins: {
          ...base.plugins,
          tooltip: {
            callbacks: {
              title: (items) => sheets[items[0]?.dataIndex]?.sheet_title || "",
              label(ctx) {
                const v = ctx.parsed.y;
                if (v == null) return `${ctx.dataset.label}: —`;
                if (ctx.dataset.yAxisID === "y1") return `${ctx.dataset.label}: ${v.toFixed(1)}%`;
                return `${ctx.dataset.label}: ${v}`;
              },
            },
          },
        },
        scales: {
          ...base.scales,
          y: {
            beginAtZero: true,
            position: "left",
            title: { display: true, text: "шт", color: "#5d6b7c", font: { size: 11 } },
            grid: { color: "rgba(28,36,48,0.07)" },
            ticks: { color: "#5d6b7c", font: { size: 10 } },
          },
          y1: {
            beginAtZero: true,
            max: 100,
            position: "right",
            title: { display: true, text: "%", color: "#5d6b7c", font: { size: 11 } },
            grid: { drawOnChartArea: false },
            ticks: {
              color: "#5d6b7c",
              font: { size: 10 },
              callback: (v) => `${v}%`,
            },
          },
        },
      },
    });
  }

  resizeVyrobotkaCharts();
}

function fmtVyrobotkaCellTip(diff) {
  if (!diff) return "";
  const label = diff.label || "поле";
  const sheetV =
    typeof diff.sheet === "number" ? fmtMoneyUa(diff.sheet) : String(diff.sheet ?? "—");
  const crmV =
    typeof diff.crm === "number"
      ? fmtMoneyUa(diff.crm)
      : diff.crm == null || diff.crm === ""
        ? "—"
        : String(diff.crm);
  return `${label}: в таблице ${sheetV} · в Gincore ${crmV}`;
}

function vyrobotkaDebtTd(displayHtml, field, verify, { strong = false } = {}) {
  const diffs = verify?.field_diffs || {};
  const diff = diffs[field];
  const inner = strong ? `<strong>${displayHtml}</strong>` : displayHtml;
  if (!diff) return `<td>${inner}</td>`;
  const tip = fmtVyrobotkaCellTip(diff);
  return `<td class="is-cell-mismatch" title="${escapeHtml(tip)}">${inner}</td>`;
}

function applyVyrobotkaVerifyUi(verify) {
  const statusEl = $("#vyrobotka-debt-verify-status");
  const btn = $("#vyrobotka-debt-verify-btn");
  const btnNew = $("#vyrobotka-debt-verify-new-btn");
  const cancel = $("#vyrobotka-debt-verify-cancel");
  const reportEl = $("#vyrobotka-debt-report");
  if (statusEl) statusEl.textContent = formatVyrobotkaVerify(verify);
  const running = verify?.status === "running";
  if (btn) btn.disabled = !!running;
  if (btnNew) btnNew.disabled = !!running;
  if (cancel) cancel.hidden = !running;

  const report = verify?.report;
  if (!reportEl) return;
  if (!report || !report.total) {
    reportEl.hidden = true;
    reportEl.innerHTML = "";
    return;
  }
  reportEl.hidden = false;
  const top = report.top_issues || [];
  reportEl.innerHTML = `
    <h3>Отчёт сверки с Gincore</h3>
    <div class="vyrobotka-verify-report-kpis">
      <span class="vyrobotka-verify-chip">всего ${report.total}</span>
      <span class="vyrobotka-verify-chip is-ok">ок ${report.ok ?? 0}</span>
      <span class="vyrobotka-verify-chip is-norm">норма ${report.norm ?? 0}</span>
      <span class="vyrobotka-verify-chip is-bad">расхождения ${report.mismatch ?? 0}</span>
      <span class="vyrobotka-verify-chip is-miss">нет в CRM ${report.missing ?? 0}</span>
      <span class="vyrobotka-verify-chip">ошибки ${report.error ?? 0}</span>
    </div>
    ${
      top.length
        ? `<ol class="vyrobotka-verify-issues">${top
            .map(
              (i) => `<li><strong>№${escapeHtml(i.ticket)}</strong> · ${escapeHtml(
                i.sheet_title || ""
              )} — ${escapeHtml(i.summary || i.verdict || "")}</li>`
            )
            .join("")}</ol>`
        : `<p class="vyrobotka-verify-status">Расхождений нет — таблица совпадает с CRM.</p>`
    }
  `;
}

function renderVyrobotkaDebt() {
  const body = $("#vyrobotka-debt-body");
  const meta = $("#vyrobotka-debt-meta");
  const kpis = $("#vyrobotka-debt-kpis");
  const tbody = $("#vyrobotka-debt-tbody");
  const canvas = $("#vyrobotka-chart-debt");
  const sheets = vyrobotkaDebtCache.sheets || [];
  const tickets = vyrobotkaDebtCache.tickets || [];
  const verify = vyrobotkaDebtCache.verify || null;
  const hasData = (vyrobotkaSheetsCache || []).length > 0;

  if (!hasData) {
    if (vyrobotkaDebtChart) {
      vyrobotkaDebtChart.destroy();
      vyrobotkaDebtChart = null;
    }
    return;
  }
  initVyrobotkaSplits();
  initVyrobotkaTableSort();
  applyVyrobotkaVerifyUi(verify);

  const last = sheets[sheets.length - 1];
  const debtSum = Number(vyrobotkaDebtCache.debt_sum) || 0;
  const debtN = Number(vyrobotkaDebtCache.tickets_count) || tickets.length;
  const daily = vyrobotkaDebtCache.daily || [];
  const lastDaily = daily.length ? daily[daily.length - 1] : null;
  const badN = Number(verify?.report?.bad_count);
  const normN = Number(verify?.report?.norm);
  const checkedN = Number(verify?.report?.total);

  if (kpis) {
    const kpiRows = [
      ["Σ недоплат", fmtMoneyUa(debtSum), `${debtN} квитанций`],
      ["Квитанций с долгом", fmtMoneyUa(debtN), "все недели"],
      [
        "CRM дебиторка",
        fmtMoneyUa(lastDaily?.crm_debt_sum),
        lastDaily ? `снимок ${fmtQualityDate(lastDaily.day)}` : "после сверки",
      ],
      ["Посл. Σ недоплат", fmtMoneyUa(last?.debt_sum), last?.sheet_title || "—"],
      ["Посл. шт. долгов", fmtMoneyUa(last?.debt_count), fmtPct(last?.debt_ratio)],
      ["Ср. долг (посл.)", fmtMoneyUa(last?.avg_debt), "на квитанцию"],
    ];
    if (checkedN) {
      kpiRows.push([
        "Расхождения CRM",
        fmtMoneyUa(Number.isFinite(badN) ? badN : 0),
        `из ${checkedN} проверенных`,
      ]);
      if (Number.isFinite(normN) && normN > 0) {
        kpiRows.push(["Норма (выдан)", fmtMoneyUa(normN), "долга в CRM нет"]);
      }
    }
    kpis.innerHTML = kpiRows
      .map(
        ([label, value, hint]) => `<div class="vyrobotka-kpi">
          <span class="vyrobotka-kpi-label">${escapeHtml(label)}</span>
          <span class="vyrobotka-kpi-value">${escapeHtml(value)}</span>
          <span class="vyrobotka-kpi-hint">${escapeHtml(hint)}</span>
        </div>`
      )
      .join("");
  }

  if (meta) {
    meta.textContent = `Недоплата = стоимость ремонта − оплачено клиентом · ${debtN} квитанций · Σ ${fmtMoneyUa(debtSum)}`;
  }

  if (tbody) {
    if (!tickets.length) {
      tbody.innerHTML = `<tr><td colspan="10" class="quality-empty">Недоплаченных квитанций нет</td></tr>`;
    } else {
      const ordered = [...tickets].sort((a, b) => {
        const dir = vyrobotkaDebtSort.dir;
        if (vyrobotkaDebtSort.key === "sheet") {
          const ds = vyrobotkaSheetOrder(a.sheet_title) - vyrobotkaSheetOrder(b.sheet_title);
          if (ds) return dir * ds;
          return dir * String(a.ticket || "").localeCompare(String(b.ticket || ""), "ru");
        }
        // сверка
        const dr =
          vyrobotkaVerdictRank(resolveVyrobotkaDisplayVerdict(a.verify)) -
          vyrobotkaVerdictRank(resolveVyrobotkaDisplayVerdict(b.verify));
        if (dr) return dir * dr;
        return (Number(b.debt) || 0) - (Number(a.debt) || 0);
      });
      updateVyrobotkaSortHeaders("vyrobotka-debt-table", vyrobotkaDebtSort, "data-debt-sort");
      const unchecked = ordered.filter((t) => !resolveVyrobotkaDisplayVerdict(t.verify)).length;
      const btnNew = $("#vyrobotka-debt-verify-new-btn");
      if (btnNew && verify?.status !== "running") {
        btnNew.textContent = unchecked
          ? `Сверить новые (${unchecked})`
          : "Сверить новые";
      }

      tbody.innerHTML = ordered
        .map((t) => {
          const v = resolveVyrobotkaDisplayVerdict(t.verify);
          const metaV = vyrobotkaVerdictMeta(v);
          const tipSummary =
            v === "norm" && t.verify?.summary && !String(t.verify.summary).toLowerCase().startsWith("норма")
              ? `Норма: в CRM «Выдан», долга нет · ${t.verify.summary}`
              : t.verify?.summary || "";
          const ticketCell = t.verify?.crm_url
            ? `<a class="vyrobotka-ticket-link" href="${escapeHtml(
                t.verify.crm_url
              )}" target="_blank" rel="noopener">${escapeHtml(t.ticket)}</a>`
            : escapeHtml(t.ticket);
          const mark =
            v === "mismatch" || v === "missing" || v === "error"
              ? "●"
              : v === "norm"
                ? "◆"
                : v === "ok"
                  ? "○"
                  : "";
          const crmDebtCell = t.verify
            ? t.verify.field_diffs?.debt
              ? `<td class="is-cell-mismatch" title="${escapeHtml(
                  fmtVyrobotkaCellTip(t.verify.field_diffs.debt)
                )}">${fmtMoneyUa(t.verify.crm_debt)}</td>`
              : `<td>${fmtMoneyUa(t.verify.crm_debt)}</td>`
            : "<td>—</td>";
          return `<tr class="${metaV.cls}">
            <td title="${escapeHtml(tipSummary)}">${mark}</td>
            <td>${escapeHtml(t.sheet_title)}</td>
            <td>${escapeHtml(t.master || "—")}</td>
            <td>${ticketCell}</td>
            ${vyrobotkaDebtTd(fmtMoneyUa(t.total_repair), "total", t.verify)}
            ${vyrobotkaDebtTd(fmtMoneyUa(t.paid), "paid", t.verify)}
            ${vyrobotkaDebtTd(fmtMoneyUa(t.debt), "debt", t.verify, { strong: true })}
            ${crmDebtCell}
            ${vyrobotkaDebtTd(escapeHtml(t.status || "—"), "status", t.verify)}
            <td title="${escapeHtml(tipSummary)}">${
              v
                ? `<span class="vyrobotka-verdict ${metaV.chip}">${escapeHtml(
                    metaV.label
                  )}</span>`
                : "—"
            }</td>
          </tr>`;
        })
        .join("");
    }
  }

  const dailyMeta = $("#vyrobotka-debt-daily-meta");
  if (dailyMeta) {
    if (!daily.length) {
      dailyMeta.textContent = "Точек динамики пока нет — появится после «Сверить новые» или «Перепроверить все».";
    } else {
      const tip = daily[daily.length - 1];
      dailyMeta.textContent = `Точек: ${daily.length} · посл. ${fmtQualityDate(tip.day)} · CRM ${fmtMoneyUa(
        tip.crm_debt_sum,
      )} · отчёты ${fmtMoneyUa(tip.sheets_debt_sum)}`;
    }
  }

  if (!canvas || typeof Chart === "undefined") return;
  if (vyrobotkaDebtChart) {
    vyrobotkaDebtChart.destroy();
    vyrobotkaDebtChart = null;
  }
  if (!daily.length) {
    resizeVyrobotkaCharts();
    return;
  }
  const labels = daily.map((d) => {
    const m = String(d.day || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m ? `${m[3]}.${m[2]}` : d.day;
  });
  const base = vyrobotkaLineDefaults();
  const n = daily.length;
  const radii = Array.from({ length: n }, (_, i) => (i === n - 1 ? 5 : 3));
  const line = {
    tension: 0.3,
    spanGaps: true,
    pointRadius: radii,
    pointHoverRadius: 6,
    borderWidth: 2.25,
    backgroundColor: "transparent",
  };

  vyrobotkaDebtChart = new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          ...line,
          label: "CRM (ожидаемая оплата)",
          data: daily.map((d) => (d.crm_debt_sum == null ? null : Number(d.crm_debt_sum))),
          borderColor: "#a12828",
        },
        {
          ...line,
          label: "Отчёты мастеров",
          data: daily.map((d) => (d.sheets_debt_sum == null ? null : Number(d.sheets_debt_sum))),
          borderColor: "#1a5f8a",
          borderDash: [5, 4],
        },
      ],
    },
    options: {
      ...base,
      plugins: {
        ...base.plugins,
        tooltip: {
          callbacks: {
            title: (items) => fmtQualityDate(daily[items[0]?.dataIndex]?.day),
            label(ctx) {
              const v = ctx.parsed.y;
              if (v == null) return `${ctx.dataset.label}: —`;
              return `${ctx.dataset.label}: ${fmtMoneyUa(v)}`;
            },
          },
        },
      },
      scales: {
        ...base.scales,
        x: {
          ...base.scales?.x,
          ticks: { maxRotation: 0, autoSkip: false, color: "#5d6b7c", font: { size: 10 } },
          grid: { color: "rgba(28,36,48,0.05)" },
        },
        y: {
          beginAtZero: true,
          title: { display: true, text: "₴", color: "#5d6b7c", font: { size: 11 } },
          grid: { color: "rgba(28,36,48,0.07)" },
          ticks: {
            color: "#5d6b7c",
            font: { size: 10 },
            callback: (v) => fmtMoneyUa(v),
          },
        },
      },
    },
  });

  resizeVyrobotkaCharts();
}

function renderVyrobotkaAll() {
  const empty = $("#vyrobotka-empty");
  const hasData = (vyrobotkaSheetsCache || []).length > 0;
  if (empty) empty.hidden = hasData;
  if (!hasData) {
    destroyVyrobotkaCharts();
    const upsell = $("#vyrobotka-upsell-body");
    const debt = $("#vyrobotka-debt-body");
    if (upsell) upsell.hidden = true;
    if (debt) debt.hidden = true;
    return;
  }
  renderVyrobotkaUpsell();
  renderVyrobotkaDebt();
  setProcessesTab(processesTab);
}

async function loadVyrobotkaStats() {
  const statusEl = $("#vyrobotka-sync-status");
  try {
    const res = await fetch("/api/vyrobotka/stats");
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    vyrobotkaSheetsCache = data.sheets || [];
    vyrobotkaDebtCache = data.debt || {
      sheets: [],
      tickets: [],
      debt_sum: 0,
      tickets_count: 0,
      verify: null,
      daily: [],
    };
    if (!Array.isArray(vyrobotkaDebtCache.daily)) vyrobotkaDebtCache.daily = [];
    if (statusEl) statusEl.textContent = formatVyrobotkaSync(data.sync);
    renderVyrobotkaAll();
    if (vyrobotkaDebtCache.verify?.status === "running") startVyrobotkaVerifyPoll();
    return data.sync || null;
  } catch (err) {
    if (statusEl) statusEl.textContent = `Ошибка: ${err.message || err}`;
    vyrobotkaSheetsCache = [];
    vyrobotkaDebtCache = { sheets: [], tickets: [], debt_sum: 0, tickets_count: 0, verify: null };
    renderVyrobotkaAll();
    return null;
  }
}

function startVyrobotkaVerifyPoll() {
  stopVyrobotkaVerifyPoll();
  vyrobotkaVerifyPollTimer = setInterval(async () => {
    try {
      const res = await fetch("/api/vyrobotka/debt-verify");
      const data = await res.json().catch(() => ({}));
      const verify = data.verify;
      if (vyrobotkaDebtCache) vyrobotkaDebtCache.verify = verify;
      applyVyrobotkaVerifyUi(verify);
      if (verify?.status !== "running") {
        stopVyrobotkaVerifyPoll();
        await loadVyrobotkaStats();
      } else {
        // частичное обновление строк во время прогона
        const map = new Map(
          (verify.rows || []).map((r) => [`${r.sheet_title}::${r.ticket}`, r])
        );
        for (const t of vyrobotkaDebtCache.tickets || []) {
          const vr = map.get(`${t.sheet_title}::${t.ticket}`);
          if (vr) {
            t.verify = {
              verdict: vr.verdict,
              summary: vr.summary,
              issues: vr.issues || [],
              field_diffs: vr.field_diffs || {},
              crm_total: vr.crm_total,
              crm_paid: vr.crm_paid,
              crm_debt: vr.crm_debt,
              crm_status: vr.crm_status,
              crm_url: vr.crm_url,
            };
          }
        }
        renderVyrobotkaDebt();
      }
    } catch {
      /* ignore */
    }
  }, 1200);
}

async function startVyrobotkaDebtVerify(mode = "all") {
  const btn = $("#vyrobotka-debt-verify-btn");
  const btnNew = $("#vyrobotka-debt-verify-new-btn");
  if (btn) btn.disabled = true;
  if (btnNew) btnNew.disabled = true;
  try {
    const res = await fetch("/api/vyrobotka/debt-verify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    if (vyrobotkaDebtCache) vyrobotkaDebtCache.verify = data.verify;
    applyVyrobotkaVerifyUi(data.verify);
    startVyrobotkaVerifyPoll();
  } catch (err) {
    applyVyrobotkaVerifyUi({
      status: "error",
      message: err.message || String(err),
    });
    if (btn) btn.disabled = false;
    if (btnNew) btnNew.disabled = false;
  }
}

async function cancelVyrobotkaDebtVerify() {
  try {
    const res = await fetch("/api/vyrobotka/debt-verify/cancel", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (vyrobotkaDebtCache) vyrobotkaDebtCache.verify = data.verify;
    applyVyrobotkaVerifyUi(data.verify);
  } catch {
    /* ignore */
  }
}

async function startVyrobotkaSync() {
  const statusEl = $("#vyrobotka-sync-status");
  const btn = $("#vyrobotka-sync-btn");
  if (btn) btn.disabled = true;
  try {
    const res = await fetch("/api/vyrobotka/sync", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    if (statusEl) statusEl.textContent = formatVyrobotkaSync(data.sync);
    startVyrobotkaPoll();
  } catch (err) {
    if (statusEl) statusEl.textContent = `Ошибка: ${err.message || err}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

const VYROBOTKA_PANEL_KEY = "jarvis.vyrobotka.panelCollapsed";

function applyVyrobotkaPanelCollapsed(collapsed) {
  const view = $("#view-processes");
  const btn = $("#vyrobotka-panel-toggle");
  if (!view || !btn) return;
  view.classList.toggle("is-panel-collapsed", !!collapsed);
  btn.setAttribute("aria-expanded", collapsed ? "false" : "true");
  btn.textContent = collapsed ? "Развернуть" : "Свернуть";
  try {
    localStorage.setItem(VYROBOTKA_PANEL_KEY, collapsed ? "1" : "0");
  } catch {
    /* ignore */
  }
  resizeVyrobotkaCharts();
}

function initVyrobotkaPanelToggle() {
  const btn = $("#vyrobotka-panel-toggle");
  if (!btn || btn.dataset.ready) return;
  btn.dataset.ready = "1";
  let collapsed = false;
  try {
    collapsed = localStorage.getItem(VYROBOTKA_PANEL_KEY) === "1";
  } catch {
    collapsed = false;
  }
  applyVyrobotkaPanelCollapsed(collapsed);
  btn.addEventListener("click", () => {
    const view = $("#view-processes");
    applyVyrobotkaPanelCollapsed(!view?.classList.contains("is-panel-collapsed"));
  });
}

async function exportVyrobotkaPages() {
  const btn = $("#vyrobotka-export-pages-btn");
  const statusEl = $("#vyrobotka-sync-status");
  if (btn) btn.disabled = true;
  try {
    const res = await fetch("/api/vyrobotka/export-pages", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    if (statusEl) {
      statusEl.textContent = `Pages: ${data.upsell_sheets ?? "—"} листов, ${
        data.debt_tickets ?? "—"
      } долгов → docs/vyrobotka/data.json (сделайте git push)`;
    }
  } catch (err) {
    if (statusEl) statusEl.textContent = `Pages: ${err.message || err}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

$("#vyrobotka-sync-btn")?.addEventListener("click", () => startVyrobotkaSync());
$("#vyrobotka-export-pages-btn")?.addEventListener("click", () => exportVyrobotkaPages());
$("#vyrobotka-debt-verify-btn")?.addEventListener("click", () => startVyrobotkaDebtVerify("all"));
$("#vyrobotka-debt-verify-new-btn")?.addEventListener("click", () =>
  startVyrobotkaDebtVerify("new")
);
$("#vyrobotka-debt-verify-cancel")?.addEventListener("click", () => cancelVyrobotkaDebtVerify());

/* —— Пользователи витрины —— */
let vitrineAccessOptions = [];
let vitrineUsersCache = [];

function accessLabel(id) {
  return vitrineAccessOptions.find((o) => o.id === id)?.label || id;
}

function renderVitrineAccessOptions(selected = []) {
  const box = $("#vitrine-access-options");
  if (!box) return;
  const byGroup = {};
  for (const opt of vitrineAccessOptions) {
    const g = opt.group || "Прочее";
    (byGroup[g] ||= []).push(opt);
  }
  box.innerHTML = Object.entries(byGroup)
    .map(
      ([group, opts]) => `<div class="vitrine-access-group">
        <div class="vitrine-access-group-title">${escapeHtml(group)}</div>
        ${opts
          .map(
            (o) => `<label class="vitrine-access-item">
          <input type="checkbox" name="access" value="${escapeHtml(o.id)}" ${
              selected.includes(o.id) ? "checked" : ""
            } />
          <span>${escapeHtml(o.label)}</span>
        </label>`
          )
          .join("")}
      </div>`
    )
    .join("");
}

function resetVitrineUserForm() {
  const form = $("#vitrine-user-form");
  if (!form) return;
  form.reset();
  form.id.value = "";
  form.enabled.checked = true;
  const pass = form.password;
  if (pass) {
    pass.required = true;
    pass.placeholder = "мин. 4 символа";
  }
  const hint = $("#vitrine-user-pass-hint");
  if (hint) hint.textContent = "При создании пароль обязателен. При правке — оставьте пустым, чтобы не менять.";
  renderVitrineAccessOptions([]);
}

function editVitrineUser(user) {
  const form = $("#vitrine-user-form");
  if (!form || !user) return;
  form.id.value = String(user.id);
  form.login.value = user.login || "";
  form.password.value = "";
  form.password.required = false;
  form.password.placeholder = "без изменений";
  form.enabled.checked = !!user.enabled;
  const hint = $("#vitrine-user-pass-hint");
  if (hint) hint.textContent = "Пароль можно не заполнять — останется прежний.";
  renderVitrineAccessOptions(user.access || []);
  form.login.focus();
}

function renderVitrineUsersTable() {
  const tbody = $("#vitrine-users-tbody");
  if (!tbody) return;
  if (!vitrineUsersCache.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="quality-empty">Пользователей пока нет — создайте первого.</td></tr>`;
    return;
  }
  tbody.innerHTML = vitrineUsersCache
    .map((u) => {
      const access = (u.access || []).map(accessLabel).join(", ") || "—";
      return `<tr>
        <td><strong>${escapeHtml(u.login)}</strong></td>
        <td class="vitrine-access-cell">${escapeHtml(access)}</td>
        <td>${u.enabled ? "активен" : "выкл"}</td>
        <td class="vitrine-users-row-actions">
          <button type="button" class="cj-import-btn is-muted" data-edit-user="${u.id}">Изменить</button>
          <button type="button" class="cj-import-btn is-muted" data-del-user="${u.id}">Удалить</button>
        </td>
      </tr>`;
    })
    .join("");
  tbody.querySelectorAll("[data-edit-user]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const u = vitrineUsersCache.find((x) => String(x.id) === btn.getAttribute("data-edit-user"));
      if (u) editVitrineUser(u);
    });
  });
  tbody.querySelectorAll("[data-del-user]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const id = btn.getAttribute("data-del-user");
      const u = vitrineUsersCache.find((x) => String(x.id) === id);
      if (!u || !confirm(`Удалить пользователя «${u.login}»?`)) return;
      const statusEl = $("#vitrine-users-status");
      try {
        const res = await fetch(`/api/vitrine/users/${id}`, { method: "DELETE" });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
        if (statusEl) statusEl.textContent = `Удалён · экспорт ${data.export?.users ?? 0} польз. → docs/auth/users.json`;
        await loadVitrineUsers();
        resetVitrineUserForm();
      } catch (err) {
        if (statusEl) statusEl.textContent = `Ошибка: ${err.message || err}`;
      }
    });
  });
}

async function loadVitrineUsers() {
  const statusEl = $("#vitrine-users-status");
  try {
    if (!vitrineAccessOptions.length) {
      const optRes = await fetch("/api/vitrine/access-options");
      const optData = await optRes.json().catch(() => ({}));
      vitrineAccessOptions = optData.options || [];
    }
    const res = await fetch("/api/vitrine/users");
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    vitrineUsersCache = data.users || [];
    const form = $("#vitrine-user-form");
    const editingId = form?.id?.value;
    if (editingId) {
      const u = vitrineUsersCache.find((x) => String(x.id) === String(editingId));
      if (u) editVitrineUser(u);
      else resetVitrineUserForm();
    } else if (!$("#vitrine-access-options")?.children.length) {
      renderVitrineAccessOptions([]);
    }
    renderVitrineUsersTable();
  } catch (err) {
    if (statusEl) statusEl.textContent = `Ошибка: ${err.message || err}`;
  }
}

$("#vitrine-user-form")?.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const statusEl = $("#vitrine-users-status");
  const id = String(form.id.value || "").trim();
  const login = String(form.login.value || "").trim();
  const password = String(form.password.value || "");
  const access = [...form.querySelectorAll('input[name="access"]:checked')].map((el) => el.value);
  const enabled = !!form.enabled.checked;
  if (!login) {
    if (statusEl) statusEl.textContent = "Укажите логин";
    return;
  }
  if (!id && password.length < 4) {
    if (statusEl) statusEl.textContent = "Пароль обязателен (мин. 4 символа)";
    return;
  }
  const body = { login, access, enabled };
  if (password) body.password = password;
  try {
    const res = await fetch(id ? `/api/vitrine/users/${id}` : "/api/vitrine/users", {
      method: id ? "PUT" : "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    if (statusEl) {
      statusEl.textContent = `Сохранено · экспорт ${data.export?.users ?? 0} польз. → docs/auth/users.json (git push)`;
    }
    await loadVitrineUsers();
    resetVitrineUserForm();
  } catch (err) {
    if (statusEl) statusEl.textContent = `Ошибка: ${err.message || err}`;
  }
});

$("#vitrine-user-reset")?.addEventListener("click", () => {
  resetVitrineUserForm();
  const statusEl = $("#vitrine-users-status");
  if (statusEl) statusEl.textContent = "";
});

$("#vitrine-users-export-btn")?.addEventListener("click", async () => {
  const statusEl = $("#vitrine-users-status");
  try {
    const res = await fetch("/api/vitrine/users/export", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    if (statusEl) {
      statusEl.textContent = `Экспорт: ${data.users ?? 0} польз. → docs/auth/users.json (git push)`;
    }
  } catch (err) {
    if (statusEl) statusEl.textContent = `Экспорт: ${err.message || err}`;
  }
});

/* —— Страница «Обновления» —— */
let updatesPollTimer = null;
let updatesBusy = false;

function stopUpdatesPoll() {
  if (updatesPollTimer) {
    clearInterval(updatesPollTimer);
    updatesPollTimer = null;
  }
}

function startUpdatesPoll() {
  stopUpdatesPoll();
  updatesPollTimer = setInterval(() => {
    if ($("#view-updates")?.classList.contains("active")) loadUpdatesStatus({ quiet: true });
  }, 4000);
}

function fmtUpdatesWhen(iso) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("ru-RU");
  } catch {
    return String(iso).slice(0, 19).replace("T", " ");
  }
}

function updatesStatusChip(status) {
  const st = String(status || "idle");
  if (st === "running") return { cls: "is-run", label: "идёт" };
  if (st === "error") return { cls: "is-err", label: "ошибка" };
  return { cls: "is-idle", label: "готово" };
}

function renderUpdatesGrid(modules) {
  const grid = $("#updates-grid");
  if (!grid) return;
  if (!modules?.length) {
    grid.innerHTML = `<p class="quality-empty">Нет модулей в сводке.</p>`;
    return;
  }
  grid.innerHTML = modules
    .map((m) => {
      const chip = updatesStatusChip(m.status);
      const pages = m.pages || {};
      const snap = m.snapshot;
      const prog = m.progress;
      const progLine =
        m.status === "running" && prog && prog.total
          ? `<div class="updates-meta">Прогресс: ${prog.done}/${prog.total}</div>`
          : "";
      const snapLine = snap
        ? `<div class="updates-meta">Снимок дебиторки ${escapeHtml(snap.day || "—")}: CRM ${fmtMoneyUa(
            snap.crm_debt_sum,
          )} · отчёты ${fmtMoneyUa(snap.sheets_debt_sum)}</div>`
        : "";
      const pagesLine = pages.exists
        ? `<div class="updates-meta">Pages: <code>${escapeHtml(pages.path)}</code> · ${fmtUpdatesWhen(
            pages.exported_at,
          )}${
            pages.users_count != null ? ` · ${pages.users_count} польз.` : ""
          }</div>`
        : `<div class="updates-meta">Pages: файла ещё нет</div>`;
      const actions = (m.actions || [])
        .map((a) => {
          const cls = a.kind === "primary" ? "cj-import-open" : "cj-import-btn is-muted";
          const disabled = updatesBusy || m.status === "running" ? " disabled" : "";
          return `<button type="button" class="${cls}" data-updates-action="${escapeHtml(
            a.id,
          )}" data-module="${escapeHtml(m.id)}"${disabled}>${escapeHtml(a.label)}</button>`;
        })
        .join("");
      return `<article class="updates-card" data-module-id="${escapeHtml(m.id)}">
        <div class="updates-card-top">
          <span class="updates-block">${escapeHtml(m.block || "")}</span>
          <span class="updates-chip ${chip.cls}">${chip.label}</span>
        </div>
        <h2>${escapeHtml(m.title)}</h2>
        <p class="updates-desc">${escapeHtml(m.description || "")}</p>
        <div class="updates-meta"><strong>Обновлено:</strong> ${fmtUpdatesWhen(
          m.finished_at || pages.exported_at,
        )}</div>
        ${m.message ? `<div class="updates-msg">${escapeHtml(m.message)}</div>` : ""}
        ${progLine}
        ${snapLine}
        ${pagesLine}
        <div class="updates-actions">${actions}</div>
      </article>`;
    })
    .join("");

  grid.querySelectorAll("[data-updates-action]").forEach((btn) => {
    btn.addEventListener("click", () =>
      runUpdatesAction(btn.getAttribute("data-updates-action")),
    );
  });
}

async function loadUpdatesStatus({ quiet = false } = {}) {
  const statusEl = $("#updates-status");
  const grid = $("#updates-grid");
  try {
    const res = await fetch("/api/updates/status");
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    renderUpdatesGrid(data.modules || []);
    if (!quiet && statusEl) statusEl.textContent = "";
    const anyRunning = (data.modules || []).some((m) => m.status === "running");
    if (anyRunning) startUpdatesPoll();
  } catch (err) {
    if (statusEl) statusEl.textContent = `Ошибка: ${err.message || err}`;
    if (grid && !quiet) {
      grid.innerHTML = `<p class="quality-empty">Не удалось загрузить статус.</p>`;
    }
  }
}

async function runUpdatesAction(actionId) {
  const statusEl = $("#updates-status");
  if (!actionId || updatesBusy) return;
  updatesBusy = true;
  if (statusEl) statusEl.textContent = "Запуск…";
  $("#updates-grid")
    ?.querySelectorAll("[data-updates-action]")
    .forEach((b) => {
      b.disabled = true;
    });
  try {
    let res;
    if (actionId === "quality-sync") {
      res = await fetch("/api/quality/sync", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: false }),
      });
    } else if (actionId === "quality-export") {
      res = await fetch("/api/quality/export-pages", { method: "POST" });
    } else if (actionId === "vyrobotka-sync") {
      res = await fetch("/api/vyrobotka/sync", { method: "POST" });
    } else if (actionId === "vyrobotka-export") {
      res = await fetch("/api/vyrobotka/export-pages", { method: "POST" });
    } else if (actionId === "debt-verify-new") {
      res = await fetch("/api/vyrobotka/debt-verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "new" }),
      });
    } else if (actionId === "debt-verify-all") {
      if (!confirm("Перепроверить все недоплаченные квитанции в Gincore? Это может занять несколько минут.")) {
        updatesBusy = false;
        await loadUpdatesStatus();
        return;
      }
      res = await fetch("/api/vyrobotka/debt-verify", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "all" }),
      });
    } else if (actionId === "users-export") {
      res = await fetch("/api/vitrine/users/export", { method: "POST" });
    } else {
      throw new Error(`Неизвестное действие: ${actionId}`);
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || data.error || res.statusText);
    if (statusEl) {
      if (actionId.endsWith("export") || actionId === "users-export") {
        statusEl.textContent = `Экспорт готов → ${data.path || "docs/…"} (сделайте git push)`;
      } else {
        statusEl.textContent = data.sync?.message || data.verify?.message || "Запущено";
      }
    }
    startUpdatesPoll();
    await loadUpdatesStatus({ quiet: true });
  } catch (err) {
    if (statusEl) statusEl.textContent = `Ошибка: ${err.message || err}`;
  } finally {
    updatesBusy = false;
    await loadUpdatesStatus({ quiet: true });
  }
}

$("#updates-refresh-btn")?.addEventListener("click", () => loadUpdatesStatus());

initQualityPanelToggle();
initQualityTabs();
initVyrobotkaPanelToggle();
initProcessesTabs();
resetVitrineUserForm();

addBubble(
  "assistant",
  "Привет. Я Jarvis. Настройте модуль Gincore (логин/пароль) и модель ИИ — затем можно спрашивать про зарплаты, затраты и аналитику."
);
loadSettings();
loadModules();
