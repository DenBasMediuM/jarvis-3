/* Аутсорс мастера — витрина.
 * Живые данные (кандидаты, передачи, журнал, план) — Worker jarvis-feedback (D1), по токену входа.
 * CRM-снимок (устройства в работе, возвраты, вал/чистые) — ./data.json из Jarvis.
 */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const KINDS = { master_home: "Мастер на дому", master_sc: "Мастер другого СЦ", service: "Сервисный центр" };
const STAGES = {
  found: "Найден",
  contacted: "Связались",
  trial: "Пробник",
  regular: "Постоянный",
  paused: "Пауза",
  lost: "Отказ",
};
const STAGE_ORDER = ["found", "contacted", "trial", "regular", "paused", "lost"];
const OPEN_STAGES = ["found", "contacted", "trial", "regular"];
const ACTIVE_STAGES = ["trial", "regular"];
const DECISIONS = { take: "Берём в постоянные", again: "Ещё пробник", reject: "Отказ" };
const ACTIONS = {
  candidate_created: "Новый кандидат",
  candidate_updated: "Правка карточки",
  stage_changed: "Смена стадии",
  trial_created: "Передача устройства",
  trial_result: "Оценка пробника",
  note: "Заметка",
};
const STUCK_DAYS = 5; // кандидат без движения на стадиях «Найден»/«Связались»
const HIGH_RETURN = 0.3; // коэффициент возврата, выше которого — тревога
const MIN_CLOSED_FOR_RATE = 3;

let STATE = null; // ответ Worker /outsource/state
let CRM = null; // data.json
let RIGHTS = { work: false, lead: false };
let LOGIN = "";
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
  if (v === null || v === undefined || Number.isNaN(Number(v))) return "—";
  return `${Math.round(Number(v)).toLocaleString("ru-RU")} грн`;
}
function pct(v) {
  if (v === null || v === undefined) return "—";
  return `${Math.round(Number(v) * 1000) / 10}%`;
}
function dayKey(d) {
  const x = d instanceof Date ? d : new Date(d);
  return `${x.getFullYear()}-${String(x.getMonth() + 1).padStart(2, "0")}-${String(x.getDate()).padStart(2, "0")}`;
}
function todayKey() {
  return dayKey(new Date());
}
function addDays(key, n) {
  const d = new Date(`${key}T12:00:00`);
  d.setDate(d.getDate() + n);
  return dayKey(d);
}
function daysSince(iso) {
  if (!iso) return null;
  const t = Date.parse(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  if (Number.isNaN(t)) return null;
  return Math.max(0, Math.floor((Date.now() - t) / 86400000));
}
function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  if (Number.isNaN(d.getTime())) return esc(iso);
  return d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit", year: "2-digit" });
}
function fmtDateTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return esc(iso);
  return `${d.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" })} ${d.toLocaleTimeString("ru-RU", {
    hour: "2-digit",
    minute: "2-digit",
  })}`;
}
function weekStart(key) {
  const d = new Date(`${key}T12:00:00`);
  const wd = (d.getDay() + 6) % 7; // пн = 0
  d.setDate(d.getDate() - wd);
  return dayKey(d);
}
function plural(n, one, few, many) {
  const a = Math.abs(n) % 100;
  const b = a % 10;
  if (a > 10 && a < 20) return many;
  if (b > 1 && b < 5) return few;
  if (b === 1) return one;
  return many;
}

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
    candidates: data.candidates || [],
    trials: data.trials || [],
    log: data.log || [],
    plan: data.plan || { candidates: 10, trials: 3, regular: 1, target_min: 5, target_max: 10 },
    now: data.now,
  };
  if (data.rights) RIGHTS = data.rights;
  if (data.login) LOGIN = data.login;
}

async function loadAll() {
  const banner = $("#os-banner");
  const crmP = fetch(`./data.json?t=${Date.now()}`)
    .then((r) => (r.ok ? r.json() : null))
    .catch(() => null);
  try {
    applyState(await api("GET", "/outsource/state"));
    banner.hidden = true;
  } catch (err) {
    STATE = null;
    banner.hidden = false;
    banner.textContent =
      err.status === 401 || err.code === "no_token"
        ? "Сессия облака истекла — выйдите и войдите на витрину заново."
        : `Нет связи с облаком (${err.message}). Записи менеджера недоступны.`;
  }
  CRM = await crmP;
  renderMeta();
}

function renderMeta() {
  const parts = [];
  if (CRM?.generated_at) parts.push(`CRM-снимок: ${fmtDateTime(CRM.generated_at)}`);
  else parts.push("CRM-снимка ещё нет");
  if (STATE) parts.push(`облако: ${fmtDateTime(STATE.now)}`);
  $("#os-meta").textContent = parts.join(" · ");
  const p = STATE?.plan;
  if (p) $("#os-target-label").textContent = `${p.target_min}–${p.target_max}`;
  if ($("#os-crm-date")) $("#os-crm-date").textContent = CRM?.generated_at ? fmtDateTime(CRM.generated_at) : "нет";
  if ($("#os-crm-window")) {
    const w = CRM?.window;
    $("#os-crm-window").textContent = w?.from ? `с ${fmtDate(w.from)} по ${fmtDate(w.to)}` : "—";
  }
}

// ---------- производные ----------
const cands = () => STATE?.candidates || [];
const candById = (id) => cands().find((c) => Number(c.id) === Number(id));
const trialsOf = (id) => (STATE?.trials || []).filter((t) => Number(t.candidate_id) === Number(id));
const logOf = (id) => (STATE?.log || []).filter((l) => Number(l.candidate_id) === Number(id));
const crmOf = (id) => CRM?.outsourcers?.[String(id)] || null;
const ticketInfo = (ticket) => CRM?.trials?.[String(ticket)] || null;

function openTrials(id) {
  return trialsOf(id).filter((t) => !t.result_decision);
}
function isOverdue(t) {
  return !t.result_decision && t.due_at && t.due_at < todayKey();
}
function lastActivity(c) {
  const l = logOf(c.id)[0];
  return l?.at || c.updated_at || c.created_at;
}

