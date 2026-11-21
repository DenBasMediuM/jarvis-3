/**
 * Маршруты раздела «Постоянные клиенты» (D1). Подключаются из index.js.
 *
 * Пользователь витрины (токен входа, доступ processes.clients / processes.clients_lead):
 *   GET   /clients/state                       — всё состояние (клиенты, договоры, журнал, справочники, CRM-снимок)
 *   POST  /clients/clients                     — новый клиент
 *   PATCH /clients/clients/:id                 — правка карточки
 *   POST  /clients/clients/:id/stage           — смена стадии
 *   POST  /clients/clients/:id/touch           — касание + следующий шаг
 *   POST  /clients/contracts                   — новый договор
 *   PATCH /clients/contracts/:id               — правка договора
 *   POST  /clients/candidates/take             — взять кандидата из базы в работу
 *   POST  /clients/candidates/decision         — «не постоянный» / «отложить»
 *   PUT   /clients/conditions                  — справочник условий
 *   PUT   /clients/templates                   — новая версия шаблона договора
 *   PUT   /clients/settings                    — реквизиты, пороги автопоиска, исключённые телефоны
 *   PUT   /clients/plan                        — недельный план (руководитель)
 * Jarvis (ADMIN_KEY):
 *   GET   /admin/clients/state                 — клиенты (телефоны, условия), решения, настройки
 *   PUT   /admin/clients/snapshot              — CRM-снимок: метрики клиентов и кандидаты
 */
import {
  CL_CHANNELS,
  CL_CONTRACT_STATUSES,
  CL_STAGES,
  ClientsInputError,
  DEFAULT_CONDITIONS,
  DEFAULT_SETTINGS,
  DEFAULT_TEMPLATES,
  TEMPLATE_KINDS,
  clientsRights,
  describeChanges,
  normPhone,
  normalizeClient,
  normalizeConditionsCatalog,
  normalizeContract,
  normalizeDecision,
  normalizePlan,
  normalizeSettings,
  normalizeStage,
  normalizeTemplate,
  normalizeTouch,
} from "./clients_lib.js";

const LOG_DAYS = 180;
const K = { conditions: "clients_conditions", settings: "clients_settings", plan: "clients_plan" };
const nowIso = () => new Date().toISOString();

async function metaGet(env, key) {
  const row = await env.DB.prepare("SELECT value, updated_at FROM meta WHERE key = ?").bind(key).first();
  if (!row?.value) return { value: null, updated_at: null };
  try {
    return { value: JSON.parse(row.value), updated_at: row.updated_at };
  } catch {
    return { value: null, updated_at: row.updated_at };
  }
}
async function metaSet(env, key, value) {
  await env.DB.prepare(
    "INSERT INTO meta (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
  )
    .bind(key, JSON.stringify(value), nowIso())
    .run();
}

async function logAction(env, { login, action, client_id = null, contract_id = null, channel = null, text = null }) {
  await env.DB.prepare(
    "INSERT INTO clients_log (at, login, action, client_id, contract_id, channel, text) VALUES (?, ?, ?, ?, ?, ?, ?)",
  )
    .bind(nowIso(), login || null, action, client_id, contract_id, channel, text ? String(text).slice(0, 2000) : null)
    .run();
}

function parseJson(v, def) {
  try {
    return v ? JSON.parse(v) : def;
  } catch {
    return def;
  }
}

export function clientRow(r) {
  return {
    ...r,
    phones: parseJson(r.phones, []),
    contacts: parseJson(r.contacts, []),
    legal: parseJson(r.legal, {}),
    conditions: parseJson(r.conditions, {}),
  };
}

async function getClient(env, id, HttpError) {
  const row = await env.DB.prepare("SELECT * FROM clients_clients WHERE id = ?").bind(id).first();
  if (!row) throw new HttpError(404, "not_found", "Клиент не найден");
  return row;
}

