/**
 * Маршруты раздела «Платная диагностика» (D1). Подключаются из index.js.
 *
 * Пользователь витрины (токен входа, доступ processes.diag / processes.diag_lead):
 *   GET   /diag/state            — записи, журнал, план, цены, CRM-снимок (кандидаты, статусы квитанций)
 *   POST  /diag/cases            — новая запись (устройство взято в работу)
 *   PATCH /diag/cases/:id        — правка / смена статуса
 *   POST  /diag/cases/:id/delete — удалить запись (руководитель; ошибочные и тестовые записи)
 *   PUT   /diag/prices           — подсказки цен по категориям
 *   PUT   /diag/plan             — дневной план (руководитель)
 * Jarvis (ADMIN_KEY):
 *   GET   /admin/diag/state      — записи (квитанции) для сверки с CRM
 *   PUT   /admin/diag/snapshot   — кандидаты и статусы квитанций из CRM
 */
import {
  DEFAULT_PRICES,
  DG_STATUSES,
  DiagInputError,
  diagRights,
  normalizeCase,
  normalizeDiagPlan,
  normalizePrices,
  statusLine,
  validateCase,
} from "./diag_lib.js";

const LOG_DAYS = 200;
const K = { plan: "diag_plan", prices: "diag_prices" };
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
async function logAction(env, { login, action, case_id = null, ticket = null, text = null }) {
  await env.DB.prepare("INSERT INTO diag_log (at, login, action, case_id, ticket, text) VALUES (?, ?, ?, ?, ?, ?)")
    .bind(nowIso(), login || null, action, case_id, ticket, text ? String(text).slice(0, 2000) : null)
    .run();
}

async function readState(env, { full = true } = {}) {
  const since = new Date(Date.now() - LOG_DAYS * 86400_000).toISOString();
  const [cases, log, snap] = await Promise.all([
    env.DB.prepare("SELECT * FROM diag_cases ORDER BY id DESC LIMIT 3000").all(),
    full ? env.DB.prepare("SELECT * FROM diag_log WHERE at >= ? ORDER BY id DESC LIMIT 5000").bind(since).all() : { results: [] },
    full ? env.DB.prepare("SELECT value, updated_at FROM diag_snapshot WHERE key = 'crm'").first() : null,
  ]);
  const plan = await metaGet(env, K.plan);
  const prices = await metaGet(env, K.prices);
  let crm = null;
  if (snap?.value) {
    try {
      crm = { ...JSON.parse(snap.value), received_at: snap.updated_at };
    } catch {
      crm = null;
    }
  }
  return {
    cases: cases.results || [],
    log: log.results || [],
    plan: { ...normalizeDiagPlan(plan.value || {}), updated_at: plan.updated_at, updated_by: plan.value?.updated_by || null },
    prices: prices.value ? normalizePrices(prices.value) : DEFAULT_PRICES,
    crm,
    now: nowIso(),
  };
}

function wrapInput(HttpError, fn) {
  try {
    return fn();
  } catch (err) {
    if (err instanceof DiagInputError) throw new HttpError(400, err.code, err.message);
    throw err;
  }
}

const CASE_COLS = ["ticket", "status", "source", "device", "category", "master", "consult_note", "price", "prepay", "decline_reason", "comment"];

