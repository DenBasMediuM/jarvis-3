/* global Chart */

const $ = (sel) => document.querySelector(sel);
let DATA = null;
let BRANCH_KPI = null;
let MASTERS_KPI = null;
let REVIEWS_STATS = null;
let rsOutcomesChart = null;
let rsGoogleChart = null;
let rsGoogleDynChart = null;
let rsCallsDynChart = null;
let moneyChart = null;
let volumeChart = null;
let debtChart = null;
let bkCharts = {};
let mkCharts = {};

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function fmtMoney(n) {
  if (n == null || Number.isNaN(Number(n))) return "—";
  return new Intl.NumberFormat("uk-UA", { maximumFractionDigits: 0 }).format(Number(n));
}

function fmtPct(ratio) {
  if (ratio == null || Number.isNaN(Number(ratio))) return "—";
  return `${(Number(ratio) * 100).toFixed(1)}%`;
}

function shortLabel(title) {
  const t = String(title || "").replace(/^!/, "");
  const m = t.match(/^(\d{6,8})\((\d{2}-\d{2})\)$/);
  if (!m) return t;
  const head = m[1];
  const range = m[2];
  if (head.length >= 8) return `${head.slice(4, 6)}.${head.slice(6, 8)}`;
  return `${head.slice(4, 6)}/${head.slice(2, 4)} · ${range}`;
}

let debtSort = { key: "flag", dir: 1 };
/** work | pending | rework — какой блок сейчас листаем */
let debtQueueMode = "work";
const DEBT_PROGRESS_KEY = "jarvis.vyrobotka.debt.progress";
/**
 * Пропуск — только на текущий проход очереди (сбрасывается при новом открытии блока).
 * Отложить — в localStorage, не в очереди, в таблице бирюзовым внизу.
 */
const debtPassSkipped = { work: new Set(), pending: new Set(), rework: new Set() };
const debtDeferred = new Set();
/** ticket → ISO времени отправки решения (нужно, чтобы не сбрасывать при старом rework в снимке) */
const debtDecidedAt = new Map();

function debtFlagRank(flag) {
  const order = { red: 0, mismatch: 1, yellow: 2, open: 3 };
  return order[flag] ?? 9;
}

function debtIsDeferred(ticket) {
  return debtDeferred.has(String(ticket));
}

function debtIsDecided(ticket) {
  return debtDecidedAt.has(String(ticket));
}

function debtProgressLoad() {
  for (const k of Object.keys(debtPassSkipped)) debtPassSkipped[k].clear();
  debtDeferred.clear();
  debtDecidedAt.clear();
  try {
    const raw = localStorage.getItem(DEBT_PROGRESS_KEY);
    if (!raw) return;
    const data = JSON.parse(raw);
    for (const t of data.deferred || []) debtDeferred.add(String(t));
    // миграция: старые persistent skipped → отложенные
    if (!data.deferred && data.skipped) {
      if (typeof data.skipped === "object" && !Array.isArray(data.skipped)) {
        for (const mode of ["work", "pending", "rework"]) {
          for (const t of data.skipped[mode] || []) debtDeferred.add(String(t));
        }
      } else {
        for (const t of data.skipped || []) debtDeferred.add(String(t));
      }
    }
    if (data.decided_at && typeof data.decided_at === "object") {
      for (const [t, at] of Object.entries(data.decided_at)) {
        if (t) debtDecidedAt.set(String(t), String(at || new Date().toISOString()));
      }
    } else {
      const fallbackAt = data.saved_at || new Date().toISOString();
      for (const t of data.decided || []) debtDecidedAt.set(String(t), fallbackAt);
    }
    if (data.queueMode === "pending" || data.queueMode === "rework" || data.queueMode === "work") {
      debtQueueMode = data.queueMode;
    }
  } catch {
    /* ignore */
  }
}

function debtProgressSave() {
  try {
    localStorage.setItem(
      DEBT_PROGRESS_KEY,
      JSON.stringify({
        v: 4,
        exported_at: DATA?.exported_at || null,
        deferred: [...debtDeferred],
        decided: [...debtDecidedAt.keys()],
        decided_at: Object.fromEntries(debtDecidedAt),
        queueMode: debtQueueMode,
        saved_at: new Date().toISOString(),
      }),
    );
  } catch {
    /* ignore */
  }
}

/** Подчистить прогресс под актуальный снимок (после модерации/экспорта). */
function debtProgressReconcile() {
  const byTicket = new Map(
    (DATA?.debt_table || []).map((r) => [String(r.ticket || ""), r]),
  );
  const snapAt = Date.parse(DATA?.exported_at || "") || 0;
  for (const t of [...debtDeferred]) {
    if (!byTicket.has(t)) debtDeferred.delete(t);
  }
  for (const t of [...debtDecidedAt.keys()]) {
    const row = byTicket.get(t);
    if (!row) {
      debtDecidedAt.delete(t);
      continue;
    }
    const ds = String(row.decision_status || "");
    // снимок уже с pending из Jarvis — локальный маркер лишний
    if (ds === "pending") {
      debtDecidedAt.delete(t);
      continue;
    }
    // admin вернул на доработку только если снимок НОВЕЕ нашего решения
    if (ds === "rework") {
      const decidedMs = Date.parse(debtDecidedAt.get(t) || "") || 0;
      if (snapAt && decidedMs && snapAt > decidedMs) {
        debtDecidedAt.delete(t);
        debtDeferred.delete(t);
      }
      // иначе: отправили с «доработать», data.json ещё старый — не трогаем
    }
  }
  debtProgressSave();
}

/** Pending из снимка + локально отправленные (пока data.json не обновили). */
function debtPendingTicketIds() {
  const ids = new Set();
  for (const r of DATA?.debt_table || []) {
    const t = String(r.ticket || "");
    if (!t) continue;
    if (String(r.decision_status || "") === "pending") ids.add(t);
    else if (debtIsDecided(t)) ids.add(t);
  }
  return ids;
}

function debtRowInMainTable(row) {
  const t = String(row?.ticket || "");
  if (!t) return false;
  if (debtIsDecided(t)) return false;
  const ds = String(row?.decision_status || "");
  if (ds === "closed") return false;
  // отложенные показываем в таблице (голубым внизу), даже если pending
  if (debtDeferred.has(t)) return true;
  if (ds === "pending") return false;
  return true;
}

function debtBrowseTicketList(mode = debtQueueMode) {
  const passSkip = debtPassSkipped[mode] || new Set();
  return (DATA?.debt_table || [])
    .filter((r) => {
      const t = String(r.ticket || "");
      if (!t) return false;
      if (debtDeferred.has(t)) return false;
      if (passSkip.has(t)) return false;
      const ds = String(r.decision_status || "");
      if (mode === "pending") {
        return ds === "pending" || debtIsDecided(t);
      }
      if (mode === "rework") return ds === "rework" && !debtIsDecided(t);
      return debtRowInMainTable(r);
    })
    .map((r) => String(r.ticket || ""));
}

