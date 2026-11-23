/* Платная диагностика — витрина.
 * Записи менеджера, план, цены и CRM-снимок (кандидаты, статусы квитанций) — Worker jarvis-feedback (D1), по токену входа.
 */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const STATUSES = {
  consult: "Консультация с мастером",
  offered: "Предложено клиенту",
  agreed: "Согласовано",
  declined: "Клиент отказался",
  not_needed: "Платная не нужна",
};
const OPEN = ["consult", "offered"];
const SOURCES = { buffer: "Буфер", undiagnosed: "У мастера, не продиагностировано", other: "Другое" };
const CATEGORY_FALLBACK = {
  power_station: "Зарядные станции",
  inverter_ups: "Инверторы, ИБП, стабилизаторы",
  laptop: "Ноутбуки",
  pc: "ПК, моноблоки, комплектующие",
  tv_monitor: "Телевизоры, мониторы, проекторы",
  console: "Игровые приставки",
  printer: "Принтеры, МФУ, 3D-принтеры",
  coffee: "Кофемашины",
  robot_vac: "Роботы-пылесосы",
  audio: "Аудио: усилители, колонки",
  tools: "Электроинструмент",
  appliances: "Крупная техника",
  phone_tablet: "Телефоны, планшеты",
  other: "Прочее",
};
const ACTIONS = {
  case_created: "Новая запись",
  case_updated: "Правка записи",
  status_offered: "Предложено клиенту",
  status_agreed: "Согласовано",
  status_declined: "Клиент отказался",
  status_not_needed: "Платная не нужна",
  status_consult: "Консультация",
  prices_saved: "Цены",
  case_deleted: "Запись удалена",
};

let STATE = null;
let RIGHTS = { work: false, lead: false };
let activeTab = null;

// ---------- утилиты ----------
function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function money(v) {
  if (v === null || v === undefined || v === "" || Number.isNaN(Number(v))) return "—";
  return `${Math.round(Number(v)).toLocaleString("ru-RU")} грн`;
}
function dayKey(d) {
  const x = d instanceof Date ? d : new Date(d);
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
}
const todayKey = () => dayKey(new Date());
function addDays(key, n) {
  const d = new Date(`${key}T12:00:00`);
  d.setDate(d.getDate() + n);
  return dayKey(d);
}
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  return Number.isNaN(d.getTime()) ? esc(iso) : d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit" });
}
function fmtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return esc(iso);
  return `${d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" })} ${d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })}`;
}
function weekStart(key) {
  const d = new Date(`${key}T12:00:00`);
  d.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return dayKey(d);
}
const isSunday = (key) => new Date(`${key}T12:00:00`).getDay() === 0;