export async function handleDiag(ctx) {
  const { request, env, path, method, requireUser, requireAdmin, loadUsers, readJson, HttpError } = ctx;

  if (path === "/admin/diag/state" && method === "GET") {
    requireAdmin(request, env);
    return { ok: true, ...(await readState(env, { full: false })) };
  }
  if (path === "/admin/diag/snapshot" && method === "PUT") {
    requireAdmin(request, env);
    const body = await readJson(request);
    const value = JSON.stringify(body).slice(0, 1_800_000);
    await env.DB.prepare(
      "INSERT INTO diag_snapshot (key, value, updated_at) VALUES ('crm', ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
    )
      .bind(value, nowIso())
      .run();
    return { ok: true, bytes: value.length };
  }
  if (!path.startsWith("/diag/")) return undefined;

  const tokenUser = await requireUser(request, env);
  const users = await loadUsers(env);
  const record = (users?.users || []).find(
    (u) => String(u.login || "").toLowerCase() === String(tokenUser.login || "").toLowerCase(),
  );
  const rights = diagRights(record?.access);
  if (!rights.view) throw new HttpError(403, "forbidden", "Нет доступа к разделу «Платная диагностика»");
  const needWork = () => {
    if (!rights.work) throw new HttpError(403, "read_only", "Режим просмотра: действия менеджера доступны с доступом «работа менеджера»");
  };
  const login = String(record?.login || tokenUser.login);
  const ok = async (extra = {}) => ({ ok: true, rights, login, ...extra, ...(await readState(env)) });
  let m;

  if (method === "GET" && path === "/diag/state") return ok();

  if (method === "POST" && path === "/diag/cases") {
    needWork();
    const body = await readJson(request);
    const c = wrapInput(HttpError, () => validateCase(normalizeCase(body)));
    const dup = await env.DB.prepare("SELECT id, status FROM diag_cases WHERE ticket = ? ORDER BY id DESC LIMIT 1").bind(c.ticket).first();
    if (dup) throw new HttpError(409, "duplicate", `По квитанции №${c.ticket} уже есть запись — откройте её`);
    const at = nowIso();
    const res = await env.DB.prepare(
      `INSERT INTO diag_cases (${CASE_COLS.join(", ")}, created_by, created_at, updated_at, status_at)
       VALUES (${CASE_COLS.map(() => "?").join(", ")}, ?, ?, ?, ?)`,
    )
      .bind(...CASE_COLS.map((k) => c[k] ?? null), login, at, at, at)
      .run();
    const id = res.meta?.last_row_id;
    await logAction(env, { login, action: "case_created", case_id: id, ticket: c.ticket, text: `№${c.ticket} · ${c.device || ""} · ${statusLine(null, c)}` });
    if (c.status === "agreed" || c.status === "declined" || c.status === "offered" || c.status === "not_needed") {
      await logAction(env, { login, action: `status_${c.status}`, case_id: id, ticket: c.ticket, text: `№${c.ticket}: ${statusLine({ status: "consult" }, c)}` });
    }
    return ok({ id });
  }

  if (method === "PATCH" && (m = path.match(/^\/diag\/cases\/(\d+)$/))) {
    needWork();
    const id = Number(m[1]);
    const before = await env.DB.prepare("SELECT * FROM diag_cases WHERE id = ?").bind(id).first();
    if (!before) throw new HttpError(404, "not_found", "Запись не найдена");
    const body = await readJson(request);
    const patch = wrapInput(HttpError, () => normalizeCase(body, { partial: true }));
    delete patch.ticket; // номер квитанции не меняем — новая квитанция = новая запись
    const merged = wrapInput(HttpError, () => validateCase({ ...before, ...patch }));
    const keys = Object.keys(patch).filter((k) => (before[k] ?? null) !== (patch[k] ?? null));
    if (!keys.length) return ok();
    const at = nowIso();
    const statusChanged = patch.status && patch.status !== before.status;
    await env.DB.prepare(
      `UPDATE diag_cases SET ${keys.map((k) => `${k} = ?`).join(", ")}, updated_at = ?${statusChanged ? ", status_at = ?" : ""} WHERE id = ?`,
    )
      .bind(...keys.map((k) => patch[k]), at, ...(statusChanged ? [at] : []), id)
      .run();
    if (statusChanged) {
      await logAction(env, { login, action: `status_${merged.status}`, case_id: id, ticket: before.ticket, text: `№${before.ticket}: ${statusLine(before, merged)}` });
    } else {
      await logAction(env, { login, action: "case_updated", case_id: id, ticket: before.ticket, text: `№${before.ticket}: изменены ${keys.join(", ")}` });
    }
    return ok();
  }

  if (method === "POST" && (m = path.match(/^\/diag\/cases\/(\d+)\/delete$/))) {
    if (!rights.lead) throw new HttpError(403, "forbidden", "Удалять записи может руководитель");
    const id = Number(m[1]);
    const before = await env.DB.prepare("SELECT * FROM diag_cases WHERE id = ?").bind(id).first();
    if (!before) throw new HttpError(404, "not_found", "Запись не найдена");
    const body = await readJson(request).catch(() => ({}));
    await env.DB.prepare("DELETE FROM diag_cases WHERE id = ?").bind(id).run();
    await logAction(env, {
      login,
      action: "case_deleted",
      case_id: id,
      ticket: before.ticket,
      text: `№${before.ticket}: запись удалена (была «${DG_STATUSES[before.status] || before.status}»${before.price ? `, ${before.price} грн` : ""})${
        body?.reason ? ` · ${String(body.reason).slice(0, 300)}` : ""
      }`,
    });
    return ok();
  }

  if (method === "PUT" && path === "/diag/prices") {
    const body = await readJson(request);
    await metaSet(env, K.prices, normalizePrices(body.prices));
    await logAction(env, { login, action: "prices_saved", text: "цены по категориям" });
    return ok();
  }

  if (method === "PUT" && path === "/diag/plan") {
    if (!rights.lead) throw new HttpError(403, "forbidden", "План задаёт руководитель");
    const body = await readJson(request);
    await metaSet(env, K.plan, { ...normalizeDiagPlan(body), updated_by: login });
    return ok();
  }

  throw new HttpError(404, "not_found");
}
