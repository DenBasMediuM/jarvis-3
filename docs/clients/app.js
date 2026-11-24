/* Постоянные клиенты — витрина.
 * Всё (клиенты, договоры, касания, справочники, шаблоны и CRM-снимок от Jarvis) — Worker jarvis-feedback (D1),
 * по токену входа. Клиентские данные НЕ лежат в публичном репозитории витрины.
 */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const KINDS = { person: "Частная особа", fop: "ФОП", company: "Компания", shop: "Магазин", service: "Другой сервис" };
const STAGES = {
  found: "Найден",
  contacted: "Связались",
  offer: "Предложение",
  trial: "Пробный заказ",
  active: "Постоянный",
  paused: "Пауза",
  lost: "Отказ",
};
const FUNNEL = ["found", "contacted", "offer", "trial", "active"];
const OPEN_STAGES = ["found", "contacted", "offer", "trial"];
const SOURCES = { crm: "Из базы CRM", cold: "Холодный поиск", referral: "Рекомендация", inbound: "Сам обратился", other: "Другое" };
const CHANNELS = { call: "Звонок", message: "Мессенджер", email: "Email", meeting: "Встреча", visit: "Визит в СЦ", other: "Другое" };
const CONTRACT_ST = { draft: "Черновик", signing: "На подписи", active: "Действует", terminated: "Расторгнут" };
const UNITS = { pct: "%", days: "дн.", uah: "грн", months: "мес.", bool: "да/нет", text: "текст" };
const AUTO = { "": "вручную", repair_days: "срок ремонта", diag_days: "срок диагностики", debt_limit: "лимит долга", pay_delay: "отсрочка оплаты" };
const ACTIONS = {
  client_created: "Новый клиент",
  client_updated: "Правка карточки",
  stage_changed: "Смена стадии",
  touch: "Касание",
  contract_created: "Новый договор",
  contract_updated: "Договор изменён",
  candidate_taken: "Взят из базы",
  candidate_dismissed: "Кандидат: не постоянный",
  candidate_snoozed: "Кандидат отложен",
  conditions_saved: "Справочник условий",
  template_saved: "Шаблон договора",
  settings_saved: "Настройки",
};
const STUCK_DAYS = 10; // воронка без движения
const DROP = -0.3; // падение вала за 90 дней
const TEMPLATE_KINDS = { legal: "Юрособа / ФОП", person: "Фізична особа" };
const DEFAULT_SUBJECT = "50310000-1 — Технічне обслуговування і ремонт офісної техніки";
const TEMPLATE_FIELDS = {
  "номер_договору": "номер договора",
  "дата_договору": "дата договора",
  "місто": "город (настройки)",
  "строк_дії_до": "договор действует до",
  "предмет_дк": "предмет по коду ДК 021 (в договоре)",
  "ціна_договору": "цена договора, грн",
  "ціна_прописом": "цена договора прописью",
  "строк_оплати": "срок оплаты, раб. дней (условие «Отсрочка», иначе 10)",
  "виконавець_назва": "мы — коротко (ФОП Прізвище І.Б.)",
  "виконавець_повна_назва": "мы — полностью",
  "виконавець_підписант": "кто подписывает от нас (в особі …)",
  "виконавець_підстава": "на основании чего действуем",
  "виконавець_код": "наш ІПН/ЄДРПОУ",
  "виконавець_адреса": "наш адрес",
  "виконавець_iban": "наш IBAN",
  "виконавець_банк": "наш банк",
  "виконавець_мфо": "МФО нашего банка",
  "виконавець_єдрпоу_банку": "ЄДРПОУ нашего банка",
  "виконавець_телефон": "наш телефон",
  "виконавець_email": "наш email",
  "клієнт_назва": "клиент (полное название / ПІБ)",
  "клієнт_підписант": "подписант клиента (в особі …)",
  "клієнт_підстава": "клиент действует на основании (Статуту…)",
  "клієнт_код": "ЄДРПОУ / ІПН клиента",
  "клієнт_адреса": "адрес клиента",
  "клієнт_iban": "счёт клиента",
  "клієнт_банк": "банк клиента",
  "клієнт_мфо": "МФО банка клиента",
  "клієнт_телефон": "телефоны клиента",
  "клієнт_email": "email клиента",
  "строк_діагностики": "срок диагностики (из условий, иначе 3)",
  "строк_ремонту": "срок ремонта (из условий, иначе 14)",
  "гарантія": "гарантия, мес. (из условий, иначе 3)",
  "індивідуальні_умови": "список индивидуальных условий клиента",
};

