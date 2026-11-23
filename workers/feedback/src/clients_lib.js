/**
 * Постоянные клиенты — чистые функции (валидация, справочник условий, шаблоны договора), без D1.
 * Тесты: test/clients.test.mjs
 */

export const CL_KINDS = {
  person: "Частная особа",
  fop: "ФОП",
  company: "Компания",
  shop: "Магазин",
  service: "Другой сервис",
};

// Воронка: порядок важен (конверсии на витрине).
export const CL_STAGES = {
  found: "Найден",
  contacted: "Связались",
  offer: "Предложение",
  trial: "Пробный заказ",
  active: "Постоянный",
  paused: "Пауза",
  lost: "Отказ",
};

export const CL_SOURCES = {
  crm: "Из базы CRM",
  cold: "Холодный поиск",
  referral: "Рекомендация",
  inbound: "Сам обратился",
  other: "Другое",
};

export const CL_CHANNELS = {
  call: "Звонок",
  message: "Мессенджер",
  email: "Email",
  meeting: "Встреча",
  visit: "Визит в СЦ",
  other: "Другое",
};

export const CL_CONTRACT_STATUSES = {
  draft: "Черновик",
  signing: "На подписи",
  active: "Действует",
  terminated: "Расторгнут",
};

export const CL_ACCESS = {
  work: "processes.clients",
  lead: "processes.clients_lead",
};

// Единицы условий; auto — какое условие Jarvis/витрина проверяет по данным CRM.
export const CL_UNITS = {
  pct: "%",
  days: "дн.",
  uah: "грн",
  months: "мес.",
  bool: "да/нет",
  text: "текст",
};
export const CL_AUTO = {
  repair_days: "срок ремонта",
  diag_days: "срок диагностики",
  debt_limit: "лимит долга",
  pay_delay: "отсрочка оплаты",
};

/** Стартовый справочник условий — менеджер может править, скрывать и добавлять свои. */
export const DEFAULT_CONDITIONS = [
  { id: "discount_work", group: "Цена", name: "Скидка на работы", unit: "pct", auto: null, clause: "Знижка на вартість робіт — {value}%." },
  { id: "discount_parts", group: "Цена", name: "Скидка на запчасти", unit: "pct", auto: null, clause: "Знижка на запчастини та матеріали — {value}%." },
  { id: "fixed_prices", group: "Цена", name: "Фиксированные цены на типовые работы", unit: "text", auto: null, clause: "Фіксовані ціни на типові роботи: {value}." },
  { id: "volume_bonus", group: "Цена", name: "Бонус за объём", unit: "text", auto: null, clause: "Бонус за обсяг: {value}." },
  { id: "pay_delay", group: "Оплата", name: "Отсрочка оплаты", unit: "days", auto: "pay_delay", clause: "Оплата виконаних робіт протягом {value} календарних днів з дати видачі техніки." },
  { id: "debt_limit", group: "Оплата", name: "Лимит долга", unit: "uah", auto: "debt_limit", clause: "Максимальна сума неоплачених робіт — {value} грн." },
  { id: "monthly_act", group: "Оплата", name: "Оплата по месячному акту", unit: "bool", auto: null, clause: "Розрахунки здійснюються щомісячно на підставі акта виконаних робіт." },
  { id: "cashless", group: "Оплата", name: "Безнал / оплата на ФОП", unit: "bool", auto: null, clause: "Оплата здійснюється в безготівковій формі на поточний рахунок Виконавця." },
  { id: "diag_days", group: "Сроки", name: "Срок диагностики", unit: "days", auto: "diag_days", clause: "Строк діагностики — не більше {value} робочих днів з дати приймання техніки." },
  { id: "repair_days", group: "Сроки", name: "Срок ремонта", unit: "days", auto: "repair_days", clause: "Строк ремонту — не більше {value} робочих днів з дати погодження вартості (за наявності запчастин)." },
  { id: "priority", group: "Сроки", name: "Приоритет в очереди", unit: "bool", auto: null, clause: "Техніка Замовника ремонтується в пріоритетному порядку." },
  { id: "approve_limit", group: "Согласование", name: "Ремонт без звонка до суммы", unit: "uah", auto: null, clause: "Ремонт вартістю до {value} грн виконується без додаткового погодження із Замовником." },
  { id: "free_diag", group: "Сервис", name: "Бесплатная диагностика", unit: "bool", auto: null, clause: "Діагностика техніки Замовника виконується безоплатно." },
  { id: "courier", group: "Сервис", name: "Курьер: забрать и вернуть", unit: "text", auto: null, clause: "Виконавець забирає та повертає техніку власним кур'єром: {value}." },
  { id: "onsite", group: "Сервис", name: "Выезд мастера", unit: "text", auto: null, clause: "Виїзд майстра на об'єкт Замовника: {value}." },
  { id: "loaner", group: "Сервис", name: "Подменная техника на время ремонта", unit: "bool", auto: null, clause: "На час ремонту Виконавець за можливості надає підмінну техніку." },
  { id: "warranty", group: "Сервис", name: "Расширенная гарантия", unit: "months", auto: null, clause: "Гарантія на виконані роботи — {value} міс." },
  { id: "contact_channel", group: "Сервис", name: "Удобный канал связи", unit: "text", auto: null, clause: "Погодження та повідомлення здійснюються через: {value}." },
];

