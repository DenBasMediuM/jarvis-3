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
  for (const k of ["full_name", "code", "address", "signer", "basis", "iban", "bank", "mfo", "email"]) {
    const v = s(b[k], k === "address" || k === "basis" ? LIM.mid : LIM.short);
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
  if (!partial || has("subject")) out.subject = s(b.subject, LIM.mid) || null;
  if (!partial || has("price")) {
    const raw = String(b.price ?? "").replace(/\s/g, "").replace(",", ".");
    if (raw === "") out.price = null;
    else {
      const n = Number(raw);
      if (!Number.isFinite(n) || n < 0 || n > 100_000_000) throw new ClientsInputError("bad_price", "Ціна договору — число");
      out.price = Math.round(n * 100) / 100;
    }
  }
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
  // Реквизиты сервиса не храним в коде (репозиторий публичный): их задают в «Настройках» раздела
  // или заливают в базу облака командой из data/ (см. README).
  requisites: {
    name: "",
    full_name: "",
    signer: "",
    basis: "",
    code: "",
    address: "",
    iban: "",
    bank: "",
    mfo: "",
    bank_code: "",
    phone: "",
    email: "",
    city: "Одеса",
  },
  thresholds: { months: 6, orders: 4, recent_days: 60, recent_orders: 3, gross: 20000 },
  excluded_phones: [],
  touch_every_days: 30,
};

