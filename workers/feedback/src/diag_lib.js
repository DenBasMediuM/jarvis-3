/**
 * Платная диагностика — чистые функции (валидация, статусы, план), без D1.
 * Тесты: test/diag.test.mjs
 */

export const DG_ACCESS = { work: "processes.diag", lead: "processes.diag_lead" };

// Путь записи: консультация с мастером → предложено клиенту → согласовано / отказ.
// «Не нужна» — мастер сказал, что диагностика простая (тоже результат работы менеджера).
export const DG_STATUSES = {
  consult: "Консультация с мастером",
  offered: "Предложено клиенту",
  agreed: "Согласовано",
  declined: "Клиент отказался",
  not_needed: "Платная не нужна",
};
export const DG_SOURCES = { buffer: "Буфер", undiagnosed: "Ещё не продиагностировано", other: "Другое" };

export const DEFAULT_DIAG_PLAN = { daily_agreed: 1, daily_offered: 2 };

/** Подсказки цены по категориям (менеджер правит в настройках). */
export const DEFAULT_PRICES = {
  power_station: 1000,
  inverter_ups: 1000,
  laptop: 1000,
  pc: 1000,
  tv_monitor: 1000,
  console: 1500,
  printer: 750,
  coffee: 750,
  robot_vac: 750,
  audio: 750,
  tools: 750,
  appliances: 750,
  phone_tablet: 500,
  other: 500,
};

export class DiagInputError extends Error {
  constructor(code, message) {
    super(message || code);
    this.code = code;
  }
}

function s(v, max) {
  return String(v ?? "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, max);
}
function sLong(v, max = 2000) {
  return String(v ?? "").trim().slice(0, max);
}

export function diagRights(access) {
  // work — действия менеджера (только при явном доступе «работа менеджера»);
  // lead — план/удаление; view — смотреть раздел (любой из двух доступов)
  const list = Array.isArray(access) ? access : [];
  const work = list.includes(DG_ACCESS.work);
  const lead = list.includes(DG_ACCESS.lead);
  return { work, lead, view: work || lead };
}

function money(v) {
  if (v === undefined || v === null || String(v).trim() === "") return null;
  const n = Number(String(v).replace(",", ".").replace(/\s/g, ""));
  if (!Number.isFinite(n) || n < 0 || n > 100000) throw new DiagInputError("bad_price", "Цена — число от 0 до 100 000");
  return Math.round(n);
}

/** Проверка полей записи в итоговом виде (после слияния с текущей записью). */
export function validateCase(c) {
  if (!/^\d{4,}$/.test(String(c.ticket || ""))) throw new DiagInputError("bad_ticket", "Укажите № квитанции из Gincore");
  if (!DG_STATUSES[c.status]) throw new DiagInputError("bad_status", "Неизвестный статус");
  if (["offered", "agreed", "not_needed"].includes(c.status) && !c.master) {
    throw new DiagInputError("master_required", "Укажите мастера, с которым консультировались");
  }
  if (c.status === "agreed" && !(Number(c.price) > 0)) throw new DiagInputError("price_required", "Укажите согласованную цену диагностики");
  if (c.status === "declined" && String(c.decline_reason || "").length < 3) {
    throw new DiagInputError("reason_required", "Укажите, почему клиент отказался");
  }
  if (c.status === "not_needed" && String(c.comment || "").length < 3) {
    throw new DiagInputError("comment_required", "Коротко: почему платная диагностика не нужна");
  }
  return c;
}

/** Поля записи из формы. partial — только переданные. */
export function normalizeCase(raw, { partial = false } = {}) {
  const b = raw && typeof raw === "object" ? raw : {};
  const has = (k) => Object.prototype.hasOwnProperty.call(b, k);
  const out = {};
  if (!partial || has("ticket")) out.ticket = String(b.ticket ?? "").replace(/\D/g, "");
  if (!partial || has("status")) out.status = String(b.status || "consult");
  if (!partial || has("source")) out.source = DG_SOURCES[b.source] ? b.source : "other";
  for (const [k, max] of [
    ["device", 160],
    ["category", 40],
    ["master", 120],
    ["decline_reason", 300],
  ]) {
    if (!partial || has(k)) out[k] = s(b[k], max) || null;
  }
  if (!partial || has("consult_note")) out.consult_note = sLong(b.consult_note, 1000) || null;
  if (!partial || has("comment")) out.comment = sLong(b.comment, 1000) || null;
  if (!partial || has("price")) out.price = money(b.price);
  if (!partial || has("prepay")) out.prepay = b.prepay ? 1 : 0;
  return out;
}

export function normalizeDiagPlan(raw) {
  const n = (k, def, max) => {
    const v = Number(raw?.[k]);
    return Number.isInteger(v) && v >= 0 && v <= max ? v : def;
  };
  return {
    daily_agreed: n("daily_agreed", DEFAULT_DIAG_PLAN.daily_agreed, 50),
    daily_offered: n("daily_offered", DEFAULT_DIAG_PLAN.daily_offered, 100),
  };
}

export function normalizePrices(raw) {
  const b = raw && typeof raw === "object" ? raw : {};
  const out = {};
  for (const k of Object.keys(DEFAULT_PRICES)) {
    const v = Number(b[k]);
    out[k] = Number.isFinite(v) && v >= 0 && v <= 100000 ? Math.round(v) : DEFAULT_PRICES[k];
  }
  return out;
}

/** Текст для журнала о смене статуса. */
export function statusLine(before, after) {
  if (!before) return `${DG_STATUSES[after.status]}${after.price ? ` · ${after.price} грн` : ""}`;
  if (before.status === after.status) return null;
  const tail =
    after.status === "agreed"
      ? ` · ${after.price} грн${after.prepay ? " (предоплата)" : ""}`
      : after.status === "declined"
        ? `: ${after.decline_reason}`
        : after.status === "not_needed"
          ? `: ${after.comment}`
          : "";
  return `${DG_STATUSES[before.status]} → ${DG_STATUSES[after.status]}${tail}`;
}