const LIM = { short: 120, mid: 300, long: 4000 };

function s(v, max) {
  return String(v ?? "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, max);
}
function sLong(v, max = LIM.long) {
  return String(v ?? "").trim().slice(0, max);
}

export function isoDay(v) {
  const t = String(v ?? "").trim().slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(t)) return null;
  const d = new Date(`${t}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? null : t;
}

/** Телефон → последние 10 цифр (как в Jarvis normalize_phone). */
export function normPhone(v) {
  const d = String(v ?? "").replace(/\D/g, "");
  return d.length >= 10 ? d.slice(-10) : d;
}

export class ClientsInputError extends Error {
  constructor(code, message) {
    super(message || code);
    this.code = code;
  }
}

export function clientsRights(access) {
  // work — действия менеджера (только при явном доступе «работа менеджера»);
  // lead — план/удаление; view — смотреть раздел (любой из двух доступов)
  const list = Array.isArray(access) ? access : [];
  const work = list.includes(CL_ACCESS.work);
  const lead = list.includes(CL_ACCESS.lead);
  return { work, lead, view: work || lead };
}

function normContacts(raw) {
  const arr = Array.isArray(raw) ? raw : [];
  return arr
    .slice(0, 12)
    .map((c) => ({
      name: s(c?.name, LIM.short),
      role: s(c?.role, 60),
      phone: s(c?.phone, 40),
      email: s(c?.email, 120),
    }))
    .filter((c) => c.name || c.phone || c.email);
}

function normLegal(raw) {
  const b = raw && typeof raw === "object" ? raw : {};
  const out = {};
  for (const k of ["full_name", "code", "address", "signer", "iban", "bank", "email"]) {
    const v = s(b[k], k === "address" ? LIM.mid : LIM.short);
    if (v) out[k] = v;
  }
  return out;
}

/** Значения условий клиента: {cond_id: {value, status: ok|violated|null, note}}. */
export function normalizeClientConditions(raw, catalog) {
  const ids = new Set((catalog || DEFAULT_CONDITIONS).map((c) => c.id));
  const b = raw && typeof raw === "object" ? raw : {};
  const out = {};
  for (const [id, v] of Object.entries(b)) {
    if (!ids.has(id) || !v || typeof v !== "object") continue;
    const status = v.status === "ok" || v.status === "violated" ? v.status : null;
    out[id] = { value: s(v.value, LIM.mid), status, note: s(v.note, LIM.mid) || null };
  }
  return out;
}

/** Поля клиента из формы. partial=true — только переданные поля. */
export function normalizeClient(raw, { partial = false, catalog } = {}) {
  const b = raw && typeof raw === "object" ? raw : {};
  const has = (k) => Object.prototype.hasOwnProperty.call(b, k);
  const out = {};
  if (!partial || has("name")) {
    out.name = s(b.name, LIM.short);
    if (out.name.length < 2) throw new ClientsInputError("name_required", "Укажите имя клиента или название компании");
  }
  if (!partial || has("kind")) {
    const kind = String(b.kind || "person");
    if (!CL_KINDS[kind]) throw new ClientsInputError("bad_kind", "Неизвестный тип клиента");
    out.kind = kind;
  }
  if (!partial || has("source")) {
    const src = String(b.source || "other");
    out.source = CL_SOURCES[src] ? src : "other";
  }
  if (!partial || has("phones")) {
    const list = (Array.isArray(b.phones) ? b.phones : String(b.phones || "").split(/[,;\n]+/))
      .map(normPhone)
      .filter((p) => p.length === 10);
    out.phones = JSON.stringify([...new Set(list)].slice(0, 10));
  }
  for (const [k, max] of [
    ["area", LIM.short],
    ["devices", LIM.mid],
  ]) {
    if (!partial || has(k)) out[k] = s(b[k], max) || null;
  }
  if (!partial || has("notes")) out.notes = sLong(b.notes) || null;
  if (!partial || has("contacts")) out.contacts = JSON.stringify(normContacts(b.contacts));
  if (!partial || has("legal")) out.legal = JSON.stringify(normLegal(b.legal));
  if (!partial || has("conditions")) out.conditions = JSON.stringify(normalizeClientConditions(b.conditions, catalog));
  if (!partial || has("next_step")) out.next_step = s(b.next_step, LIM.mid) || null;
  if (!partial || has("next_step_at")) out.next_step_at = isoDay(b.next_step_at);
  if (!partial && JSON.parse(out.phones).length === 0) {
    const contacts = JSON.parse(out.contacts);
    if (!contacts.some((c) => c.phone || c.email)) {
      throw new ClientsInputError("contact_required", "Нужен хотя бы один телефон клиента");
    }
  }
  return out;
}

export function normalizeStage(raw) {
  const stage = String(raw?.stage || "");
  if (!CL_STAGES[stage]) throw new ClientsInputError("bad_stage", "Неизвестная стадия");
  const reason = s(raw?.lost_reason, LIM.mid);
  if (stage === "lost" && reason.length < 3) throw new ClientsInputError("reason_required", "Укажите причину отказа");
  return { stage, lost_reason: stage === "lost" ? reason : null, comment: sLong(raw?.comment, 1000) || null };
}

/** Касание: что сделано + следующий шаг (обязателен, кроме «Пауза»/«Отказ»). */
export function normalizeTouch(raw, { stage } = {}) {
  const channel = CL_CHANNELS[raw?.channel] ? raw.channel : "call";
  const text = sLong(raw?.text, 2000);
  if (text.length < 3) throw new ClientsInputError("too_short", "Напишите, что сделано");
  const next_step = s(raw?.next_step, LIM.mid) || null;
  const next_step_at = isoDay(raw?.next_step_at);
  const needNext = stage !== "paused" && stage !== "lost";
  if (needNext && (!next_step || !next_step_at)) {
    throw new ClientsInputError("next_required", "Укажите следующий шаг и дату");
  }
  return { channel, text, next_step, next_step_at };
}

export function normalizeContract(raw, { partial = false } = {}) {
  const b = raw && typeof raw === "object" ? raw : {};
  const has = (k) => Object.prototype.hasOwnProperty.call(b, k);
  const out = {};
  if (!partial) {
    const cid = Number(b.client_id);
    if (!Number.isInteger(cid) || cid <= 0) throw new ClientsInputError("bad_client", "Не выбран клиент");
    out.client_id = cid;
  }
  if (!partial || has("number")) out.number = s(b.number, 60) || null;
  if (!partial || has("kind")) out.kind = b.kind === "person" ? "person" : "legal";
  if (!partial || has("status")) {
    const st = String(b.status || "draft");
    if (!CL_CONTRACT_STATUSES[st]) throw new ClientsInputError("bad_status", "Неизвестный статус договора");
    out.status = st;
  }
  for (const k of ["signed_at", "valid_from", "valid_to"]) {
    if (!partial || has(k)) out[k] = isoDay(b[k]);
  }
  if (out.valid_from && out.valid_to && out.valid_to < out.valid_from) {
    throw new ClientsInputError("bad_dates", "Окончание договора раньше начала");
  }
  if (!partial || has("file_url")) {
    const u = s(b.file_url, 500);
    out.file_url = u ? (/^https?:\/\//i.test(u) ? u : `https://${u}`) : null;
  }
  if (!partial || has("body")) out.body = sLong(b.body, 60000) || null;
  if (!partial || has("notes")) out.notes = sLong(b.notes, 1000) || null;
  if ((out.status === "active" || out.status === "signing") && !partial && !out.valid_to) {
    throw new ClientsInputError("valid_to_required", "Укажите срок действия договора");
  }
  return out;
}