function debtMarkDecided(ticket) {
  const t = String(ticket);
  debtDecidedAt.set(t, new Date().toISOString());
  debtDeferred.delete(t);
  for (const mode of Object.keys(debtPassSkipped)) debtPassSkipped[mode].delete(t);
  const row = (DATA?.debt_table || []).find((r) => String(r.ticket) === t);
  if (row) row.decision_status = "pending";
  debtProgressSave();
}

/** Пропуск только до конца текущего прохода очереди. */
function debtMarkPassSkipped(ticket) {
  const mode = debtQueueMode;
  if (!debtPassSkipped[mode]) debtPassSkipped[mode] = new Set();
  debtPassSkipped[mode].add(String(ticket));
}

/** Отложить — переживает F5 и новое открытие блока. */
function debtMarkDeferred(ticket) {
  const t = String(ticket);
  debtDeferred.add(t);
  for (const mode of Object.keys(debtPassSkipped)) debtPassSkipped[mode].delete(t);
  debtProgressSave();
}

function debtClearDeferred() {
  debtDeferred.clear();
  debtProgressSave();
  renderDebt();
}

/** Следующая квитанция после current в текущем блоке. */
function debtNextBrowseTicket(current, mode = debtQueueMode) {
  const eligible = new Set(debtBrowseTicketList(mode));
  eligible.delete(String(current));
  if (!eligible.size) return null;
  const ordered = (DATA?.debt_table || [])
    .map((r) => String(r.ticket || ""))
    .filter(Boolean);
  const start = ordered.indexOf(String(current));
  const from = start >= 0 ? start + 1 : 0;
  for (let i = from; i < ordered.length; i++) {
    if (eligible.has(ordered[i])) return ordered[i];
  }
  for (let i = 0; i < from; i++) {
    if (eligible.has(ordered[i])) return ordered[i];
  }
  return null;
}

function startDebtQueue(mode) {
  debtQueueMode = mode || "work";
  // «Пропустить» сбрасывается при каждом новом открытии блока
  debtPassSkipped[debtQueueMode] = new Set();
  debtProgressSave();
  const list = debtBrowseTicketList(debtQueueMode);
  if (!list.length) {
    const labels = { pending: "на модерации", rework: "на доработке", work: "к обработке" };
    const deferredHere = (DATA?.debt_table || []).filter((r) => {
      const t = String(r.ticket || "");
      if (!debtDeferred.has(t)) return false;
      const ds = String(r.decision_status || "");
      if (debtQueueMode === "pending") return ds === "pending";
      if (debtQueueMode === "rework") return ds === "rework";
      return debtRowInMainTable(r);
    }).length;
    const hint = deferredHere
      ? `\n(${deferredHere} отложено — нажмите «Вернуть отложенные»)`
      : "";
    alert(`Нет квитанций «${labels[debtQueueMode] || debtQueueMode}».${hint}`);
    return;
  }
  openDebtModal(list[0]);
}

function debtFlagMeta(flag, decisionStatus, ticket) {
  if (ticket && debtIsDeferred(ticket)) {
    return { label: "отложено", cls: "is-debt-deferred", chip: "is-deferred" };
  }
  const ds = String(decisionStatus || "");
  if (ds === "pending") return { label: "решение", cls: "is-debt-pending", chip: "is-ok" };
  if (ds === "rework") return { label: "доработать", cls: "is-debt-rework", chip: "is-miss" };
  const f = String(flag || "");
  if (f === "red") return { label: "красный", cls: "is-debt-red", chip: "is-bad" };
  if (f === "yellow") return { label: "жёлтый", cls: "is-debt-yellow", chip: "is-ok" };
  if (f === "mismatch") return { label: "разница", cls: "is-debt-mismatch", chip: "is-bad" };
  if (f === "open") return { label: "CRM", cls: "is-debt-open", chip: "" };
  return { label: "—", cls: "", chip: "" };
}

function debtDecisionCodes() {
  return (
    DATA?.debt_inbox?.decision_codes || {
      mgmt_ok: "закрыть с разрешения руководства",
      paid_fact: "оплата по факту была",
      no_pay: "оплаты не было и не будет",
    }
  );
}

function vitrineLogin() {
  try {
    return window.JarvisVitrineAuth?.session()?.login || "";
  } catch {
    return "";
  }
}

function debtSortValue(row, key) {
  if (key === "ticket") return String(row.ticket || "");
  if (key === "crm_status") return String(row.crm_status || "");
  if (key === "flag" || key === "flag_reason") return debtFlagRank(row.flag);
  if (key === "sheet_debt") return Number(row.sheet_debt) || 0;
  if (key === "crm_debt") return Number(row.crm_debt) || 0;
  if (key === "crm_paid") return Number(row.crm_paid) || 0;
  if (key === "report_amount") return Number(row.report_amount) || 0;
  return Number(row.crm_debt || row.sheet_debt) || 0;
}