function computeAlerts() {
  const out = [];
  const today = todayKey();
  for (const c of cands()) {
    const name = c.name;
    const crm = crmOf(c.id);
    if (ACTIVE_STAGES.includes(c.stage)) {
      if (!c.crm_engineer) {
        out.push({ lvl: "warn", id: c.id, text: `<b>${esc(name)}</b>: не привязан к мастеру Gincore — нет данных по устройствам и деньгам` });
      } else if (crm && crm.bound && crm.engineers_matched?.length === 0 && CRM) {
        out.push({ lvl: "warn", id: c.id, text: `<b>${esc(name)}</b>: мастер «${esc(c.crm_engineer)}» не найден в CRM` });
      } else if (crm && crm.in_work === 0 && openTrials(c.id).length === 0) {
        out.push({ lvl: "bad", id: c.id, text: `<b>${esc(name)}</b>: нет ни одного устройства в работе — простаивает` });
      }
      if (crm && crm.return_rate !== null && crm.issued + crm.refusals >= MIN_CLOSED_FOR_RATE && crm.return_rate > HIGH_RETURN) {
        out.push({ lvl: "bad", id: c.id, text: `<b>${esc(name)}</b>: высокий возврат ${pct(crm.return_rate)} (${crm.refusals} из ${crm.issued + crm.refusals})` });
      }
      if (crm && crm.long_at_master > 0) {
        out.push({ lvl: "warn", id: c.id, text: `<b>${esc(name)}</b>: ${crm.long_at_master} устр. дольше 14 дней у мастера` });
      }
      if (c.stage === "regular" && c.cash_contractor && crm && crm.payouts_matched === false) {
        out.push({ lvl: "warn", id: c.id, text: `<b>${esc(name)}</b>: получатель «${esc(c.cash_contractor)}» не найден в кассе — чистые не считаются` });
      }
    }
    for (const t of trialsOf(c.id)) {
      if (isOverdue(t)) {
        const info = ticketInfo(t.ticket);
        out.push({
          lvl: "bad",
          id: c.id,
          text: `<b>${esc(name)}</b>: просрочен №${esc(t.ticket)} (срок ${fmtDate(t.due_at)}${info?.status ? `, в CRM: ${esc(info.status)}` : ""}) — нет оценки`,
        });
      } else if (!t.result_decision && ticketInfo(t.ticket)?.kind && ["issued", "ready", "refusal"].includes(ticketInfo(t.ticket).kind)) {
        out.push({ lvl: "warn", id: c.id, text: `<b>${esc(name)}</b>: №${esc(t.ticket)} в CRM «${esc(ticketInfo(t.ticket).status)}» — оцените пробник` });
      }
    }
    if ((c.stage === "found" || c.stage === "contacted") && (daysSince(lastActivity(c)) ?? 0) > STUCK_DAYS) {
      out.push({ lvl: "warn", id: c.id, text: `<b>${esc(name)}</b>: ${daysSince(lastActivity(c))} дн. без движения на стадии «${STAGES[c.stage]}»` });
    }
  }
  const weight = { bad: 0, warn: 1 };
  out.sort((a, b) => weight[a.lvl] - weight[b.lvl]);
  void today;
  return out;
}

function alertsHtml(list, empty = "Всё в порядке") {
  if (!list.length) return `<p class="os-muted">${esc(empty)}</p>`;
  return `<ul class="os-list">${list
    .map(
      (a) =>
        `<li class="os-alert is-${a.lvl}"><span>${a.lvl === "bad" ? "●" : "○"}</span><span>${a.text} · <button type="button" class="os-link" data-open-cand="${a.id}">открыть</button></span></li>`,
    )
    .join("")}</ul>`;
}

// Факт за период по журналу
function periodRange(kind) {
  const today = todayKey();
  if (kind === "prev") {
    const ws = addDays(weekStart(today), -7);
    return { from: ws, to: addDays(ws, 6), label: "прошлая неделя" };
  }
  if (kind === "30") return { from: addDays(today, -29), to: today, label: "30 дней" };
  return { from: weekStart(today), to: today, label: "эта неделя" };
}
function inRange(iso, r) {
  const k = dayKey(iso);
  return k >= r.from && k <= r.to;
}
function factFor(range, login) {
  const log = (STATE?.log || []).filter((l) => inRange(l.at, range) && (!login || l.login === login));
  const toRegular = log.filter((l) => l.action === "stage_changed" && /→ Постоянный/.test(l.text || "")).length;
  return {
    actions: log.length,
    candidates: log.filter((l) => l.action === "candidate_created").length,
    trials: log.filter((l) => l.action === "trial_created").length,
    results: log.filter((l) => l.action === "trial_result").length,
    notes: log.filter((l) => l.action === "note").length,
    regular: toRegular,
    log,
  };
}
function workDaysWithoutActions(days, login) {
  // пн–сб без единой записи журнала за последние N дней (не считая сегодня)
  const byDay = new Set((STATE?.log || []).filter((l) => !login || l.login === login).map((l) => dayKey(l.at)));
  const out = [];
  const today = todayKey();
  for (let i = 1; i <= days; i++) {
    const k = addDays(today, -i);
    const wd = new Date(`${k}T12:00:00`).getDay();
    if (wd === 0) continue;
    if (!byDay.has(k)) out.push(k);
  }
  return out;
}
function scalePlan(plan, range) {
  // недельный план → на выбранный период
  const days = Math.round((Date.parse(`${range.to}T12:00:00`) - Date.parse(`${range.from}T12:00:00`)) / 86400000) + 1;
  const k = range.label === "эта неделя" ? 1 : days / 7;
  return {
    candidates: Math.round(plan.candidates * k),
    trials: Math.round(plan.trials * k),
    regular: Math.round(plan.regular * k),
  };
}

// ---------- Воронка ----------
function candidateMatches(c, q) {
  if (!q) return true;
  const blob = [c.name, c.contact, c.area, c.devices, c.terms, c.crm_engineer, c.notes, KINDS[c.kind]]
    .join(" ")
    .toLowerCase();
  return q
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean)
    .every((w) => blob.includes(w));
}

function cardTags(c) {
  const tags = [`<span class="os-tag">${esc(KINDS[c.kind] || c.kind)}</span>`];
  const crm = crmOf(c.id);
  const open = openTrials(c.id);
  if (open.length) {
    const overdue = open.filter(isOverdue).length;
    tags.push(`<span class="os-tag ${overdue ? "is-bad" : "is-warn"}">пробник ${open.length}${overdue ? " · просрочен" : ""}</span>`);
  }
  if (ACTIVE_STAGES.includes(c.stage)) {
    if (!c.crm_engineer) tags.push(`<span class="os-tag is-warn">нет привязки к CRM</span>`);
    else if (crm) {
      tags.push(
        `<span class="os-tag ${crm.in_work ? "is-ok" : "is-bad"}">в работе ${crm.in_work}</span>`,
      );
      if (crm.return_rate !== null) {
        const bad = crm.return_rate > HIGH_RETURN && crm.issued + crm.refusals >= MIN_CLOSED_FOR_RATE;
        tags.push(`<span class="os-tag ${bad ? "is-bad" : ""}">возврат ${pct(crm.return_rate)}</span>`);
      }
    }
  }
  return tags.join("");
}

