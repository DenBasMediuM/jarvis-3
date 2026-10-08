/* GitHub Pages viewer for Jarvis quality snapshot (data.json). */
const DATA_URL = "./data.json";

let DATA = null;
let chartMasters = null;
let chartKpi = null;
let chartDays = null;

const $ = (sel) => document.querySelector(sel);

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

function kpiClass(v) {
  if (v == null) return "muted";
  if (v >= 70) return "kpi-good";
  if (v >= 40) return "kpi-mid";
  return "kpi-bad";
}

function heatStyle(kpi) {
  if (kpi == null || Number.isNaN(Number(kpi))) return "";
  const raw = Math.max(0, Math.min(100, Number(kpi))) / 100;
  const t = Math.pow(raw, 1.65);
  const hue = Math.round(t * 118);
  return `background: hsla(${hue}, 55%, 92%, 0.95)`;
}

function avg(nums) {
  const vals = nums.filter((n) => n != null && !Number.isNaN(Number(n))).map(Number);
  if (!vals.length) return null;
  return Math.round((vals.reduce((a, b) => a + b, 0) / vals.length) * 10) / 10;
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
  const eng = engineer
    ? `<td>${esc(r.engineer || r.master_name || "—")}</td>`
    : "";
  const rw =
    Number(r.rework_count) > 0 && r.rework_kpi != null
      ? `<span class="${kpiClass(r.rework_kpi)}">${r.rework_kpi}</span>`
      : `<span class="muted">—</span>`;
  const calls =
    r.calls_kpi != null
      ? `<span class="${kpiClass(r.calls_kpi)}">${r.calls_kpi}</span>`
      : `<span class="muted">—</span>`;
  const orderKpi =
    kpi == null
      ? `<span class="muted">—</span>`
      : `<span class="${kpiClass(kpi)}">${kpi}</span>`;
  const mgr = r.manager_no_answer_missed
    ? `<span class="flag">статус?</span>`
    : `<span class="muted">—</span>`;
  return `<tr>
    <td>${link}</td>
    <td>${esc(r.status || "—")}</td>
    ${eng}
    <td title="${esc(r.device || "")}" style="${heatStyle(kpi)}">${esc((r.device || "—").slice(0, 28))}</td>
    <td class="${dayClass(r.total_days, 7, 14)}" title="Принят: ${esc(fmtDate(r.accepted_at))}">${fmtDays(r.total_days)}</td>
    <td class="${dayClass(r.wait_master_days, 2, 5)}">${fmtDays(r.wait_master_days)}</td>
    <td class="${dayClass(r.diag_days, 3, 7)}">${fmtDays(r.diag_days)}</td>
    <td>${rw}</td>
    <td>${calls}</td>
    <td>${orderKpi}</td>
    <td>${mgr}</td>
  </tr>`;
}

function renderOverview() {
  const tbody = $("#tbody-overview");
  const orders = DATA?.orders || [];
  if (!orders.length) {
    tbody.innerHTML = `<tr><td colspan="11" class="muted">Нет данных. Обновите из CRM локально и сделайте git push.</td></tr>`;
    return;
  }
  const sorted = [...orders].sort((a, b) => (a.order_kpi ?? 999) - (b.order_kpi ?? 999));
  tbody.innerHTML = sorted.map((r) => orderRowHtml(r)).join("");
}

function renderMasters() {
  const root = $("#masters-root");
  const groups = groupByMaster(DATA?.orders || []);
  if (!groups.length) {
    root.innerHTML = `<div class="empty">Нет данных по мастерам.</div>`;
    return;
  }
  root.innerHTML = groups
    .map((g) => {
      const rows = [...g.rows]
        .sort((a, b) => (a.order_kpi ?? 999) - (b.order_kpi ?? 999))
        .map((r) => orderRowHtml(r, { engineer: false }))
        .join("");
      return `<article class="master-card">
        <h3>${esc(g.name)}
          <span class="meta-bits">KPI ${g.avgKpi ?? "—"} · ${g.count} зак.</span>
        </h3>
        <div class="table-wrap">
          <table class="qtable">
            <thead><tr>
              <th>№</th><th>Статус</th><th>Устройство</th><th>Всего дн</th>
              <th>До мастера</th><th>До диагн.</th><th>Дораб.</th><th>Звонки</th><th>KPI</th><th>Мен.</th>
            </tr></thead>
            <tbody>${rows}</tbody>
          </table>
        </div>
      </article>`;
    })
    .join("");
}

function renderSummary() {
  const groups = groupByMaster(DATA?.orders || []);
  const tbody = $("#tbody-summary");
  if (!groups.length) {
    tbody.innerHTML = `<tr><td colspan="8" class="muted">Нет данных</td></tr>`;
  } else {
    tbody.innerHTML = groups
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
  if (typeof Chart === "undefined") return;
  const canvas = $("#chart-masters");
  if (!canvas) return;
  if (chartMasters) chartMasters.destroy();
  const top = groups.slice(0, 20);
  chartMasters = new Chart(canvas, {
    type: "bar",
    data: {
      labels: top.map((g) => g.name),
      datasets: [
        {
          label: "KPI",
          data: top.map((g) => g.avgKpi),
          backgroundColor: "rgba(15,110,86,0.65)",
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: { y: { min: 0, max: 100 } },
      plugins: { legend: { display: false } },
    },
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
    plugins: { legend: { position: "bottom" } },
  };
  chartKpi = new Chart($("#chart-kpi"), {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "KPI", data: series("avg_order_kpi"), borderColor: "#0f6e56", tension: 0.25, spanGaps: true },
        { label: "Звонки", data: series("avg_calls_kpi"), borderColor: "#1a5f8a", tension: 0.25, spanGaps: true },
        { label: "Дораб.", data: series("avg_rework_kpi"), borderColor: "#c45c26", tension: 0.25, spanGaps: true },
      ],
    },
    options: { ...opts, scales: { y: { min: 0, max: 100 } } },
  });
  chartDays = new Chart($("#chart-days"), {
    type: "line",
    data: {
      labels,
      datasets: [
        { label: "Всего дн", data: series("avg_total_days"), borderColor: "#a12828", tension: 0.25, spanGaps: true },
        { label: "До мастера", data: series("avg_wait_master_days"), borderColor: "#a15c12", tension: 0.25, spanGaps: true },
        { label: "До диагн.", data: series("avg_diag_days"), borderColor: "#5d6b7c", tension: 0.25, spanGaps: true },
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
    const on = btn.dataset.tab === id;
    btn.classList.toggle("is-active", on);
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