function fmtDay(day) {
  const m = String(day || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
  return m ? `${m[3]}.${m[2]}.${m[1]}` : String(day || "—");
}

function closeDebtModal() {
  document.getElementById("debt-order-modal")?.remove();
}

function openDebtModal(ticket) {
  if (!ticket) return;
  closeDebtModal();
  const table = DATA?.debt_table || [];
  const row = table.find((r) => String(r.ticket) === String(ticket));
  if (!row) return;
  const displayStatus = debtIsDecided(ticket) ? "pending" : row.decision_status;
  const flagMeta = debtFlagMeta(row.flag, displayStatus, row.ticket);
  const codes = debtDecisionCodes();
  const feed = Array.isArray(row.live_feed) ? row.live_feed : [];
  const feedAt = row.crm_feed_at
    ? `<span class="debt-feed-cached">кэш ${escapeHtml(String(row.crm_feed_at).slice(0, 19).replace("T", " "))}</span>`
    : `<span class="debt-feed-cached">лента не в снимке</span>`;
  const feedHtml = feed.length
    ? feed
        .map(
          (f) => `<article class="debt-feed-item">
            <header><time>${escapeHtml(f.date || "")}</time><span>${escapeHtml(f.author || "")}</span></header>
            <p>${escapeHtml(f.text || "")}</p>
          </article>`,
        )
        .join("")
    : `<p class="debt-feed-empty">${row.crm_feed_at ? "Комментариев в CRM нет" : "Лента ещё не сохранена при сверке"}</p>`;
  const crmLink = row.crm_url
    ? `<a class="debt-order-crm-link" href="${escapeHtml(row.crm_url)}" target="_blank" rel="noopener">Открыть в CRM ↗</a>`
    : "";
  const opts = Object.entries(codes)
    .map(
      ([code, label]) =>
        `<option value="${escapeHtml(code)}"${row.decision_code === code ? " selected" : ""}>${escapeHtml(label)}</option>`,
    )
    .join("");
  const inboxUrl = (DATA?.debt_inbox?.url || "").replace(/\/$/, "");
  const writeKey = DATA?.debt_inbox?.write_key || "";
  const overlay = document.createElement("div");
  overlay.id = "debt-order-modal";
  overlay.className = "debt-order-overlay";
  overlay.innerHTML = `<div class="debt-order-card">
    <div class="debt-order-head">
      <div>
        <p class="debt-order-kicker">Дебиторка · ${
          debtQueueMode === "pending"
            ? "на модерации"
            : debtQueueMode === "rework"
              ? "доработать"
              : "карточка"
        }</p>
        <h2>№${escapeHtml(row.ticket)}</h2>
        <p class="debt-order-status-line">
          <span class="debt-order-status">${escapeHtml(row.crm_status || "—")}</span>
          <span class="chip ${flagMeta.chip}">${escapeHtml(flagMeta.label)}</span>
        </p>
      </div>
      <div class="debt-order-head-actions">
        ${crmLink}
        <button type="button" class="debt-close-btn" data-close>Закрыть</button>
      </div>
    </div>
    ${
      row.flag_reason
        ? `<div class="debt-order-reason ${flagMeta.cls}">${escapeHtml(row.flag_reason)}</div>`
        : ""
    }
    <div class="debt-order-grid">
      <section class="debt-order-panel">
        <h3>CRM</h3>
        <dl>
          <div><dt>Стоимость</dt><dd>${fmtMoney(row.crm_total)}</dd></div>
          <div><dt>Оплачено</dt><dd>${fmtMoney(row.crm_paid)}</dd></div>
          <div><dt>Долг</dt><dd class="is-emphasis">${fmtMoney(row.crm_debt)}</dd></div>
        </dl>
      </section>
      <section class="debt-order-panel">
        <h3>Отчёт мастера</h3>
        <dl>
          <div><dt>Мастер</dt><dd>${escapeHtml(row.master || "—")}</dd></div>
          <div><dt>Лист</dt><dd>${escapeHtml(row.sheet_title || "—")}</dd></div>
          <div><dt>Долг в отчёте</dt><dd class="is-emphasis">${fmtMoney(row.sheet_debt)}</dd></div>
          <div><dt>ЗП мастеру</dt><dd>${fmtMoney(row.report_amount)}</dd></div>
        </dl>
      </section>
    </div>
    <section class="debt-order-decision">
      <h3>Решение</h3>
      ${
        displayStatus
          ? `<p class="debt-order-decision-hint">Сейчас: <strong>${escapeHtml(displayStatus)}</strong>
             ${row.decision_code ? ` · ${escapeHtml(codes[row.decision_code] || row.decision_code)}` : ""}</p>`
          : ""
      }
      <div class="debt-decision-row">
        <button type="button" class="debt-close-btn" data-skip title="Только до конца этого прохода; при новом открытии блока снова в очереди">Пропустить</button>
        <button type="button" class="debt-defer-btn" data-defer title="Убрать из очереди до «Вернуть отложенные»">Отложить</button>
        <select data-decision-select>
          <option value="">— выбрать решение —</option>
          ${opts}
        </select>
      </div>
      <p class="debt-order-decision-hint" data-decision-status></p>
    </section>
    <section class="debt-order-feed">
      <h3>Комментарии CRM <span>${feed.length}</span> ${feedAt}</h3>
      <div class="debt-feed-list">${feedHtml}</div>
    </section>
  </div>`;
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeDebtModal();
  });
  overlay.querySelector("[data-close]")?.addEventListener("click", () => {
    debtQueueMode = "work";
    debtProgressSave();
    closeDebtModal();
  });
  const goNextInQueue = () => {
    const next = debtNextBrowseTicket(ticket);
    if (next) openDebtModal(next);
    else {
      debtQueueMode = "work";
      debtProgressSave();
      closeDebtModal();
      renderDebt();
    }
  };
  overlay.querySelector("[data-skip]")?.addEventListener("click", () => {
    debtMarkPassSkipped(ticket);
    goNextInQueue();
  });
  overlay.querySelector("[data-defer]")?.addEventListener("click", () => {
    debtMarkDeferred(ticket);
    renderDebt();
    goNextInQueue();
  });
  overlay.querySelector("[data-decision-select]")?.addEventListener("change", async (ev) => {
    const code = ev.target.value;
    const statusEl = overlay.querySelector("[data-decision-status]");
    if (!code) return;
    if (!inboxUrl || !writeKey) {
      if (statusEl) statusEl.textContent = "Inbox не настроен в снимке — обновите экспорт из Jarvis.";
      ev.target.value = row.decision_code || "";
      return;
    }
    if (statusEl) statusEl.textContent = "Отправка…";
    try {
      const res = await fetch(`${inboxUrl}/decision`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${writeKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          ticket: String(ticket),
          decision_code: code,
          decision_by: vitrineLogin() || undefined,
        }),
      });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(j.error || res.statusText);
      const next = debtNextBrowseTicket(ticket);
      debtMarkDecided(ticket);
      renderDebt();
      if (next) openDebtModal(next);
      else {
        debtQueueMode = "work";
        debtProgressSave();
        closeDebtModal();
      }
    } catch (err) {
      if (statusEl) statusEl.textContent = `Ошибка: ${err.message || err}`;
      ev.target.value = row.decision_code || "";
    }
  });
  document.body.appendChild(overlay);
}

function initDebtSort() {
  const table = $("#table-debt");
  if (!table || table.dataset.sortReady) return;
  table.dataset.sortReady = "1";
  table.querySelectorAll("th[data-debt-sort]").forEach((th) => {
    th.addEventListener("click", () => {
      const key = th.getAttribute("data-debt-sort");
      if (!key) return;
      if (debtSort.key === key) debtSort.dir *= -1;
      else {
        debtSort.key = key;
        debtSort.dir = 1;
      }
      renderDebt();
    });
  });
}

function destroyCharts() {
  moneyChart?.destroy();
  volumeChart?.destroy();
  debtChart?.destroy();
  moneyChart = volumeChart = debtChart = null;
}

function lineDefaults() {
  return {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: {
      legend: {
        position: "bottom",
        labels: { boxWidth: 10, boxHeight: 10, font: { size: 11 }, padding: 12 },
      },
    },
    scales: {
      x: {
        grid: { color: "rgba(28,36,48,0.06)" },
        ticks: { maxRotation: 40, autoSkip: true, maxTicksLimit: 12, font: { size: 10 }, color: "#5d6b7c" },
      },
    },
  };
}

function setTab(tab) {
  if (tab === "reviews") {
    location.href = "../reviews/";
    return;
  }
  document.querySelectorAll(".mod-tab").forEach((btn) => {
    const on = btn.getAttribute("data-tab") === tab;
    btn.classList.toggle("is-active", on);
  });
  document.querySelectorAll("main .panel").forEach((panel) => {
    const on = panel.id === `panel-${tab}`;
    panel.hidden = !on;
    panel.classList.toggle("is-active", on);
  });
  if (tab === "reviews_stats") {
    requestAnimationFrame(() => renderReviewsStats(REVIEWS_STATS));
  }
  try {
    localStorage.setItem("jarvis.pages.vyrobotka.tab", tab);
  } catch {
    /* ignore */
  }
  requestAnimationFrame(() => {
    moneyChart?.resize();
    volumeChart?.resize();
    debtChart?.resize();
    Object.values(bkCharts).forEach((c) => {
      try {
        c.resize();
      } catch {
        /* ignore */
      }
    });
    Object.values(mkCharts).forEach((c) => {
      try {
        c.resize();
      } catch {
        /* ignore */
      }
    });
  });
}

