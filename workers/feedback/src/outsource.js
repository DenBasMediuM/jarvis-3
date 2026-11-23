/**
 * Маршруты раздела «Аутсорс мастера» (D1). Подключаются из index.js.
 *
 * Пользователь витрины (токен входа):
 *   GET  /outsource/state                      — всё состояние (кандидаты, передачи, журнал, план)
 *   POST /outsource/candidates                 — новый кандидат
 *   PATCH /outsource/candidates/:id            — правка полей
 *   POST /outsource/candidates/:id/stage       — смена стадии воронки
 *   POST /outsource/candidates/:id/note        — заметка в журнал (звонок, переписка)
 *   POST /outsource/trials                     — передача устройства (пробник)
 *   POST /outsource/trials/:id/result          — оценка пробника
 *   PUT  /outsource/plan                       — недельный план (только руководитель)
 * Jarvis (ADMIN_KEY):
 *   GET  /admin/outsource/state
 */
import {
  OUT_DECISIONS,
  OUT_STAGES,
  OutsourceInputError,
  describeChanges,
  normalizeCandidate,
  normalizePlan,
  normalizeStage,
  normalizeTrial,
  normalizeTrialResult,
  outsourceRights,
  stageAfterDecision,
} from "./outsource_lib.js";

const PLAN_KEY = "outsource_plan";
const LOG_DAYS = 180;

const nowIso = () => new Date().toISOString();

async function logAction(env, { login, action, candidate_id = null, trial_id = null, text = null }) {
  await env.DB.prepare(
    "INSERT INTO outsource_log (at, login, action, candidate_id, trial_id, text) VALUES (?, ?, ?, ?, ?, ?)",
  )
    .bind(nowIso(), login || null, action, candidate_id, trial_id, text ? String(text).slice(0, 2000) : null)
    .run();
}

async function getCandidate(env, id, HttpError) {
  const row = await env.DB.prepare("SELECT * FROM outsource_candidates WHERE id = ?").bind(id).first();
  if (!row) throw new HttpError(404, "not_found", "Кандидат не найден");
  return row;
}

async function readPlan(env) {
  const row = await env.DB.prepare("SELECT value, updated_at FROM meta WHERE key = ?").bind(PLAN_KEY).first();
  let plan = null;
  try {
    plan = row?.value ? JSON.parse(row.value) : null;
  } catch {
    plan = null;
  }
  return { ...normalizePlan(plan || {}), ...(plan?.updated_by ? { updated_by: plan.updated_by } : {}), updated_at: row?.updated_at || null };
}

async function readState(env) {
  const since = new Date(Date.now() - LOG_DAYS * 86400_000).toISOString();
  const [cands, trials, log] = await Promise.all([
    env.DB.prepare("SELECT * FROM outsource_candidates ORDER BY id").all(),
    env.DB.prepare("SELECT * FROM outsource_trials ORDER BY id").all(),
    env.DB.prepare("SELECT * FROM outsource_log WHERE at >= ? ORDER BY id DESC LIMIT 5000").bind(since).all(),
  ]);
  return {
    candidates: cands.results || [],
    trials: trials.results || [],
    log: log.results || [],
    plan: await readPlan(env),
    now: nowIso(),
  };
}

function wrapInput(HttpError, fn) {
  try {
    return fn();
  } catch (err) {
    if (err instanceof OutsourceInputError) throw new HttpError(400, err.code, err.message);
    throw err;
  }
}

/**
 * Вернёт результат запроса или undefined, если путь не относится к разделу.
 * ctx: {request, env, path, method, requireUser, requireAdmin, loadUsers, readJson, HttpError}
 */