/** Справочник условий от менеджера. */
export function normalizeConditionsCatalog(raw) {
  const arr = Array.isArray(raw) ? raw : [];
  const seen = new Set();
  const out = [];
  for (const c of arr.slice(0, 80)) {
    const name = s(c?.name, LIM.short);
    if (name.length < 2) continue;
    let id = s(c?.id, 40).replace(/[^\w-]/g, "");
    if (!id) id = `c_${Math.random().toString(36).slice(2, 8)}`;
    if (seen.has(id)) continue;
    seen.add(id);
    const unit = CL_UNITS[c?.unit] ? c.unit : "text";
    const auto = CL_AUTO[c?.auto] ? c.auto : null;
    out.push({
      id,
      group: s(c?.group, 40) || "Прочее",
      name,
      unit,
      auto,
      clause: sLong(c?.clause, 500) || `${name}: {value}.`,
      hidden: !!c?.hidden,
    });
  }
  if (!out.length) throw new ClientsInputError("empty", "Справочник не может быть пустым");
  return out;
}

export const DEFAULT_SETTINGS = {
  requisites: {
    name: "",
    code: "",
    address: "",
    iban: "",
    bank: "",
    phone: "",
    email: "",
    signer: "",
    city: "Одеса",
  },
  thresholds: { months: 6, orders: 4, recent_days: 60, recent_orders: 3, gross: 20000 },
  excluded_phones: [],
  touch_every_days: 30,
};