function renderUpsell(sheets) {
  const empty = $("#upsell-empty");
  const body = $("#upsell-body");
  if (!sheets?.length) {
    if (empty) empty.hidden = false;
    if (body) body.hidden = true;
    return;
  }
  if (empty) empty.hidden = true;
  if (body) body.hidden = false;

  const last = sheets[sheets.length - 1];
  const totalTickets = sheets.reduce((a, s) => a + (Number(s.tickets_count) || 0), 0);
  const totalUpsell = sheets.reduce((a, s) => a + (Number(s.upsell_sum) || 0), 0);
  const totalUpsellN = sheets.reduce((a, s) => a + (Number(s.upsell_count) || 0), 0);
  const totalReport = sheets.reduce((a, s) => a + (Number(s.report_sum) || 0), 0);

  const kpis = $("#upsell-kpis");
  if (kpis) {
    kpis.innerHTML = [
      ["Листов", String(sheets.length), last?.sheet_title || ""],
      ["Квитанций", fmtMoney(totalTickets), "все недели"],
      ["Σ досогл.", fmtMoney(totalUpsell), `${totalUpsellN} шт.`],
      ["Σ в отчёте", fmtMoney(totalReport), "мастера"],
      ["Посл. ср.", fmtMoney(last?.avg_upsell), last?.sheet_title || ""],
      ["Посл. доля", fmtPct(last?.upsell_ratio), ""],
    ]
      .map(
        ([l, v, h]) => `<div class="kpi"><span class="kpi-label">${escapeHtml(l)}</span>
        <span class="kpi-value">${escapeHtml(v)}</span>
        <span class="kpi-hint">${escapeHtml(h)}</span></div>`
      )
      .join("");
  }

  const tbody = $("#tbody-upsell");
  if (tbody) {
    tbody.innerHTML = sheets
      .map(
        (s) => `<tr>
          <td>${escapeHtml(s.sheet_title)}</td>
          <td>${fmtMoney(s.avg_upsell)}</td>
          <td>${fmtMoney(s.upsell_sum)}</td>
          <td>${s.upsell_count ?? 0}</td>
          <td>${fmtPct(s.upsell_ratio)}</td>
          <td>${s.tickets_count ?? 0}</td>
          <td>${fmtMoney(s.report_sum)}</td>
        </tr>`
      )
      .join("");
  }

  const labels = sheets.map((s) => shortLabel(s.sheet_title));
  const base = lineDefaults();
  const line = { tension: 0.3, spanGaps: true, pointRadius: 2, borderWidth: 2.25, backgroundColor: "transparent" };

  const moneyCanvas = $("#chart-money");
  if (moneyCanvas && typeof Chart !== "undefined") {
    moneyChart?.destroy();
    moneyChart = new Chart(moneyCanvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            ...line,
            label: "Ср. досогласование",
            data: sheets.map((s) => s.avg_upsell),
            borderColor: "#0f6e56",
            yAxisID: "yAvg",
          },
          {
            ...line,
            label: "Σ досогласований",
            data: sheets.map((s) => s.upsell_sum),
            borderColor: "#c45c26",
            yAxisID: "y",
          },
          {
            ...line,
            label: "Σ в отчёте",
            data: sheets.map((s) => s.report_sum),
            borderColor: "#1a5f8a",
            yAxisID: "y",
          },
        ],
      },
      options: {
        ...base,
        scales: {
          ...base.scales,
          y: {
            beginAtZero: true,
            position: "left",
            title: { display: true, text: "Σ", color: "#5d6b7c", font: { size: 11 } },
            ticks: { callback: (v) => fmtMoney(v), color: "#5d6b7c", font: { size: 10 } },
            grid: { color: "rgba(28,36,48,0.07)" },
          },
          yAvg: {
            beginAtZero: true,
            position: "right",
            title: { display: true, text: "Ср.", color: "#0f6e56", font: { size: 11 } },
            grid: { drawOnChartArea: false },
            ticks: { callback: (v) => fmtMoney(v), color: "#0f6e56", font: { size: 10 } },
          },
        },
      },
    });
  }

  const volumeCanvas = $("#chart-volume");
  if (volumeCanvas && typeof Chart !== "undefined") {
    volumeChart?.destroy();
    volumeChart = new Chart(volumeCanvas, {
      type: "line",
      data: {
        labels,
        datasets: [
          { ...line, label: "Кол-во досогл.", data: sheets.map((s) => s.upsell_count), borderColor: "#6b4f9a", yAxisID: "y" },
          { ...line, label: "Квитанций", data: sheets.map((s) => s.tickets_count), borderColor: "#5d6b7c", yAxisID: "y" },
          {
            ...line,
            label: "Доля, %",
            data: sheets.map((s) => (s.upsell_ratio == null ? null : Number(s.upsell_ratio) * 100)),
            borderColor: "#a12828",
            borderDash: [5, 4],
            yAxisID: "y1",
          },
        ],
      },
      options: {
        ...base,
        scales: {
          ...base.scales,
          y: { beginAtZero: true, position: "left", grid: { color: "rgba(28,36,48,0.07)" }, ticks: { color: "#5d6b7c", font: { size: 10 } } },
          y1: {
            beginAtZero: true,
            max: 100,
            position: "right",
            grid: { drawOnChartArea: false },
            ticks: { color: "#5d6b7c", font: { size: 10 }, callback: (v) => `${v}%` },
          },
        },
      },
    });
  }
}