function renderBoard() {
  const board = $("#os-board");
  if (!STATE) {
    board.innerHTML = `<div class="empty">Нет связи с облаком.</div>`;
    $("#os-todo").innerHTML = "";
    return;
  }
  const q = $("#os-search").value.trim();
  const showClosed = $("#os-show-closed").checked;
  const stages = showClosed ? STAGE_ORDER : OPEN_STAGES;
  board.innerHTML = stages
    .map((st) => {
      const list = cands()
        .filter((c) => c.stage === st && candidateMatches(c, q))
        .sort((a, b) => String(b.stage_at).localeCompare(String(a.stage_at)));
      return `<div class="os-col">
        <div class="os-col-head">${STAGES[st]} <span>${list.length}</span></div>
        <div class="os-cards">${
          list
            .map((c) => {
              const d = daysSince(c.stage_at);
              const meta = [c.area, c.devices].filter(Boolean).join(" · ");
              return `<button type="button" class="os-card" data-open-cand="${c.id}">
                <span class="os-card-name">${esc(c.name)}</span>
                ${meta ? `<span class="os-card-meta">${esc(meta)}</span>` : ""}
                <span class="os-card-meta">на стадии ${d ?? "—"} дн.${st === "lost" && c.lost_reason ? ` · ${esc(c.lost_reason)}` : ""}</span>
                <span class="os-tags">${cardTags(c)}</span>
              </button>`;
            })
            .join("") || `<p class="os-muted" style="font-size:.8rem;padding:4px 6px">пусто</p>`
        }</div>
      </div>`;
    })
    .join("");
  const alerts = computeAlerts();
  $("#os-todo").innerHTML = alerts.length
    ? `<div class="os-todo-card"><h3>Что сделать сейчас (${alerts.length})</h3>${alertsHtml(alerts.slice(0, 12))}${
        alerts.length > 12 ? `<p class="os-muted">и ещё ${alerts.length - 12}…</p>` : ""
      }</div>`
    : "";
}

// ---------- Аутсорсеры ----------
function outsourcersRows() {
  return cands()
    .filter((c) => ["trial", "regular", "paused"].includes(c.stage))
    .sort((a, b) => STAGE_ORDER.indexOf(b.stage) - STAGE_ORDER.indexOf(a.stage) || a.name.localeCompare(b.name));
}

function outsourcersTable() {
  const rows = outsourcersRows();
  if (!rows.length) return `<div class="empty">Пока нет аутсорсеров на стадиях «Пробник» / «Постоянный».</div>`;
  const body = rows
    .map((c) => {
      const m = crmOf(c.id);
      const closed = m ? m.issued + m.refusals : 0;
      const rateBad = m && m.return_rate !== null && closed >= MIN_CLOSED_FOR_RATE && m.return_rate > HIGH_RETURN;
      const tr = trialsOf(c.id);
      const done = tr.filter((t) => t.result_quality);
      const avgQ = done.length ? (done.reduce((s, t) => s + Number(t.result_quality), 0) / done.length).toFixed(1) : "—";
      const inWork = !c.crm_engineer ? `<span class="os-warn">нет привязки</span>` : m ? (m.in_work ? m.in_work : `<span class="os-bad">0</span>`) : "—";
      return `<tr>
        <td><button type="button" class="os-link" data-open-cand="${c.id}">${esc(c.name)}</button><br><span class="os-muted">${esc(KINDS[c.kind] || "")}</span></td>
        <td>${STAGES[c.stage]}</td>
        <td>${esc(c.crm_engineer || "—")}</td>
        <td class="os-num">${inWork}</td>
        <td class="os-num">${m ? (m.long_at_master ? `<span class="os-warn">${m.long_at_master}</span>` : 0) : "—"}</td>
        <td class="os-num">${m ? m.ready : "—"}</td>
        <td class="os-num">${m ? `${m.issued} / ${m.refusals}` : "—"}</td>
        <td class="os-num ${rateBad ? "os-bad" : ""}">${m ? pct(m.return_rate) : "—"}</td>
        <td class="os-num">${m ? money(m.gross) : "—"}</td>
        <td class="os-num">${m?.payouts_matched ? money(m.payouts) : c.cash_contractor ? `<span class="os-warn" title="получатель не найден в кассе">?</span>` : "—"}</td>
        <td class="os-num"><b>${m?.net !== null && m?.net !== undefined ? money(m.net) : "—"}</b></td>
        <td class="os-num">${tr.length} · ${avgQ}</td>
        <td>${fmtDate(lastActivity(c))}</td>
      </tr>`;
    })
    .join("");
  return `<div class="table-wrap os-table-scroll"><table class="vtable">
    <thead><tr>
      <th>Аутсорсер</th><th>Стадия</th><th>Мастер в CRM</th><th>В работе</th><th>&gt;14 дн.</th><th>Готово</th>
      <th>Выдано / возврат</th><th>Коэф. возврата</th><th>Вал</th><th>Выплаты</th><th>Чистые</th><th>Пробники · ср. оценка</th><th>Посл. действие</th>
    </tr></thead><tbody>${body}</tbody></table></div>`;
}

function renderOutsourcers() {
  $("#os-out-table").innerHTML = STATE ? outsourcersTable() : `<div class="empty">Нет связи с облаком.</div>`;
}