let STATE = null;
let RIGHTS = { work: false, lead: false };
let LOGIN = "";
let activeTab = null;
let tplKind = "legal";

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
function pctSigned(v) {
  if (v === null || v === undefined) return "—";
  const n = Math.round(Number(v) * 100);
  return `${n > 0 ? "+" : ""}${n}%`;
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
function daysBetween(a, b) {
  return Math.round((Date.parse(`${b}T12:00:00`) - Date.parse(`${a}T12:00:00`)) / 86400000);
}
function daysSince(iso) {
  if (!iso) return null;
  const t = Date.parse(iso.length <= 10 ? `${iso}T12:00:00` : iso);
  return Number.isNaN(t) ? null : Math.max(0, Math.floor((Date.now() - t) / 86400000));
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
function normPhone(v) {
  const d = String(v ?? "").replace(/\D/g, "");
  return d.length >= 10 ? d.slice(-10) : d;
}
function fmtPhone(p) {
  const d = normPhone(p);
  return d.length === 10 ? `+38 ${d.slice(0, 3)} ${d.slice(3, 6)} ${d.slice(6, 8)} ${d.slice(8)}` : String(p || "");
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

function applyReadonly() {
  const ro = !RIGHTS.work;
  document.body.classList.toggle("is-readonly", ro);
  const h = document.querySelector(".mod-sub");
  if (h && ro && !h.querySelector(".ro-note")) h.insertAdjacentHTML("beforeend", '<span class="ro-note">режим просмотра</span>');
}

function applyState(data) {
  STATE = {
    clients: data.clients || [],
    contracts: data.contracts || [],
    log: data.log || [],
    decisions: data.decisions || [],
    conditions: data.conditions || [],
    settings: data.settings || {},
    plan: data.plan || {},
    templates: data.templates || {},
    defaults: data.defaults || null,
    crm: data.crm || null,
    now: data.now,
  };
  if (data.rights) RIGHTS = data.rights;
  applyReadonly();
  if (data.login) LOGIN = data.login;
}

async function loadAll() {
  const banner = $("#cl-banner");
  try {
    applyState(await api("GET", "/clients/state"));
    banner.hidden = true;
  } catch (err) {
    STATE = null;
    banner.hidden = false;
    banner.textContent =
      err.status === 401 || err.code === "no_token"
        ? "Сессия облака истекла — выйдите и войдите на витрину заново."
        : err.status === 403
          ? "Нет доступа к разделу — попросите выдать «Постоянные клиенты» в Jarvis."
          : `Нет связи с облаком (${err.message}).`;
  }
  renderMeta();
}

function renderMeta() {
  const parts = [];
  const crm = STATE?.crm;
  parts.push(crm?.generated_at ? `CRM-снимок: ${fmtDateTime(crm.generated_at)}` : "CRM-снимка ещё нет");
  if (STATE) parts.push(`облако: ${fmtDateTime(STATE.now)}`);
  $("#cl-meta").textContent = parts.join(" · ");
  const n = openCandidates().length;
  $("#cl-cand-count").textContent = n ? `(${n})` : "";
}

// ---------- производные ----------
const clients = () => STATE?.clients || [];
const clientById = (id) => clients().find((c) => Number(c.id) === Number(id));
const crmOf = (id) => STATE?.crm?.clients?.[String(id)] || null;
const contractsOf = (id) => (STATE?.contracts || []).filter((c) => Number(c.client_id) === Number(id));
const logOf = (id) => (STATE?.log || []).filter((l) => Number(l.client_id) === Number(id));
const catalog = () => STATE?.conditions || [];
const condById = (id) => catalog().find((c) => c.id === id);
const settings = () => STATE?.settings || {};

function currentContract(id) {
  const t = todayKey();
  const list = contractsOf(id).filter((c) => c.status !== "terminated");
  const active = list.filter((c) => c.status === "active").sort((a, b) => String(b.valid_to || "").localeCompare(String(a.valid_to || "")));
  return active.find((c) => !c.valid_to || c.valid_to >= t) || active[0] || list.sort((a, b) => b.id - a.id)[0] || null;
}
function contractState(c) {
  if (!c) return { key: "none", label: "нет договора" };
  const t = todayKey();
  if (c.status === "terminated") return { key: "terminated", label: "расторгнут" };
  if (c.status !== "active") return { key: c.status, label: CONTRACT_ST[c.status] };
  if (!c.valid_to) return { key: "active", label: "действует" };
  const left = daysBetween(t, c.valid_to);
  if (left < 0) return { key: "expired", label: `истёк ${fmtDate(c.valid_to)}`, left };
  if (left <= 30) return { key: "expiring", label: `истекает через ${left} дн.`, left };
  return { key: "active", label: `до ${fmtDate(c.valid_to)}`, left };
}

function openCandidates() {
  const list = STATE?.crm?.candidates || [];
  const known = new Set(clients().flatMap((c) => c.phones || []));
  const t = todayKey();
  const dec = new Map((STATE?.decisions || []).map((d) => [d.phone, d]));
  return list.filter((c) => {
    if (known.has(c.phone)) return false;
    const d = dec.get(c.phone);
    if (!d) return true;
    if (d.decision === "snoozed") return String(d.until || "") <= t;
    return false;
  });
}

/** Проверка условий клиента по CRM-снимку + ручные отметки. */
function checkConditions(c) {
  const m = crmOf(c.id);
  const out = [];
  for (const [id, v] of Object.entries(c.conditions || {})) {
    const cond = condById(id);
    if (!cond) continue;
    const num = Number(String(v.value || "").replace(",", "."));
    let ok = null;
    let detail = "";
    if (cond.auto && m && Number.isFinite(num) && num > 0) {
      if (cond.auto === "repair_days") {
        const late = (m.in_work || []).filter((o) => !o.diag && !o.ready && (o.days || 0) > num);
        ok = late.length === 0;
        detail = ok ? "все заказы в срок" : `${late.length} заказ(ов) дольше ${num} дн.: ${late.map((o) => `№${o.ticket} (${o.days} дн.)`).join(", ")}`;
      } else if (cond.auto === "diag_days") {
        const late = (m.in_work || []).filter((o) => o.diag && (o.days || 0) > num);
        ok = late.length === 0;
        detail = ok ? "диагностика в срок" : `на диагностике дольше ${num} дн.: ${late.map((o) => `№${o.ticket} (${o.days} дн.)`).join(", ")}`;
      } else if (cond.auto === "debt_limit") {
        ok = (m.debt || 0) <= num;
        detail = `долг ${money(m.debt || 0)}`;
      } else if (cond.auto === "pay_delay") {
        const late = (m.debt_orders || []).filter((o) => (o.days || 0) > num);
        ok = late.length === 0;
        detail = ok ? "просрочек оплаты нет" : `не оплачено дольше ${num} дн.: ${late.map((o) => `№${o.ticket} ${money(o.due)}`).join(", ")}`;
      }
    } else if (v.status) {
      ok = v.status === "ok";
      detail = v.note || (ok ? "соблюдается (отметка менеджера)" : "нарушено (отметка менеджера)");
    }
    out.push({ cond, value: v.value, ok, detail, auto: !!cond.auto && !!m });
  }
  return out;
}

function condValueLabel(cond, value) {
  if (cond.unit === "bool") return "да";
  const u = UNITS[cond.unit];
  return cond.unit === "text" ? String(value || "") : `${value} ${u}`;
}

/** Тревоги «Что сделать сейчас». */
function computeAlerts() {
  if (!STATE) return [];
  const t = todayKey();
  const touchEvery = Number(settings().touch_every_days || 30);
  const out = [];
  const push = (level, c, text, sort = 0) => out.push({ level, client: c, text, sort });
  for (const c of clients()) {
    if (c.stage === "lost" || c.stage === "paused") continue;
    const m = crmOf(c.id);
    if (!c.next_step_at) push("warn", c, "нет следующего шага", 1);
    else if (c.next_step_at < t) push("bad", c, `просрочен шаг «${c.next_step || "—"}» (${fmtDate(c.next_step_at)})`, 3);
    else if (c.next_step_at === t) push("warn", c, `сегодня: ${c.next_step || "шаг"}`, 2);
    if (c.stage === "active") {
      const ct = currentContract(c.id);
      const st = contractState(ct);
      if (st.key === "expired") push("bad", c, `договор ${ct.number || "б/н"} ${st.label}`, 4);
      else if (st.key === "expiring") push(st.left <= 14 ? "bad" : "warn", c, `договор ${ct.number || "б/н"} ${st.label}`, 3);
      else if (st.key === "none" && c.kind !== "person") push("warn", c, "постоянный клиент без договора", 1);
      const last = c.last_touch_at ? daysSince(c.last_touch_at) : daysSince(c.created_at);
      if (last !== null && last > touchEvery) push("warn", c, `не было касания ${last} дн.`, 1);
      if (m?.asleep) push("bad", c, `«заснул»: не заказывает ${m.days_since_last} дн. (обычно раз в ${Math.round(m.avg_interval)} дн.)`, 3);
      if (m && m.trend !== null && m.trend <= DROP && (m.gross_prev_90 || 0) >= 2000) {
        push("warn", c, `вал упал на ${Math.round(-m.trend * 100)}% к прошлым 90 дням`, 2);
      }
      if (c.phones?.length && m && !m.phones_matched?.length) push("warn", c, "по телефонам нет заказов в CRM — проверьте номера", 0);
    }
    if (OPEN_STAGES.includes(c.stage)) {
      const d = daysSince(c.stage_at);
      if (d !== null && d > STUCK_DAYS) push("warn", c, `${d} дн. на стадии «${STAGES[c.stage]}»`, 1);
    }
    for (const r of checkConditions(c)) {
      if (r.ok === false) push("bad", c, `нарушено «${r.cond.name}»: ${r.detail}`, 4);
    }
  }
  out.sort((a, b) => (a.level === b.level ? b.sort - a.sort : a.level === "bad" ? -1 : 1));
  const n = openCandidates().length;
  if (n) out.unshift({ level: "warn", client: null, text: `кандидатов из базы не разобрано: ${n}`, goto: "candidates", sort: 9 });
  return out;
}

function alertsHtml(list, empty = "Всё в порядке") {
  if (!list.length) return `<p class="os-muted">${empty}</p>`;
  return `<ul class="os-list">${list
    .map(
      (a) => `<li class="os-alert is-${a.level}"><span>${a.level === "bad" ? "●" : "○"}</span><span>${
        a.client ? `<b>${esc(a.client.name)}</b>: ` : ""
      }${esc(a.text)} · ${
        a.client
          ? `<button class="os-link" data-open="${a.client.id}">открыть</button>`
          : `<button class="os-link" data-goto="${a.goto}">разобрать</button>`
      }</span></li>`,
    )
    .join("")}</ul>`;
}

// ---------- период / план-факт ----------
function periodRange(kind) {
  const t = todayKey();
  if (kind === "prev") {
    const ws = addDays(weekStart(t), -7);
    return { from: ws, to: addDays(ws, 6), label: "прошлая неделя", weeks: 1 };
  }
  if (kind === "30") return { from: addDays(t, -29), to: t, label: "30 дней", weeks: 30 / 7 };
  return { from: weekStart(t), to: t, label: "эта неделя", weeks: 1 };
}
function inRange(iso, r) {
  const k = dayKey(iso);
  return k >= r.from && k <= r.to;
}
function factFor(r) {
  const log = (STATE?.log || []).filter((l) => inRange(l.at, r));
  return {
    log,
    candidates: log.filter((l) => /^candidate_/.test(l.action)).length,
    new_clients: log.filter((l) => l.action === "client_created" || l.action === "candidate_taken").length,
    touches: log.filter((l) => l.action === "touch").length,
    contracts: log.filter(
      (l) => (l.action === "contract_created" && /Действует/.test(l.text || "")) || (l.action === "contract_updated" && /→ Действует|срок до/.test(l.text || "")),
    ).length,
    regular: log.filter((l) => l.action === "stage_changed" && /→ Постоянный/.test(l.text || "")).length,
  };
}

// ---------- Клиенты ----------
function matches(c, q) {
  if (!q) return true;
  const s = q.toLowerCase();
  const hay = [c.name, c.area, c.devices, c.notes, ...(c.phones || []), ...(c.contacts || []).map((x) => `${x.name} ${x.phone}`)]
    .join(" ")
    .toLowerCase();
  return hay.includes(s) || (normPhone(q).length >= 5 && (c.phones || []).some((p) => p.includes(normPhone(q))));
}

function renderClients() {
  if (!STATE) {
    $("#cl-table").innerHTML = `<p class="os-muted">Нет связи с облаком.</p>`;
    $("#cl-todo").innerHTML = "";
    return;
  }
  const alerts = computeAlerts();
  $("#cl-todo").innerHTML = alerts.length
    ? `<div class="os-todo-card"><h3>Что сделать сейчас (${alerts.length})</h3>${alertsHtml(alerts.slice(0, 15))}${
        alerts.length > 15 ? `<p class="os-muted">и ещё ${alerts.length - 15}…</p>` : ""
      }</div>`
    : "";
  const q = $("#cl-search").value.trim();
  const f = $("#cl-stage-filter").value;
  const order = ["active", "trial", "offer", "contacted", "found", "paused", "lost"];
  const list = clients()
    .filter((c) => matches(c, q))
    .filter((c) =>
      f === "active" ? c.stage === "active" : f === "funnel" ? OPEN_STAGES.includes(c.stage) : f === "all" ? true : !["paused", "lost"].includes(c.stage),
    )
    .sort((a, b) => order.indexOf(a.stage) - order.indexOf(b.stage) || String(a.name).localeCompare(String(b.name)));
  const badByClient = new Map();
  for (const a of alerts) if (a.client) badByClient.set(a.client.id, (badByClient.get(a.client.id) || 0) + (a.level === "bad" ? 1 : 0));
  const t = todayKey();
  $("#cl-table").innerHTML = list.length
    ? `<div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr>
        <th>Клиент</th><th>Стадия</th><th>Договор</th><th>Заказов 90 дн.</th><th>Вал 90 дн.</th><th>Тренд</th>
        <th>Последний заказ</th><th>Долг</th><th>В работе</th><th>Следующий шаг</th></tr></thead><tbody>${list
        .map((c) => {
          const m = crmOf(c.id);
          const st = contractState(currentContract(c.id));
          const stCls = st.key === "expired" ? "os-bad" : st.key === "expiring" ? "os-warn" : st.key === "active" ? "os-good" : "os-muted";
          const late = c.next_step_at && c.next_step_at < t;
          const bad = badByClient.get(c.id) || 0;
          return `<tr>
            <td class="os-wrap"><button class="os-link" data-open="${c.id}">${esc(c.name)}</button>${bad ? ` <span class="os-tag is-bad">${bad}</span>` : ""}<br><small class="os-muted">${esc(KINDS[c.kind] || "")}</small></td>
            <td>${esc(STAGES[c.stage] || c.stage)}</td>
            <td class="${stCls}">${esc(st.label)}</td>
            <td class="os-num">${m ? m.orders_90 : "—"}</td>
            <td class="os-num">${m ? money(m.gross_90) : "—"}</td>
            <td class="os-num ${m?.trend != null && m.trend <= DROP ? "os-bad" : m?.trend > 0.1 ? "os-good" : ""}">${m ? pctSigned(m.trend) : "—"}</td>
            <td class="${m?.asleep ? "os-bad" : ""}">${m?.last_order_at ? `${fmtDate(m.last_order_at)}${m.asleep ? " · заснул" : ""}` : "—"}</td>
            <td class="os-num ${m?.debt ? "os-warn" : ""}">${m?.debt ? money(m.debt) : "—"}</td>
            <td class="os-num">${m ? (m.in_work || []).length : "—"}</td>
            <td class="os-wrap ${late ? "os-bad" : ""}">${c.next_step ? `${esc(c.next_step)} · ${fmtDate(c.next_step_at)}` : '<span class="os-muted">не задан</span>'}</td>
          </tr>`;
        })
        .join("")}</tbody></table></div>`
    : `<p class="os-muted">Клиентов нет. Заведите первого или возьмите из вкладки «Кандидаты из базы».</p>`;
}

// ---------- Кандидаты ----------
function renderCandidates() {
  const box = $("#cl-cand-list");
  if (!STATE) {
    box.innerHTML = `<p class="os-muted">Нет связи с облаком.</p>`;
    return;
  }
  const crm = STATE.crm;
  const th = settings().thresholds || {};
  $("#cl-cand-sub").textContent =
    `Клиенты, которые часто обращаются в последнее время и ещё не заведены в раздел: от ${th.orders || 4} заказов за ${th.months || 6} мес., ` +
    `или от ${th.recent_orders || 3} за ${th.recent_days || 60} дн.${th.gross ? `, или вал от ${money(th.gross)}` : ""}. ` +
    `${crm?.generated_at ? `Снимок CRM: ${fmtDateTime(crm.generated_at)}.` : "Снимка CRM ещё нет — его делает Jarvis при утренней пересборке."}`;
  const q = $("#cl-cand-search").value.trim().toLowerCase();
  const onlyB2b = $("#cl-cand-b2b").checked;
  const list = openCandidates().filter(
    (c) =>
      (!onlyB2b || c.b2b) &&
      (!q || `${c.name} ${c.phone} ${(c.devices || []).join(" ")}`.toLowerCase().includes(q) || (normPhone(q).length >= 5 && c.phone.includes(normPhone(q)))),
  );
  box.innerHTML = list.length
    ? list
        .map(
          (c) => `<div class="cl-cand">
        <div class="cl-cand-head">
          <span><span class="cl-cand-name">${esc(c.name || "Без имени")}</span> · <span class="os-muted">${esc(fmtPhone(c.phone))}</span>
            ${c.b2b ? '<span class="os-tag is-ok">похоже на компанию</span>' : ""}</span>
          <span class="os-muted">оценка ${c.score}</span>
        </div>
        <div class="os-tags">${(c.reasons || []).map((r) => `<span class="os-tag">${esc(r)}</span>`).join("")}</div>
        ${c.devices?.length ? `<div class="os-card-meta">Техника: ${esc(c.devices.join(", "))}</div>` : ""}
        <div class="cl-tickets">${(c.tickets || [])
          .map((t) => `${t.url ? `<a href="${esc(t.url)}" target="_blank" rel="noopener">№${esc(t.ticket)}</a>` : `№${esc(t.ticket)}`} ${fmtDate(t.date)} · ${esc(t.device || "")} · ${esc(t.status || "")}`)
          .map((x) => `<span>${x}</span>`)
          .join("")}</div>
        <div class="cl-cand-actions" data-write>
          <button class="os-btn is-primary is-small" data-take="${esc(c.phone)}">Взять в работу</button>
          <button class="os-btn is-small" data-dismiss="${esc(c.phone)}">Не постоянный</button>
          <button class="os-btn is-small" data-snooze="${esc(c.phone)}">Отложить</button>
        </div>
      </div>`,
        )
        .join("")
    : `<p class="os-muted">${(crm?.candidates || []).length ? "Все кандидаты разобраны." : "Кандидатов нет."}</p>`;
}
const candByPhone = (p) => (STATE?.crm?.candidates || []).find((c) => c.phone === p);

function openTakeForm(phone) {
  const c = candByPhone(phone);
  if (!c) return;
  const kindOpts = Object.entries(KINDS)
    .map(([k, l]) => `<option value="${k}" ${k === (c.b2b ? "company" : "person") ? "selected" : ""}>${l}</option>`)
    .join("");
  openDialog(
    `<h2>Взять в работу</h2>
    <p class="card-sub">${esc(fmtPhone(c.phone))} · ${esc((c.reasons || []).join(" · "))}</p>
    <form class="os-form" id="cl-take-form">
      <div class="os-row">
        <label class="req">Имя / название<input name="name" required value="${esc(c.name || "")}" /></label>
        <label>Тип<select name="kind">${kindOpts}</select></label>
      </div>
      <label>Какую технику сдаёт<input name="devices" value="${esc((c.devices || []).join(", "))}" /></label>
      <div class="os-form-actions"><button class="os-btn is-primary" type="submit">Завести клиента</button><span class="os-status"></span></div>
    </form>`,
    (root) => {
      $("#cl-take-form", root).addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          const data = await submitForm(e.target, (b) =>
            api("POST", "/clients/candidates/take", { ...b, phone: c.phone, notes: `Из базы CRM: ${(c.reasons || []).join(", ")}` }),
          );
          openClient(data.id);
        } catch {
          /* в форме */
        }
      });
    },
  );
}