export async function handleOutsource(ctx) {
  const { request, env, path, method, requireUser, requireAdmin, loadUsers, readJson, HttpError } = ctx;

  if (path === "/admin/outsource/state" && method === "GET") {
    requireAdmin(request, env);
    return { ok: true, ...(await readState(env)) };
  }
  if (!path.startsWith("/outsource/")) return undefined;

  const tokenUser = await requireUser(request, env);
  const users = await loadUsers(env);
  const record = (users?.users || []).find(
    (u) => String(u.login || "").toLowerCase() === String(tokenUser.login || "").toLowerCase(),
  );
  const rights = outsourceRights(record?.access);
  if (!rights.view) throw new HttpError(403, "forbidden", "Нет доступа к разделу «Аутсорс мастера»");
  const needWork = () => {
    if (!rights.work) throw new HttpError(403, "read_only", "Режим просмотра: действия менеджера доступны с доступом «работа менеджера»");
  };
  const login = String(record?.login || tokenUser.login);
  let m;

  if (method === "GET" && path === "/outsource/state") {
    return { ok: true, rights, login, ...(await readState(env)) };
  }

  if (method === "POST" && path === "/outsource/candidates") {
    needWork();
    const body = await readJson(request);
    const c = wrapInput(HttpError, () => normalizeCandidate(body));
    const at = nowIso();
    const res = await env.DB.prepare(
      `INSERT INTO outsource_candidates
        (kind, name, contact, source_url, area, devices, terms, stage, stage_at, crm_engineer, cash_contractor, notes, created_by, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, 'found', ?, ?, ?, ?, ?, ?, ?)`,
    )
      .bind(c.kind, c.name, c.contact, c.source_url, c.area, c.devices, c.terms, at, c.crm_engineer, c.cash_contractor, c.notes, login, at, at)
      .run();
    const id = res.meta?.last_row_id;
    await logAction(env, { login, action: "candidate_created", candidate_id: id, text: c.name });
    return { ok: true, id, ...(await readState(env)) };
  }

  if (method === "PATCH" && (m = path.match(/^\/outsource\/candidates\/(\d+)$/))) {
    needWork();
    const id = Number(m[1]);
    const before = await getCandidate(env, id, HttpError);
    const body = await readJson(request);
    const patch = wrapInput(HttpError, () => normalizeCandidate(body, { partial: true }));
    const keys = Object.keys(patch);
    if (!keys.length) throw new HttpError(400, "nothing_to_save", "Нечего сохранять");
    const changed = describeChanges(before, patch);
    if (changed.length) {
      await env.DB.prepare(
        `UPDATE outsource_candidates SET ${keys.map((k) => `${k} = ?`).join(", ")}, updated_at = ? WHERE id = ?`,
      )
        .bind(...keys.map((k) => patch[k]), nowIso(), id)
        .run();
      await logAction(env, { login, action: "candidate_updated", candidate_id: id, text: changed.join(", ") });
    }
    return { ok: true, ...(await readState(env)) };
  }

  if (method === "POST" && (m = path.match(/^\/outsource\/candidates\/(\d+)\/stage$/))) {
    needWork();
    const id = Number(m[1]);
    const before = await getCandidate(env, id, HttpError);
    const body = await readJson(request);
    const st = wrapInput(HttpError, () => normalizeStage(body));
    if (st.stage !== before.stage) {
      const at = nowIso();
      await env.DB.prepare(
        "UPDATE outsource_candidates SET stage = ?, stage_at = ?, lost_reason = ?, updated_at = ? WHERE id = ?",
      )
        .bind(st.stage, at, st.lost_reason, at, id)
        .run();
      const text = `${OUT_STAGES[before.stage] || before.stage} → ${OUT_STAGES[st.stage]}${
        st.lost_reason ? `: ${st.lost_reason}` : ""
      }${st.comment ? ` · ${st.comment}` : ""}`;
      await logAction(env, { login, action: "stage_changed", candidate_id: id, text });
    }
    return { ok: true, ...(await readState(env)) };
  }

  if (method === "POST" && (m = path.match(/^\/outsource\/candidates\/(\d+)\/note$/))) {
    needWork();
    const id = Number(m[1]);
    await getCandidate(env, id, HttpError);
    const body = await readJson(request);
    const text = String(body.text || "").trim().slice(0, 2000);
    if (text.length < 3) throw new HttpError(400, "too_short", "Напишите, что сделано");
    await logAction(env, { login, action: "note", candidate_id: id, text });
    await env.DB.prepare("UPDATE outsource_candidates SET updated_at = ? WHERE id = ?").bind(nowIso(), id).run();
    return { ok: true, ...(await readState(env)) };
  }

  if (method === "POST" && path === "/outsource/trials") {
    needWork();
    const body = await readJson(request);
    const t = wrapInput(HttpError, () => normalizeTrial(body));
    const cand = await getCandidate(env, t.candidate_id, HttpError);
    if (cand.stage === "lost") throw new HttpError(400, "candidate_lost", "Кандидат в отказе — сначала верните его в воронку");
    const dup = await env.DB.prepare(
      "SELECT id FROM outsource_trials WHERE ticket = ? AND candidate_id = ? AND result_decision IS NULL",
    )
      .bind(t.ticket, t.candidate_id)
      .first();
    if (dup) throw new HttpError(409, "duplicate", "Эта квитанция уже передана этому аутсорсеру и ещё не оценена");
    const at = nowIso();
    const res = await env.DB.prepare(
      `INSERT INTO outsource_trials
        (candidate_id, ticket, source, device, issue, handed_at, due_at, price, comment, created_by, created_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    )
      .bind(t.candidate_id, t.ticket, t.source, t.device, t.issue, t.handed_at, t.due_at, t.price, t.comment, login, at)
      .run();
    const trialId = res.meta?.last_row_id;
    await logAction(env, {
      login,
      action: "trial_created",
      candidate_id: t.candidate_id,
      trial_id: trialId,
      text: `№${t.ticket} · ${t.device} · ${t.source === "donor" ? "донор" : "клиентский"} · срок ${t.due_at}`,
    });
    // первая передача переводит кандидата на стадию «Пробник»
    if (cand.stage === "found" || cand.stage === "contacted" || cand.stage === "paused") {
      await env.DB.prepare("UPDATE outsource_candidates SET stage = 'trial', stage_at = ?, updated_at = ? WHERE id = ?")
        .bind(at, at, t.candidate_id)
        .run();
      await logAction(env, {
        login,
        action: "stage_changed",
        candidate_id: t.candidate_id,
        text: `${OUT_STAGES[cand.stage]} → ${OUT_STAGES.trial} (передан №${t.ticket})`,
      });
    }
    return { ok: true, id: trialId, ...(await readState(env)) };
  }

  if (method === "POST" && (m = path.match(/^\/outsource\/trials\/(\d+)\/result$/))) {
    needWork();
    const id = Number(m[1]);
    const trial = await env.DB.prepare("SELECT * FROM outsource_trials WHERE id = ?").bind(id).first();
    if (!trial) throw new HttpError(404, "not_found", "Передача не найдена");
    if (trial.result_decision) throw new HttpError(409, "already_rated", "Эта передача уже оценена");
    const body = await readJson(request);
    const r = wrapInput(HttpError, () => normalizeTrialResult(body));
    const at = nowIso();
    await env.DB.prepare(
      `UPDATE outsource_trials SET result_quality = ?, result_on_time = ?, result_decision = ?, result_comment = ?,
        result_by = ?, result_at = ? WHERE id = ?`,
    )
      .bind(r.result_quality, r.result_on_time, r.result_decision, r.result_comment, login, at, id)
      .run();
    await logAction(env, {
      login,
      action: "trial_result",
      candidate_id: trial.candidate_id,
      trial_id: id,
      text: `№${trial.ticket}: качество ${r.result_quality}/5, ${r.result_on_time ? "в срок" : "не в срок"}, ${OUT_DECISIONS[r.result_decision] || r.result_decision}${
        r.result_comment ? ` · ${r.result_comment}` : ""
      }`,
    });
    const cand = await getCandidate(env, trial.candidate_id, HttpError);
    const next = stageAfterDecision(cand.stage, r.result_decision);
    if (next && next !== cand.stage) {
      await env.DB.prepare(
        "UPDATE outsource_candidates SET stage = ?, stage_at = ?, lost_reason = ?, updated_at = ? WHERE id = ?",
      )
        .bind(next, at, next === "lost" ? r.result_comment : null, at, cand.id)
        .run();
      await logAction(env, {
        login,
        action: "stage_changed",
        candidate_id: cand.id,
        text: `${OUT_STAGES[cand.stage]} → ${OUT_STAGES[next]} (по итогам №${trial.ticket})`,
      });
    }
    return { ok: true, ...(await readState(env)) };
  }

  if (method === "PUT" && path === "/outsource/plan") {
    if (!rights.lead) throw new HttpError(403, "forbidden", "План задаёт руководитель");
    const body = await readJson(request);
    const plan = normalizePlan(body);
    const value = JSON.stringify({ ...plan, updated_by: login });
    await env.DB.prepare(
      "INSERT INTO meta (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
    )
      .bind(PLAN_KEY, value, nowIso())
      .run();
    return { ok: true, ...(await readState(env)) };
  }

  throw new HttpError(404, "not_found");
}