function renderDebt() {
  const empty = $("#debt-empty");
  const body = $("#debt-body");
  const allRows = DATA?.debt_table || [];
  const table = allRows.filter(debtRowInMainTable);
  const counts = DATA?.debt_table_counts || {};
  const pendingN = debtPendingTicketIds().size;
  const reworkN = allRows.filter(
    (r) => String(r.decision_status || "") === "rework" && !debtIsDecided(r.ticket),
  ).length;
  const daily = DATA?.debt_daily || [];
  const hasData = allRows.length > 0 || daily.length > 0;
  if (!hasData) {
    if (empty) empty.hidden = false;
    if (body) body.hidden = true;
    return;
  }
  if (empty) empty.hidden = true;
  if (body) body.hidden = false;
  initDebtSort();

  const lastDaily = daily.length ? daily[daily.length - 1] : null;
  const flags = {
    red: table.filter((r) => r.flag === "red").length,
    yellow: table.filter((r) => r.flag === "yellow").length,
    open: table.filter((r) => r.flag === "open").length,
    mismatch: table.filter((r) => r.flag === "mismatch").length,
  };
  const tableCrmDebt = table.reduce((s, r) => s + (Number(r.crm_debt) || 0), 0);

  const meta = $("#debt-meta");
  if (meta) {
    const bl = DATA?.debt_baseline;
    const blNote = bl?.day ? ` · отчёты мастеров с ${fmtDay(bl.day)}` : "";
    const progBits = [];
    if (debtDeferred.size) progBits.push(`отложено ${debtDeferred.size}`);
    if (debtDecidedAt.size) progBits.push(`решений ${debtDecidedAt.size}`);
    const prog = progBits.length ? ` · прогресс: ${progBits.join(", ")}` : "";
    meta.textContent = `Таблица дебиторки · ${table.length} активных${blNote}${prog}`;
  }
  const verifyStatus = $("#debt-verify-status");
  if (verifyStatus) {
    verifyStatus.textContent = DATA?.debt_verify_message || "";
  }

  const actions = $("#debt-queue-actions");
  if (actions) {
    actions.innerHTML = debtDeferred.size
      ? `<button type="button" class="debt-return-deferred-btn" data-return-deferred>
           Вернуть отложенные (${debtDeferred.size})
         </button>`
      : "";
    actions.querySelector("[data-return-deferred]")?.addEventListener("click", () => {
      debtClearDeferred();
    });
  }

  const kpis = $("#debt-kpis");
  if (kpis) {
    kpis.innerHTML = [
      ["CRM (фильтр)", fmtMoney(lastDaily?.crm_debt_sum), lastDaily ? `other=pay · ${fmtDay(lastDaily.day)}` : "после сверки", null],
      ["Σ в таблице", fmtMoney(tableCrmDebt), `${table.length} активных`, null],
      ["Красных", String(flags.red || 0), "подозрение", null],
      ["Жёлтых", String(flags.yellow || 0), "совпадает", null],
      ["Только CRM", String(flags.open || 0), "без отчёта", null],
      ["Расхождение", String(flags.mismatch || 0), "отчёт ≠ CRM", null],
      ["На модерации", String(pendingN), pendingN ? "клик — открыть очередь" : "очередь пуста", "pending"],
      ["Доработать", String(reworkN), reworkN ? "клик — открыть очередь" : "очередь пуста", "rework"],
    ]
      .map(([l, v, h, queue]) => {
        if (queue) {
          return `<div class="kpi kpi-queue" role="button" tabindex="0" data-debt-queue="${queue}">
            <span class="kpi-label">${escapeHtml(l)}</span>
            <span class="kpi-value">${escapeHtml(v)}</span>
            <span class="kpi-hint">${escapeHtml(h)}</span></div>`;
        }
        return `<div class="kpi"><span class="kpi-label">${escapeHtml(l)}</span>
        <span class="kpi-value">${escapeHtml(v)}</span>
        <span class="kpi-hint">${escapeHtml(h)}</span></div>`;
      })
      .join("");
    kpis.querySelectorAll("[data-debt-queue]").forEach((el) => {
      const run = () => startDebtQueue(el.getAttribute("data-debt-queue"));
      el.addEventListener("click", run);
      el.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          run();
        }
      });
    });
  }

  const tbody = $("#tbody-debt");
  if (tbody) {
    if (!table.length) {
      tbody.innerHTML = `<tr><td colspan="7" class="empty-cell">Таблица пуста</td></tr>`;
    } else {
      const key = debtSort.key || "flag";
      const dir = debtSort.dir || 1;
      const ordered = [...table].sort((a, b) => {
        const aDef = debtIsDeferred(a.ticket) ? 1 : 0;
        const bDef = debtIsDeferred(b.ticket) ? 1 : 0;
        if (aDef !== bDef) return aDef - bDef; // отложенные в самый низ
        const av = debtSortValue(a, key);
        const bv = debtSortValue(b, key);
        let cmp = 0;
        if (typeof av === "string" || typeof bv === "string") {
          cmp = String(av).localeCompare(String(bv), "ru", { numeric: true });
        } else {
          cmp = Number(av) - Number(bv);
        }
        if (cmp) return dir * cmp;
        const fr = debtFlagRank(a.flag) - debtFlagRank(b.flag);
        if (fr) return fr;
        const da = (Number(b.crm_debt) || 0) - (Number(a.crm_debt) || 0);
        if (da) return da;
        return String(a.ticket || "").localeCompare(String(b.ticket || ""), "ru");
      });
      tbody.innerHTML = ordered
        .map((r) => {
          const metaF = debtFlagMeta(r.flag, r.decision_status, r.ticket);
          const sheetDebtHtml = r.sheet_url
            ? `<a class="ticket-link" href="${escapeHtml(r.sheet_url)}" target="_blank" rel="noopener"><strong>${fmtMoney(r.sheet_debt)}</strong></a>`
            : `<strong>${fmtMoney(r.sheet_debt)}</strong>`;
          const crmDebtHtml = r.crm_url
            ? `<a class="ticket-link" href="${escapeHtml(r.crm_url)}" target="_blank" rel="noopener"><strong>${fmtMoney(r.crm_debt)}</strong></a>`
            : `<strong>${fmtMoney(r.crm_debt)}</strong>`;
          return `<tr class="${metaF.cls}" title="${escapeHtml(r.flag_reason || "")}">
            <td><button type="button" class="debt-ticket-btn" data-debt-ticket="${escapeHtml(r.ticket || "")}">${escapeHtml(r.ticket || "—")}</button></td>
            <td>${sheetDebtHtml}</td>
            <td>${crmDebtHtml}</td>
            <td>${fmtMoney(r.crm_paid)}</td>
            <td>${fmtMoney(r.report_amount)}</td>
            <td>${escapeHtml(r.crm_status || "—")}</td>
            <td class="debt-flag-reason">${escapeHtml(r.flag_reason || "—")}</td>
          </tr>`;
        })
        .join("");
      tbody.querySelectorAll("[data-debt-ticket]").forEach((btn) => {
        btn.addEventListener("click", () => {
          debtQueueMode = "work";
          debtProgressSave();
          openDebtModal(btn.getAttribute("data-debt-ticket"));
        });
      });
    }
  }

  const decisionsSeriesEarly = DATA?.debt_decisions_series || {};
  const dailyMeta = $("#debt-daily-meta");
  if (dailyMeta) {
    const closedDays = (decisionsSeriesEarly.days || []).length;
    if (!daily.length && !closedDays) {
      dailyMeta.textContent = "Точек динамики пока нет в снимке.";
    } else {
      const tip = daily.length ? daily[daily.length - 1] : null;
      dailyMeta.textContent = tip
        ? `CRM точек: ${daily.length} · посл. ${fmtDay(tip.day)} · ${fmtMoney(tip.crm_debt_sum)} · закрытий по дням: ${closedDays}`
        : `Закрытий по дням: ${closedDays}`;
    }
  }

  const canvas = $("#chart-debt");
  if (!canvas || typeof Chart === "undefined") return;
  debtChart?.destroy();
  debtChart = null;
  if (!daily.length && !(decisionsSeriesEarly.days || []).length) return;
  const labels = daily.map((d) => {
    const m = String(d.day || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m ? `${m[3]}.${m[2]}` : d.day;
  });
  const base = lineDefaults();
  const decisionsSeries = decisionsSeriesEarly;
  const daySet = new Set([
    ...daily.map((d) => String(d.day || "").slice(0, 10)),
    ...((decisionsSeries.days || []).map((d) => String(d).slice(0, 10))),
  ]);
  const dayList = [...daySet].filter((d) => d.length >= 8).sort();
  const labels2 = dayList.map((d) => {
    const m = String(d).match(/^(\d{4})-(\d{2})-(\d{2})/);
    return m ? `${m[3]}.${m[2]}` : d;
  });
  const crmByDay = Object.fromEntries(daily.map((d) => [String(d.day || "").slice(0, 10), d.crm_debt_sum]));
  const mgrColors = [
    "rgba(26, 79, 134, 0.55)",
    "rgba(15, 110, 86, 0.55)",
    "rgba(196, 92, 38, 0.55)",
    "rgba(110, 70, 180, 0.5)",
    "rgba(138, 90, 0, 0.5)",
  ];
  const barDatasets = Object.entries(decisionsSeries.by_manager || {}).map(([mgr, points], i) => {
    const map = Object.fromEntries((points || []).map((p) => [p.day, p.count]));
    return {
      type: "bar",
      label: mgr,
      data: dayList.map((d) => map[d] || 0),
      backgroundColor: mgrColors[i % mgrColors.length],
      yAxisID: "yCount",
      stack: "closed",
      order: 2,
    };
  });
  debtChart = new Chart(canvas, {
    data: {
      labels: labels2.length ? labels2 : labels,
      datasets: [
        {
          type: "line",
          label: "CRM (ожидаемая оплата)",
          data: (dayList.length ? dayList : daily.map((d) => d.day)).map((d) => {
            const key = String(d).slice(0, 10);
            const v = crmByDay[key];
            return v == null ? null : Number(v);
          }),
          borderColor: "#a12828",
          backgroundColor: "transparent",
          tension: 0.3,
          spanGaps: true,
          pointRadius: 3,
          borderWidth: 2.25,
          yAxisID: "y",
          order: 1,
        },
        ...barDatasets,
      ],
    },
    options: {
      ...base,
      interaction: { mode: "index", intersect: false },
      scales: {
        ...base.scales,
        x: {
          stacked: true,
          ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 14, color: "#5d6b7c", font: { size: 10 } },
        },
        y: {
          position: "left",
          beginAtZero: true,
          title: { display: true, text: "₴ CRM", color: "#5d6b7c", font: { size: 11 } },
          ticks: { callback: (v) => fmtMoney(v), color: "#5d6b7c", font: { size: 10 } },
          grid: { color: "rgba(28,36,48,0.07)" },
        },
        yCount: {
          position: "right",
          stacked: true,
          beginAtZero: true,
          grid: { drawOnChartArea: false },
          title: { display: true, text: "закрыто, шт", color: "#5d6b7c", font: { size: 11 } },
          ticks: { precision: 0, color: "#5d6b7c" },
        },
      },
    },
  });
}