// ---------- Активность ----------
function renderActivity() {
  if (!STATE) {
    $("#os-act-kpis").innerHTML = "";
    $("#os-act-days").innerHTML = "";
    $("#os-act-log").innerHTML = `<div class="empty">Нет связи с облаком.</div>`;
    return;
  }
  const loginSel = $("#os-act-login");
  const logins = [...new Set((STATE.log || []).map((l) => l.login).filter(Boolean))].sort();
  const prev = loginSel.value;
  loginSel.innerHTML = `<option value="">Все сотрудники</option>${logins
    .map((l) => `<option value="${esc(l)}">${esc(l)}</option>`)
    .join("")}`;
  if (logins.includes(prev)) loginSel.value = prev;
  const login = loginSel.value;
  const range = periodRange($("#os-act-period").value);
  const f = factFor(range, login);
  const plan = scalePlan(STATE.plan, range);
  const kpi = (label, val, planV, sub = "") => {
    const ok = planV ? val >= planV : true;
    return `<div class="kpi"><span class="kpi-label">${esc(label)}</span>
      <span class="kpi-value ${planV ? (ok ? "os-good" : "os-bad") : ""}">${val}${planV ? ` <span class="os-muted" style="font-size:.9rem">/ ${planV}</span>` : ""}</span>
      ${sub ? `<span class="kpi-sub">${sub}</span>` : ""}</div>`;
  };
  const idle = workDaysWithoutActions(14, login);
  const last = (STATE.log || []).find((l) => !login || l.login === login);
  $("#os-act-kpis").innerHTML = [
    kpi("Новых кандидатов", f.candidates, plan.candidates, "план / факт"),
    kpi("Передано устройств", f.trials, plan.trials, "план / факт"),
    kpi("Новых постоянных", f.regular, plan.regular, "план / факт"),
    kpi("Оценено пробников", f.results),
    kpi("Заметок / контактов", f.notes),
    kpi("Всего действий", f.actions, 0, range.label),
    `<div class="kpi"><span class="kpi-label">Дней без действий (14 дн., пн–сб)</span>
      <span class="kpi-value ${idle.length > 2 ? "os-bad" : idle.length ? "os-warn" : "os-good"}">${idle.length}</span>
      <span class="kpi-sub">${idle.slice(0, 4).map(fmtDate).join(", ")}${idle.length > 4 ? "…" : ""}</span></div>`,
    `<div class="kpi"><span class="kpi-label">Последнее действие</span>
      <span class="kpi-value" style="font-size:1rem">${last ? fmtDateTime(last.at) : "—"}</span>
      <span class="kpi-sub">${last ? `${daysSince(last.at)} дн. назад` : ""}</span></div>`,
  ].join("");

  // по дням
  const today = todayKey();
  const counts = {};
  for (const l of STATE.log || []) {
    if (login && l.login !== login) continue;
    const k = dayKey(l.at);
    counts[k] = (counts[k] || 0) + 1;
  }
  const days = [];
  for (let i = 27; i >= 0; i--) days.push(addDays(today, -i));
  const max = Math.max(1, ...days.map((k) => counts[k] || 0));
  $("#os-act-days").innerHTML = `<div class="os-days">${days
    .map((k) => {
      const n = counts[k] || 0;
      const sunday = new Date(`${k}T12:00:00`).getDay() === 0;
      const cls = n ? "" : sunday ? "is-off" : k === today ? "" : "is-zero";
      return `<div class="os-day ${cls}" style="height:${n ? Math.max(6, (n / max) * 100) : 6}%" title="${fmtDate(k)}: ${n} ${plural(n, "действие", "действия", "действий")}"></div>`;
    })
    .join("")}</div><div class="os-days-legend"><span>${fmtDate(days[0])}</span><span>розовый — рабочий день без действий</span><span>${fmtDate(today)}</span></div>`;

  // журнал
  const rows = f.log.slice(0, 300);
  $("#os-act-log").innerHTML = rows.length
    ? `<div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr><th>Когда</th><th>Кто</th><th>Действие</th><th>Кандидат</th><th>Детали</th></tr></thead><tbody>${rows
        .map((l) => {
          const c = candById(l.candidate_id);
          return `<tr><td>${fmtDateTime(l.at)}</td><td>${esc(l.login || "—")}</td><td>${esc(ACTIONS[l.action] || l.action)}</td>
            <td>${c ? `<button type="button" class="os-link" data-open-cand="${c.id}">${esc(c.name)}</button>` : "—"}</td>
            <td class="os-wrap">${esc(l.text || "")}</td></tr>`;
        })
        .join("")}</tbody></table></div>`
    : `<div class="empty">За период действий нет.</div>`;
}

// ---------- Сводка руководителя ----------
function funnelCounts() {
  // сколько кандидатов когда-либо доходило до стадии (по текущей стадии + журналу смен)
  const reached = { found: new Set(), contacted: new Set(), trial: new Set(), regular: new Set() };
  const rank = { found: 0, contacted: 1, trial: 2, regular: 3, paused: 2, lost: 0 };
  for (const c of cands()) {
    reached.found.add(c.id);
    const r = rank[c.stage] ?? 0;
    if (r >= 1) reached.contacted.add(c.id);
    if (r >= 2) reached.trial.add(c.id);
    if (r >= 3) reached.regular.add(c.id);
    if (trialsOf(c.id).length) {
      reached.contacted.add(c.id);
      reached.trial.add(c.id);
    }
  }
  for (const l of STATE?.log || []) {
    if (l.action !== "stage_changed" || !l.candidate_id) continue;
    const to = (l.text || "").split("→")[1] || "";
    if (/Связались/.test(to)) reached.contacted.add(l.candidate_id);
    if (/Пробник/.test(to)) {
      reached.contacted.add(l.candidate_id);
      reached.trial.add(l.candidate_id);
    }
    if (/Постоянный/.test(to)) {
      reached.contacted.add(l.candidate_id);
      reached.trial.add(l.candidate_id);
      reached.regular.add(l.candidate_id);
    }
  }
  return ["found", "contacted", "trial", "regular"].map((k) => ({ key: k, n: reached[k].size }));
}