// ---------- данные ----------
const auth = () => window.JarvisVitrineAuth;
async function api(method, path, body) {
  const base = auth()?.feedbackUrl?.() || "";
  const token = auth()?.feedbackToken?.() || "";
  if (!base) throw new Error("облако не настроено");
  if (!token) {
    const e = new Error("Нет токена облака — выйдите и войдите на витрину заново");
    e.code = "no_token";
    throw e;
  }
  const res = await fetch(`${base}${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    const e = new Error(data.message || data.error || `HTTP ${res.status}`);
    e.code = data.error;
    e.status = res.status;
    throw e;
  }
  return data;
}
function applyState(data) {
  STATE = {
    cases: data.cases || [],
    log: data.log || [],
    plan: data.plan || { daily_agreed: 1, daily_offered: 2 },
    prices: data.prices || {},
    crm: data.crm || null,
    now: data.now,
  };
  if (data.rights) RIGHTS = data.rights;
}
async function loadAll() {
  const banner = $("#dg-banner");
  try {
    applyState(await api("GET", "/diag/state"));
    banner.hidden = true;
  } catch (err) {
    STATE = null;
    banner.hidden = false;
    banner.textContent =
      err.status === 401 || err.code === "no_token"
        ? "Сессия облака истекла — выйдите и войдите на витрину заново."
        : err.status === 403
          ? "Нет доступа к разделу — попросите выдать «Платная диагностика» в Jarvis."
          : `Нет связи с облаком (${err.message}).`;
  }
  renderMeta();
}
function renderMeta() {
  const crm = STATE?.crm;
  $("#dg-meta").textContent = [
    crm?.generated_at ? `кандидаты: ${fmtDateTime(crm.generated_at)}` : "кандидатов ещё нет",
    STATE ? `облако: ${fmtDateTime(STATE.now)}` : "",
  ]
    .filter(Boolean)
    .join(" · ");
}

const cases = () => STATE?.cases || [];
const caseById = (id) => cases().find((c) => Number(c.id) === Number(id));
const catLabel = (id) => STATE?.crm?.category_labels?.[id] || CATEGORY_FALLBACK[id] || id || "—";
const ticketInfo = (t) => STATE?.crm?.tickets?.[String(t)] || null;
const candByTicket = (t) => (STATE?.crm?.candidates || []).find((c) => String(c.ticket) === String(t));

/** События по дням из журнала: первое «предложено/согласовано/отказ» на запись и согласования. */
function events() {
  const offered = new Map(); // case_id → день первого предложения (включая сразу «согласовано»/«отказ»)
  const agreed = new Map(); // case_id → день согласования (последний)
  const log = [...(STATE?.log || [])].sort((a, b) => String(a.at).localeCompare(String(b.at)));
  const alive = new Set(cases().map((c) => c.id));
  for (const l of log) {
    if (!l.case_id || !alive.has(l.case_id)) continue; // удалённые записи в статистику не идут
    const d = dayKey(l.at);
    if (["status_offered", "status_agreed", "status_declined"].includes(l.action) && !offered.has(l.case_id)) offered.set(l.case_id, d);
    if (l.action === "status_agreed") agreed.set(l.case_id, d);
    if (["status_declined", "status_consult", "status_offered", "status_not_needed"].includes(l.action) && agreed.has(l.case_id)) agreed.delete(l.case_id);
  }
  // запись, у которой статус «согласовано», но журнала нет (старше 200 дней) — по status_at
  for (const c of cases()) {
    if (c.status === "agreed" && !agreed.has(c.id)) agreed.set(c.id, dayKey(c.status_at || c.updated_at));
  }
  return { offered, agreed };
}
function countByDay(map) {
  const out = {};
  for (const d of map.values()) out[d] = (out[d] || 0) + 1;
  return out;
}

// ---------- Сегодня ----------
function renderToday() {
  if (!STATE) {
    $("#dg-goal").innerHTML = "";
    $("#dg-cands").innerHTML = `<p class="os-muted">Нет связи с облаком.</p>`;
    return;
  }
  const t = todayKey();
  const ev = events();
  const agreedToday = countByDay(ev.agreed)[t] || 0;
  const offeredToday = countByDay(ev.offered)[t] || 0;
  const plan = STATE.plan;
  const ws = weekStart(t);
  let weekAgreed = 0;
  let weekSum = 0;
  for (const [id, d] of ev.agreed) {
    if (d >= ws) {
      weekAgreed += 1;
      weekSum += Number(caseById(id)?.price) || 0;
    }
  }
  const box = (cls, label, val, sub) => `<div class="dg-goal-box ${cls}"><span class="os-muted">${esc(label)}</span><b>${val}</b><span class="os-muted">${sub}</span></div>`;
  const doneA = agreedToday >= (plan.daily_agreed || 1);
  $("#dg-goal").innerHTML = [
    box(doneA ? "is-done" : "", "Согласовано сегодня", `${agreedToday} / ${plan.daily_agreed}`, doneA ? "план дня выполнен ✓" : "цель — хотя бы одна платная диагностика"),
    box(offeredToday >= (plan.daily_offered || 0) ? "is-done" : "", "Предложено клиентам сегодня", `${offeredToday} / ${plan.daily_offered}`, "включая согласованные и отказы"),
    box("", "За неделю", `${weekAgreed}`, `согласовано на ${money(weekSum)}`),
  ].join("");
  const open = cases().filter((c) => OPEN.includes(c.status));
  $("#dg-open").innerHTML = open.length
    ? `<article class="card"><h3>В работе (${open.length})</h3>${casesTable(open, { quick: true })}</article>`
    : "";
  renderCandidates();
}

function renderCandidates() {
  const crm = STATE?.crm;
  const pool = crm?.pool || {};
  $("#dg-cand-sub").textContent = crm
    ? `Из кэша «Качества» на ${fmtDateTime(crm.generated_at)}: в буфере ${pool.buffer ?? 0}, у мастеров без диагностики ${pool.undiagnosed ?? 0}. ` +
      "Выберите сложное устройство, проконсультируйтесь с ведущим или профильным мастером и согласуйте с клиентом платную диагностику."
    : "Кандидатов ещё нет — их готовит Jarvis при утренней пересборке (после «Качества»).";
  const taken = new Set(cases().map((c) => String(c.ticket)));
  const q = $("#dg-search").value.trim().toLowerCase();
  const src = $("#dg-src").value;
  const simple = $("#dg-simple").checked;
  const list = (crm?.candidates || []).filter(
    (c) =>
      !taken.has(String(c.ticket)) &&
      (!src || c.source === src) &&
      (simple || c.complexity >= 2) &&
      (!q || `${c.ticket} ${c.device} ${c.engineer || ""}`.toLowerCase().includes(q)),
  );
  $("#dg-cands").innerHTML = list.length
    ? list
        .slice(0, 40)
        .map(
          (c) => `<div class="cl-cand">
        <div class="cl-cand-head">
          <span><span class="cl-cand-name">${esc(c.device || "—")}</span> · ${
            c.url ? `<a href="${esc(c.url)}" target="_blank" rel="noopener">№${esc(c.ticket)}</a>` : `№${esc(c.ticket)}`
          } · <span class="os-muted">${esc(c.status)}</span></span>
          <span>${c.source === "buffer" ? '<span class="os-tag is-warn">буфер</span>' : `<span class="os-tag">мастер: ${esc(c.engineer || "—")}</span>`} ${
            c.complexity >= 3 ? '<span class="os-tag is-bad">сложная</span>' : ""
          }</span>
        </div>
        <div class="os-tags">${(c.reasons || []).map((r) => `<span class="os-tag">${esc(r)}</span>`).join("")}</div>
        <div class="cl-cand-actions">
          <button class="os-btn is-primary is-small" data-take="${esc(c.ticket)}">Взять в работу</button>
          <span class="os-muted" style="font-size:.8rem">подсказка цены: ${money(STATE.prices?.[c.category])}</span>
        </div>
      </div>`,
        )
        .join("")
    : `<p class="os-muted">${(crm?.candidates || []).length ? "Подходящих кандидатов нет — уберите фильтры или включите простые категории." : "Кандидатов нет."}</p>`;
}

function statusBadge(st) {
  return `<span class="dg-status s-${esc(st)}">${esc(STATUSES[st] || st)}</span>`;
}
function crmCell(c) {
  const t = ticketInfo(c.ticket);
  if (!t) return '<span class="os-muted">—</span>';
  if (!t.closed) return `${esc(t.status || "")}`;
  const paid = Number(t.paid) || 0;
  const cls = c.status === "agreed" ? (paid >= (Number(c.price) || 0) && paid > 0 ? "os-good" : "os-bad") : "";
  return `<span class="${cls}">${esc(t.status || "закрыт")} · оплачено ${money(paid)}</span>`;
}
function casesTable(list, { quick = false } = {}) {
  return `<div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr>
    <th>Дата</th><th>№</th><th>Устройство</th><th>Мастер</th><th>Статус</th><th>Цена</th><th>В CRM</th>${quick ? "<th></th>" : "<th>Кто</th>"}</tr></thead><tbody>${list
    .map(
      (c) => `<tr>
        <td>${fmtDate(c.status_at || c.created_at)}</td>
        <td><button class="os-link" data-open="${c.id}">${esc(c.ticket)}</button></td>
        <td class="os-wrap">${esc(c.device || "—")}<br><small class="os-muted">${esc(catLabel(c.category))}</small></td>
        <td>${esc(c.master || "—")}</td>
        <td>${statusBadge(c.status)}${c.status === "declined" && c.decline_reason ? `<br><small class="os-muted">${esc(c.decline_reason)}</small>` : ""}</td>
        <td class="os-num">${c.price ? money(c.price) : "—"}${c.prepay ? "<br><small class='os-muted'>предоплата</small>" : ""}</td>
        <td class="os-wrap">${crmCell(c)}</td>
        ${
          quick
            ? `<td><div class="dg-quick">${
                c.status === "consult" ? `<button class="os-btn is-small" data-quick="${c.id}" data-st="offered">Предложил клиенту</button>` : ""
              }<button class="os-btn is-small is-primary" data-quick="${c.id}" data-st="agreed">Согласовано</button><button class="os-btn is-small" data-quick="${c.id}" data-st="declined">Отказ</button></div></td>`
            : `<td>${esc(c.created_by || "")}</td>`
        }
      </tr>`,
    )
    .join("")}</tbody></table></div>`;
}

// ---------- Записи ----------
function renderCases() {
  if (!STATE) {
    $("#dg-cases").innerHTML = `<p class="os-muted">Нет связи с облаком.</p>`;
    return;
  }
  const q = $("#dg-cases-search").value.trim().toLowerCase();
  const st = $("#dg-cases-status").value;
  const list = cases().filter(
    (c) => (!st || c.status === st) && (!q || `${c.ticket} ${c.device} ${c.master}`.toLowerCase().includes(q)),
  );
  $("#dg-cases").innerHTML = list.length ? casesTable(list) : `<p class="os-muted">Записей нет.</p>`;
}

// ---------- Статистика ----------
function periodRange(kind) {
  const t = todayKey();
  if (kind === "prev") {
    const ws = addDays(weekStart(t), -7);
    return { from: ws, to: addDays(ws, 6), label: "прошлая неделя" };
  }
  if (kind === "month") return { from: `${t.slice(0, 7)}-01`, to: t, label: "этот месяц" };
  if (kind === "prevmonth") {
    const d = new Date(`${t.slice(0, 7)}-01T12:00:00`);
    d.setDate(0);
    const end = dayKey(d);
    return { from: `${end.slice(0, 7)}-01`, to: end, label: "прошлый месяц" };
  }
  if (kind === "30") return { from: addDays(t, -29), to: t, label: "30 дней" };
  return { from: weekStart(t), to: t, label: "эта неделя" };
}
function workdays(r) {
  const out = [];
  for (let d = r.from; d <= r.to; d = addDays(d, 1)) if (!isSunday(d)) out.push(d);
  return out;
}

function renderStats() {
  if (!STATE) return;
  const r = periodRange($("#dg-period").value);
  const ev = events();
  const inR = (d) => d >= r.from && d <= r.to;
  const agreedIds = [...ev.agreed].filter(([, d]) => inR(d)).map(([id]) => id);
  const offeredIds = [...ev.offered].filter(([, d]) => inR(d)).map(([id]) => id);
  const agreedCases = agreedIds.map(caseById).filter(Boolean);
  const sum = agreedCases.reduce((s, c) => s + (Number(c.price) || 0), 0);
  let paid = 0;
  let closed = 0;
  for (const c of agreedCases) {
    const t = ticketInfo(c.ticket);
    if (t?.closed) {
      closed += 1;
      paid += Math.min(Number(c.price) || 0, Number(t.paid) || 0);
    }
  }
  const declined = offeredIds.map(caseById).filter((c) => c?.status === "declined");
  const notNeeded = (STATE.log || []).filter((l) => l.action === "status_not_needed" && inR(dayKey(l.at))).length;
  const byDayA = countByDay(new Map([...ev.agreed].filter(([, d]) => inR(d))));
  const wds = workdays({ from: r.from, to: r.to > todayKey() ? todayKey() : r.to });
  const goal = STATE.plan.daily_agreed || 1;
  const met = wds.filter((d) => (byDayA[d] || 0) >= goal).length;
  const kpi = (label, val, sub, good) =>
    `<div class="kpi"><span class="kpi-label">${esc(label)}</span><span class="kpi-value ${good === true ? "os-good" : good === false ? "os-bad" : ""}">${val}</span><span class="kpi-sub">${esc(sub)}</span></div>`;
  $("#dg-kpis").innerHTML = [
    kpi("Дней с выполненным планом", `${met} / ${wds.length}`, `рабочих дней (пн–сб), план — ${goal} в день`, wds.length ? met === wds.length : null),
    kpi("Согласовано", agreedCases.length, `на ${money(sum)}`),
    kpi("Оплачено по CRM", money(paid), `закрыто ${closed} из ${agreedCases.length} согласованных`),
    kpi("Предложено клиентам", offeredIds.length, "устройств"),
    kpi("Конверсия", offeredIds.length ? `${Math.round((agreedCases.length / offeredIds.length) * 100)}%` : "—", "согласовано ÷ предложено"),
    kpi("Средняя цена", agreedCases.length ? money(sum / agreedCases.length) : "—", `«платная не нужна»: ${notNeeded}`),
  ].join("");
  // 30 дней
  const t = todayKey();
  const days = [];
  for (let i = 29; i >= 0; i--) days.push(addDays(t, -i));
  const allA = countByDay(ev.agreed);
  const allO = countByDay(ev.offered);
  const max = Math.max(goal, 1, ...days.map((d) => Math.max(allA[d] || 0, allO[d] || 0)));
  const started = cases().reduce((m, c) => (dayKey(c.created_at) < m ? dayKey(c.created_at) : m), t);
  $("#dg-days").innerHTML = `<div class="dg-bars">${days
    .map((d) => {
      const a = allA[d] || 0;
      const o = allO[d] || 0;
      const miss = !isSunday(d) && a < goal && d < t && d >= started;
      return `<div class="dg-bar ${isSunday(d) ? "is-sun" : ""} ${miss ? "is-miss" : ""}" title="${fmtDate(d)}: предложено ${o}, согласовано ${a}">
        <span class="b-off" style="height:${(Math.max(0, o - a) / max) * 100}%"></span>
        <span class="b-ok" style="height:${(Math.max(a, miss ? 0.15 : 0) / max) * 100}%"></span></div>`;
    })
    .join("")}<div class="dg-goal-line" style="bottom:${(goal / max) * 100}%"></div></div>
    <div class="os-days-legend"><span>${fmtDate(days[0])}</span><span>зелёный — согласовано, голубой — предложено без согласия, розовый — рабочий день без согласования</span><span>${fmtDate(t)}</span></div>`;
  // мастера и категории
  const periodCases = cases().filter((c) => inR(dayKey(c.created_at)) || agreedIds.includes(c.id));
  const group = (keyFn, labelFn) => {
    const m = new Map();
    for (const c of periodCases) {
      const k = keyFn(c) || "—";
      const g = m.get(k) || { n: 0, agreed: 0, sum: 0, not_needed: 0 };
      g.n += 1;
      if (agreedIds.includes(c.id)) {
        g.agreed += 1;
        g.sum += Number(c.price) || 0;
      }
      if (c.status === "not_needed") g.not_needed += 1;
      m.set(k, g);
    }
    const rows = [...m.entries()].sort((a, b) => b[1].sum - a[1].sum || b[1].n - a[1].n);
    return rows.length
      ? `<div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr><th></th><th>Записей</th><th>Согласовано</th><th>Сумма</th><th>«Не нужна»</th></tr></thead><tbody>${rows
          .map(([k, g]) => `<tr><td>${esc(labelFn(k))}</td><td class="os-num">${g.n}</td><td class="os-num">${g.agreed}</td><td class="os-num">${money(g.sum)}</td><td class="os-num">${g.not_needed}</td></tr>`)
          .join("")}</tbody></table></div>`
      : `<p class="os-muted">За период записей нет.</p>`;
  };
  $("#dg-by-master").innerHTML = group((c) => c.master, (k) => k);
  $("#dg-by-cat").innerHTML = group((c) => c.category, (k) => catLabel(k));
  const reasons = {};
  for (const c of declined) {
    const k = String(c.decline_reason || "—").toLowerCase().trim();
    reasons[k] = (reasons[k] || 0) + 1;
  }
  const rs = Object.entries(reasons).sort((a, b) => b[1] - a[1]);
  $("#dg-declines").innerHTML = rs.length ? `<ul>${rs.map(([k, n]) => `<li>${esc(k)} — ${n}</li>`).join("")}</ul>` : `<p class="os-muted">Отказов за период нет.</p>`;
  const p = STATE.plan;
  $("#dg-plan-form").innerHTML = `
    <label>Согласовать в день<input type="number" min="0" name="daily_agreed" value="${p.daily_agreed}" ${RIGHTS.lead ? "" : "disabled"} /></label>
    <label>Предложить клиентам в день<input type="number" min="0" name="daily_offered" value="${p.daily_offered}" ${RIGHTS.lead ? "" : "disabled"} /></label>
    <div class="os-form-actions">${RIGHTS.lead ? '<button class="os-btn is-primary" type="submit">Сохранить план</button>' : ""}
    <span class="os-status">${p.updated_by ? `задал ${esc(p.updated_by)} · ${fmtDateTime(p.updated_at)}` : "по умолчанию"}</span></div>`;
  const log = (STATE.log || []).filter((l) => inR(dayKey(l.at)));
  $("#dg-log").innerHTML = log.length
    ? `<div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr><th>Когда</th><th>Кто</th><th>Действие</th><th>Детали</th></tr></thead><tbody>${log
        .map((l) => `<tr><td>${fmtDateTime(l.at)}</td><td>${esc(l.login || "")}</td><td>${esc(ACTIONS[l.action] || l.action)}</td><td class="os-wrap">${esc(l.text || "")}</td></tr>`)
        .join("")}</tbody></table></div>`
    : `<p class="os-muted">За период действий нет.</p>`;
}

// ---------- Настройки ----------
function renderSettings() {
  if (!STATE) return;
  const pr = STATE.prices || {};
  $("#dg-prices-form").innerHTML = `<div class="os-row">${Object.keys(CATEGORY_FALLBACK)
    .map((k) => `<label>${esc(catLabel(k))}<input type="number" min="0" step="50" name="${k}" value="${esc(pr[k] ?? "")}" /></label>`)
    .join("")}</div><div class="os-form-actions"><button class="os-btn is-primary" type="submit">Сохранить цены</button><span class="os-status"></span></div>`;
  const stats = STATE.crm?.categories || {};
  const rows = Object.entries(stats)
    .filter(([, v]) => v.closed >= 5)
    .sort((a, b) => (b[1].refusal_share || 0) - (a[1].refusal_share || 0));
  $("#dg-cat-stats").innerHTML = rows.length
    ? `<div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr><th>Категория</th><th>Закрыто за 12 мес.</th><th>Без ремонта</th><th>Средний чек ремонта</th></tr></thead><tbody>${rows
        .map(([k, v]) => `<tr><td>${esc(v.label || catLabel(k))}</td><td class="os-num">${v.closed}</td><td class="os-num ${(v.refusal_share || 0) >= 0.3 ? "os-bad" : ""}">${Math.round((v.refusal_share || 0) * 100)}%</td><td class="os-num">${money(v.avg_check)}</td></tr>`)
        .join("")}</tbody></table></div>`
    : `<p class="os-muted">Нет данных — нужна история ремонтов (её качает модуль «Постоянные клиенты»).</p>`;
}

// ---------- Диалоги ----------
const dlg = () => $("#dg-dialog");
function openDialog(html, onMount) {
  $("#dg-dialog-body").innerHTML = html;
  if (!dlg().open) dlg().showModal();
  onMount?.($("#dg-dialog-body"));
}
function closeDialog() {
  if (dlg().open) dlg().close();
}
async function submitForm(form, fn) {
  const status = $(".os-status", form);
  const btns = $$("button[type=submit]", form);
  btns.forEach((b) => (b.disabled = true));
  if (status) {
    status.classList.remove("is-error");
    status.textContent = "Сохраняю…";
  }
  try {
    const data = await fn(Object.fromEntries(new FormData(form).entries()));
    if (data) applyState(data);
    renderAll();
    return data;
  } catch (err) {
    if (status) {
      status.classList.add("is-error");
      status.textContent = err.message || String(err);
    }
    throw err;
  } finally {
    btns.forEach((b) => (b.disabled = false));
  }
}

function caseFormHtml(c, seed) {
  const v = (k) => esc(c?.[k] ?? seed?.[k] ?? "");
  const cur = c?.status || seed?.status || "consult";
  const cat = c?.category || seed?.category || "other";
  const price = c?.price ?? STATE.prices?.[cat] ?? "";
  const engineers = STATE.crm?.engineers || [];
  const statusRadios = Object.entries(STATUSES)
    .map(([k, l]) => `<label><input type="radio" name="status" value="${k}" ${cur === k ? "checked" : ""}/> <span>${l}</span></label>`)
    .join("");
  const catOpts = Object.keys(CATEGORY_FALLBACK).map((k) => `<option value="${k}" ${cat === k ? "selected" : ""}>${esc(catLabel(k))}</option>`).join("");
  const srcOpts = Object.entries(SOURCES).map(([k, l]) => `<option value="${k}" ${(c?.source || seed?.source || "other") === k ? "selected" : ""}>${l}</option>`).join("");
  const t = c ? ticketInfo(c.ticket) : null;
  return `<h2>${c ? `Квитанция №${esc(c.ticket)}` : "Платная диагностика: новая запись"}</h2>
    ${c ? `<p class="card-sub">${statusBadge(c.status)} · создал ${esc(c.created_by || "")} ${fmtDateTime(c.created_at)}${t ? ` · в CRM: ${crmCell(c)}` : ""}</p>` : ""}
    <form class="os-form" id="dg-case-form">
      <div class="os-row">
        <label class="req">№ квитанции<input name="ticket" required value="${v("ticket")}" ${c ? "readonly" : ""} /></label>
        <label>Устройство<input name="device" value="${v("device")}" /></label>
        <label>Категория<select name="category" id="dg-cat">${catOpts}</select></label>
        <label>Где нашли<select name="source">${srcOpts}</select></label>
      </div>
      <div class="os-row">
        <label>Мастер, с которым консультировались<input name="master" list="dg-engineers" value="${v("master")}" placeholder="ведущий или профильный мастер" /></label>
      </div>
      <datalist id="dg-engineers">${engineers.map((e) => `<option value="${esc(e)}"></option>`).join("")}</datalist>
      <label>Что сказал мастер<textarea name="consult_note" placeholder="почему диагностика сложная, сколько займёт, какую цену назвать">${v("consult_note")}</textarea></label>
      <div class="os-seg">${statusRadios}</div>
      <div class="os-row">
        <label>Цена диагностики, грн<input type="number" min="0" step="50" name="price" id="dg-price" value="${esc(price)}" /></label>
        <label class="dg-check"><input type="checkbox" name="prepay" ${c?.prepay ? "checked" : ""}/> берём предоплату</label>
      </div>
      <label>Почему клиент отказался<input name="decline_reason" value="${v("decline_reason")}" placeholder="дорого, заберёт без диагностики, подумает…" /></label>
      <label>Комментарий<textarea name="comment">${v("comment")}</textarea></label>
      <p class="os-muted" style="margin:0">После согласования оставьте комментарий в квитанции Gincore («погоджено платну діагностику … грн») — так мастер не начнёт её бесплатно.</p>
      <div class="os-form-actions">
        <button class="os-btn is-primary" type="submit">${c ? "Сохранить" : "Создать запись"}</button>
        ${c?.id && RIGHTS.lead ? '<button class="os-btn is-danger" type="button" id="dg-delete">Удалить запись</button>' : ""}
        <span class="os-status"></span>
      </div>
    </form>`;
}
function openCaseForm(c, seed = null) {
  openDialog(caseFormHtml(c, seed), (root) => {
    const f = $("#dg-case-form", root);
    $("#dg-cat", root).addEventListener("change", (e) => {
      const p = STATE.prices?.[e.target.value];
      if (p && !c?.price) $("#dg-price", root).value = p;
    });
    $("#dg-delete", root)?.addEventListener("click", async () => {
      const reason = prompt(`Удалить запись по №${c.ticket}? Она пропадёт из списков и статистики (в журнале останется отметка).\nПричина (необязательно):`, "тестовая запись");
      if (reason === null) return;
      const st = $(".os-status", f);
      try {
        st.textContent = "Удаляю…";
        applyState(await api("POST", `/diag/cases/${c.id}/delete`, { reason }));
        renderAll();
        closeDialog();
      } catch (err) {
        st.classList.add("is-error");
        st.textContent = err.message;
      }
    });
    f.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await submitForm(f, (b) => {
          const body = { ...b, prepay: !!f.querySelector("[name=prepay]").checked };
          return c ? api("PATCH", `/diag/cases/${c.id}`, body) : api("POST", "/diag/cases", body);
        });
        closeDialog();
      } catch {
        /* в форме */
      }
    });
  });
}
function quick(c, st) {
  // «Согласовано» / «Отказ» / «Предложил» — открываем форму с выбранным статусом (там проверки цены и причины)
  openCaseForm({ ...c, status: st });
}

// ---------- вкладки ----------
const LS_TAB = "jarvis.diag.tab";
function setTab(tab) {
  const btn = $(`.mod-tab[data-dgtab="${tab}"]`);
  if (!btn || btn.hidden) tab = "today";
  activeTab = tab;
  $$(".mod-tab[data-dgtab]").forEach((b) => b.classList.toggle("is-active", b.dataset.dgtab === tab));
  $$(".os-panel").forEach((p) => (p.hidden = p.id !== `dg-panel-${tab}`));
  try {
    localStorage.setItem(LS_TAB, tab);
  } catch {
    /* ignore */
  }
  renderActive();
}
function renderActive() {
  if (activeTab === "today") renderToday();
  else if (activeTab === "cases") renderCases();
  else if (activeTab === "stats") renderStats();
  else if (activeTab === "settings") renderSettings();
}
function renderAll() {
  renderMeta();
  renderActive();
}
function bindEvents() {
  $$(".mod-tab[data-dgtab]").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.dgtab)));
  $("#dg-search").addEventListener("input", renderCandidates);
  $("#dg-src").addEventListener("change", renderCandidates);
  $("#dg-simple").addEventListener("change", renderCandidates);
  $("#dg-cases-search").addEventListener("input", renderCases);
  $("#dg-cases-status").addEventListener("change", renderCases);
  $("#dg-period").addEventListener("change", renderStats);
  $("#dg-add-manual").addEventListener("click", () => STATE && openCaseForm(null, { source: "other" }));
  $("#dg-plan-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await submitForm(e.target, (b) => api("PUT", "/diag/plan", { daily_agreed: Number(b.daily_agreed), daily_offered: Number(b.daily_offered) }));
    } catch {
      /* в форме */
    }
  });
  $("#dg-prices-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await submitForm(e.target, (b) => api("PUT", "/diag/prices", { prices: Object.fromEntries(Object.entries(b).map(([k, v]) => [k, Number(v)])) }));
    } catch {
      /* в форме */
    }
  });
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-take],[data-open],[data-quick]");
    if (!t || !STATE) return;
    if (t.dataset.take) {
      const c = candByTicket(t.dataset.take);
      if (c) openCaseForm(null, { ticket: c.ticket, device: c.device, category: c.category, source: c.source, master: c.engineer || "", status: "consult" });
    } else if (t.dataset.open) openCaseForm(caseById(t.dataset.open));
    else if (t.dataset.quick) quick(caseById(t.dataset.quick), t.dataset.st);
  });
}

async function init() {
  const s = auth()?.session?.();
  if (!s) return;
  RIGHTS = {
    work: auth().hasAccess(s.access, "processes.diag") || auth().hasAccess(s.access, "processes.diag_lead"),
    lead: auth().hasAccess(s.access, "processes.diag_lead"),
  };
  bindEvents();
  await loadAll();
  $(`.mod-tab[data-dgtab="stats"]`).hidden = !RIGHTS.lead;
  let saved = null;
  try {
    saved = localStorage.getItem(LS_TAB);
  } catch {
    /* ignore */
  }
  setTab(saved || "today");
  setInterval(async () => {
    if (document.hidden || dlg().open || activeTab === "settings") return;
    await loadAll();
    renderActive();
  }, 120000);
}

document.addEventListener("DOMContentLoaded", init);