function destroyBkCharts() {
  Object.values(bkCharts).forEach((c) => {
    try {
      c.destroy();
    } catch {
      /* ignore */
    }
  });
  bkCharts = {};
}

function bkLine(canvas, series, labels, { pct = false } = {}) {
  if (!canvas || typeof Chart === "undefined") return null;
  const base = lineDefaults();
  const line = {
    tension: 0.3,
    spanGaps: true,
    pointRadius: 2,
    pointHoverRadius: 4,
    borderWidth: 2.25,
    backgroundColor: "transparent",
  };
  return new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: (series || []).map((s) => ({
        ...line,
        label: s.label,
        data: s.data,
        borderColor: s.color || "#0f6e56",
      })),
    },
    options: {
      ...base,
      scales: {
        ...base.scales,
        y: {
          ticks: {
            callback: (v) => (pct ? `${v}%` : fmtMoney(v)),
            color: "#5d6b7c",
            font: { size: 10 },
          },
          grid: { color: "rgba(28,36,48,0.07)" },
        },
      },
    },
  });
}

function renderBranchKpi(data) {
  const empty = $("#branch-kpi-empty");
  const body = $("#branch-kpi-body");
  const months = data?.months || [];
  const branches = data?.branches || [];
  const charts = data?.charts || {};
  const titleById = Object.fromEntries(branches.map((b) => [b.id, b.title]));
  destroyBkCharts();
  if (!months.length) {
    if (empty) empty.hidden = false;
    if (body) body.hidden = true;
    return;
  }
  if (empty) empty.hidden = true;
  if (body) body.hidden = false;

  const latestKey = months.reduce((best, r) => {
    const k = Number(r.year) * 100 + Number(r.month);
    return k > best ? k : best;
  }, 0);
  const latest = months.filter((r) => Number(r.year) * 100 + Number(r.month) === latestKey);
  const kpis = $("#branch-kpi-kpis");
  if (kpis) {
    kpis.innerHTML = latest
      .map((r) => {
        const title = titleById[r.branch_id] || r.branch_id;
        const mm = `${String(r.month).padStart(2, "0")}.${String(r.year).slice(2)}`;
        return `<div class="kpi"><span class="kpi-label">${escapeHtml(title)} · ${mm}</span>
          <strong>${r.acceptances ?? "—"} приёмок</strong>
          <span class="kpi-sub">вал ${fmtMoney(r.gross_profit)} · чист ${fmtMoney(r.net_profit)} · возвр. ${
            r.return_rate == null ? "—" : fmtPct(r.return_rate)
          }</span></div>`;
      })
      .join("");
  }

  const tbody = $("#tbody-branch-kpi");
  if (tbody) {
    const order = { karetn: 0, seged: 1, levitan: 2 };
    const sorted = [...months].sort((a, b) => {
      const ka = Number(a.year) * 100 + Number(a.month);
      const kb = Number(b.year) * 100 + Number(b.month);
      if (ka !== kb) return kb - ka;
      return (order[a.branch_id] ?? 9) - (order[b.branch_id] ?? 9);
    });
    tbody.innerHTML = sorted
      .map((r) => {
        const mm = `${String(r.month).padStart(2, "0")}.${String(r.year).slice(2)}`;
        return `<tr>
          <td>${mm}</td>
          <td><strong>${escapeHtml(titleById[r.branch_id] || r.branch_id)}</strong></td>
          <td>${r.acceptances ?? "—"}</td>
          <td>${fmtMoney(r.gross_profit)}</td>
          <td>${fmtMoney(r.net_profit)}</td>
          <td>${r.refusals ?? "—"}</td>
          <td>${r.return_rate == null ? "—" : fmtPct(r.return_rate)}</td>
        </tr>`;
      })
      .join("");
  }

  const labels = charts.labels || [];
  bkCharts.accept = bkLine($("#chart-bk-accept"), charts.acceptances, labels);
  bkCharts.gross = bkLine($("#chart-bk-gross"), charts.gross_profit, labels);
  bkCharts.net = bkLine($("#chart-bk-net"), charts.net_profit, labels);
  bkCharts.ret = bkLine($("#chart-bk-return"), charts.return_rate_pct, labels, { pct: true });
}

function destroyMkCharts() {
  Object.values(mkCharts).forEach((c) => {
    try {
      c.destroy();
    } catch {
      /* ignore */
    }
  });
  mkCharts = {};
}

function mkLine(canvas, series, labels, { money = false } = {}) {
  if (!canvas || typeof Chart === "undefined") return null;
  const base = lineDefaults();
  const line = {
    tension: 0.28,
    spanGaps: true,
    pointRadius: 2,
    pointHoverRadius: 4,
    borderWidth: 2.1,
    backgroundColor: "transparent",
  };
  return new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: (series || []).map((s) => ({
        ...line,
        label: s.label,
        data: s.data,
        borderColor: s.color || "#0f6e56",
      })),
    },
    options: {
      ...base,
      scales: {
        ...base.scales,
        y: {
          beginAtZero: true,
          ticks: {
            callback: (v) => (money ? fmtMoney(v) : Number(v).toLocaleString("uk-UA")),
            color: "#5d6b7c",
            font: { size: 10 },
          },
          grid: { color: "rgba(28,36,48,0.07)" },
        },
      },
    },
  });
}

