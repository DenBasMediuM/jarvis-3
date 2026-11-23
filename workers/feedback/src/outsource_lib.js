/**
 * Аутсорс мастера — чистые функции (валидация форм, права), без D1.
 * Тесты: test/outsource.test.mjs
 */

export const OUT_KINDS = {
  master_home: "Мастер на дому",
  master_sc: "Мастер другого СЦ",
  service: "Сервисный центр",
};

// Воронка: порядок важен (для конверсий на витрине).
export const OUT_STAGES = {
  found: "Найден",
  contacted: "Связались",
  trial: "Пробник",
  regular: "Постоянный",
  paused: "Пауза",
  lost: "Отказ",
};

export const OUT_DECISIONS = {
  take: "Берём в постоянные",
  again: "Ещё пробник",
  reject: "Отказ",
};

export const OUT_ACCESS = {
  work: "processes.outsource", // менеджер: воронка, формы
  lead: "processes.outsource_lead", // руководитель: сводка, план
};

const LIM = {
  short: 120,
  mid: 300,
  long: 2000,
};

function s(v, max) {
  return String(v ?? "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, max);
}

function sLong(v, max = LIM.long) {
  return String(v ?? "")
    .trim()
    .slice(0, max);
}

export function isoDay(v) {
  const t = String(v ?? "").trim().slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(t)) return null;
  const d = new Date(`${t}T00:00:00Z`);
  return Number.isNaN(d.getTime()) ? null : t;
}

export class OutsourceInputError extends Error {
  constructor(code, message) {
    super(message || code);
    this.code = code;
  }
}

/** Что пользователь может в разделе: {work, lead}. */
export function outsourceRights(access) {
  // work — действия менеджера (только при явном доступе «работа менеджера»);
  // lead — план/удаление; view — смотреть раздел (любой из двух доступов)
  const list = Array.isArray(access) ? access : [];
  const work = list.includes(OUT_ACCESS.work);
  const lead = list.includes(OUT_ACCESS.lead);
  return { work, lead, view: work || lead };
}