function renderSummary() {
  if (!STATE) {
    $("#os-sum-kpis").innerHTML = `<div class="empty">Нет связи с облаком.</div>`;
    return;
  }
  const plan = STATE.plan;
  const regular = cands().filter((c) => c.stage === "regular");
  const active = cands().filter((c) => ACTIVE_STAGES.includes(c.stage));
  const crmActive = active.map((c) => crmOf(c.id)).filter((m) => m && m.bound);
  const inWork = crmActive.reduce((s, m) => s + (m.in_work || 0), 0);
  const idle = active.filter((c) => {
    const m = crmOf(c.id);
    return c.crm_engineer && m && m.in_work === 0 && openTrials(c.id).length === 0;
  }).length;
  const issued = crmActive.reduce((s, m) => s + m.issued, 0);
  const refusals = crmActive.reduce((s, m) => s + m.refusals, 0);
  const gross = crmActive.reduce((s, m) => s + (m.gross || 0), 0);
  const netKnown = crmActive.filter((m) => m.net !== null && m.net !== undefined);
  const net = netKnown.reduce((s, m) => s + m.net, 0);
  const week = factFor(periodRange("week"));
  const k = (label, val, sub, cls = "") =>
    `<div class="kpi"><span class="kpi-label">${esc(label)}</span><span class="kpi-value ${cls}">${val}</span>${sub ? `<span class="kpi-sub">${sub}</span>` : ""}</div>`;
  $("#os-sum-kpis").innerHTML = [
    k("Постоянных аутсорсеров", `${regular.length}`, `цель ${plan.target_min}–${plan.target_max}`, regular.length >= plan.target_min ? "os-good" : ""),
    k("На пробнике", cands().filter((c) => c.stage === "trial").length, "кандидатов"),
    k("Устройств у аутсорсеров", inWork, CRM ? "по CRM-снимку" : "нет CRM-снимка"),
    k("Без устройств", idle, "активных аутсорсеров", idle ? "os-bad" : "os-good"),
    k("Коэф. возврата", issued + refusals ? pct(refusals / (issued + refusals)) : "—", `${refusals} из ${issued + refusals} закрытых`),
    k("Вал", money(gross), CRM?.window?.from ? `с ${fmtDate(CRM.window.from)}` : ""),
    k("Чистые", netKnown.length ? money(net) : "—", netKnown.length < crmActive.length ? `по ${netKnown.length} из ${crmActive.length} (нет выплат в кассе)` : "вал − выплаты"),
    k("Действий в разделе", week.actions, "эта неделя, все сотрудники"),
  ].join("");

  // прогресс
  const max = Math.max(plan.target_max, regular.length, 1);
  $("#os-sum-progress").innerHTML = `<div class="os-progress">
      <div class="os-progress-fill" style="width:${(regular.length / max) * 100}%"></div>
      <div class="os-progress-mark" style="left:${(plan.target_min / max) * 100}%" title="минимум цели"></div>
    </div>
    <div class="os-progress-legend"><span>0</span><span>${regular.length} постоянных · минимум ${plan.target_min}</span><span>${max}</span></div>
    ${regular.length ? `<p class="card-sub" style="margin-top:8px">${regular.map((c) => `<button type="button" class="os-link" data-open-cand="${c.id}">${esc(c.name)}</button>`).join(", ")}</p>` : ""}`;

  const fc = funnelCounts();
  const top = Math.max(1, fc[0].n);
  $("#os-sum-funnel").innerHTML = `<div class="os-funnel">${fc
    .map((r, i) => {
      const conv = i === 0 ? "" : fc[i - 1].n ? `${Math.round((r.n / fc[i - 1].n) * 100)}% от пред.` : "—";
      return `<div class="os-funnel-row"><span>${STAGES[r.key]}</span><div class="os-funnel-bar" style="width:${(r.n / top) * 100}%"></div><span class="os-num">${r.n} <span class="os-muted" style="font-size:.75rem">${conv}</span></span></div>`;
    })
    .join("")}</div><p class="card-sub" style="margin-top:8px">Отказ: ${cands().filter((c) => c.stage === "lost").length} · пауза: ${
    cands().filter((c) => c.stage === "paused").length
  }</p>`;

  $("#os-sum-alerts").innerHTML = alertsHtml(computeAlerts(), "Тревог нет");

  // менеджер
  const rows = ["week", "prev"].map((kind) => {
    const r = periodRange(kind);
    const f = factFor(r);
    const p = scalePlan(plan, r);
    const cell = (v, pv) => `<td class="os-num ${v >= pv ? "os-good" : "os-bad"}">${v} / ${pv}</td>`;
    return `<tr><td>${r.label} (${fmtDate(r.from)}–${fmtDate(r.to)})</td>${cell(f.candidates, p.candidates)}${cell(f.trials, p.trials)}${cell(f.regular, p.regular)}<td class="os-num">${f.results}</td><td class="os-num">${f.notes}</td><td class="os-num">${f.actions}</td></tr>`;
  });
  const idleDays = workDaysWithoutActions(14);
  const last = (STATE.log || [])[0];
  $("#os-sum-manager").innerHTML = `<div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr><th>Период</th><th>Новых кандидатов</th><th>Передано устройств</th><th>Новых постоянных</th><th>Оценок</th><th>Заметок</th><th>Действий</th></tr></thead><tbody>${rows.join(
    "",
  )}</tbody></table></div>
    <p class="card-sub" style="margin-top:10px">Последнее действие: ${last ? `${fmtDateTime(last.at)} (${esc(last.login || "—")})` : "—"} ·
    рабочих дней без действий за 14 дней: <b class="${idleDays.length > 2 ? "os-bad" : ""}">${idleDays.length}</b>
    · <button type="button" class="os-link" data-goto="activity">подробнее</button></p>`;

  $("#os-sum-table").innerHTML = outsourcersTable();
  renderPlanForm();
}

function renderPlanForm() {
  const card = $("#os-plan-card");
  card.hidden = !RIGHTS.lead;
  if (!RIGHTS.lead) return;
  const p = STATE.plan;
  const f = (name, label, v) => `<label>${label}<input type="number" min="0" name="${name}" value="${esc(v)}" /></label>`;
  $("#os-plan-form").innerHTML = `${f("candidates", "Новых кандидатов / нед.", p.candidates)}
    ${f("trials", "Передач устройств / нед.", p.trials)}
    ${f("regular", "Новых постоянных / нед.", p.regular)}
    ${f("target_min", "Цель: минимум постоянных", p.target_min)}
    ${f("target_max", "Цель: максимум", p.target_max)}
    <div class="os-form-actions"><button class="os-btn is-primary" type="submit">Сохранить план</button>
    <span class="os-status" id="os-plan-status">${p.updated_by ? `задал ${esc(p.updated_by)} · ${fmtDateTime(p.updated_at)}` : "по умолчанию"}</span></div>`;
}