async function catalog(env) {
  return (await metaGet(env, K.conditions)).value || DEFAULT_CONDITIONS;
}
async function settings(env) {
  const v = (await metaGet(env, K.settings)).value;
  return v ? normalizeSettings(v) : DEFAULT_SETTINGS;
}

async function latestTemplates(env) {
  const out = {};
  for (const kind of Object.keys(TEMPLATE_KINDS)) {
    const row = await env.DB.prepare(
      "SELECT id, body, created_by, created_at FROM clients_templates WHERE kind = ? ORDER BY id DESC LIMIT 1",
    )
      .bind(kind)
      .first();
    const count = await env.DB.prepare("SELECT COUNT(*) AS n FROM clients_templates WHERE kind = ?").bind(kind).first();
    out[kind] = row
      ? { body: row.body, version: count?.n || 1, updated_by: row.created_by, updated_at: row.created_at, is_default: false }
      : { body: DEFAULT_TEMPLATES[kind], version: 0, is_default: true };
  }
  return out;
}

async function readState(env, { full = true } = {}) {
  const since = new Date(Date.now() - LOG_DAYS * 86400_000).toISOString();
  const [cl, ct, lg, dec, snap] = await Promise.all([
    env.DB.prepare("SELECT * FROM clients_clients ORDER BY id").all(),
    env.DB.prepare("SELECT * FROM clients_contracts ORDER BY id").all(),
    env.DB.prepare("SELECT * FROM clients_log WHERE at >= ? ORDER BY id DESC LIMIT 5000").bind(since).all(),
    env.DB.prepare("SELECT * FROM clients_decisions").all(),
    full ? env.DB.prepare("SELECT value, updated_at FROM clients_snapshot WHERE key = 'crm'").first() : null,
  ]);
  const plan = await metaGet(env, K.plan);
  const out = {
    clients: (cl.results || []).map(clientRow),
    contracts: (ct.results || []).map((c) => (full ? c : { ...c, body: undefined })),
    log: lg.results || [],
    decisions: dec.results || [],
    conditions: await catalog(env),
    settings: await settings(env),
    plan: { ...normalizePlan(plan.value || {}), updated_at: plan.updated_at, updated_by: plan.value?.updated_by || null },
    now: nowIso(),
  };
  if (full) {
    out.templates = await latestTemplates(env);
    out.crm = snap?.value ? { ...parseJson(snap.value, {}), received_at: snap.updated_at } : null;
  }
  return out;
}

function wrapInput(HttpError, fn) {
  try {
    return fn();
  } catch (err) {
    if (err instanceof ClientsInputError) throw new HttpError(400, err.code, err.message);
    throw err;
  }
}