function openDecisionForm(phone, decision) {
  const c = candByPhone(phone);
  if (!c) return;
  const dismiss = decision === "dismissed";
  openDialog(
    `<h2>${dismiss ? "Не постоянный" : "Отложить"}: ${esc(c.name || fmtPhone(c.phone))}</h2>
    <form class="os-form" id="cl-dec-form">
      ${
        dismiss
          ? `<label class="req">Почему<input name="reason" required placeholder="разовые обращения, родственник сотрудника, перекупщик…" /></label>`
          : `<label>На сколько<select name="days"><option value="30">30 дней</option><option value="60">60 дней</option><option value="90">90 дней</option></select></label>
             <label>Комментарий<input name="reason" /></label>`
      }
      <div class="os-form-actions"><button class="os-btn is-primary" type="submit">${dismiss ? "Больше не предлагать" : "Отложить"}</button><span class="os-status"></span></div>
    </form>`,
    (root) => {
      $("#cl-dec-form", root).addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          await submitForm(e.target, (b) => api("POST", "/clients/candidates/decision", { ...b, phone: c.phone, decision, name: c.name }));
          closeDialog();
        } catch {
          /* в форме */
        }
      });
    },
  );
}

// ---------- Воронка ----------
function renderBoard() {
  const board = $("#cl-board");
  if (!STATE) {
    board.innerHTML = `<p class="os-muted">Нет связи с облаком.</p>`;
    return;
  }
  const col = (st) => {
    const list = clients()
      .filter((c) => c.stage === st)
      .sort((a, b) => String(b.stage_at).localeCompare(String(a.stage_at)));
    return `<div class="os-col"><div class="os-col-head">${STAGES[st]} <span>${list.length}</span></div><div class="os-cards">${
      list
        .map((c) => {
          const m = crmOf(c.id);
          const tags = [`<span class="os-tag">${esc(KINDS[c.kind] || c.kind)}</span>`];
          if (c.source === "crm") tags.push('<span class="os-tag">из базы</span>');
          if (m?.orders_90) tags.push(`<span class="os-tag is-ok">${m.orders_90} зак. / 90 дн.</span>`);
          if (m?.asleep) tags.push('<span class="os-tag is-bad">заснул</span>');
          if (c.next_step_at && c.next_step_at < todayKey()) tags.push('<span class="os-tag is-bad">шаг просрочен</span>');
          return `<button type="button" class="os-card" data-open="${c.id}">
            <span class="os-card-name">${esc(c.name)}</span>
            <span class="os-card-meta">на стадии ${daysSince(c.stage_at) ?? "—"} дн.${st === "lost" && c.lost_reason ? ` · ${esc(c.lost_reason)}` : ""}</span>
            ${c.next_step ? `<span class="os-card-meta">→ ${esc(c.next_step)} · ${fmtDate(c.next_step_at)}</span>` : ""}
            <span class="os-tags">${tags.join("")}</span>
          </button>`;
        })
        .join("") || `<p class="os-muted os-col-empty">пусто</p>`
    }</div></div>`;
  };
  board.innerHTML =
    `<div class="os-board-main is-5">${FUNNEL.map(col).join("")}</div>` +
    ($("#cl-show-closed").checked ? `<div class="os-board-closed">${["paused", "lost"].map(col).join("")}</div>` : "");
}

// ---------- Договоры ----------
function renderContracts() {
  const box = $("#cl-contracts");
  if (!STATE) {
    box.innerHTML = `<p class="os-muted">Нет связи с облаком.</p>`;
    return;
  }
  const rank = (c) => {
    const st = contractState(c);
    return st.key === "expired" ? 0 : st.key === "expiring" ? 1 : c.status === "signing" ? 2 : c.status === "draft" ? 3 : c.status === "active" ? 4 : 5;
  };
  const list = [...(STATE.contracts || [])].sort((a, b) => rank(a) - rank(b) || String(a.valid_to || "").localeCompare(String(b.valid_to || "")));
  box.innerHTML = list.length
    ? `<div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr><th>Клиент</th><th>№</th><th>Вид</th><th>Статус</th><th>Действует</th><th>Срок</th><th></th></tr></thead><tbody>${list
        .map((c) => {
          const cl = clientById(c.client_id);
          const st = contractState(c);
          const cls = st.key === "expired" ? "os-bad" : st.key === "expiring" ? "os-warn" : "";
          return `<tr>
            <td>${cl ? `<button class="os-link" data-open="${cl.id}">${esc(cl.name)}</button>` : "—"}</td>
            <td>${esc(c.number || "б/н")}</td>
            <td>${esc(TEMPLATE_KINDS[c.kind] || c.kind)}</td>
            <td>${esc(CONTRACT_ST[c.status] || c.status)}</td>
            <td>${fmtDate(c.valid_from)} — ${fmtDate(c.valid_to)}</td>
            <td class="${cls}">${esc(st.label)}</td>
            <td><button class="os-btn is-small" data-contract="${c.id}">Открыть</button>${c.file_url ? ` <a class="os-link" href="${esc(c.file_url)}" target="_blank" rel="noopener">скан</a>` : ""}</td>
          </tr>`;
        })
        .join("")}</tbody></table></div>`
    : `<p class="os-muted">Договоров ещё нет. Договор создаётся из карточки клиента.</p>`;
}

// ---------- Активность ----------
function renderActivity() {
  if (!STATE) {
    $("#cl-act-kpis").innerHTML = "";
    return;
  }
  const r = periodRange($("#cl-act-period").value);
  const f = factFor(r);
  const plan = STATE.plan || {};
  const k = r.weeks;
  const kpi = (label, val, planV) => {
    const p = planV ? Math.round(planV * k) : 0;
    return `<div class="kpi"><span class="kpi-label">${esc(label)}</span>
      <span class="kpi-value ${p ? (val >= p ? "os-good" : "os-bad") : ""}">${val}${p ? ` <span class="os-muted" style="font-size:.9rem">/ ${p}</span>` : ""}</span>
      <span class="kpi-sub">${p ? "факт / план" : r.label}</span></div>`;
  };
  $("#cl-act-kpis").innerHTML = [
    kpi("Разобрано кандидатов", f.candidates, plan.candidates),
    kpi("Новых клиентов в работе", f.new_clients, plan.new_clients),
    kpi("Касаний", f.touches, plan.touches),
    kpi("Договоров оформлено / продлено", f.contracts, plan.contracts),
    kpi("Новых постоянных", f.regular, 0),
    kpi("Всего действий", f.log.length, 0),
  ].join("");
  const t = todayKey();
  const byDay = {};
  for (const l of STATE.log || []) byDay[dayKey(l.at)] = (byDay[dayKey(l.at)] || 0) + 1;
  const days = [];
  for (let i = 27; i >= 0; i--) days.push(addDays(t, -i));
  const max = Math.max(1, ...days.map((d) => byDay[d] || 0));
  $("#cl-act-days").innerHTML = `<div class="os-days">${days
    .map((d) => {
      const n = byDay[d] || 0;
      const off = new Date(`${d}T12:00:00`).getDay() === 0;
      return `<div class="os-day ${n ? "" : off ? "is-off" : "is-zero"}" style="height:${n ? Math.max(6, (n / max) * 100) : 6}%" title="${fmtDate(d)}: ${n}"></div>`;
    })
    .join("")}</div><div class="os-days-legend"><span>${fmtDate(days[0])}</span><span>розовый — рабочий день без действий</span><span>${fmtDate(t)}</span></div>`;
  $("#cl-act-log").innerHTML = f.log.length
    ? `<div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr><th>Когда</th><th>Кто</th><th>Действие</th><th>Клиент</th><th>Детали</th></tr></thead><tbody>${f.log
        .map((l) => {
          const c = clientById(l.client_id);
          return `<tr><td>${fmtDateTime(l.at)}</td><td>${esc(l.login || "")}</td><td>${esc(ACTIONS[l.action] || l.action)}</td>
            <td>${c ? `<button class="os-link" data-open="${c.id}">${esc(c.name)}</button>` : "—"}</td><td class="os-wrap">${esc(l.text || "")}</td></tr>`;
        })
        .join("")}</tbody></table></div>`
    : `<p class="os-muted">За период действий нет.</p>`;
}