/** Поля кандидата из формы. partial=true — только переданные поля (правка). */
export function normalizeCandidate(raw, { partial = false } = {}) {
  const b = raw && typeof raw === "object" ? raw : {};
  const out = {};
  const has = (k) => Object.prototype.hasOwnProperty.call(b, k);
  if (!partial || has("name")) {
    out.name = s(b.name, LIM.short);
    if (out.name.length < 2) throw new OutsourceInputError("name_required", "Укажите имя мастера или название сервиса");
  }
  if (!partial || has("kind")) {
    const kind = String(b.kind || "master_home");
    if (!OUT_KINDS[kind]) throw new OutsourceInputError("bad_kind", "Неизвестный тип кандидата");
    out.kind = kind;
  }
  for (const [k, max] of [
    ["contact", LIM.short],
    ["area", LIM.short],
    ["devices", LIM.mid],
    ["terms", LIM.mid],
    ["crm_engineer", LIM.short],
    ["cash_contractor", LIM.short],
  ]) {
    if (!partial || has(k)) out[k] = s(b[k], max) || null;
  }
  if (!partial || has("source_url")) {
    const u = s(b.source_url, 500);
    out.source_url = u ? (/^https?:\/\//i.test(u) ? u : `https://${u}`) : null;
  }
  if (!partial || has("notes")) out.notes = sLong(b.notes) || null;
  if (!partial && !out.contact && !out.source_url) {
    throw new OutsourceInputError("contact_required", "Нужен контакт или ссылка на объявление");
  }
  return out;
}

/** Смена стадии воронки. */
export function normalizeStage(raw) {
  const stage = String(raw?.stage || "");
  if (!OUT_STAGES[stage]) throw new OutsourceInputError("bad_stage", "Неизвестная стадия");
  const reason = s(raw?.lost_reason, LIM.mid);
  if (stage === "lost" && reason.length < 3) {
    throw new OutsourceInputError("reason_required", "Укажите причину отказа");
  }
  return { stage, lost_reason: stage === "lost" ? reason : null, comment: sLong(raw?.comment, 1000) || null };
}

/** Форма «Передача устройства» (пробник или очередная единица). */
export function normalizeTrial(raw, { today } = {}) {
  const b = raw && typeof raw === "object" ? raw : {};
  const candidate_id = Number(b.candidate_id);
  if (!Number.isInteger(candidate_id) || candidate_id <= 0) {
    throw new OutsourceInputError("bad_candidate", "Не выбран аутсорсер");
  }
  const ticket = String(b.ticket ?? "").replace(/\D/g, "");
  if (ticket.length < 4) throw new OutsourceInputError("bad_ticket", "Укажите № квитанции из Gincore");
  const source = String(b.source || "client");
  if (source !== "donor" && source !== "client") throw new OutsourceInputError("bad_source", "Источник: донор или клиентский");
  const handed_at = isoDay(b.handed_at) || today || new Date().toISOString().slice(0, 10);
  const due_at = isoDay(b.due_at);
  if (!due_at) throw new OutsourceInputError("due_required", "Укажите обещанный срок");
  if (due_at < handed_at) throw new OutsourceInputError("bad_due", "Срок не может быть раньше даты передачи");
  let price = null;
  if (b.price !== undefined && b.price !== null && String(b.price).trim() !== "") {
    price = Number(String(b.price).replace(",", ".").replace(/\s/g, ""));
    if (!Number.isFinite(price) || price < 0) throw new OutsourceInputError("bad_price", "Цена — число");
  }
  const device = s(b.device, LIM.short);
  const issue = s(b.issue, LIM.mid);
  if (device.length < 2) throw new OutsourceInputError("device_required", "Укажите устройство");
  if (issue.length < 2) throw new OutsourceInputError("issue_required", "Укажите неисправность");
  return {
    candidate_id,
    ticket,
    source,
    device,
    issue,
    handed_at,
    due_at,
    price,
    comment: sLong(b.comment, 1000) || null,
  };
}

/** Оценка результата пробника. */
export function normalizeTrialResult(raw) {
  const q = Number(raw?.quality);
  if (!Number.isInteger(q) || q < 1 || q > 5) throw new OutsourceInputError("bad_quality", "Оценка качества 1–5");
  const decision = String(raw?.decision || "");
  if (!OUT_DECISIONS[decision]) throw new OutsourceInputError("bad_decision", "Выберите решение");
  const comment = sLong(raw?.comment, 1000);
  if (decision === "reject" && comment.length < 3) {
    throw new OutsourceInputError("comment_required", "Опишите, почему отказ");
  }
  return {
    result_quality: q,
    result_on_time: raw?.on_time ? 1 : 0,
    result_decision: decision,
    result_comment: comment || null,
  };
}

/** Стадия кандидата после решения по пробнику (null — не менять). */
export function stageAfterDecision(currentStage, decision) {
  if (decision === "take") return "regular";
  if (decision === "reject") return currentStage === "regular" ? null : "lost";
  return null;
}

/** Недельный план менеджера. */
export function normalizePlan(raw) {
  const n = (k, def, max) => {
    const v = Number(raw?.[k]);
    return Number.isInteger(v) && v >= 0 && v <= max ? v : def;
  };
  const target_min = n("target_min", 5, 100);
  const target_max = Math.max(target_min, n("target_max", 10, 100));
  return {
    candidates: n("candidates", 10, 500),
    trials: n("trials", 3, 200),
    regular: n("regular", 1, 50),
    target_min,
    target_max,
  };
}

/** Короткое описание изменений для журнала. */
export function describeChanges(before, patch) {
  const labels = {
    name: "имя",
    kind: "тип",
    contact: "контакт",
    source_url: "объявление",
    area: "район",
    devices: "техника",
    terms: "условия",
    crm_engineer: "мастер в Gincore",
    cash_contractor: "получатель в кассе",
    notes: "заметки",
  };
  const changed = Object.keys(patch).filter((k) => (before?.[k] ?? null) !== (patch[k] ?? null));
  return changed.map((k) => labels[k] || k);
}
