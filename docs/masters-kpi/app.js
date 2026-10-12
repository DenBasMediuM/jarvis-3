/* global Chart, JarvisVitrineAuth */
(async function () {
  const auth = window.JarvisVitrineAuth;
  if (!auth?.requireAuth("processes.masters_kpi")) return;
  auth.applyShellNav("processes.masters_kpi");

  const el = (id) => document.getElementById(id);
  const money = (n) =>
    n == null || Number.isNaN(Number(n))
      ? "—"
      : Number(n).toLocaleString("uk-UA", { maximumFractionDigits: 0 });

  let data;
  try {
    const res = await fetch(`./data.json?t=${Date.now()}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`data.json ${res.status}`);
    data = await res.json();
  } catch (err) {
    document.body.innerHTML = `<p class="empty">Нет снимка КПД мастеров (${err.message}). Экспортируйте из Jarvis.</p>`;
    return;
  }

  el("app").hidden = false;
  const masters = data.masters || [];
  const charts = data.charts || {};
  el("meta").textContent = data.exported_at
    ? `Экспорт ${new Date(data.exported_at).toLocaleString("ru-RU")} · ${masters.length} мастеров`
    : `${masters.length} мастеров`;

  el("kpis").innerHTML = masters
    .slice(0, 6)
    .map(
      (m) => `<div class="mod-kpi">
        <span>${m.display_name}</span>
        <strong>${money(m.work_sum)}</strong>
        <small>КПД ${m.efficiency == null ? "—" : Number(m.efficiency).toLocaleString("uk-UA")}</small>
      </div>`,
    )
    .join("");

  const lineOpts = {
    responsive: true,
    maintainAspectRatio: false,
    interaction: { mode: "index", intersect: false },
    plugins: { legend: { position: "bottom", labels: { boxWidth: 10, font: { size: 10 } } } },
    scales: {
      x: { ticks: { font: { size: 10 } } },
      y: { beginAtZero: true, ticks: { font: { size: 10 } } },
    },
  };
  const mkLine = (canvas, series, labels) => {
    if (!canvas || typeof Chart === "undefined") return;
    new Chart(canvas, {
      type: "line",
      data: {
        labels,
        datasets: (series || []).map((s) => ({
          label: s.label,
          data: s.data,
          borderColor: s.color,
          backgroundColor: "transparent",
          tension: 0.28,
          spanGaps: true,
          pointRadius: 1.5,
          borderWidth: 2,
        })),
      },
      options: lineOpts,
    });
  };
  mkLine(el("chart-eff"), charts.efficiency, charts.labels || []);
  mkLine(el("chart-work"), charts.work_sum, charts.labels || []);

  el("cards").innerHTML = masters
    .map(
      (m) => `<article class="masters-card">
        <h3 style="border-color:${m.color || "#334155"}">${m.display_name}</h3>
        <dl>
          <div><dt>Σ работ</dt><dd>${money(m.work_sum)}</dd></div>
          <div><dt>Кв.</dt><dd>${m.tickets ?? "—"}</dd></div>
          <div><dt>Ср. квит.</dt><dd>${m.avg_ticket == null ? "—" : money(m.avg_ticket)}</dd></div>
          <div><dt>КПД</dt><dd>${m.efficiency == null ? "—" : Number(m.efficiency).toLocaleString("uk-UA")}</dd></div>
        </dl>
      </article>`,
    )
    .join("");
})();