// ---------- Сводка руководителя ----------
function renderSummary() {
  if (!STATE) return;
  const act = clients().filter((c) => c.stage === "active");
  const withContract = act.filter((c) => ["active", "expiring"].includes(contractState(currentContract(c.id)).key)).length;
  const gross = act.reduce((s, c) => s + (crmOf(c.id)?.gross_90 || 0), 0);
  const total = STATE.crm?.totals?.gross_90 || 0;
  const asleep = act.filter((c) => crmOf(c.id)?.asleep).length;
  const kpi = (label, val, sub) => `<div class="kpi"><span class="kpi-label">${esc(label)}</span><span class="kpi-value">${val}</span><span class="kpi-sub">${esc(sub)}</span></div>`;
  $("#cl-sum-kpis").innerHTML = [
    kpi("Постоянных клиентов", act.length, `с действующим договором: ${withContract}`),
    kpi("В воронке", clients().filter((c) => OPEN_STAGES.includes(c.stage)).length, "найден → пробный заказ"),
    kpi("Вал постоянных, 90 дн.", money(gross), total ? `${Math.round((gross / total) * 1000) / 10}% общего вала` : "нет снимка CRM"),
    kpi("«Заснули»", asleep, "не заказывают дольше обычного"),
    kpi("Кандидатов из базы", openCandidates().length, "ждут разбора"),
    kpi("Тревог", computeAlerts().filter((a) => a.level === "bad").length, "красных в «Что сделать»"),
  ].join("");
  // воронка: сколько когда-либо доходило до стадии (по журналу) + текущие
  const reached = {};
  FUNNEL.forEach((s) => (reached[s] = new Set()));
  const idx = (s) => FUNNEL.indexOf(s);
  for (const c of clients()) {
    const cur = c.stage === "paused" || c.stage === "lost" ? null : c.stage;
    if (cur) FUNNEL.slice(0, idx(cur) + 1).forEach((s) => reached[s].add(c.id));
    reached.found.add(c.id);
  }
  for (const l of STATE.log || []) {
    if (l.action !== "stage_changed" || !l.client_id) continue;
    const m = /→ ([^:·(]+)/.exec(l.text || "");
    const st = m && Object.keys(STAGES).find((k) => STAGES[k] === m[1].trim());
    if (st && idx(st) >= 0) FUNNEL.slice(0, idx(st) + 1).forEach((s) => reached[s].add(l.client_id));
  }
  const maxN = Math.max(1, reached.found.size);
  $("#cl-sum-funnel").innerHTML = `<div class="os-funnel">${FUNNEL.map((s, i) => {
    const n = reached[s].size;
    const prev = i ? reached[FUNNEL[i - 1]].size : 0;
    return `<div class="os-funnel-row"><span>${STAGES[s]}</span><div class="os-funnel-bar" style="width:${(n / maxN) * 100}%"></div>
      <span class="os-num">${n}${i && prev ? ` <span class="os-muted">${Math.round((n / prev) * 100)}% от пред.</span>` : ""}</span></div>`;
  }).join("")}</div><p class="os-muted" style="margin-top:8px">Отказ: ${clients().filter((c) => c.stage === "lost").length} · пауза: ${
    clients().filter((c) => c.stage === "paused").length
  }</p>`;
  $("#cl-sum-alerts").innerHTML = alertsHtml(computeAlerts().slice(0, 12));
  const withTrend = act.map((c) => ({ c, m: crmOf(c.id) })).filter((x) => x.m && x.m.trend !== null);
  const up = [...withTrend].sort((a, b) => b.m.trend - a.m.trend).slice(0, 5);
  const down = [...withTrend].sort((a, b) => a.m.trend - b.m.trend).filter((x) => x.m.trend < 0).slice(0, 5);
  const row = (x) => `<li><button class="os-link" data-open="${x.c.id}">${esc(x.c.name)}</button> — <span class="${x.m.trend < 0 ? "os-bad" : "os-good"}">${pctSigned(
    x.m.trend,
  )}</span> <span class="os-muted">(${money(x.m.gross_90)} против ${money(x.m.gross_prev_90)})</span></li>`;
  $("#cl-sum-trend").innerHTML = withTrend.length
    ? `<p><b>Растут</b></p><ul>${up.map(row).join("")}</ul><p><b>Падают</b></p><ul>${down.map(row).join("") || '<li class="os-muted">нет</li>'}</ul>`
    : `<p class="os-muted">Нет данных (нужен снимок CRM и заказы за полгода).</p>`;
  const soon = (STATE.contracts || [])
    .filter((c) => c.status === "active" && c.valid_to)
    .sort((a, b) => String(a.valid_to).localeCompare(String(b.valid_to)))
    .slice(0, 8);
  $("#cl-sum-contracts").innerHTML = soon.length
    ? `<ul class="os-list">${soon
        .map((c) => {
          const st = contractState(c);
          const cl = clientById(c.client_id);
          return `<li class="os-alert ${st.key === "expired" ? "is-bad" : st.key === "expiring" ? "is-warn" : ""}">${cl ? `<b>${esc(cl.name)}</b>` : "—"} · №${esc(c.number || "б/н")} · ${esc(st.label)} · <button class="os-link" data-contract="${c.id}">открыть</button></li>`;
        })
        .join("")}</ul>`
    : `<p class="os-muted">Действующих договоров нет.</p>`;
  const plan = STATE.plan || {};
  const rows = ["week", "prev"].map((k) => {
    const r = periodRange(k);
    const f = factFor(r);
    const cell = (v, p) => `<td class="os-num ${p ? (v >= p ? "os-good" : "os-bad") : ""}">${v}${p ? ` / ${p}` : ""}</td>`;
    return `<tr><td>${r.label} (${fmtDate(r.from)}–${fmtDate(r.to)})</td>${cell(f.candidates, plan.candidates)}${cell(f.new_clients, plan.new_clients)}${cell(
      f.touches,
      plan.touches,
    )}${cell(f.contracts, plan.contracts)}<td class="os-num">${f.log.length}</td></tr>`;
  });
  $("#cl-sum-manager").innerHTML = `<div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr><th>Период</th><th>Разобрано кандидатов</th><th>Новых клиентов</th><th>Касаний</th><th>Договоров</th><th>Действий</th></tr></thead><tbody>${rows.join(
    "",
  )}</tbody></table></div>`;
  const p = STATE.plan || {};
  $("#cl-plan-form").innerHTML = `
    <label>Разобрать кандидатов / нед.<input type="number" min="0" name="candidates" value="${p.candidates ?? 10}" ${RIGHTS.lead ? "" : "disabled"} /></label>
    <label>Новых клиентов в работе / нед.<input type="number" min="0" name="new_clients" value="${p.new_clients ?? 3}" ${RIGHTS.lead ? "" : "disabled"} /></label>
    <label>Касаний / нед.<input type="number" min="0" name="touches" value="${p.touches ?? 15}" ${RIGHTS.lead ? "" : "disabled"} /></label>
    <label>Договоров (новых и продлений) / нед.<input type="number" min="0" name="contracts" value="${p.contracts ?? 1}" ${RIGHTS.lead ? "" : "disabled"} /></label>
    <div class="os-form-actions">${RIGHTS.lead ? '<button class="os-btn is-primary" type="submit">Сохранить план</button>' : ""}
      <span class="os-status">${p.updated_by ? `задал ${esc(p.updated_by)} · ${fmtDateTime(p.updated_at)}` : "по умолчанию"}</span></div>`;
}

// ---------- Диалоги ----------
const dlg = () => $("#cl-dialog");
function openDialog(html, onMount) {
  $("#cl-dialog-body").innerHTML = html;
  if (!dlg().open) dlg().showModal();
  onMount?.($("#cl-dialog-body"));
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
    if (status && status.isConnected) status.textContent = "Сохранено ✓";
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

function conditionsEditorHtml(values) {
  const vals = values || {};
  const groups = {};
  for (const c of catalog()) {
    if (c.hidden && !vals[c.id]) continue;
    (groups[c.group] = groups[c.group] || []).push(c);
  }
  return Object.entries(groups)
    .map(
      ([g, list]) => `<div class="cl-cond-group">${esc(g)}</div>${list
        .map((c) => {
          const v = vals[c.id];
          const on = !!v;
          const valInput =
            c.unit === "bool"
              ? `<span class="os-muted">да</span>`
              : `<input type="${c.unit === "text" ? "text" : "number"}" step="any" min="0" name="cv_${c.id}" value="${esc(v?.value || "")}" placeholder="${esc(UNITS[c.unit])}" />`;
          const statusSel = c.auto
            ? `<span class="os-muted" title="Jarvis проверяет по заказам клиента">проверка по CRM</span>`
            : `<select name="cs_${c.id}"><option value="">не проверено</option><option value="ok" ${v?.status === "ok" ? "selected" : ""}>соблюдается</option><option value="violated" ${
                v?.status === "violated" ? "selected" : ""
              }>нарушено</option></select>`;
          return `<div class="cl-cond-line"><input type="checkbox" name="con_${c.id}" ${on ? "checked" : ""} title="включить условие" />
            <span>${esc(c.name)}</span>${valInput}${statusSel}</div>`;
        })
        .join("")}`,
    )
    .join("");
}
function collectConditions(form) {
  const out = {};
  for (const c of catalog()) {
    const on = form.querySelector(`[name="con_${c.id}"]`)?.checked;
    if (!on) continue;
    const value = c.unit === "bool" ? "1" : String(form.querySelector(`[name="cv_${c.id}"]`)?.value || "").trim();
    if (c.unit !== "bool" && !value) continue;
    out[c.id] = { value, status: form.querySelector(`[name="cs_${c.id}"]`)?.value || null };
  }
  return out;
}
function contactsRowsHtml(list) {
  const rows = (list && list.length ? list : [{}]).concat([{}]);
  return rows
    .map(
      (x, i) => `<div class="cl-contacts-row" data-contact-row>
        <input placeholder="Имя" name="ct_name_${i}" value="${esc(x.name || "")}" />
        <input placeholder="Роль (директор, бухгалтер…)" name="ct_role_${i}" value="${esc(x.role || "")}" />
        <input placeholder="Телефон" name="ct_phone_${i}" value="${esc(x.phone || "")}" />
        <input placeholder="Email" name="ct_email_${i}" value="${esc(x.email || "")}" />
        <span></span></div>`,
    )
    .join("");
}
function collectContacts(form) {
  return $$("[data-contact-row]", form)
    .map((row) => {
      const [name, role, phone, email] = $$("input", row).map((i) => i.value.trim());
      return { name, role, phone, email };
    })
    .filter((c) => c.name || c.phone || c.email);
}

function clientFormHtml(c) {
  const v = (k) => esc(c?.[k] ?? "");
  const lg = c?.legal || {};
  const opts = (obj, cur) => Object.entries(obj).map(([k, l]) => `<option value="${k}" ${cur === k ? "selected" : ""}>${l}</option>`).join("");
  return `<h2>${c ? "Карточка клиента" : "Новый клиент"}</h2>
    <form class="os-form" id="cl-client-form">
      <div class="os-row">
        <label class="req">Имя / название<input name="name" required value="${v("name")}" /></label>
        <label>Тип<select name="kind">${opts(KINDS, c?.kind || "person")}</select></label>
        <label>Откуда<select name="source">${opts(SOURCES, c?.source || "other")}</select></label>
      </div>
      <label class="req">Телефоны клиента <span class="os-muted">(по ним Jarvis находит его заказы в CRM; через запятую)</span>
        <input name="phones" value="${esc((c?.phones || []).map(fmtPhone).join(", "))}" placeholder="050 111 22 33, 067 …" /></label>
      <div class="os-row">
        <label>Район / адрес<input name="area" value="${v("area")}" /></label>
        <label>Какую технику сдаёт<input name="devices" value="${v("devices")}" /></label>
      </div>
      <h3>Контактные лица</h3>
      <div class="cl-cond-edit">${contactsRowsHtml(c?.contacts)}</div>
      <h3>Реквизиты для договора</h3>
      <div class="os-row">
        <label>Полное название / ПІБ<input name="lg_full_name" value="${esc(lg.full_name || "")}" placeholder="ТОВ «…» / Петренко Петро Петрович" /></label>
        <label>ЄДРПОУ / ІПН<input name="lg_code" value="${esc(lg.code || "")}" /></label>
        <label>Подписант<input name="lg_signer" value="${esc(lg.signer || "")}" placeholder="директора Петренка П.П." /></label>
      </div>
      <div class="os-row">
        <label>Действует на основании<input name="lg_basis" value="${esc(lg.basis || "")}" placeholder="Статуту / виписки з ЄДР …" /></label>
        <label>Адрес<input name="lg_address" value="${esc(lg.address || "")}" /></label>
        <label>Email<input name="lg_email" value="${esc(lg.email || "")}" /></label>
      </div>
      <div class="os-row">
        <label>Счёт (IBAN / р/р)<input name="lg_iban" value="${esc(lg.iban || "")}" /></label>
        <label>Банк<input name="lg_bank" value="${esc(lg.bank || "")}" placeholder="напр. Держказначейська служба України м. Київ" /></label>
        <label>МФО<input name="lg_mfo" value="${esc(lg.mfo || "")}" /></label>
      </div>
      <h3>Условия и договорённости</h3>
      <p class="os-muted" style="margin:0">Отметьте, что договорились, и укажите значение. Список условий правится во вкладке «Настройки».</p>
      <div class="cl-cond-edit">${conditionsEditorHtml(c?.conditions)}</div>
      ${
        c
          ? ""
          : `<h3>Следующий шаг</h3><div class="os-row">
        <label>Что сделать<input name="next_step" placeholder="позвонить, предложить условия…" /></label>
        <label>Когда<input type="date" name="next_step_at" value="${addDays(todayKey(), 2)}" /></label></div>`
      }
      <label>Заметки<textarea name="notes">${v("notes")}</textarea></label>
      <div class="os-form-actions">
        <button class="os-btn is-primary" type="submit">${c ? "Сохранить" : "Завести клиента"}</button>
        ${c ? `<button class="os-btn" type="button" data-open="${c.id}">Назад</button>` : ""}
        <span class="os-status"></span>
      </div>
    </form>`;
}
function openClientForm(c) {
  openDialog(clientFormHtml(c), (root) => {
    $("#cl-client-form", root).addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = e.target;
      try {
        const data = await submitForm(f, (b) => {
          const body = {
            name: b.name,
            kind: b.kind,
            source: b.source,
            phones: b.phones,
            area: b.area,
            devices: b.devices,
            notes: b.notes,
            contacts: collectContacts(f),
            legal: {
              full_name: b.lg_full_name,
              code: b.lg_code,
              signer: b.lg_signer,
              address: b.lg_address,
              basis: b.lg_basis,
              iban: b.lg_iban,
              bank: b.lg_bank,
              mfo: b.lg_mfo,
              email: b.lg_email,
            },
            conditions: collectConditions(f),
          };
          if (!c) {
            body.next_step = b.next_step;
            body.next_step_at = b.next_step_at;
          }
          return c ? api("PATCH", `/clients/clients/${c.id}`, body) : api("POST", "/clients/clients", body);
        });
        openClient(c ? c.id : data.id);
      } catch {
        /* в форме */
      }
    });
  });
}