async function insertClient(env, c, { stage = "found", login }) {
  const at = nowIso();
  const res = await env.DB.prepare(
    `INSERT INTO clients_clients
      (kind, name, source, stage, stage_at, phones, contacts, legal, conditions, area, devices, notes,
       next_step, next_step_at, created_by, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
  )
    .bind(
      c.kind, c.name, c.source, stage, at, c.phones, c.contacts, c.legal, c.conditions, c.area, c.devices, c.notes,
      c.next_step, c.next_step_at, login, at, at,
    )
    .run();
  return res.meta?.last_row_id;
}

/** Телефон уже есть у другого клиента? */
async function phoneOwner(env, phones, exceptId = null) {
  const list = parseJson(phones, []);
  if (!list.length) return null;
  const rows = (await env.DB.prepare("SELECT id, name, phones FROM clients_clients").all()).results || [];
  for (const r of rows) {
    if (exceptId && Number(r.id) === Number(exceptId)) continue;
    const ph = parseJson(r.phones, []);
    const hit = list.find((p) => ph.includes(p));
    if (hit) return { id: r.id, name: r.name, phone: hit };
  }
  return null;
}

/**
 * Вернёт результат или undefined, если путь не относится к разделу.
 * ctx: {request, env, path, method, requireUser, requireAdmin, loadUsers, readJson, HttpError}
 */
export async function handleClients(ctx) {
  const { request, env, path, method, requireUser, requireAdmin, loadUsers, readJson, HttpError } = ctx;

  if (path === "/admin/clients/state" && method === "GET") {
    requireAdmin(request, env);
    return { ok: true, ...(await readState(env, { full: false })) };
  }
  if (path === "/admin/clients/snapshot" && method === "PUT") {
    requireAdmin(request, env);
    const body = await readJson(request);
    const value = JSON.stringify(body).slice(0, 1_800_000);
    await env.DB.prepare(
      "INSERT INTO clients_snapshot (key, value, updated_at) VALUES ('crm', ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
    )
      .bind(value, nowIso())
      .run();
    return { ok: true, bytes: value.length };
  }
  if (!path.startsWith("/clients/")) return undefined;

  const tokenUser = await requireUser(request, env);
  const users = await loadUsers(env);
  const record = (users?.users || []).find(
    (u) => String(u.login || "").toLowerCase() === String(tokenUser.login || "").toLowerCase(),
  );
  const rights = clientsRights(record?.access);
  if (!rights.work) throw new HttpError(403, "forbidden", "Нет доступа к разделу «Постоянные клиенты»");
  const login = String(record?.login || tokenUser.login);
  const ok = async (extra = {}) => ({ ok: true, rights, login, ...extra, ...(await readState(env)) });
  let m;

  if (method === "GET" && path === "/clients/state") return ok();

  if (method === "POST" && path === "/clients/clients") {
    const body = await readJson(request);
    const cat = await catalog(env);
    const c = wrapInput(HttpError, () => normalizeClient(body, { catalog: cat }));
    const dup = await phoneOwner(env, c.phones);
    if (dup) throw new HttpError(409, "duplicate_phone", `Телефон уже у клиента «${dup.name}»`);
    const stage = CL_STAGES[body.stage] && body.stage !== "lost" ? body.stage : "found";
    const id = await insertClient(env, c, { stage, login });
    await logAction(env, { login, action: "client_created", client_id: id, text: `${c.name} · ${CL_STAGES[stage]}` });
    return ok({ id });
  }

  if (method === "PATCH" && (m = path.match(/^\/clients\/clients\/(\d+)$/))) {
    const id = Number(m[1]);
    const before = await getClient(env, id, HttpError);
    const body = await readJson(request);
    const cat = await catalog(env);
    const patch = wrapInput(HttpError, () => normalizeClient(body, { partial: true, catalog: cat }));
    if (patch.phones) {
      const dup = await phoneOwner(env, patch.phones, id);
      if (dup) throw new HttpError(409, "duplicate_phone", `Телефон уже у клиента «${dup.name}»`);
    }
    const keys = Object.keys(patch);
    if (!keys.length) throw new HttpError(400, "nothing_to_save", "Нечего сохранять");
    const changed = describeChanges(before, patch);
    if (changed.length) {
      await env.DB.prepare(`UPDATE clients_clients SET ${keys.map((k) => `${k} = ?`).join(", ")}, updated_at = ? WHERE id = ?`)
        .bind(...keys.map((k) => patch[k]), nowIso(), id)
        .run();
      await logAction(env, { login, action: "client_updated", client_id: id, text: changed.join(", ") });
    }
    return ok();
  }

  if (method === "POST" && (m = path.match(/^\/clients\/clients\/(\d+)\/stage$/))) {
    const id = Number(m[1]);
    const before = await getClient(env, id, HttpError);
    const stBody = await readJson(request);
    const st = wrapInput(HttpError, () => normalizeStage(stBody));
    if (st.stage !== before.stage) {
      const at = nowIso();
      await env.DB.prepare("UPDATE clients_clients SET stage = ?, stage_at = ?, lost_reason = ?, updated_at = ? WHERE id = ?")
        .bind(st.stage, at, st.lost_reason, at, id)
        .run();
      await logAction(env, {
        login,
        action: "stage_changed",
        client_id: id,
        text: `${CL_STAGES[before.stage] || before.stage} → ${CL_STAGES[st.stage]}${st.lost_reason ? `: ${st.lost_reason}` : ""}${
          st.comment ? ` · ${st.comment}` : ""
        }`,
      });
    }
    return ok();
  }

  if (method === "POST" && (m = path.match(/^\/clients\/clients\/(\d+)\/touch$/))) {
    const id = Number(m[1]);
    const before = await getClient(env, id, HttpError);
    const body = await readJson(request);
    const t = wrapInput(HttpError, () => normalizeTouch(body, { stage: before.stage }));
    const at = nowIso();
    await env.DB.prepare("UPDATE clients_clients SET next_step = ?, next_step_at = ?, last_touch_at = ?, updated_at = ? WHERE id = ?")
      .bind(t.next_step, t.next_step_at, at, at, id)
      .run();
    await logAction(env, {
      login,
      action: "touch",
      client_id: id,
      channel: t.channel,
      text: `${CL_CHANNELS[t.channel]}: ${t.text}${t.next_step ? ` → ${t.next_step} (${t.next_step_at})` : ""}`,
    });
    return ok();
  }

  if (method === "POST" && path === "/clients/contracts") {
    const body = await readJson(request);
    const c = wrapInput(HttpError, () => normalizeContract(body));
    const client = await getClient(env, c.client_id, HttpError);
    const at = nowIso();
    const res = await env.DB.prepare(
      `INSERT INTO clients_contracts (client_id, number, kind, status, signed_at, valid_from, valid_to, file_url, body, notes, created_by, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
      .bind(c.client_id, c.number, c.kind, c.status, c.signed_at, c.valid_from, c.valid_to, c.file_url, c.body, c.notes, login, at, at)
      .run();
    const id = res.meta?.last_row_id;
    await logAction(env, {
      login,
      action: "contract_created",
      client_id: c.client_id,
      contract_id: id,
      text: `№${c.number || "б/н"} · ${CL_CONTRACT_STATUSES[c.status]}${c.valid_to ? ` · до ${c.valid_to}` : ""} · ${client.name}`,
    });
    return ok({ id });
  }

  if (method === "PATCH" && (m = path.match(/^\/clients\/contracts\/(\d+)$/))) {
    const id = Number(m[1]);
    const before = await env.DB.prepare("SELECT * FROM clients_contracts WHERE id = ?").bind(id).first();
    if (!before) throw new HttpError(404, "not_found", "Договор не найден");
    const body = await readJson(request);
    const patch = wrapInput(HttpError, () => normalizeContract(body, { partial: true }));
    const merged = { ...before, ...patch };
    if (merged.valid_from && merged.valid_to && merged.valid_to < merged.valid_from) {
      throw new HttpError(400, "bad_dates", "Окончание договора раньше начала");
    }
    if ((merged.status === "active" || merged.status === "signing") && !merged.valid_to) {
      throw new HttpError(400, "valid_to_required", "Укажите срок действия договора");
    }
    const keys = Object.keys(patch);
    if (!keys.length) throw new HttpError(400, "nothing_to_save", "Нечего сохранять");
    await env.DB.prepare(`UPDATE clients_contracts SET ${keys.map((k) => `${k} = ?`).join(", ")}, updated_at = ? WHERE id = ?`)
      .bind(...keys.map((k) => patch[k]), nowIso(), id)
      .run();
    const bits = [];
    if (patch.status && patch.status !== before.status) {
      bits.push(`${CL_CONTRACT_STATUSES[before.status]} → ${CL_CONTRACT_STATUSES[patch.status]}`);
    }
    if (patch.valid_to && patch.valid_to !== before.valid_to) bits.push(`срок до ${patch.valid_to}`);
    if (!bits.length) bits.push("изменён");
    await logAction(env, {
      login,
      action: "contract_updated",
      client_id: before.client_id,
      contract_id: id,
      text: `№${merged.number || "б/н"}: ${bits.join(", ")}`,
    });
    return ok();
  }

  if (method === "POST" && path === "/clients/candidates/take") {
    const body = await readJson(request);
    const phone = normPhone(body.phone);
    if (phone.length !== 10) throw new HttpError(400, "bad_phone", "Нет телефона кандидата");
    const cat = await catalog(env);
    const c = wrapInput(HttpError, () =>
      normalizeClient(
        { name: body.name || `Клиент ${phone}`, kind: body.kind || "person", source: "crm", phones: [phone], devices: body.devices, notes: body.notes },
        { catalog: cat },
      ),
    );
    const dup = await phoneOwner(env, c.phones);
    if (dup) throw new HttpError(409, "duplicate_phone", `Телефон уже у клиента «${dup.name}»`);
    const id = await insertClient(env, c, { stage: "found", login });
    await env.DB.prepare(
      "INSERT INTO clients_decisions (phone, decision, until, reason, client_id, login, at) VALUES (?, 'taken', NULL, NULL, ?, ?, ?) ON CONFLICT(phone) DO UPDATE SET decision='taken', until=NULL, reason=NULL, client_id=excluded.client_id, login=excluded.login, at=excluded.at",
    )
      .bind(phone, id, login, nowIso())
      .run();
    await logAction(env, { login, action: "candidate_taken", client_id: id, text: `${c.name} · из базы CRM` });
    return ok({ id });
  }

  if (method === "POST" && path === "/clients/candidates/decision") {
    const body = await readJson(request);
    const d = wrapInput(HttpError, () => normalizeDecision(body));
    await env.DB.prepare(
      "INSERT INTO clients_decisions (phone, decision, until, reason, client_id, login, at) VALUES (?, ?, ?, ?, NULL, ?, ?) ON CONFLICT(phone) DO UPDATE SET decision=excluded.decision, until=excluded.until, reason=excluded.reason, login=excluded.login, at=excluded.at",
    )
      .bind(d.phone, d.decision, d.until, d.reason, login, nowIso())
      .run();
    const name = String(body.name || d.phone).slice(0, 120);
    await logAction(env, {
      login,
      action: d.decision === "dismissed" ? "candidate_dismissed" : "candidate_snoozed",
      text: d.decision === "dismissed" ? `${name}: не постоянный · ${d.reason}` : `${name}: отложен до ${d.until}`,
    });
    return ok();
  }

  if (method === "PUT" && path === "/clients/conditions") {
    const body = await readJson(request);
    const list = wrapInput(HttpError, () => normalizeConditionsCatalog(body.conditions));
    await metaSet(env, K.conditions, list);
    await logAction(env, { login, action: "conditions_saved", text: `${list.filter((c) => !c.hidden).length} условий` });
    return ok();
  }

  if (method === "PUT" && path === "/clients/templates") {
    const body = await readJson(request);
    const t = wrapInput(HttpError, () => normalizeTemplate(body));
    await env.DB.prepare("INSERT INTO clients_templates (kind, body, created_by, created_at) VALUES (?, ?, ?, ?)")
      .bind(t.kind, t.body, login, nowIso())
      .run();
    await logAction(env, { login, action: "template_saved", text: `шаблон «${TEMPLATE_KINDS[t.kind]}»` });
    return ok();
  }

  if (method === "PUT" && path === "/clients/settings") {
    const body = await readJson(request);
    const st = normalizeSettings(body);
    await metaSet(env, K.settings, st);
    await logAction(env, { login, action: "settings_saved", text: "настройки раздела" });
    return ok();
  }

  if (method === "PUT" && path === "/clients/plan") {
    if (!rights.lead) throw new HttpError(403, "forbidden", "План задаёт руководитель");
    const body = await readJson(request);
    await metaSet(env, K.plan, { ...normalizePlan(body), updated_by: login });
    return ok();
  }

  throw new HttpError(404, "not_found");
}