// ---------- Диалоги ----------
const dlg = () => $("#os-dialog");
function openDialog(html, onMount) {
  $("#os-dialog-body").innerHTML = html;
  if (!dlg().open) dlg().showModal();
  onMount?.($("#os-dialog-body"));
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

function engineersDatalist() {
  const names = CRM?.engineers || [];
  return `<datalist id="os-engineers">${names.map((n) => `<option value="${esc(n)}"></option>`).join("")}</datalist>`;
}

function candidateFormHtml(c) {
  const v = (k) => esc(c?.[k] ?? "");
  const kindOpts = Object.entries(KINDS)
    .map(([k, l]) => `<option value="${k}" ${c?.kind === k ? "selected" : ""}>${l}</option>`)
    .join("");
  return `<h2>${c ? "Карточка кандидата" : "Новый кандидат"}</h2>
    <p class="card-sub">Нашли объявление мастера или сервиса — заведите его сюда сразу, даже если ещё не связались.</p>
    <form class="os-form" id="os-cand-form">
      <div class="os-row">
        <label class="req">Имя мастера / название сервиса<input name="name" required value="${v("name")}" /></label>
        <label>Тип<select name="kind">${kindOpts}</select></label>
      </div>
      <div class="os-row">
        <label>Контакт (телефон, Telegram)<input name="contact" value="${v("contact")}" /></label>
        <label>Ссылка на объявление<input name="source_url" value="${v("source_url")}" placeholder="olx.ua/…" /></label>
      </div>
      <div class="os-row">
        <label>Город / район<input name="area" value="${v("area")}" /></label>
        <label>Какую технику берёт<input name="devices" value="${v("devices")}" placeholder="ноутбуки, пылесосы, телефоны…" /></label>
      </div>
      <label>Условия оплаты<input name="terms" value="${v("terms")}" placeholder="процент / фикс за работу, запчасти чьи…" /></label>
      <div class="os-row">
        <label>Мастер в Gincore <span class="os-muted">(на кого назначают квитанции)</span>
          <input name="crm_engineer" list="os-engineers" value="${v("crm_engineer")}" placeholder="например: Саша Андрусяк" /></label>
        <label>Получатель выплат в кассе Gincore<input name="cash_contractor" value="${v("cash_contractor")}" placeholder="как в расходах кассы" /></label>
      </div>
      ${engineersDatalist()}
      <label>Заметки<textarea name="notes">${v("notes")}</textarea></label>
      <div class="os-form-actions">
        <button class="os-btn is-primary" type="submit">${c ? "Сохранить" : "Добавить в воронку"}</button>
        ${c ? `<button class="os-btn" type="button" data-open-cand="${c.id}">Назад</button>` : ""}
        <span class="os-status"></span>
      </div>
    </form>`;
}

function openCandidateForm(c) {
  openDialog(candidateFormHtml(c), (root) => {
    $("#os-cand-form", root).addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const data = await submitForm(e.target, (body) =>
          c ? api("PATCH", `/outsource/candidates/${c.id}`, body) : api("POST", "/outsource/candidates", body),
        );
        openCandidate(c ? c.id : data.id);
      } catch {
        /* показано в форме */
      }
    });
  });
}

function trialFormHtml(candId) {
  const opts = cands()
    .filter((c) => c.stage !== "lost")
    .sort((a, b) => a.name.localeCompare(b.name))
    .map((c) => `<option value="${c.id}" ${Number(candId) === Number(c.id) ? "selected" : ""}>${esc(c.name)} · ${STAGES[c.stage]}</option>`)
    .join("");
  const today = todayKey();
  return `<h2>Передача устройства</h2>
    <p class="card-sub">Заполните в момент передачи. Если квитанция ещё не назначена в Gincore на мастера-аутсорсера — назначьте, иначе статусы не подтянутся.</p>
    <form class="os-form" id="os-trial-form">
      <label class="req">Кому передаём<select name="candidate_id" required><option value="">— выберите —</option>${opts}</select></label>
      <div class="os-row">
        <label class="req">№ квитанции Gincore<input name="ticket" required inputmode="numeric" placeholder="124450" /></label>
        <label class="req">Источник
          <span class="os-seg">
            <label><input type="radio" name="source" value="client" checked /> клиентский</label>
            <label><input type="radio" name="source" value="donor" /> донор</label>
          </span></label>
      </div>
      <div class="os-row">
        <label class="req">Устройство<input name="device" required placeholder="Ноутбук Lenovo IdeaPad 3" /></label>
        <label class="req">Неисправность<input name="issue" required placeholder="не включается" /></label>
      </div>
      <div class="os-row">
        <label class="req">Дата передачи<input type="date" name="handed_at" value="${today}" required /></label>
        <label class="req">Обещанный срок<input type="date" name="due_at" value="${addDays(today, 3)}" required /></label>
        <label>Согласованная цена работы, грн<input name="price" inputmode="decimal" /></label>
      </div>
      <label>Комментарий<textarea name="comment" placeholder="что обсудили, нюансы"></textarea></label>
      <div class="os-form-actions"><button class="os-btn is-primary" type="submit">Сохранить передачу</button><span class="os-status"></span></div>
    </form>`;
}

function openTrialForm(candId) {
  if (!STATE) return;
  openDialog(trialFormHtml(candId), (root) => {
    $("#os-trial-form", root).addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        const data = await submitForm(e.target, (body) => api("POST", "/outsource/trials", body));
        const t = (data.trials || []).find((x) => Number(x.id) === Number(data.id));
        openCandidate(t ? t.candidate_id : e.target.candidate_id.value);
      } catch {
        /* показано в форме */
      }
    });
  });
}

function openResultForm(trial) {
  const info = ticketInfo(trial.ticket);
  openDialog(
    `<h2>Оценка пробника №${esc(trial.ticket)}</h2>
    <p class="card-sub">${esc(trial.device)} · ${esc(trial.issue)} · передан ${fmtDate(trial.handed_at)}, срок ${fmtDate(trial.due_at)}${
      info?.status ? ` · в CRM: <b>${esc(info.status)}</b>` : ""
    }</p>
    <form class="os-form" id="os-result-form">
      <label class="req">Качество работы
        <span class="os-seg">${[1, 2, 3, 4, 5]
          .map((n) => `<label><input type="radio" name="quality" value="${n}" ${n === 4 ? "checked" : ""}/> ${n}</label>`)
          .join("")}</span></label>
      <label class="os-check" style="flex-direction:row;color:var(--ink)"><input type="checkbox" name="on_time" value="1" ${
        trial.due_at >= todayKey() ? "checked" : ""
      } /> уложился в срок</label>
      <label class="req">Решение
        <span class="os-seg">${Object.entries(DECISIONS)
          .map(([k, l], i) => `<label><input type="radio" name="decision" value="${k}" ${i === 0 ? "checked" : ""}/> ${l}</label>`)
          .join("")}</span></label>
      <label>Комментарий <span class="os-muted">(обязателен при отказе)</span><textarea name="comment"></textarea></label>
      <div class="os-form-actions"><button class="os-btn is-primary" type="submit">Сохранить оценку</button>
        <button class="os-btn" type="button" data-open-cand="${trial.candidate_id}">Назад</button><span class="os-status"></span></div>
    </form>`,
    (root) => {
      $("#os-result-form", root).addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          await submitForm(e.target, (b) =>
            api("POST", `/outsource/trials/${trial.id}/result`, { ...b, quality: Number(b.quality), on_time: !!b.on_time }),
          );
          openCandidate(trial.candidate_id);
        } catch {
          /* показано в форме */
        }
      });
    },
  );
}