function openTouchForm(c) {
  const opts = Object.entries(CHANNELS).map(([k, l]) => `<option value="${k}">${l}</option>`).join("");
  const needNext = !["paused", "lost"].includes(c.stage);
  openDialog(
    `<h2>Касание: ${esc(c.name)}</h2>
    <form class="os-form" id="cl-touch-form">
      <div class="os-row"><label>Как<select name="channel">${opts}</select></label></div>
      <label class="req">Что сделано / о чём договорились<textarea name="text" required></textarea></label>
      <div class="os-row">
        <label class="${needNext ? "req" : ""}">Следующий шаг<input name="next_step" ${needNext ? "required" : ""} value="${esc(c.next_step || "")}" /></label>
        <label class="${needNext ? "req" : ""}">Когда<input type="date" name="next_step_at" ${needNext ? "required" : ""} value="${addDays(todayKey(), 7)}" /></label>
      </div>
      <div class="os-form-actions"><button class="os-btn is-primary" type="submit">Сохранить</button><button class="os-btn" type="button" data-open="${c.id}">Назад</button><span class="os-status"></span></div>
    </form>`,
    (root) => {
      $("#cl-touch-form", root).addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          await submitForm(e.target, (b) => api("POST", `/clients/clients/${c.id}/touch`, b));
          openClient(c.id);
        } catch {
          /* в форме */
        }
      });
    },
  );
}

function openStageForm(c, stage) {
  if (stage !== "lost") {
    api("POST", `/clients/clients/${c.id}/stage`, { stage })
      .then((d) => {
        applyState(d);
        renderAll();
        openClient(c.id);
      })
      .catch((err) => alert(err.message));
    return;
  }
  openDialog(
    `<h2>Отказ: ${esc(c.name)}</h2>
    <form class="os-form" id="cl-stage-form">
      <label class="req">Причина<input name="lost_reason" required placeholder="не заинтересован, дорого, ушёл к конкурентам…" /></label>
      <div class="os-form-actions"><button class="os-btn is-danger" type="submit">Перевести в «Отказ»</button><button class="os-btn" type="button" data-open="${c.id}">Назад</button><span class="os-status"></span></div>
    </form>`,
    (root) => {
      $("#cl-stage-form", root).addEventListener("submit", async (e) => {
        e.preventDefault();
        try {
          await submitForm(e.target, (b) => api("POST", `/clients/clients/${c.id}/stage`, { stage: "lost", lost_reason: b.lost_reason }));
          openClient(c.id);
        } catch {
          /* в форме */
        }
      });
    },
  );
}

// ---------- Договор: шаблон → текст ----------
function conditionClause(cond, value) {
  return cond.unit === "bool" ? cond.clause.replace("{value}", "так") : cond.clause.replace("{value}", String(value ?? "").trim());
}
const UK_MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"];
function fmtDayUk(iso) {
  if (!iso || !/^\d{4}-\d{2}-\d{2}/.test(iso)) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  return `«${d}» ${UK_MONTHS[m - 1]} ${y} р.`;
}
// ---------- суммы прописью (украинский) ----------
const W_ONES_M = ["", "один", "два", "три", "чотири", "п'ять", "шість", "сім", "вісім", "дев'ять"];
const W_ONES_F = ["", "одна", "дві", "три", "чотири", "п'ять", "шість", "сім", "вісім", "дев'ять"];
const W_TEENS = ["десять", "одинадцять", "дванадцять", "тринадцять", "чотирнадцять", "п'ятнадцять", "шістнадцять", "сімнадцять", "вісімнадцять", "дев'ятнадцять"];
const W_TENS = ["", "", "двадцять", "тридцять", "сорок", "п'ятдесят", "шістдесят", "сімдесят", "вісімдесят", "дев'яносто"];
const W_HUNDREDS = ["", "сто", "двісті", "триста", "чотириста", "п'ятсот", "шістсот", "сімсот", "вісімсот", "дев'ятсот"];

function wPlural(n, one, few, many) {
  const a = n % 100;
  const b = n % 10;
  if (a > 10 && a < 20) return many;
  if (b === 1) return one;
  if (b > 1 && b < 5) return few;
  return many;
}
function wTriad(n, fem) {
  const out = [];
  const h = Math.floor(n / 100);
  const t = Math.floor((n % 100) / 10);
  const o = n % 10;
  if (h) out.push(W_HUNDREDS[h]);
  if (t === 1) out.push(W_TEENS[o]);
  else {
    if (t) out.push(W_TENS[t]);
    if (o) out.push((fem ? W_ONES_F : W_ONES_M)[o]);
  }
  return out.join(" ");
}
/** 32100 → «тридцять дві тисячі сто гривень 00 копійок» */
function uahWords(amount) {
  const total = Math.round(Number(amount || 0) * 100);
  let n = Math.floor(total / 100);
  const kop = total % 100;
  const parts = [];
  const groups = [
    [1_000_000_000, ["мільярд", "мільярди", "мільярдів"], false],
    [1_000_000, ["мільйон", "мільйони", "мільйонів"], false],
    [1000, ["тисяча", "тисячі", "тисяч"], true],
  ];
  for (const [div, names, fem] of groups) {
    const g = Math.floor(n / div);
    if (g) {
      parts.push(wTriad(g, fem), wPlural(g, ...names));
      n %= div;
    }
  }
  const whole = Math.floor(total / 100);
  if (n) parts.push(wTriad(n, true));
  if (!whole) parts.push("нуль");
  parts.push(wPlural(whole, "гривня", "гривні", "гривень"));
  parts.push(String(kop).padStart(2, "0"), wPlural(kop, "копійка", "копійки", "копійок"));
  return parts.filter(Boolean).join(" ");
}
/** «10» → «10 (десяти)» — родовий відмінок для «протягом … робочих днів» */
const W_GEN = { 1: "одного", 2: "двох", 3: "трьох", 4: "чотирьох", 5: "п'яти", 6: "шести", 7: "семи", 8: "восьми", 9: "дев'яти", 10: "десяти", 14: "чотирнадцяти", 15: "п'ятнадцяти", 20: "двадцяти", 30: "тридцяти", 45: "сорока п'яти", 60: "шістдесяти" };
function daysWords(v) {
  const n = Number(String(v).replace(",", "."));
  if (!Number.isInteger(n) || n <= 0) return String(v);
  return W_GEN[n] ? `${n} (${W_GEN[n]})` : String(n);
}
function fmtMoneyUk(v) {
  const n = Number(v || 0);
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
}