export function normalizeSettings(raw) {
  const b = raw && typeof raw === "object" ? raw : {};
  const req = {};
  for (const k of Object.keys(DEFAULT_SETTINGS.requisites)) {
    req[k] = s(b.requisites?.[k], k === "address" || k === "basis" || k === "full_name" ? LIM.mid : LIM.short);
  }
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
export const DEFAULT_SUBJECT = "50310000-1 — Технічне обслуговування і ремонт офісної техніки";

export const TEMPLATE_FIELDS = {
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

export const DEFAULT_TEMPLATES = {
  legal: `# Договір № {{номер_договору}}

м. {{місто}} · {{дата_договору}}

{{клієнт_назва}}, надалі іменується Замовник, в особі {{клієнт_підписант}}, який діє на підставі {{клієнт_підстава}}, з однієї сторони, і {{виконавець_повна_назва}}, надалі іменується Виконавець, в особі {{виконавець_підписант}}, що діє на підставі {{виконавець_підстава}}, з іншої сторони, разом Сторони, а кожне окремо – Сторона, уклали цей договір (надалі – Договір) про наступне:

## 1. Предмет Договору
1.1. На умовах Договору Виконавець зобов’язується надавати, а Замовник приймати та оплатити згідно коду ДК 021-2015: {{предмет_дк}}, надалі – Послуги.

## 2. Якість послуг
2.1. Виконавець повинен надати Замовнику Послуги, якість яких відповідає умовам цього Договору, вимогам відповідних технічних умов, стандартів та інструкцій, що діють на території України та/або передбачені виробниками обладнання, щодо якого надаються Послуги.
2.2. Виконавець забезпечує якість наданих послуг, надійність і працездатність обладнання та систем.

## 3. Ціна Договору
3.1. Ціна Договору складає {{ціна_договору}} грн. ({{ціна_прописом}}) без ПДВ.
3.2. Ціна Договору може бути зменшена лише за взаємною згодою Сторін.

## 4. Порядок здійснення оплати та приймання – передачі послуг
4.1. Розрахунки за цим Договором здійснюються у безготівковій формі, шляхом перерахування коштів Замовником на поточний рахунок Виконавця, протягом {{строк_оплати}} робочих днів після підписання Сторонами Акту здачі-приймання робіт (надання послуг), при наявності фінансування. Датою оплати вважається дата списання коштів з поточного рахунку Замовника.
4.2. Виконавець протягом 3 (трьох) робочих днів після закінчення надання послуг надає Замовнику для підписання Акти здачі-приймання робіт (надання послуг).
4.3. Замовник протягом 5 (п'яти) робочих днів після отримання від Виконавця двох примірників Акту здачі-приймання робіт (надання послуг) повертає один підписаний екземпляр Виконавцю або направляє мотивовану відмову від підписання Акту здачі-приймання робіт (надання послуг).
4.4. У випадку мотивованої письмової відмови Замовника у прийманні наданих Послуг Сторонами складається акт із переліком необхідних доробок із зазначенням строків їх виконання. В зазначені строки Виконавець зобов'язаний усунути недоліки.
4.5. Належним чином оформлений і підписаний Акт здачі-приймання робіт (надання послуг) є підтвердженням приймання Послуг за якістю і кількістю.
4.6. Оплата Послуг здійснюється в межах затверджених кошторисних призначень на відповідний період.
4.7. У разі затримки фінансування оплата Виконавцю проводиться Замовником протягом 5 (п’яти) робочих днів з дати отримання фінансування.

## 5. Порядок надання послуг
5.1. Виконавець надає послуги, передбачені даним Договором, з використанням власних матеріалів протягом дії даного Договору.
5.2. Індивідуальні умови обслуговування Замовника:
{{індивідуальні_умови}}

## 6. Права та обов’язки Сторін
6.1. Замовник зобов’язаний:
6.1.1. Своєчасно та в повному обсязі сплачувати за надані Послуги.
6.1.2. Прийняти Послуги Виконавця, за умови відсутності зауважень, шляхом підписання Акту здачі-приймання робіт (надання послуг) та оплатити Послуги згідно з п. 4.1 цього Договору.
6.1.3. Забезпечити Виконавцю вільний доступ до об’єкту протягом усього терміну надання Послуг.
6.2. Замовник має право:
6.2.1. Контролювати надання Послуг протягом строку дії Договору, не втручаючись в оперативно-господарську діяльність Виконавця.
6.2.2. За згодою Виконавця зменшувати обсяг надання Послуг та ціну Договору залежно від реального фінансування. У такому разі Сторони вносять відповідні зміни до Договору.
6.2.3. Відмовитись від прийняття наданих Виконавцем Послуг, якщо надані Послуги не відповідають умовам даного Договору, і вимагати від Виконавця усунення недоліків за його рахунок.
6.2.4. Достроково розірвати цей Договір у разі невиконання Виконавцем зобов’язань за цим Договором, письмово повідомивши Виконавця про розірвання цього Договору не пізніше ніж за 10 (десять) календарних днів до дати розірвання шляхом направлення додаткової угоди рекомендованим листом з повідомленням про вручення або кур’єрською доставкою.
6.2.5. Повернути Акт здачі-приймання робіт (надання послуг) Виконавцю без здійснення оплати в разі неналежного його оформлення (відсутність печатки, підписів тощо).
6.3. Виконавець зобов’язаний:
6.3.1. Забезпечити надання Послуг у строки та порядку, встановлені Договором.
6.3.2. Нести ризик випадкової загибелі або випадкового пошкодження матеріалів та обладнання; нести ризик випадкової загибелі або випадкового пошкодження результату надання Послуги до її приймання Замовником.
6.3.3. При наданні послуг дотримуватися необхідних заходів протипожежної безпеки, техніки безпеки, з охорони праці й охорони навколишнього середовища протягом усього терміну надання Послуг відповідно до діючих норм і правил України.
6.3.4. Надавати Послуги у повній відповідності з діючими нормативно-технічними документами.
6.3.5. Забезпечити наявність відповідних дозволів, допусків тощо на право виконання певних видів послуг Виконавцем (в разі необхідності).
6.4. Виконавець має право:
6.4.1. Своєчасно та в повному обсязі отримувати плату за надані Послуги.
6.4.2. У разі невиконання зобов’язань Замовником достроково розірвати цей Договір, попередньо повідомивши Замовника у письмовій формі за 10 (десять) календарних днів до дати розірвання шляхом направлення додаткової угоди рекомендованим листом з повідомленням про вручення або кур’єрською доставкою.

## 7. Відповідальність Сторін та вирішення спорів
7.1. У випадку порушення зобов'язання, що виникає з цього Договору (далі – Порушення Договору), Сторона несе відповідальність, визначену цим Договором та чинним законодавством України.
7.2. Порушенням Договору є його невиконання або неналежне виконання, тобто виконання з порушенням умов, визначених змістом цього Договору.
7.3. Виконавець несе відповідальність за поведінку своїх працівників на об’єкті Замовника, вживає заходів, спрямованих на попередження порушень його працівниками технологічної дисципліни, громадського порядку, недопущення протизаконної поведінки на об’єкті Замовника.
7.4. Виконавець несе повну матеріальну відповідальність за збитки, спричинені Замовнику внаслідок неналежного виконання своїх зобов’язань.
7.5. У випадку порушення Договору будь-якою із Сторін уповноважена Сторона має право відтермінувати виконання своїх обов'язків за цим Договором до моменту належного виконання винною Стороною порушених зобов'язань.
7.6. Сторона, що порушила цей Договір, зобов'язана відшкодувати збитки, завдані таким порушенням, незалежно від вжиття іншою Стороною будь-яких заходів щодо запобігання збиткам або зменшення збитків.
7.7. Сплата Стороною визначених цим Договором та (або) чинним законодавством України штрафних санкцій не звільняє її від обов'язку відшкодувати за вимогою іншої Сторони збитки, завдані порушенням Договору (реальні збитки), у повному обсязі, а відшкодування збитків не звільняє її від обов’язку сплатити за вимогою іншої Сторони штрафні санкції у повному обсязі.
7.8. Сплата Стороною штрафних санкцій та (або) відшкодування збитків, завданих порушенням Договору, не звільняє її від обов’язку виконати цей Договір в натурі, якщо інше прямо не передбачено чинним законодавством України.
7.9. Нарахування пені та штрафних санкцій до Замовника не проводиться у випадку затримки фінансування та/або несвоєчасного проведення оплати з боку органів Державної казначейської служби України, або у випадку відсутності на дату платежу коштів, призначених на фінансування відповідних видатків.
7.10. Замовник та Виконавець є невинуватими, якщо доведуть, що вжили всіх залежних від них заходів щодо належного виконання своїх зобов’язань за цим Договором.
7.11. Виконавець несе матеріальну відповідальність за шкоду, заподіяну третім особам під час надання Послуг за цим Договором, у тому числі пов’язану з наданням неякісних Послуг, завданням шкоди життю та/або здоров’ю інших осіб та іншими негативними наслідками, які можуть настати в процесі виконання цього Договору.
7.12. У випадку виникнення спорів або розбіжностей Сторони зобов’язуються вирішувати їх шляхом взаємних переговорів та консультацій.
7.13. У разі недосягнення Сторонами згоди спори (розбіжності) вирішуються у судовому порядку згідно з чинним законодавством України із обов’язковим застосуванням порядку досудового врегулювання спорів, що передбачений розділом ІІ Господарського процесуального кодексу України.

## 8. Обставини непереборної сили (форс-мажор)
8.1. Сторони звільняються від відповідальності за невиконання або неналежне виконання зобов’язань за цим Договором у разі виникнення обставин непереборної сили, які не існували під час укладання Договору та виникли поза волею Сторін, а саме: стихійне лихо, аварія, катастрофа, епідемія, епізоотія тощо.
8.2. Сторона, що не може виконати зобов’язання за цим Договором унаслідок дії обставин непереборної сили, повинна не пізніше 10 (десяти) робочих днів з моменту їх виникнення повідомити про це іншу Сторону у письмовій формі.
8.3. Доказом виникнення обставин непереборної сили та строку їх дії є відповідні документи, які видаються Торгово-промисловою палатою України або іншими уповноваженими на це органами.
8.4. У разі, якщо дія обставин непереборної сили триває більш ніж 30 (тридцять) робочих днів, кожна із Сторін в установленому порядку має право ініціювати розірвання цього Договору.
8.5. Неповідомлення або несвоєчасне повідомлення про настання або припинення обставин непереборної сили позбавляє Сторони права щодо посилання на них.

## 9. Строк дії Договору та інші умови
9.1. Договір діє з моменту підписання до {{строк_дії_до}}, а в частині виконання грошових зобов’язань – до повного виконання зобов’язань.
9.2. Договір може бути припинений, у тому числі внаслідок його одностороннього розірвання або відмови від нього будь-якою із Сторін.
9.3. Будь-які укладені протягом строку дії Договору в письмовій формі та підписані Сторонами додаткові угоди, додатки, інші документи з питань врегулювання зобов’язань за Договором є невід’ємними частинами Договору та припиняють свою дію разом з ним, якщо інше не встановлено такими документами.
9.4. Договір складено українською мовою в двох однакових примірниках, по одному примірнику для кожної Сторони.

## 10. Реквізити та підписи Сторін
**ЗАМОВНИК:** {{клієнт_назва}}
Код ЄДРПОУ: {{клієнт_код}}
Адреса: {{клієнт_адреса}}
р/р {{клієнт_iban}}, {{клієнт_банк}}, МФО {{клієнт_мфо}}
Тел.: {{клієнт_телефон}} · {{клієнт_email}}
________________ / {{клієнт_підписант}} /
МП

**ВИКОНАВЕЦЬ:** {{виконавець_назва}}
Адреса: {{виконавець_адреса}}
IBAN: {{виконавець_iban}}
ІПН/ЄДРПОУ: {{виконавець_код}}
Банк: {{виконавець_банк}}, МФО {{виконавець_мфо}}, ЄДРПОУ банку {{виконавець_єдрпоу_банку}}
Тел.: {{виконавець_телефон}} · e-mail: {{виконавець_email}}
________________ {{виконавець_назва}}
МП
`,
  person: `# ДОГОВІР № {{номер_договору}}
## про сервісне обслуговування техніки фізичної особи

м. {{місто}} · {{дата_договору}}

{{виконавець_повна_назва}} (далі — «Виконавець»), в особі {{виконавець_підписант}}, що діє на підставі {{виконавець_підстава}}, та {{клієнт_назва}} (далі — «Клієнт») уклали цей Договір про таке.

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
**Виконавець:** {{виконавець_повна_назва}}, ІПН {{виконавець_код}}, {{виконавець_адреса}}, IBAN {{виконавець_iban}} ({{виконавець_банк}}), тел. {{виконавець_телефон}}
Підпис: ____________ {{виконавець_назва}}

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
    "предмет_дк": contract?.subject || DEFAULT_SUBJECT,
    "ціна_договору": contract?.price ? fmtMoneyUk(contract.price) : blank,
    "ціна_прописом": contract?.price ? uahWords(contract.price) : blank,
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
export function uahWords(amount) {
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
export function daysWords(v) {
  const n = Number(String(v).replace(",", "."));
  if (!Number.isInteger(n) || n <= 0) return String(v);
  return W_GEN[n] ? `${n} (${W_GEN[n]})` : String(n);
}
export function fmtMoneyUk(v) {
  const n = Number(v || 0);
  return Number.isInteger(n) ? String(n) : n.toFixed(2);
}