function mkMini(canvas, labels, data, color) {
  if (!canvas || typeof Chart === "undefined" || !labels.length) return null;
  return new Chart(canvas, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          data,
          borderColor: color || "#0f6e56",
          backgroundColor: "transparent",
          tension: 0.3,
          spanGaps: true,
          pointRadius: 0,
          pointHoverRadius: 3,
          borderWidth: 2,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false }, tooltip: { enabled: true } },
      scales: { x: { display: false }, y: { display: false, beginAtZero: true } },
    },
  });
}

function renderMastersKpi(data) {
  const empty = $("#masters-kpi-empty");
  const body = $("#masters-kpi-body");
  const masters = data?.masters || [];
  const charts = data?.charts || {};
  destroyMkCharts();
  if (!masters.length) {
    if (empty) empty.hidden = false;
    if (body) body.hidden = true;
    return;
  }
  if (empty) empty.hidden = true;
  if (body) body.hidden = false;

  const totalWork = masters.reduce((s, m) => s + (Number(m.work_sum) || 0), 0);
  const totalTickets = masters.reduce((s, m) => s + (Number(m.tickets) || 0), 0);
  const withEff = masters.filter((m) => m.efficiency != null);
  const best = withEff.slice().sort((a, b) => Number(b.efficiency) - Number(a.efficiency))[0];
  const kpis = $("#masters-kpi-kpis");
  if (kpis) {
    kpis.innerHTML = [
      ["Σ работ", fmtMoney(totalWork), `${totalTickets} кв. · ${masters.length} мастеров`],
      [
        "Лучший КПД",
        best ? best.display_name : "—",
        best?.efficiency != null ? Number(best.efficiency).toLocaleString("uk-UA") : "",
      ],
      ...masters.slice(0, 4).map((m) => [
        m.display_name,
        fmtMoney(m.work_sum),
        `${m.tickets ?? "—"} кв. · КПД ${
          m.efficiency == null ? "—" : Number(m.efficiency).toLocaleString("uk-UA")
        }`,
      ]),
    ]
      .map(
        ([l, v, h]) => `<div class="kpi"><span class="kpi-label">${escapeHtml(l)}</span>
        <span class="kpi-value">${escapeHtml(v)}</span>
        <span class="kpi-hint">${escapeHtml(h)}</span></div>`,
      )
      .join("");
  }

  const labels = charts.labels || [];
  mkCharts.eff = mkLine($("#chart-mk-eff"), charts.efficiency, labels);
  mkCharts.work = mkLine($("#chart-mk-work"), charts.work_sum, labels, { money: true });

  const cards = $("#masters-kpi-cards");
  const per = charts.per_master || {};
  if (cards) {
    cards.innerHTML = masters
      .map((m) => {
        const id = `mk-mini-${escapeHtml(m.master_key)}`;
        return `<article class="masters-kpi-card">
          <h3><span class="mk-dot" style="background:${escapeHtml(m.color || "#334155")}"></span>${escapeHtml(m.display_name)}</h3>
          <p class="mk-sub">${m.crm_orders || 0} в CRM · ${m.files || 0} отчётов</p>
          <div class="mk-metrics">
            <div><span>Σ работ</span><strong>${fmtMoney(m.work_sum)}</strong></div>
            <div><span>Квитанции</span><strong>${m.tickets ?? "—"}</strong></div>
            <div><span>КПД</span><strong>${m.efficiency == null ? "—" : Number(m.efficiency).toLocaleString("uk-UA")}</strong></div>
            <div><span>Ср. квит.</span><strong>${m.avg_ticket == null ? "—" : fmtMoney(m.avg_ticket)}</strong></div>
          </div>
          <div class="mk-mini"><canvas id="${id}"></canvas></div>
        </article>`;
      })
      .join("");
    masters.forEach((m) => {
      const pm = per[m.master_key] || {};
      const rawLabels = pm.labels || [];
      const rawVals = pm.work_sum || [];
      const pairs = rawLabels
        .map((lab, i) => ({ lab, v: rawVals[i] }))
        .filter((p) => p.v != null && Number(p.v) !== 0);
      mkCharts[`mini_${m.master_key}`] = mkMini(
        document.getElementById(`mk-mini-${m.master_key}`),
        pairs.map((p) => p.lab),
        pairs.map((p) => p.v),
        m.color,
      );
    });
  }
}

function renderAll() {
  destroyCharts();
  if (DATA) {
    const meta = $("#export-meta");
    if (meta) {
      const when = DATA.exported_at ? new Date(DATA.exported_at).toLocaleString("ru-RU") : "—";
      const title = DATA.spreadsheet_title ? ` · ${DATA.spreadsheet_title}` : "";
      let line = `Снимок: ${when}${title}`;
      if (DATA.debt_daily?.length) {
        const last = DATA.debt_daily[DATA.debt_daily.length - 1];
        const dayLabel = String(last.day || "").replace(/^(\d{4})-(\d{2})-(\d{2}).*/, "$3.$2.$1");
        line += ` · дебиторка CRM ${fmtMoney(last.crm_debt_sum)} (${dayLabel})`;
      }
      if (BRANCH_KPI?.exported_at) {
        line += ` · КПД фил. ${new Date(BRANCH_KPI.exported_at).toLocaleString("ru-RU")}`;
      }
      if (MASTERS_KPI?.exported_at) {
        line += ` · КПД маст. ${new Date(MASTERS_KPI.exported_at).toLocaleString("ru-RU")}`;
      }
      meta.textContent = line;
    }
    renderUpsell(DATA.upsell_sheets || []);
    renderDebt();
  }
  renderBranchKpi(BRANCH_KPI);
  renderMastersKpi(MASTERS_KPI);
}