function renderContractText(template, client, contract) {
  const legal = client?.legal || {};
  const conds = client?.conditions || {};
  const items = catalog().filter((c) => conds[c.id] && (c.unit === "bool" || String(conds[c.id].value || "").trim()));
  const val = (id, def) => (conds[id] && String(conds[id].value || "").trim()) || def;
  const r = settings().requisites || {};
  const blank = "________________";
  const fields = {
    "номер_договору": contract?.number || blank,
    "дата_договору": fmtDayUk(contract?.signed_at || contract?.valid_from) || blank,
    "місто": r.city || blank,
    "строк_дії_до": fmtDayUk(contract?.valid_to) || blank,
    "предмет_дк": contract?.subject || DEFAULT_SUBJECT,
    "ціна_договору": Number(contract?.price) > 0 ? fmtMoneyUk(contract.price) : blank,
    "ціна_прописом": Number(contract?.price) > 0 ? uahWords(contract.price) : blank,
    "строк_оплати": daysWords(val("pay_delay", "10")),
    "виконавець_назва": r.name || blank,
    "виконавець_повна_назва": r.full_name || r.name || blank,
    "виконавець_підстава": r.basis || blank,
    "виконавець_код": r.code || blank,
    "виконавець_адреса": r.address || blank,
    "виконавець_iban": r.iban || blank,
    "виконавець_банк": r.bank || blank,
    "виконавець_мфо": r.mfo || blank,
    "виконавець_єдрпоу_банку": r.bank_code || blank,
    "виконавець_телефон": r.phone || blank,
    "виконавець_email": r.email || blank,
    "виконавець_підписант": r.signer || blank,
    "клієнт_назва": legal.full_name || client?.name || blank,
    "клієнт_підстава": legal.basis || blank,
    "клієнт_код": legal.code || blank,
    "клієнт_адреса": legal.address || blank,
    "клієнт_телефон": (client?.phones || []).map(fmtPhone).join(", ") || blank,
    "клієнт_email": legal.email || blank,
    "клієнт_iban": legal.iban || blank,
    "клієнт_банк": legal.bank || blank,
    "клієнт_мфо": legal.mfo || blank,
    "клієнт_підписант": legal.signer || (client?.kind === "person" ? client?.name : "") || blank,
    "строк_діагностики": val("diag_days", "3"),
    "строк_ремонту": val("repair_days", "14"),
    "гарантія": val("warranty", "3"),
    "індивідуальні_умови": items.length
      ? items.map((c, i) => `${i + 1}. ${conditionClause(c, conds[c.id].value)}`).join("\n")
      : "Індивідуальні умови не встановлені; діють загальні умови Виконавця.",
  };
  return String(template || "").replace(/\{\{\s*([^}]+?)\s*\}\}/g, (m, k) => (k in fields ? fields[k] : m));
}
function docHtml(text) {
  const inline = (s) => esc(s).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
  return String(text || "")
    .split(/\n/)
    .map((line) => {
      if (/^#\s+/.test(line)) return `<h1>${inline(line.replace(/^#\s+/, ""))}</h1>`;
      if (/^##\s+/.test(line)) return `<h2>${inline(line.replace(/^##\s+/, ""))}</h2>`;
      if (!line.trim()) return "";
      return `<p>${inline(line)}</p>`;
    })
    .join("\n");
}
function printDoc(title, text) {
  const w = window.open("", "_blank");
  if (!w) {
    alert("Браузер заблокировал окно печати — разрешите всплывающие окна для этой страницы.");
    return;
  }
  w.document.write(`<!doctype html><html lang="uk"><head><meta charset="utf-8"><title>${esc(title)}</title>
    <style>body{font-family:"Times New Roman",serif;font-size:12pt;line-height:1.4;max-width:720px;margin:24px auto;padding:0 16px;color:#000}
    h1{font-size:14pt;text-align:center;margin:0}h2{font-size:12pt;margin:12px 0 4px}p{margin:0 0 5px;text-align:justify}
    @media print{body{margin:0 auto}}</style></head><body>${docHtml(text)}<script>window.onload=()=>window.print()<\/script></body></html>`);
  w.document.close();
}

function contractFormHtml(client, ct) {
  const v = (k) => esc(ct?.[k] ?? "");
  const t = todayKey();
  const kind = ct?.kind || (client.kind === "person" ? "person" : "legal");
  const stOpts = Object.entries(CONTRACT_ST).map(([k, l]) => `<option value="${k}" ${(ct?.status || "draft") === k ? "selected" : ""}>${l}</option>`).join("");
  const kindOpts = Object.entries(TEMPLATE_KINDS).map(([k, l]) => `<option value="${k}" ${kind === k ? "selected" : ""}>${l}</option>`).join("");
  const num = ct?.number || `${new Date().getFullYear()}-${String((STATE.contracts || []).length + 1).padStart(3, "0")}`;
  return `<h2>${ct ? `Договор №${esc(ct.number || "б/н")}` : "Новый договор"} · ${esc(client.name)}</h2>
    <form class="os-form" id="cl-contract-form">
      <div class="os-row">
        <label>Номер<input name="number" value="${esc(num)}" /></label>
        <label>Вид (шаблон)<select name="kind">${kindOpts}</select></label>
        <label>Статус<select name="status">${stOpts}</select></label>
      </div>
      <div class="os-row">
        <label>Дата подписания<input type="date" name="signed_at" value="${v("signed_at") || t}" /></label>
        <label>Действует с<input type="date" name="valid_from" value="${v("valid_from") || t}" /></label>
        <label class="req">Действует до<input type="date" name="valid_to" value="${v("valid_to") || addDays(addDays(t, 365), -1)}" /></label>
      </div>
      <div class="os-row">
        <label>Цена договора, грн (без ПДВ)<input type="number" min="0" step="0.01" name="price" value="${v("price")}" placeholder="напр. 32100" /></label>
        <label>Предмет (код ДК 021-2015)<input name="subject" value="${esc(ct?.subject || STATE.defaults?.subject || DEFAULT_SUBJECT)}" /></label>
      </div>
      <label>Ссылка на скан (Google Drive и т.п.)<input name="file_url" value="${v("file_url")}" placeholder="https://drive.google.com/…" /></label>
      <label>Заметки<input name="notes" value="${v("notes")}" /></label>
      <div class="os-form-actions">
        <button class="os-btn" type="button" id="cl-gen">Сформировать текст по шаблону</button>
        ${ct?.body ? '<button class="os-btn" type="button" id="cl-print-saved">Печать сохранённого текста</button>' : ""}
      </div>
      <div id="cl-gen-box"></div>
      <div class="os-form-actions">
        <button class="os-btn is-primary" type="submit" data-write>${ct ? "Сохранить" : "Создать договор"}</button>
        <button class="os-btn" type="button" data-open="${client.id}">Назад</button>
        <span class="os-status"></span>
      </div>
    </form>`;
}
function openContractForm(client, ct) {
  let body = ct?.body || null;
  openDialog(contractFormHtml(client, ct), (root) => {
    const form = $("#cl-contract-form", root);
    const current = () => Object.fromEntries(new FormData(form).entries());
    $("#cl-gen", root).addEventListener("click", () => {
      const b = current();
      const tpl = STATE.templates?.[b.kind]?.body || "";
      body = renderContractText(tpl, client, b);
      const missing = (body.match(/_{8,}/g) || []).length;
      $("#cl-gen-box", root).innerHTML = `<div class="cl-doc">${docHtml(body)}</div>
        <div class="os-form-actions" style="margin-top:8px"><button class="os-btn" type="button" id="cl-print">Печать / PDF</button>
        <span class="os-muted">${missing ? `не заполнено полей: ${missing} — реквизиты в «Настройках» и в карточке клиента` : "все поля заполнены"} · текст сохранится вместе с договором</span></div>`;
      $("#cl-print", root).addEventListener("click", () => printDoc(`Договір ${b.number}`, body));
    });
    $("#cl-print-saved", root)?.addEventListener("click", () => printDoc(`Договір ${ct.number}`, ct.body));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      try {
        await submitForm(form, (b) => {
          const payload = { ...b, client_id: client.id };
          if (body) payload.body = body;
          return ct ? api("PATCH", `/clients/contracts/${ct.id}`, payload) : api("POST", "/clients/contracts", payload);
        });
        openClient(client.id);
      } catch {
        /* в форме */
      }
    });
  });
}