export function normalizeSettings(raw) {
  const b = raw && typeof raw === "object" ? raw : {};
  const req = {};
  for (const k of Object.keys(DEFAULT_SETTINGS.requisites)) req[k] = s(b.requisites?.[k], k === "address" ? LIM.mid : LIM.short);
  const n = (v, def, min, max) => {
    const x = Number(v);
    return Number.isFinite(x) && x >= min && x <= max ? Math.round(x) : def;
  };
  const t = b.thresholds || {};
  const d = DEFAULT_SETTINGS.thresholds;
  return {
    requisites: req,
    thresholds: {
      months: n(t.months, d.months, 2, 12),
      orders: n(t.orders, d.orders, 2, 50),
      recent_days: n(t.recent_days, d.recent_days, 14, 180),
      recent_orders: n(t.recent_orders, d.recent_orders, 2, 50),
      gross: n(t.gross, d.gross, 0, 10_000_000),
    },
    excluded_phones: [
      ...new Set(
        (Array.isArray(b.excluded_phones) ? b.excluded_phones : String(b.excluded_phones || "").split(/[,;\n]+/))
          .map(normPhone)
          .filter((p) => p.length === 10),
      ),
    ].slice(0, 500),
    touch_every_days: n(b.touch_every_days, DEFAULT_SETTINGS.touch_every_days, 3, 180),
  };
}

export function normalizePlan(raw) {
  const n = (k, def, max) => {
    const v = Number(raw?.[k]);
    return Number.isInteger(v) && v >= 0 && v <= max ? v : def;
  };
  return {
    candidates: n("candidates", 10, 500), // разобрать кандидатов из базы
    new_clients: n("new_clients", 3, 100), // новых в воронке (любым способом)
    touches: n("touches", 15, 500), // касаний
    contracts: n("contracts", 1, 50), // договоров оформлено / продлено
  };
}

/** Решение по кандидату из базы. */
export function normalizeDecision(raw) {
  const phone = normPhone(raw?.phone);
  if (phone.length !== 10) throw new ClientsInputError("bad_phone", "Нет телефона кандидата");
  const decision = String(raw?.decision || "");
  if (!["dismissed", "snoozed"].includes(decision)) throw new ClientsInputError("bad_decision", "Неизвестное решение");
  const reason = s(raw?.reason, LIM.mid);
  if (decision === "dismissed" && reason.length < 3) {
    throw new ClientsInputError("reason_required", "Укажите, почему не постоянный");
  }
  const days = Math.min(365, Math.max(7, Number(raw?.days) || 30));
  const until = decision === "snoozed" ? new Date(Date.now() + days * 86400_000).toISOString().slice(0, 10) : null;
  return { phone, decision, reason: reason || null, until };
}