function renderReviewsStats(data) {
  const empty = $("#reviews-stats-empty");
  const body = $("#reviews-stats-body");
  if (!data || !(data.calls_total || data.cards?.length || data.google_latest?.length)) {
    if (empty) empty.hidden = false;
    if (body) body.hidden = true;
    return;
  }
  if (empty) empty.hidden = true;
  if (body) body.hidden = false;
  const oc = data.outcome_counts || {};
  const rate = Math.round((data.will_review_rate || 0) * 100);
  const kpis = $("#reviews-stats-kpis");
  if (kpis) {
    kpis.innerHTML = [
      ["Всего звонков", String(data.calls_total ?? 0), "в журнале"],
      ["Оставит отзыв", String(oc.will_review ?? 0), `${rate}%`],
      ["Не дозвон", String(oc.no_answer ?? 0), ""],
      ["Пул", String(data.cards?.length ?? data.counts?.pool ?? 0), `окно ${data.queue_size ?? 10}`],
      ["Менеджеров", String((data.managers || []).length), ""],
    ]
      .map(([l, v, h]) => `<div class="kpi"><span class="kpi-label">${escapeHtml(l)}</span>
        <span class="kpi-value">${escapeHtml(v)}</span>
        <span class="kpi-hint">${escapeHtml(h)}</span></div>`)
      .join("");
  }
  const tbody = $("#tbody-rs-managers");
  if (tbody) {
    const rows = data.managers || [];
    tbody.innerHTML = rows.length
      ? rows
          .map((m) => {
            const r = Math.round((m.will_review_rate || 0) * 100);
            return `<tr><td>${escapeHtml(m.manager || "—")}</td><td>${escapeHtml(String(m.total ?? 0))}</td>
              <td>${escapeHtml(String(m.will_review ?? 0))}</td><td>${escapeHtml(String(r))}%</td></tr>`;
          })
          .join("")
      : `<tr><td colspan="4" class="empty-cell">Пока нет звонков</td></tr>`;
  }
  if (typeof Chart === "undefined") return;
  const outcomes = data.outcomes || {};
  const labels = Object.keys(outcomes);
  rsOutcomesChart?.destroy();
  const c1 = $("#chart-rs-outcomes");
  if (c1) {
    rsOutcomesChart = new Chart(c1, {
      type: "doughnut",
      data: {
        labels: labels.map((k) => outcomes[k] || k),
        datasets: [{
          data: labels.map((k) => oc[k] || 0),
          backgroundColor: [
            "rgba(15, 110, 86, 0.75)",
            "rgba(138, 90, 0, 0.65)",
            "rgba(26, 79, 134, 0.55)",
            "rgba(161, 40, 40, 0.7)",
          ],
          borderWidth: 0,
        }],
      },
      options: { responsive: true, maintainAspectRatio: false, plugins: { legend: { position: "bottom" } } },
    });
  }
  const latest = data.google_latest || [];
  const nameBy = Object.fromEntries((data.branches || []).map((b) => [b.id, b.name]));
  const colors = {
    karetnaya: "rgba(26, 79, 134, 0.95)",
    segedskaya: "rgba(15, 110, 86, 0.95)",
    levitana: "rgba(196, 92, 38, 0.95)",
  };
  rsGoogleChart?.destroy();
  const c2 = $("#chart-rs-google");
  if (c2) {
    rsGoogleChart = new Chart(c2, {
      type: "bar",
      data: {
        labels: latest.map((r) => nameBy[r.branch_id] || r.branch_id),
        datasets: [{
          label: "Рейтинг",
          data: latest.map((r) => r.rating),
          backgroundColor: latest.map((r) => colors[r.branch_id] || "rgba(70,150,220,0.55)"),
          borderRadius: 8,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: { y: { min: 1, max: 5 } },
        plugins: { legend: { display: false } },
      },
    });
  }
  const gSeries = data.google_series || {};
  const gDays = gSeries.days || [];
  const byBranch = gSeries.by_branch || {};
  rsGoogleDynChart?.destroy();
  const c3 = $("#chart-rs-google-dyn");
  if (c3) {
    rsGoogleDynChart = new Chart(c3, {
      type: "line",
      data: {
        labels: gDays.map((d) => {
          const m = String(d).match(/^(\d{4})-(\d{2})-(\d{2})/);
          return m ? `${m[3]}.${m[2]}` : d;
        }),
        datasets: Object.keys(byBranch).map((bid) => {
          const map = Object.fromEntries((byBranch[bid] || []).map((p) => [p.day, p.rating]));
          return {
            label: nameBy[bid] || bid,
            data: gDays.map((d) => (map[d] != null ? map[d] : null)),
            borderColor: colors[bid] || "rgba(26,79,134,0.8)",
            backgroundColor: "transparent",
            spanGaps: true,
            tension: 0.25,
            pointRadius: 3,
            borderWidth: 2,
          };
        }),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: { y: { min: 1, max: 5 } },
        plugins: { legend: { position: "bottom" } },
      },
    });
  }
  const cSeries = data.calls_series || {};
  const cDays = cSeries.days || [];
  const byMgr = cSeries.by_manager || {};
  rsCallsDynChart?.destroy();
  const c4 = $("#chart-rs-calls-dyn");
  if (c4) {
    const mgrColors = [
      "rgba(26, 79, 134, 0.7)",
      "rgba(15, 110, 86, 0.7)",
      "rgba(196, 92, 38, 0.7)",
      "rgba(110, 70, 180, 0.65)",
    ];
    rsCallsDynChart = new Chart(c4, {
      type: "bar",
      data: {
        labels: cDays.map((d) => {
          const m = String(d).match(/^(\d{4})-(\d{2})-(\d{2})/);
          return m ? `${m[3]}.${m[2]}` : d;
        }),
        datasets: Object.keys(byMgr).map((mgr, i) => {
          const map = Object.fromEntries((byMgr[mgr] || []).map((p) => [p.day, p.count]));
          return {
            label: mgr,
            data: cDays.map((d) => map[d] || 0),
            backgroundColor: mgrColors[i % mgrColors.length],
            stack: "calls",
          };
        }),
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { stacked: true },
          y: { stacked: true, beginAtZero: true, ticks: { precision: 0 } },
        },
        plugins: { legend: { position: "bottom" } },
      },
    });
  }
}


async function boot() {
  document.querySelectorAll(".mod-tab").forEach((btn) => {
    btn.addEventListener("click", () => setTab(btn.getAttribute("data-tab")));
  });
  let tab = "upsell";
  try {
    tab = localStorage.getItem("jarvis.pages.vyrobotka.tab") || "upsell";
  } catch {
    tab = "upsell";
  }
  const allowed = new Set(["upsell", "debt", "branch_kpi", "masters_kpi", "reviews", "reviews_stats"]);
  setTab(allowed.has(tab) ? tab : "upsell");

  const meta = $("#export-meta");
  try {
    const res = await fetch(`./data.json?t=${Date.now()}`);
    if (!res.ok) throw new Error(`data.json: ${res.status}`);
    DATA = await res.json();
    debtProgressLoad();
    debtProgressReconcile();
  } catch (err) {
    if (meta) meta.textContent = `Нет снимка: ${err.message || err}. Экспортируйте из Jarvis.`;
    $("#upsell-empty").hidden = false;
    $("#debt-empty").hidden = false;
  }
  try {
    const res = await fetch(`../branch-kpi/data.json?t=${Date.now()}`);
    if (res.ok) BRANCH_KPI = await res.json();
  } catch {
    BRANCH_KPI = null;
  }
  try {
    const res = await fetch(`../reviews/data.json?t=${Date.now()}`);
    if (res.ok) REVIEWS_STATS = await res.json();
  } catch {
    REVIEWS_STATS = null;
  }
  renderReviewsStats(REVIEWS_STATS);
  if (!BRANCH_KPI?.months?.length) {
    const empty = $("#branch-kpi-empty");
    if (empty) empty.hidden = false;
  }
  try {
    const res = await fetch(`../masters-kpi/data.json?t=${Date.now()}`);
    if (res.ok) MASTERS_KPI = await res.json();
  } catch {
    MASTERS_KPI = null;
  }
  if (!MASTERS_KPI?.masters?.length) {
    const empty = $("#masters-kpi-empty");
    if (empty) empty.hidden = false;
  }
  renderAll();
}

boot();