function openClient(id) {
  const c = clientById(id);
  if (!c) return;
  const m = crmOf(c.id);
  const crm = STATE.crm;
  const stageBtns = Object.entries(STAGES)
    .filter(([k]) => k !== c.stage)
    .map(([k, l]) => `<button class="os-btn is-small ${k === "lost" ? "is-danger" : ""}" data-stage="${k}">${l}</button>`)
    .join("");
  const checks = checkConditions(c);
  const condHtml = checks.length
    ? `<div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr><th>Условие</th><th>Значение</th><th>Проверка</th></tr></thead><tbody>${checks
        .map(
          (r) => `<tr><td>${esc(r.cond.name)}</td><td>${esc(condValueLabel(r.cond, r.value))}</td>
          <td class="os-wrap ${r.ok === true ? "cl-check-ok" : r.ok === false ? "cl-check-bad" : "os-muted"}">${
            r.ok === null ? (r.cond.auto ? "нет данных CRM" : "не проверено") : `${r.ok ? "✓" : "✗"} ${esc(r.detail)}`
          }</td></tr>`,
        )
        .join("")}</tbody></table></div>`
    : `<p class="os-muted">Условия не заданы — «Редактировать» → «Условия и договорённости».</p>`;
  const cts = contractsOf(c.id).sort((a, b) => b.id - a.id);
  const ctHtml = cts.length
    ? `<div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr><th>№</th><th>Статус</th><th>Срок</th><th></th></tr></thead><tbody>${cts
        .map((x) => {
          const st = contractState(x);
          return `<tr><td>${esc(x.number || "б/н")}</td><td>${esc(CONTRACT_ST[x.status])}</td><td class="${st.key === "expired" ? "os-bad" : st.key === "expiring" ? "os-warn" : ""}">${esc(
            st.label,
          )}</td><td><button class="os-btn is-small" data-contract="${x.id}">Открыть</button></td></tr>`;
        })
        .join("")}</tbody></table></div>`
    : `<p class="os-muted">Договоров нет.</p>`;
  const months = m
    ? Object.entries(m.by_month || {})
        .sort((a, b) => a[0].localeCompare(b[0]))
        .slice(-12)
    : [];
  const maxG = Math.max(1, ...months.map(([, v]) => v.gross || 0));
  const crmHtml = !m
    ? `<p class="os-muted">${crm ? "В снимке CRM нет данных по этому клиенту — проверьте телефоны." : "Снимка CRM ещё нет — его делает Jarvis при утренней пересборке."}</p>`
    : `<div class="os-kv">
        <div><span>Заказов за 90 дн.</span><b>${m.orders_90}</b></div>
        <div><span>Вал за 90 дн.</span><b>${money(m.gross_90)}</b></div>
        <div><span>Тренд к прошлым 90</span><b class="${m.trend != null && m.trend <= DROP ? "os-bad" : ""}">${pctSigned(m.trend)}</b></div>
        <div><span>Всего за год</span><b>${m.orders} · ${money(m.gross)}</b></div>
        <div><span>Последний заказ</span><b class="${m.asleep ? "os-bad" : ""}">${m.last_order_at ? `${fmtDate(m.last_order_at)} (${m.days_since_last} дн.)` : "—"}</b></div>
        <div><span>Обычно раз в</span><b>${m.avg_interval ? `${Math.round(m.avg_interval)} дн.` : "—"}</b></div>
        <div><span>Долг</span><b class="${m.debt ? "os-warn" : ""}">${money(m.debt)}</b></div>
        <div><span>Возвраты</span><b>${m.refusals} из ${m.issued + m.refusals}</b></div>
      </div>
      ${
        months.length
          ? `<div class="os-days" style="grid-template-columns:repeat(${months.length},1fr);height:80px;margin-top:10px">${months
              .map(([k, v]) => `<div class="os-day" style="height:${Math.max(4, ((v.gross || 0) / maxG) * 100)}%" title="${k}: ${v.orders} зак., ${money(v.gross)}"></div>`)
              .join("")}</div><div class="os-days-legend"><span>${months[0][0]}</span><span>вал по месяцам</span><span>${months.at(-1)[0]}</span></div>`
          : ""
      }
      ${
        (m.in_work || []).length
          ? `<h3>Сейчас в работе</h3><div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr><th>№</th><th>Устройство</th><th>Статус</th><th>Дней</th></tr></thead><tbody>${m.in_work
              .map((o) => `<tr><td>${o.url ? `<a href="${esc(o.url)}" target="_blank" rel="noopener">${esc(o.ticket)}</a>` : esc(o.ticket)}</td><td>${esc(o.device || "")}</td><td>${esc(o.status || "")}</td><td class="os-num">${o.days ?? "—"}</td></tr>`)
              .join("")}</tbody></table></div>`
          : ""
      }
      ${
        (m.debt_orders || []).length
          ? `<h3>Не оплачено</h3><div class="table-wrap os-table-scroll"><table class="vtable"><thead><tr><th>№</th><th>Стоимость</th><th>Оплачено</th><th>Долг</th><th>Дней</th></tr></thead><tbody>${m.debt_orders
              .map((o) => `<tr><td>${o.url ? `<a href="${esc(o.url)}" target="_blank" rel="noopener">${esc(o.ticket)}</a>` : esc(o.ticket)}</td><td class="os-num">${money(o.cost)}</td><td class="os-num">${money(o.paid)}</td><td class="os-num os-warn">${money(o.due)}</td><td class="os-num">${o.days ?? "—"}</td></tr>`)
              .join("")}</tbody></table></div>`
          : ""
      }`;
  const contacts = (c.contacts || []).length
    ? `<ul>${c.contacts.map((x) => `<li>${esc(x.name || "")}${x.role ? ` <span class="os-muted">(${esc(x.role)})</span>` : ""} ${esc(x.phone || "")} ${esc(x.email || "")}</li>`).join("")}</ul>`
    : "";
  const history = logOf(c.id);
  openDialog(
    `<h2>${esc(c.name)}</h2>
    <p class="card-sub">${esc(KINDS[c.kind] || "")} · ${esc(STAGES[c.stage])} (${daysSince(c.stage_at) ?? 0} дн.)${c.lost_reason ? ` · ${esc(c.lost_reason)}` : ""} · ${esc(SOURCES[c.source] || "")}
      ${(c.phones || []).length ? `<br>${c.phones.map((p) => `<a href="tel:+38${p}">${esc(fmtPhone(p))}</a>`).join(", ")}` : ""}
      ${c.area ? ` · ${esc(c.area)}` : ""}${c.devices ? ` · ${esc(c.devices)}` : ""}</p>
    ${contacts}
    <div class="os-alert ${c.next_step_at && c.next_step_at < todayKey() ? "is-bad" : ""}" style="margin:8px 0">Следующий шаг: <b>${esc(c.next_step || "не задан")}</b>${
      c.next_step_at ? ` · ${fmtDate(c.next_step_at)}` : ""
    }</div>
    <div class="os-form-actions" data-write>
      <button class="os-btn is-primary" data-touch="${c.id}">Отметить касание</button>
      <button class="os-btn" data-edit="${c.id}">Редактировать</button>
      <button class="os-btn" data-new-contract="${c.id}">Новый договор</button>
    </div>
    <div class="os-form-actions" style="margin-top:6px" data-write><span class="os-muted">Перевести на стадию:</span> ${stageBtns}</div>
    <h3>CRM: заказы и деньги</h3>${crmHtml}
    <h3>Условия и их соблюдение</h3>${condHtml}
    <h3>Договоры</h3>${ctHtml}
    ${c.notes ? `<h3>Заметки</h3><p style="white-space:pre-wrap">${esc(c.notes)}</p>` : ""}
    <h3>История</h3>
    <div class="os-timeline">${
      history.map((l) => `<div><time>${fmtDateTime(l.at)}</time>${esc(ACTIONS[l.action] || l.action)} · ${esc(l.login || "")} — ${esc(l.text || "")}</div>`).join("") ||
      '<p class="os-muted">пусто</p>'
    }</div>`,
    (root) => {
      $$("[data-stage]", root).forEach((b) => b.addEventListener("click", () => openStageForm(c, b.dataset.stage)));
    },
  );
}

// ---------- Настройки ----------
function renderSettings() {
  if (!STATE) return;
  // справочник
  const rows = catalog()
    .map(
      (c, i) => `<tr data-cond-row>
      <td><input type="text" name="group" value="${esc(c.group)}" /></td>
      <td><input type="hidden" name="id" value="${esc(c.id)}" /><input type="text" name="name" value="${esc(c.name)}" /></td>
      <td><select name="unit">${Object.entries(UNITS).map(([k, l]) => `<option value="${k}" ${c.unit === k ? "selected" : ""}>${l}</option>`).join("")}</select></td>
      <td><select name="auto">${Object.entries(AUTO).map(([k, l]) => `<option value="${k}" ${(c.auto || "") === k ? "selected" : ""}>${l}</option>`).join("")}</select></td>
      <td><input type="text" name="clause" value="${esc(c.clause)}" /></td>
      <td style="text-align:center"><input type="checkbox" name="hidden" ${c.hidden ? "checked" : ""} title="скрыть из формы клиента" /></td>
      <td><button type="button" class="os-btn is-small is-danger" data-del-cond="${i}">✕</button></td></tr>`,
    )
    .join("");
  $("#cl-cond-form").innerHTML = `<div class="table-wrap os-table-scroll"><table class="vtable cl-cond-table"><thead><tr><th>Группа</th><th>Условие</th><th>Единица</th><th>Проверка по CRM</th><th>Текст в договоре</th><th>Скрыть</th><th></th></tr></thead><tbody id="cl-cond-rows">${rows}</tbody></table></div>
    <div class="os-form-actions"><button type="button" class="os-btn" id="cl-cond-add">+ Своё условие</button><button class="os-btn is-primary" type="submit">Сохранить справочник</button><span class="os-status"></span></div>`;
  // шаблон
  $("#cl-tpl-tabs").innerHTML = Object.entries(TEMPLATE_KINDS)
    .map(([k, l]) => `<button type="button" class="os-btn is-small ${k === tplKind ? "is-active" : ""}" data-tpl="${k}">${l}</button>`)
    .join("");
  const tpl = STATE.templates?.[tplKind] || {};
  $("#cl-tpl-form").innerHTML = `
    <p class="os-muted" style="margin:0">${tpl.is_default ? "Стандартный шаблон (ещё не правился)." : `Версия ${tpl.version} · ${esc(tpl.updated_by || "")} · ${fmtDateTime(tpl.updated_at)}`}
      Разметка: <code># Заголовок</code>, <code>## Раздел</code>, <code>**жирный**</code>. Подстановки (клик — вставить):</p>
    <div class="cl-fields">${Object.entries(TEMPLATE_FIELDS).map(([k, l]) => `<code data-field="${esc(k)}" title="${esc(l)}">{{${esc(k)}}}</code>`).join("")}</div>
    <textarea class="cl-template" name="body">${esc(tpl.body || "")}</textarea>
    <div class="os-form-actions"><button class="os-btn is-primary" type="submit">Сохранить новую версию</button><button type="button" class="os-btn" id="cl-tpl-preview">Предпросмотр на примере</button><button type="button" class="os-btn" id="cl-tpl-reset" title="Загрузить в редактор стандартный шаблон; сохранится только после «Сохранить новую версию»">Взять стандартный шаблон</button><span class="os-status"></span></div>
    <div id="cl-tpl-preview-box"></div>`;
  // реквизиты
  const r = settings().requisites || {};
  const rf = (k, label, ph = "") => `<label>${label}<input name="${k}" value="${esc(r[k] || "")}" placeholder="${esc(ph)}" /></label>`;
  $("#cl-req-form").innerHTML = `<div class="os-row">${rf("name", "Коротко (подпись)", "ФОП ПРІЗВИЩЕ І.П.")}${rf("full_name", "Полностью (в преамбуле)", "Фізична особа-підприємець …")}</div>
    <div class="os-row">${rf("signer", "В особі (кто подписывает)", "Прізвище І.П.")}${rf("basis", "Действует на основании", "виписки з ЄДР від … №…")}</div>
    <div class="os-row">${rf("code", "ІПН / ЄДРПОУ")}${rf("address", "Адрес")}${rf("city", "Город", "Одеса")}</div>
    <div class="os-row">${rf("iban", "IBAN", "UA…")}${rf("bank", "Банк")}${rf("mfo", "МФО")}${rf("bank_code", "ЄДРПОУ банка")}</div>
    <div class="os-row">${rf("phone", "Телефон")}${rf("email", "Email")}</div>
    <div class="os-form-actions"><button class="os-btn is-primary" type="submit">Сохранить реквизиты</button><span class="os-status"></span></div>`;
  // пороги
  const th = settings().thresholds || {};
  $("#cl-thr-form").innerHTML = `<div class="os-row">
      <label>Окно, мес.<input type="number" min="2" max="12" name="months" value="${th.months ?? 6}" /></label>
      <label>Заказов за окно (от)<input type="number" min="2" name="orders" value="${th.orders ?? 4}" /></label>
      <label>«Недавно», дн.<input type="number" min="14" max="180" name="recent_days" value="${th.recent_days ?? 60}" /></label>
      <label>Заказов за «недавно» (от)<input type="number" min="2" name="recent_orders" value="${th.recent_orders ?? 3}" /></label>
      <label>Или вал за окно от, грн<input type="number" min="0" name="gross" value="${th.gross ?? 20000}" /></label>
    </div>
    <label>Не предлагать эти телефоны <span class="os-muted">(сотрудники, мастера, свои номера — через запятую или с новой строки)</span>
      <textarea name="excluded_phones">${esc((settings().excluded_phones || []).map(fmtPhone).join("\n"))}</textarea></label>
    <div class="os-row"><label>Касание постоянного клиента — не реже чем раз в, дн.<input type="number" min="3" max="180" name="touch_every_days" value="${settings().touch_every_days ?? 30}" /></label></div>
    <div class="os-form-actions"><button class="os-btn is-primary" type="submit">Сохранить</button><span class="os-status">Новые пороги применятся при следующей синхронизации Jarvis.</span></div>`;
}