function openStageForm(c, stage) {
  const needReason = stage === "lost";
  openDialog(
    `<h2>${esc(c.name)}: ${STAGES[c.stage]} → ${STAGES[stage]}</h2>
    <form class="os-form" id="os-stage-form">
      <input type="hidden" name="stage" value="${stage}" />
      ${needReason ? `<label class="req">Причина отказа<input name="lost_reason" required placeholder="дорого / пропал / плохое качество…" /></label>` : ""}
      <label>Комментарий<textarea name="comment"></textarea></label>
      <div class="os-form-actions"><button class="os-btn is-primary" type="submit">Перевести</button>
        <button class="os-btn" type="button" data-open-cand="${c.id}">Назад</button><span class="os-status"></span></div>
    </form>`,
    (root) => {
      $("#os-stage-form", root).addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          await submitForm(e.target, (b) => api("POST", `/outsource/candidates/${c.id}/stage`, b));
          openCandidate(c.id);
        } catch {
          /* показано в форме */
        }
      });
    },
  );
}

function openCandidate(id) {
  const c = candById(id);
  if (!c) {
    closeDialog();
    return;
  }
  const m = crmOf(c.id);
  const trials = trialsOf(c.id).slice().reverse();
  const log = logOf(c.id);
  const nextStages = STAGE_ORDER.filter((s) => s !== c.stage);
  const contactLine = [
    c.contact ? esc(c.contact) : "",
    c.source_url ? `<a href="${esc(c.source_url)}" target="_blank" rel="noopener">объявление ↗</a>` : "",
    c.area ? esc(c.area) : "",
  ]
    .filter(Boolean)
    .join(" · ");
  let crmHtml = "";
  if (!c.crm_engineer) {
    crmHtml = `<p class="os-warn">Не привязан к мастеру Gincore — укажите в карточке, чтобы видеть устройства, возвраты и деньги.</p>`;
  } else if (!m) {
    crmHtml = `<p class="os-muted">Данных CRM пока нет — появятся после ближайшей пересборки Jarvis.</p>`;
  } else {
    const closed = m.issued + m.refusals;
    crmHtml = `<div class="os-kv">
        <div><span>В работе</span><b class="${m.in_work ? "" : "os-bad"}">${m.in_work}</b></div>
        <div><span>Готово, ждут выдачи</span><b>${m.ready}</b></div>
        <div><span>Выдано / возврат</span><b>${m.issued} / ${m.refusals}</b></div>
        <div><span>Коэф. возврата</span><b class="${m.return_rate > HIGH_RETURN && closed >= MIN_CLOSED_FOR_RATE ? "os-bad" : ""}">${pct(m.return_rate)}</b></div>
        <div><span>Вал</span><b>${money(m.gross)}</b></div>
        <div><span>Выплаты из кассы</span><b>${m.payouts_matched ? money(m.payouts) : c.cash_contractor ? "не найден" : "—"}</b></div>
        <div><span>Чистые</span><b>${m.net !== null && m.net !== undefined ? money(m.net) : "—"}</b></div>
      </div>
      <p class="card-sub" style="margin-top:6px">Мастер в CRM: ${esc((m.engineers_matched || []).join(", ") || c.crm_engineer)}
        ${m.payouts_contractor ? ` · касса: ${esc(m.payouts_contractor)}` : ""} · снимок ${CRM?.generated_at ? fmtDateTime(CRM.generated_at) : "—"}</p>
      ${
        m.in_work_orders?.length
          ? `<div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr><th>№</th><th>Устройство</th><th>Статус</th><th>Принят</th><th>Дней у мастера</th></tr></thead><tbody>${m.in_work_orders
              .map(
                (o) =>
                  `<tr><td>${o.url ? `<a href="${esc(o.url)}" target="_blank" rel="noopener">${esc(o.ticket)}</a>` : esc(o.ticket)}</td><td class="os-wrap">${esc(
                    o.device || "",
                  )}</td><td>${esc(o.status || "")}</td><td>${fmtDate(o.accepted_at)}</td><td class="${o.long ? "os-warn" : ""}">${o.days_at_master ?? "—"}</td></tr>`,
              )
              .join("")}</tbody></table></div>`
          : ""
      }
      ${
        m.by_month?.length
          ? `<h3>По месяцам</h3><div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr><th>Месяц</th><th>Квитанций</th><th>Выдано</th><th>Возврат</th><th>Вал</th><th>Выплаты</th><th>Чистые</th></tr></thead><tbody>${m.by_month
              .map(
                (r) =>
                  `<tr><td>${esc(r.month)}</td><td>${r.orders}</td><td>${r.issued}</td><td>${r.refusals}</td><td>${money(r.gross)}</td><td>${money(r.payouts)}</td><td>${r.net === null ? "—" : money(r.net)}</td></tr>`,
              )
              .join("")}</tbody></table></div>`
          : ""
      }`;
  }
  const trialsHtml = trials.length
    ? `<div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr><th>№</th><th>Устройство</th><th>Источник</th><th>Передан</th><th>Срок</th><th>CRM</th><th>Итог</th></tr></thead><tbody>${trials
        .map((t) => {
          const info = ticketInfo(t.ticket);
          const res = t.result_decision
            ? `${t.result_quality}/5 · ${t.result_on_time ? "в срок" : "не в срок"} · ${esc(DECISIONS[t.result_decision])}`
            : `<button type="button" class="os-btn is-small ${isOverdue(t) ? "is-danger" : ""}" data-result="${t.id}">Оценить${isOverdue(t) ? " (просрочен)" : ""}</button>`;
          return `<tr><td>${info?.url ? `<a href="${esc(info.url)}" target="_blank" rel="noopener">${esc(t.ticket)}</a>` : esc(t.ticket)}</td>
            <td class="os-wrap">${esc(t.device)} · ${esc(t.issue)}${t.price ? ` · ${money(t.price)}` : ""}</td>
            <td>${t.source === "donor" ? "донор" : "клиентский"}</td><td>${fmtDate(t.handed_at)}</td>
            <td class="${isOverdue(t) ? "os-bad" : ""}">${fmtDate(t.due_at)}</td>
            <td>${esc(info?.status || "—")}</td><td>${res}</td></tr>`;
        })
        .join("")}</tbody></table></div>`
    : `<p class="os-muted">Передач ещё не было.</p>`;
  const logHtml = log.length
    ? `<div class="os-timeline">${log
        .slice(0, 40)
        .map((l) => `<div><time>${fmtDateTime(l.at)}</time><b>${esc(ACTIONS[l.action] || l.action)}</b> · ${esc(l.login || "")}${l.text ? ` — ${esc(l.text)}` : ""}</div>`)
        .join("")}</div>`
    : `<p class="os-muted">Журнал пуст.</p>`;

  openDialog(
    `<h2>${esc(c.name)}</h2>
    <p class="card-sub">${esc(KINDS[c.kind] || "")} · стадия <b>${STAGES[c.stage]}</b> (${daysSince(c.stage_at) ?? "—"} дн.)${
      c.lost_reason && c.stage === "lost" ? ` · причина: ${esc(c.lost_reason)}` : ""
    }<br>${contactLine || "контакт не указан"}${c.devices ? `<br>Техника: ${esc(c.devices)}` : ""}${c.terms ? `<br>Условия: ${esc(c.terms)}` : ""}${
      c.notes ? `<br>Заметки: ${esc(c.notes)}` : ""
    }</p>
    <div class="os-form-actions">
      <button type="button" class="os-btn is-primary" data-trial-for="${c.id}" ${c.stage === "lost" ? "disabled" : ""}>Передать устройство</button>
      <button type="button" class="os-btn" data-edit="${c.id}">Редактировать</button>
      <select class="os-input" id="os-stage-select"><option value="">Перевести на стадию…</option>${nextStages
        .map((s) => `<option value="${s}">${STAGES[s]}</option>`)
        .join("")}</select>
    </div>
    <h3>CRM: устройства и деньги</h3>${crmHtml}
    <h3>Передачи устройств</h3>${trialsHtml}
    <h3>Отметить действие</h3>
    <form class="os-form os-form-inline" id="os-note-form" style="grid-template-columns:1fr auto">
      <input name="text" class="os-input" placeholder="Позвонил, договорились о пробнике на пятницу…" />
      <button class="os-btn" type="submit">Добавить в журнал</button>
      <span class="os-status"></span>
    </form>
    <h3>История</h3>${logHtml}`,
    (root) => {
      $("#os-stage-select", root).addEventListener("change", (e) => {
        if (e.target.value) openStageForm(c, e.target.value);
      });
      $("#os-note-form", root).addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          await submitForm(e.target, (b) => api("POST", `/outsource/candidates/${c.id}/note`, b));
          openCandidate(c.id);
        } catch {
          /* показано */
        }
      });
    },
  );
}