export function describeChanges(before, patch) {
  const labels = {
    name: "имя",
    kind: "тип",
    source: "источник",
    phones: "телефоны",
    area: "район",
    devices: "техника",
    notes: "заметки",
    contacts: "контакты",
    legal: "реквизиты",
    conditions: "условия",
    next_step: "следующий шаг",
    next_step_at: "дата шага",
  };
  return Object.keys(patch)
    .filter((k) => (before?.[k] ?? null) !== (patch[k] ?? null))
    .map((k) => labels[k] || k);
}

// ---------- Шаблоны договора ----------

export const TEMPLATE_KINDS = { legal: "Юрособа / ФОП", person: "Фізична особа" };

/** Подстановки, которые понимает шаблон (для подсказки в редакторе). */
export const TEMPLATE_FIELDS = {
  "номер_договору": "номер договора",
  "дата_договору": "дата договора",
  "місто": "город (настройки)",
  "строк_дії_до": "договор действует до",
  "виконавець_назва": "наша организация",
  "виконавець_код": "наш ЄДРПОУ / ІПН",
  "виконавець_адреса": "наш адрес",
  "виконавець_iban": "наш IBAN",
  "виконавець_банк": "наш банк",
  "виконавець_телефон": "наш телефон",
  "виконавець_email": "наш email",
  "виконавець_підписант": "кто подписывает от нас",
  "клієнт_назва": "клиент (полное название / ПІБ)",
  "клієнт_код": "ЄДРПОУ / ІПН клиента",
  "клієнт_адреса": "адрес клиента",
  "клієнт_телефон": "телефоны клиента",
  "клієнт_email": "email клиента",
  "клієнт_iban": "IBAN клиента",
  "клієнт_підписант": "кто подписывает от клиента",
  "строк_діагностики": "срок диагностики (из условий, иначе 3)",
  "строк_ремонту": "срок ремонта (из условий, иначе 14)",
  "гарантія": "гарантия, мес. (из условий, иначе 3)",
  "індивідуальні_умови": "список индивидуальных условий клиента",
};