function bindSettings() {
  $("#cl-cond-form").addEventListener("click", (e) => {
    if (e.target.id === "cl-cond-add") {
      const tr = document.createElement("tr");
      tr.setAttribute("data-cond-row", "");
      tr.innerHTML = `<td><input type="text" name="group" value="Прочее" /></td><td><input type="hidden" name="id" value="" /><input type="text" name="name" placeholder="Название условия" /></td>
        <td><select name="unit">${Object.entries(UNITS).map(([k, l]) => `<option value="${k}" ${k === "text" ? "selected" : ""}>${l}</option>`).join("")}</select></td>
        <td><select name="auto">${Object.entries(AUTO).map(([k, l]) => `<option value="${k}">${l}</option>`).join("")}</select></td>
        <td><input type="text" name="clause" placeholder="Текст пункта договору, {value} — значення" /></td><td style="text-align:center"><input type="checkbox" name="hidden" /></td>
        <td><button type="button" class="os-btn is-small is-danger" data-del-cond>✕</button></td>`;
      $("#cl-cond-rows").appendChild(tr);
    } else if (e.target.hasAttribute("data-del-cond")) {
      e.target.closest("tr").remove();
    }
  });
  $("#cl-cond-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const list = $$("[data-cond-row]", e.target).map((tr) => ({
      id: $("[name=id]", tr).value,
      group: $("[name=group]", tr).value,
      name: $("[name=name]", tr).value,
      unit: $("[name=unit]", tr).value,
      auto: $("[name=auto]", tr).value || null,
      clause: $("[name=clause]", tr).value,
      hidden: $("[name=hidden]", tr).checked,
    }));
    try {
      await submitForm(e.target, () => api("PUT", "/clients/conditions", { conditions: list }));
    } catch {
      /* в форме */
    }
  });
  $("#cl-tpl-tabs").addEventListener("click", (e) => {
    const k = e.target.dataset.tpl;
    if (k) {
      tplKind = k;
      renderSettings();
    }
  });
  $("#cl-tpl-form").addEventListener("click", (e) => {
    const f = e.target.dataset.field;
    if (f) {
      const ta = $("#cl-tpl-form textarea");
      const ins = `{{${f}}}`;
      const p = ta.selectionStart ?? ta.value.length;
      ta.value = ta.value.slice(0, p) + ins + ta.value.slice(ta.selectionEnd ?? p);
      ta.focus();
      ta.selectionStart = ta.selectionEnd = p + ins.length;
    } else if (e.target.id === "cl-tpl-reset") {
      const def = STATE.defaults?.templates?.[tplKind];
      if (!def) return alert("Стандартный шаблон недоступен — обновите облако (wrangler deploy).");
      if (!confirm("Заменить текст в редакторе стандартным шаблоном? Сохранится только после «Сохранить новую версию».")) return;
      $("#cl-tpl-form textarea").value = def;
    } else if (e.target.id === "cl-tpl-preview") {
      const sample = clients().find((c) => c.stage === "active") || {
        name: "Приклад Клієнт",
        phones: ["0501112233"],
        legal: { full_name: "ТОВ «Приклад»", code: "12345678", signer: "директора Прикладенка П.П." },
        conditions: { repair_days: { value: "5" }, discount_work: { value: "10" }, free_diag: { value: "1" } },
      };
      const text = renderContractText($("#cl-tpl-form textarea").value, sample, {
        number: "ПРИКЛАД-1",
        signed_at: todayKey(),
        valid_to: addDays(addDays(todayKey(), 365), -1),
      });
      $("#cl-tpl-preview-box").innerHTML = `<p class="os-muted">Пример: ${esc(sample.name)}</p><div class="cl-doc">${docHtml(text)}</div>`;
    }
  });
  $("#cl-tpl-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await submitForm(e.target, (b) => api("PUT", "/clients/templates", { kind: tplKind, body: b.body }));
    } catch {
      /* в форме */
    }
  });
  $("#cl-req-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await submitForm(e.target, (b) => api("PUT", "/clients/settings", { ...settings(), requisites: b }));
    } catch {
      /* в форме */
    }
  });
  $("#cl-thr-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await submitForm(e.target, (b) =>
        api("PUT", "/clients/settings", {
          ...settings(),
          thresholds: { months: b.months, orders: b.orders, recent_days: b.recent_days, recent_orders: b.recent_orders, gross: b.gross },
          excluded_phones: b.excluded_phones,
          touch_every_days: b.touch_every_days,
        }),
      );
    } catch {
      /* в форме */
    }
  });
}

// ---------- вкладки и события ----------
const LS_TAB = "jarvis.clients.tab";
function setTab(tab) {
  const btn = $(`.mod-tab[data-cltab="${tab}"]`);
  if (!btn || btn.hidden) tab = RIGHTS.lead ? "summary" : "clients";
  activeTab = tab;
  $$(".mod-tab[data-cltab]").forEach((b) => b.classList.toggle("is-active", b.dataset.cltab === tab));
  $$(".os-panel").forEach((p) => (p.hidden = p.id !== `cl-panel-${tab}`));
  try {
    localStorage.setItem(LS_TAB, tab);
  } catch {
    /* ignore */
  }
  renderActive();
}
function renderActive() {
  if (activeTab === "summary") renderSummary();
  else if (activeTab === "clients") renderClients();
  else if (activeTab === "candidates") renderCandidates();
  else if (activeTab === "funnel") renderBoard();
  else if (activeTab === "contracts") renderContracts();
  else if (activeTab === "activity") renderActivity();
  else if (activeTab === "settings") renderSettings();
}
function renderAll() {
  renderMeta();
  // настройки не перерисовываем на каждое сохранение карточки — там может быть недописанный текст
  if (activeTab !== "settings") renderActive();
}

function bindEvents() {
  $$(".mod-tab[data-cltab]").forEach((b) => b.addEventListener("click", () => setTab(b.dataset.cltab)));
  $("#cl-add").addEventListener("click", () => STATE && RIGHTS.work && openClientForm(null));
  $("#cl-add-2").addEventListener("click", () => STATE && RIGHTS.work && openClientForm(null));
  $("#cl-search").addEventListener("input", renderClients);
  $("#cl-stage-filter").addEventListener("change", renderClients);
  $("#cl-cand-search").addEventListener("input", renderCandidates);
  $("#cl-cand-b2b").addEventListener("change", renderCandidates);
  $("#cl-show-closed").addEventListener("change", renderBoard);
  $("#cl-act-period").addEventListener("change", renderActivity);
  $("#cl-plan-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const st = $(".os-status", e.target);
    try {
      st.textContent = "Сохраняю…";
      const body = Object.fromEntries([...new FormData(e.target).entries()].map(([k, v]) => [k, Number(v)]));
      applyState(await api("PUT", "/clients/plan", body));
      renderAll();
    } catch (err) {
      st.textContent = err.message;
      st.classList.add("is-error");
    }
  });
  bindSettings();
  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-open],[data-edit],[data-touch],[data-new-contract],[data-contract],[data-take],[data-dismiss],[data-snooze],[data-goto]");
    if (!t || !STATE) return;
    if (!RIGHTS.work && (t.closest("[data-write]") || t.dataset.edit || t.dataset.touch || t.dataset.newContract || t.dataset.take || t.dataset.dismiss || t.dataset.snooze)) return;
    if (t.dataset.open) openClient(t.dataset.open);
    else if (t.dataset.edit) openClientForm(clientById(t.dataset.edit));
    else if (t.dataset.touch) openTouchForm(clientById(t.dataset.touch));
    else if (t.dataset.newContract) openContractForm(clientById(t.dataset.newContract), null);
    else if (t.dataset.contract) {
      const ct = (STATE.contracts || []).find((x) => String(x.id) === t.dataset.contract);
      if (ct) openContractForm(clientById(ct.client_id), ct);
    } else if (t.dataset.take) openTakeForm(t.dataset.take);
    else if (t.dataset.dismiss) openDecisionForm(t.dataset.dismiss, "dismissed");
    else if (t.dataset.snooze) openDecisionForm(t.dataset.snooze, "snoozed");
    else if (t.dataset.goto) {
      closeDialog();
      setTab(t.dataset.goto);
    }
  });
}

async function init() {
  const s = auth()?.session?.();
  if (!s) return;
  LOGIN = s.login;
  RIGHTS = {
    work: (s.access || []).includes("processes.clients"),
    lead: (s.access || []).includes("processes.clients_lead"),
  };
  applyReadonly();
  bindEvents();
  await loadAll();
  $(`.mod-tab[data-cltab="summary"]`).hidden = !RIGHTS.lead;
  let saved = null;
  try {
    saved = localStorage.getItem(LS_TAB);
  } catch {
    /* ignore */
  }
  setTab(saved || (RIGHTS.lead ? "summary" : "clients"));
  setInterval(async () => {
    if (document.hidden || dlg().open || activeTab === "settings") return;
    await loadAll();
    renderActive();
  }, 120000);
}

document.addEventListener("DOMContentLoaded", init);
