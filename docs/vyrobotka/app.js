/* global Chart */

const $ = (sel) => document.querySelector(sel);
let DATA = null;
let BRANCH_KPI = null;
let moneyChart = null;
let volumeChart = null;
let debtChart = null;
let bkCharts = {};

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

function resolveVerdict(verify) {
  if (!verify) return null;
  const raw = verify.verdict || null;
  if (raw === "norm" || raw === "ok" || raw === "missing" || raw === "error") return raw;
  if (raw !== "mismatch") return raw;
  const st = String(verify.crm_status || verify.field_diffs?.status?.crm || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
  if (st !== "выдан") return raw;
  const debt = verify.crm_debt;
  if (debt == null || debt === "" || Number(debt) <= 1) return "norm";
  return raw;
}

function verdictMeta(v) {
  if (v === "ok") return { row: "tr-ok", chip: "is-ok", label: "ок" };
  if (v === "norm") return { row: "tr-norm", chip: "is-norm", label: "норма" };
  if (v === "mismatch") return { row: "tr-bad", chip: "is-bad", label: "расхождение" };
  if (v === "missing") return { row: "tr-miss", chip: "is-miss", label: "нет в CRM" };
  if (v === "error") return { row: "", chip: "is-error", label: "ошибка" };
  return { row: "", chip: "", label: "—" };
}

function cellTip(diff) {
  if (!diff) return "";
  const label = diff.label || "поле";
  const sheetV = typeof diff.sheet === "number" ? fmtMoney(diff.sheet) : String(diff.sheet ?? "—");
  const crmV =
    typeof diff.crm === "number"
      ? fmtMoney(diff.crm)
      : diff.crm == null || diff.crm === ""
        ? "—"
        : String(diff.crm);
  return `${label}: в таблице ${sheetV} · в Gincore ${crmV}`;
}

function tdMoney(value, field, verify) {
  const diff = verify?.field_diffs?.[field];
  const html = fmtMoney(value);
  if (!diff) return `<td>${html}</td>`;
  return `<td class="cell-mismatch" title="${escapeHtml(cellTip(diff))}">${html}</td>`;
}

function tdText(value, field, verify) {
  const diff = verify?.field_diffs?.[field];
  const html = escapeHtml(value || "—");
  if (!diff) return `<td>${html}</td>`;
  return `<td class="cell-mismatch" title="${escapeHtml(cellTip(diff))}">${html}</td>`;
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
  document.querySelectorAll(".mod-tab").forEach((btn) => {
    const on = btn.getAttribute("data-tab") === tab;
    btn.classList.toggle("is-active", on);
  });
  document.querySelectorAll("main .panel").forEach((panel) => {
    const on = panel.id === `panel-${tab}`;
    panel.hidden = !on;
    panel.classList.toggle("is-active", on);
  });
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
          { ...line, label: "Ср. досогласование", data: sheets.map((s) => s.avg_upsell), borderColor: "#0f6e56" },
          { ...line, label: "Σ досогласований", data: sheets.map((s) => s.upsell_sum), borderColor: "#c45c26" },
          { ...line, label: "Σ в отчёте", data: sheets.map((s) => s.report_sum), borderColor: "#1a5f8a" },
        ],
      },
      options: {
        ...base,
        scales: {
          ...base.scales,
          y: {
            beginAtZero: true,
            ticks: { callback: (v) => fmtMoney(v), color: "#5d6b7c", font: { size: 10 } },
            grid: { color: "rgba(28,36,48,0.07)" },
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

function renderDebt(sheets, tickets, report) {
  const empty = $("#debt-empty");
  const body = $("#debt-body");
  const daily = DATA?.debt_daily || [];
  if (!sheets?.length && !tickets?.length && !daily.length) {
    if (empty) empty.hidden = false;
    if (body) body.hidden = true;
    return;
  }
  if (empty) empty.hidden = true;
  if (body) body.hidden = false;

  const last = sheets[sheets.length - 1];
  const debtSum = tickets.reduce((a, t) => a + (Number(t.debt) || 0), 0);
  const lastDaily = daily.length ? daily[daily.length - 1] : null;
  const byV = { mismatch: 0, norm: 0, ok: 0, missing: 0, error: 0 };
  for (const t of tickets) {
    const v = resolveVerdict(t.verify);
    if (v && byV[v] != null) byV[v] += 1;
  }

  const kpis = $("#debt-kpis");
  if (kpis) {
    const rows = [
      ["Σ недоплат", fmtMoney(debtSum), `${tickets.length} квитанций`],
      [
        "CRM дебиторка",
        fmtMoney(lastDaily?.crm_debt_sum),
        lastDaily
          ? String(lastDaily.day || "").replace(/^(\d{4})-(\d{2})-(\d{2}).*/, "$3.$2.$1")
          : "—",
      ],
      ["Посл. Σ", fmtMoney(last?.debt_sum), last?.sheet_title || ""],
      ["Посл. шт.", fmtMoney(last?.debt_count), fmtPct(last?.debt_ratio)],
    ];
    if (report?.total) {
      rows.push(["Расхождения", fmtMoney(report.mismatch ?? byV.mismatch), `из ${report.total}`]);
      rows.push(["Норма", fmtMoney(report.norm ?? byV.norm), "выдан, оплачено"]);
    }
    kpis.innerHTML = rows
      .map(
        ([l, v, h]) => `<div class="kpi"><span class="kpi-label">${escapeHtml(l)}</span>
        <span class="kpi-value">${escapeHtml(v)}</span>
        <span class="kpi-hint">${escapeHtml(h)}</span></div>`
      )
      .join("");
  }

  const reportEl = $("#debt-report");
  if (reportEl) {
    if (report?.total) {
      reportEl.hidden = false;
      reportEl.innerHTML = `
        <h3>Отчёт сверки с Gincore</h3>
        <div class="chip-row">
          <span class="chip">всего ${report.total}</span>
          <span class="chip is-ok">ок ${report.ok ?? 0}</span>
          <span class="chip is-norm">норма ${report.norm ?? 0}</span>
          <span class="chip is-bad">расхождения ${report.mismatch ?? 0}</span>
          <span class="chip is-miss">нет в CRM ${report.missing ?? 0}</span>
        </div>`;
    } else {
      reportEl.hidden = true;
      reportEl.innerHTML = "";
    }
  }

  const tbody = $("#tbody-debt");
  if (tbody) {
    const rank = (t) => {
      const v = resolveVerdict(t.verify);
      if (v === "mismatch") return 0;
      if (v === "missing") return 1;
      if (v === "error") return 2;
      if (!v) return 3;
      if (v === "norm") return 4;
      return 5;
    };
    const ordered = [...tickets].sort((a, b) => {
      const dr = rank(a) - rank(b);
      if (dr) return dr;
      return (Number(b.debt) || 0) - (Number(a.debt) || 0);
    });
    tbody.innerHTML = ordered
      .map((t) => {
        const v = resolveVerdict(t.verify);
        const meta = verdictMeta(v);
        const tip =
          v === "norm" && t.verify?.summary && !String(t.verify.summary).toLowerCase().startsWith("норма")
            ? `Норма: в CRM «Выдан», долга нет · ${t.verify.summary}`
            : t.verify?.summary || "";
        const ticketCell = t.verify?.crm_url
          ? `<a class="ticket-link" href="${escapeHtml(t.verify.crm_url)}" target="_blank" rel="noopener">${escapeHtml(t.ticket)}</a>`
          : escapeHtml(t.ticket);
        const crmDebt = t.verify
          ? t.verify.field_diffs?.debt
            ? `<td class="cell-mismatch" title="${escapeHtml(cellTip(t.verify.field_diffs.debt))}">${fmtMoney(t.verify.crm_debt)}</td>`
            : `<td>${fmtMoney(t.verify.crm_debt)}</td>`
          : "<td>—</td>";
        return `<tr class="${meta.row}">
          <td>${escapeHtml(t.sheet_title)}</td>
          <td>${escapeHtml(t.master || "—")}</td>
          <td>${ticketCell}</td>
          ${tdMoney(t.total_repair, "total", t.verify)}
          ${tdMoney(t.paid, "paid", t.verify)}
          ${tdMoney(t.debt, "debt", t.verify)}
          ${crmDebt}
          ${tdText(t.status || "—", "status", t.verify)}
          <td title="${escapeHtml(tip)}">${
            v ? `<span class="verdict ${meta.chip}">${escapeHtml(meta.label)}</span>` : "—"
          }</td>
        </tr>`;
      })
      .join("");
  }

  const dailyMeta = $("#debt-daily-meta");
  if (dailyMeta) {
    if (!daily.length) {
      dailyMeta.textContent = "Точек динамики пока нет в снимке.";
    } else {
      const tip = daily[daily.length - 1];
      const dayLabel = String(tip.day || "").replace(/^(\d{4})-(\d{2})-(\d{2}).*/, "$3.$2.$1");
      dailyMeta.textContent = `Точек: ${daily.length} · посл. ${dayLabel} · CRM ${fmtMoney(
        tip.crm_debt_sum,
      )} · отчёты ${fmtMoney(tip.sheets_debt_sum)}`;
    }
  }

  const canvas = $("#chart-debt");
  if (canvas && typeof Chart !== "undefined" && daily.length) {
    debtChart?.destroy();
    const labels = daily.map((d) => {
      const m = String(d.day || "").match(/^(\d{4})-(\d{2})-(\d{2})/);
      return m ? `${m[3]}.${m[2]}` : d.day;
    });
    const base = lineDefaults();
    const n = daily.length;
    const radii = Array.from({ length: n }, (_, i) => (i === n - 1 ? 5 : 3));
    const line = {
      tension: 0.3,
      spanGaps: true,
      pointRadius: radii,
      borderWidth: 2.25,
      backgroundColor: "transparent",
    };
    debtChart = new Chart(canvas, {
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
        scales: {
          ...base.scales,
          x: { ticks: { maxRotation: 0, autoSkip: false, color: "#5d6b7c", font: { size: 10 } } },
          y: {
            beginAtZero: true,
            ticks: { callback: (v) => fmtMoney(v), color: "#5d6b7c", font: { size: 10 } },
            grid: { color: "rgba(28,36,48,0.07)" },
          },
        },
      },
    });
  }
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
        line += ` · КПД ${new Date(BRANCH_KPI.exported_at).toLocaleString("ru-RU")}`;
      }
      meta.textContent = line;
    }
    renderUpsell(DATA.upsell_sheets || []);
    renderDebt(DATA.debt_sheets || [], DATA.debt_tickets || [], DATA.verify_report || null);
  }
  renderBranchKpi(BRANCH_KPI);
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
  const allowed = new Set(["upsell", "debt", "branch_kpi"]);
  setTab(allowed.has(tab) ? tab : "upsell");

  const meta = $("#export-meta");
  try {
    const res = await fetch(`./data.json?t=${Date.now()}`);
    if (!res.ok) throw new Error(`data.json: ${res.status}`);
    DATA = await res.json();
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
  if (!BRANCH_KPI?.months?.length) {
    const empty = $("#branch-kpi-empty");
    if (empty) empty.hidden = false;
  }
  renderAll();
}

boot();
