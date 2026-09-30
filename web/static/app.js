const state = {
  conversationId: null,
  charts: [],
};

const $ = (sel) => document.querySelector(sel);
const messagesEl = $("#messages");

document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".view").forEach((v) => v.classList.remove("active"));
    btn.classList.add("active");
    $(`#view-${btn.dataset.view}`).classList.add("active");
  });
});

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
  return /^\s*>/.test(String(raw || "").trim());
}

function ensureLineMeta(data) {
  for (const line of data.lines || []) {
    if (!line.is_quote && isQuoteLine(line.raw)) {
      line.is_quote = true;
      line.action = "ignore";
    }
    if (!line.is_checkpoint) {
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
  return `<label>
    ${field.label}
    <input name="${field.key}" type="${field.type}" value="${value ?? ""}" placeholder="${field.placeholder || ""}" />
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
}

addBubble(
  "assistant",
  "Привет. Я Jarvis. Настройте модуль Gincore (логин/пароль) и модель ИИ — затем можно спрашивать про зарплаты, затраты и аналитику."
);
loadSettings();
loadModules();