export const DEFAULT_TEMPLATES = {
  legal: `# ДОГОВІР № {{номер_договору}}
## про надання послуг з ремонту та технічного обслуговування електронної техніки

м. {{місто}} · {{дата_договору}}

{{виконавець_назва}} (далі — «Виконавець»), в особі {{виконавець_підписант}}, з однієї сторони, та {{клієнт_назва}} (далі — «Замовник»), в особі {{клієнт_підписант}}, з другої сторони (разом — «Сторони»), уклали цей Договір про таке.

## 1. Предмет договору
1.1. Виконавець зобов'язується за завданням Замовника виконувати діагностику, ремонт і технічне обслуговування електронної та побутової техніки Замовника (далі — «Техніка»), а Замовник зобов'язується приймати та оплачувати виконані роботи.
1.2. Перелік робіт, їх вартість і строки щодо кожної одиниці Техніки визначаються в квитанції (замовленні) Виконавця, що оформлюється під час приймання Техніки та є невід'ємною частиною цього Договору.

## 2. Приймання та видача Техніки
2.1. Техніка приймається в сервісному центрі Виконавця або кур'єром Виконавця (якщо це передбачено індивідуальними умовами). Під час приймання оформлюється квитанція із зазначенням моделі, серійного номера (за наявності), комплектності, зовнішнього стану та заявленої несправності.
2.2. Видача Техніки здійснюється представнику Замовника за пред'явлення квитанції або за усним/письмовим підтвердженням уповноваженої особи Замовника.
2.3. Техніка, не забрана Замовником протягом 60 календарних днів після повідомлення про готовність, може зберігатися платно за тарифами Виконавця.

## 3. Діагностика та погодження вартості
3.1. Діагностика виконується протягом {{строк_діагностики}} робочих днів з дати приймання Техніки.
3.2. За результатами діагностики Виконавець повідомляє Замовнику вартість і строк ремонту. Ремонт розпочинається після погодження Замовником (телефоном, у месенджері або електронною поштою), якщо інше не передбачено індивідуальними умовами.
3.3. У разі відмови Замовника від ремонту Техніка повертається в стані, в якому була прийнята; вартість діагностики оплачується відповідно до прейскуранта Виконавця, якщо інше не передбачено індивідуальними умовами.

## 4. Строки виконання робіт
4.1. Строк ремонту — не більше {{строк_ремонту}} робочих днів з дати погодження вартості за наявності необхідних запчастин.
4.2. Якщо запчастини потрібно замовити, строк ремонту продовжується на час їх доставки, про що Виконавець повідомляє Замовника.

## 5. Вартість і порядок розрахунків
5.1. Вартість робіт визначається за прейскурантом Виконавця з урахуванням індивідуальних умов Замовника і погоджується Сторонами до початку ремонту.
5.2. Оплата здійснюється під час видачі Техніки готівкою, карткою або в безготівковій формі на рахунок Виконавця, якщо інше не передбачено індивідуальними умовами.

## 6. Гарантійні зобов'язання
6.1. Виконавець надає гарантію на виконані роботи та встановлені запчастини строком {{гарантія}} міс. з дати видачі Техніки.
6.2. Гарантія не поширюється на випадки механічних пошкоджень, потрапляння рідини, порушення правил експлуатації, втручання третіх осіб, а також на несправності, не пов'язані з виконаним ремонтом.

## 7. Індивідуальні умови
{{індивідуальні_умови}}

## 8. Відповідальність сторін
8.1. За невиконання або неналежне виконання зобов'язань Сторони несуть відповідальність відповідно до чинного законодавства України.
8.2. Виконавець не несе відповідальності за збереження даних на Техніці. Замовник самостійно забезпечує резервне копіювання інформації перед передачею Техніки в ремонт.
8.3. Сторони звільняються від відповідальності за невиконання зобов'язань унаслідок обставин непереборної сили (форс-мажору), підтверджених у встановленому порядку.

## 9. Строк дії договору
9.1. Договір набирає чинності з дати підписання і діє до {{строк_дії_до}}.
9.2. Якщо жодна зі Сторін не повідомила письмово про припинення Договору не пізніше ніж за 30 днів до закінчення строку його дії, Договір вважається продовженим на той самий строк на тих самих умовах.
9.3. Кожна зі Сторін може розірвати Договір, письмово повідомивши іншу Сторону не пізніше ніж за 30 календарних днів, за умови виконання зобов'язань щодо вже прийнятої Техніки та проведення взаєморозрахунків.

## 10. Конфіденційність і персональні дані
10.1. Сторони зобов'язуються не розголошувати інформацію, отриману під час виконання Договору, у тому числі дані, що зберігаються на Техніці.
10.2. Підписуючи Договір, представники Сторін надають згоду на обробку своїх персональних даних з метою виконання Договору відповідно до Закону України «Про захист персональних даних».

## 11. Інші умови
11.1. Усі зміни та доповнення до Договору дійсні, якщо вони оформлені письмово та підписані Сторонами.
11.2. Договір складено у двох примірниках, що мають однакову юридичну силу, по одному для кожної зі Сторін.

## 12. Реквізити та підписи сторін
**Виконавець:** {{виконавець_назва}}
Код: {{виконавець_код}}
Адреса: {{виконавець_адреса}}
IBAN: {{виконавець_iban}}, {{виконавець_банк}}
Тел.: {{виконавець_телефон}} · {{виконавець_email}}
Підпис: ____________ / {{виконавець_підписант}} /

**Замовник:** {{клієнт_назва}}
Код: {{клієнт_код}}
Адреса: {{клієнт_адреса}}
IBAN: {{клієнт_iban}}
Тел.: {{клієнт_телефон}} · {{клієнт_email}}
Підпис: ____________ / {{клієнт_підписант}} /
`,
  person: `# ДОГОВІР № {{номер_договору}}
## про сервісне обслуговування техніки фізичної особи

м. {{місто}} · {{дата_договору}}

{{виконавець_назва}} (далі — «Виконавець») та {{клієнт_назва}} (далі — «Клієнт») уклали цей Договір про таке.

## 1. Предмет договору
1.1. Виконавець на постійній основі надає Клієнту послуги з діагностики та ремонту електронної і побутової техніки на індивідуальних умовах, зазначених у розділі 4.
1.2. Перелік робіт, вартість і строки щодо кожного звернення фіксуються в квитанції, яку Клієнт отримує під час здачі техніки.

## 2. Діагностика, погодження і строки
2.1. Діагностика — до {{строк_діагностики}} робочих днів, ремонт — до {{строк_ремонту}} робочих днів з дати погодження вартості (за наявності запчастин).
2.2. Ремонт розпочинається після погодження вартості з Клієнтом, якщо інше не передбачено індивідуальними умовами.

## 3. Оплата і гарантія
3.1. Оплата здійснюється під час видачі техніки, якщо інше не передбачено індивідуальними умовами.
3.2. Гарантія на виконані роботи та встановлені запчастини — {{гарантія}} міс. з дати видачі. Гарантія не поширюється на механічні пошкодження, потрапляння рідини та порушення правил експлуатації.
3.3. Виконавець не несе відповідальності за збереження даних на техніці; Клієнт самостійно робить резервні копії.

## 4. Індивідуальні умови
{{індивідуальні_умови}}

## 5. Строк дії
5.1. Договір діє з дати підписання до {{строк_дії_до}} і продовжується на той самий строк, якщо жодна зі Сторін письмово не заявила про припинення.
5.2. Клієнт надає згоду на обробку своїх персональних даних для виконання цього Договору відповідно до Закону України «Про захист персональних даних».

## 6. Підписи сторін
**Виконавець:** {{виконавець_назва}}, код {{виконавець_код}}, {{виконавець_адреса}}, тел. {{виконавець_телефон}}
Підпис: ____________ / {{виконавець_підписант}} /

**Клієнт:** {{клієнт_назва}}, тел. {{клієнт_телефон}}
Підпис: ____________
`,
};