// ---------- вкладки и события ----------
const LS_TAB = "jarvis.outsource.tab";

function setTab(tab) {
  const btn = $(`.mod-tab[data-ostab="${tab}"]`);
  if (!btn || btn.hidden) tab = RIGHTS.lead ? "summary" : "funnel";
  activeTab = tab;
  $$(".mod-tab[data-ostab]").forEach((b) => b.classList.toggle("is-active", b.dataset.ostab === tab));
  $$(".os-panel").forEach((p) => (p.hidden = p.id !== `os-panel-${tab}`));
  try {
    localStorage.setItem(LS_TAB, tab);
  } catch {
    /* ignore */
  }
  renderActive();
}

function renderActive() {
  if (activeTab === "summary") renderSummary();
  else if (activeTab === "funnel") renderBoard();
  else if (activeTab === "outsourcers") renderOutsourcers();
  else if (activeTab === "activity") renderActivity();
}

function renderAll() {
  renderMeta();
  renderActive();
}

function bindEvents() {
  $$(".mod-tab[data-ostab]").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.ostab)));
  $("#os-add-cand").addEventListener("click", () => STATE && openCandidateForm(null));
  $("#os-add-trial").addEventListener("click", () => openTrialForm(null));
  $("#os-search").addEventListener("input", renderBoard);
  $("#os-show-closed").addEventListener("change", renderBoard);
  $("#os-act-period").addEventListener("change", renderActivity);
  $("#os-act-login").addEventListener("change", renderActivity);
  $("#os-plan-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const status = $("#os-plan-status");
    try {
      status.textContent = "Сохраняю…";
      const body = Object.fromEntries([...new FormData(f).entries()].map(([k, v]) => [k, Number(v)]));
      applyState(await api("PUT", "/outsource/plan", body));
      renderAll();
    } catch (err) {
      status.textContent = err.message;
      status.classList.add("is-error");
    }
  });
  // делегирование: открыть карточку, редактировать, передать, оценить, перейти на вкладку
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-open-cand],[data-edit],[data-trial-for],[data-result],[data-goto]");
    if (!t) return;
    if (t.dataset.openCand) openCandidate(t.dataset.openCand);
    else if (t.dataset.edit) openCandidateForm(candById(t.dataset.edit));
    else if (t.dataset.trialFor) openTrialForm(t.dataset.trialFor);
    else if (t.dataset.result) {
      const tr = (STATE?.trials || []).find((x) => String(x.id) === t.dataset.result);
      if (tr) openResultForm(tr);
    } else if (t.dataset.goto) setTab(t.dataset.goto);
  });
}

async function init() {
  const s = auth()?.session?.();
  if (!s) return;
  LOGIN = s.login;
  RIGHTS = {
    work: auth().hasAccess(s.access, "processes.outsource") || auth().hasAccess(s.access, "processes.outsource_lead"),
    lead: auth().hasAccess(s.access, "processes.outsource_lead"),
  };
  bindEvents();
  await loadAll();
  $(`.mod-tab[data-ostab="summary"]`).hidden = !RIGHTS.lead;
  let saved = null;
  try {
    saved = localStorage.getItem(LS_TAB);
  } catch {
    /* ignore */
  }
  setTab(saved || (RIGHTS.lead ? "summary" : "funnel"));
  // живые данные облака — обновлять раз в 2 минуты, пока страница открыта и диалог закрыт
  setInterval(async () => {
    if (document.hidden || dlg().open) return;
    await loadAll();
    renderActive();
  }, 120000);
}

document.addEventListener("DOMContentLoaded", init);