export function normalizeTemplate(raw) {
  const kind = TEMPLATE_KINDS[raw?.kind] ? raw.kind : null;
  if (!kind) throw new ClientsInputError("bad_kind", "Неизвестный вид шаблона");
  const body = String(raw?.body ?? "").replace(/\r\n/g, "\n").slice(0, 60000);
  if (body.trim().length < 50) throw new ClientsInputError("too_short", "Шаблон слишком короткий");
  return { kind, body };
}

/** Текст пункта условия: «{value}» → значение; для bool — как есть. */
export function conditionClause(cond, value) {
  const v = String(value ?? "").trim();
  if (cond.unit === "bool") return cond.clause.replace("{value}", "так");
  return cond.clause.replace("{value}", v);
}

/** Собрать договор из шаблона (то же делает витрина; функция для тестов и единообразия). */
export function renderContract(template, { client, contract, requisites, catalog }) {
  const legal = client?.legal || {};
  const conds = client?.conditions || {};
  const cat = (catalog || DEFAULT_CONDITIONS).filter((c) => !c.hidden || conds[c.id]);
  const items = cat.filter((c) => {
    const v = conds[c.id];
    if (!v) return false;
    return c.unit === "bool" ? v.value !== "" && v.value !== "0" && v.value !== "ні" : String(v.value || "").trim() !== "";
  });
  const val = (id, def) => (conds[id] && String(conds[id].value || "").trim()) || def;
  const r = requisites || {};
  const blank = "________________";
  const fields = {
    "номер_договору": contract?.number || blank,
    "дата_договору": fmtDayUk(contract?.signed_at || contract?.valid_from) || blank,
    "місто": r.city || blank,
    "строк_дії_до": fmtDayUk(contract?.valid_to) || blank,
    "виконавець_назва": r.name || blank,
    "виконавець_код": r.code || blank,
    "виконавець_адреса": r.address || blank,
    "виконавець_iban": r.iban || blank,
    "виконавець_банк": r.bank || blank,
    "виконавець_телефон": r.phone || blank,
    "виконавець_email": r.email || blank,
    "виконавець_підписант": r.signer || blank,
    "клієнт_назва": legal.full_name || client?.name || blank,
    "клієнт_код": legal.code || blank,
    "клієнт_адреса": legal.address || blank,
    "клієнт_телефон": (client?.phones || []).map(fmtPhone).join(", ") || blank,
    "клієнт_email": legal.email || blank,
    "клієнт_iban": legal.iban || blank,
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

const UK_MONTHS = ["січня", "лютого", "березня", "квітня", "травня", "червня", "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"];
export function fmtDayUk(iso) {
  const d = isoDay(iso);
  if (!d) return "";
  const [y, m, dd] = d.split("-").map(Number);
  return `«${dd}» ${UK_MONTHS[m - 1]} ${y} р.`;
}
export function fmtPhone(p) {
  const d = normPhone(p);
  return d.length === 10 ? `+38 ${d.slice(0, 3)} ${d.slice(3, 6)} ${d.slice(6, 8)} ${d.slice(8)}` : String(p || "");
}
