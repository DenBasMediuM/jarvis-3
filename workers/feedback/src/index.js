/**
 * jarvis-feedback — модуль «Улучшения»: заявки пользователей витрины → ИИ → дорожная карта в Jarvis.
 * Bindings: DB (D1). Vars: USERS_URL, ALLOWED_ORIGINS, OPENAI_MODEL, MAX_ROUNDS.
 * Secrets: OPENAI_API_KEY, TOKEN_SECRET, ADMIN_KEY.
 */
import {
  LIMITS,
  REQUEST_STATUSES,
  buildSystemPrompt,
  clip,
  draftIsComplete,
  normalizeAiReply,
  normalizeDraft,
  signToken,
  timingSafeEqual,
  verifyToken,
  verifyUserProof,
} from "./lib.js";

class HttpError extends Error {
  constructor(status, code, message) {
    super(message || code);
    this.status = status;
    this.code = code;
  }
}

function corsHeaders(request, env) {
  const origin = request.headers.get("Origin") || "";
  const allowed = String(env.ALLOWED_ORIGINS || "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
  const ok = allowed.includes(origin) || /^http:\/\/(127\.0\.0\.1|localhost)(:\d+)?$/.test(origin);
  return {
    "Access-Control-Allow-Origin": ok ? origin : allowed[0] || "*",
    "Access-Control-Allow-Methods": "GET, POST, PATCH, PUT, OPTIONS",
    "Access-Control-Allow-Headers": "Authorization, Content-Type",
    "Access-Control-Max-Age": "86400",
    Vary: "Origin",
  };
}

const now = () => new Date().toISOString();

function bearer(req) {
  const m = (req.headers.get("Authorization") || "").match(/^Bearer\s+(.+)$/i);
  return m ? m[1].trim() : "";
}

async function readJson(request) {
  const body = await request.json().catch(() => null);
  if (!body || typeof body !== "object") throw new HttpError(400, "invalid_json");
  return body;
}

async function requireUser(request, env) {
  const user = await verifyToken(env.TOKEN_SECRET, bearer(request));
  if (!user) throw new HttpError(401, "unauthorized", "Сессия истекла — войдите заново");
  return user;
}

function requireAdmin(request, env) {
  if (!env.ADMIN_KEY || !timingSafeEqual(bearer(request), env.ADMIN_KEY)) {
    throw new HttpError(401, "unauthorized");
  }
}

let usersCache = { at: 0, data: null };
async function loadUsers(env) {
  if (usersCache.data && Date.now() - usersCache.at < 60_000) return usersCache.data;
  const res = await fetch(`${env.USERS_URL}?t=${Date.now()}`, { cf: { cacheTtl: 0 } });
  if (!res.ok) throw new HttpError(502, "users_unavailable", `users.json: ${res.status}`);
  usersCache = { at: Date.now(), data: await res.json() };
  return usersCache.data;
}

async function getProduct(env) {
  const row = await env.DB.prepare("SELECT value FROM meta WHERE key = 'product'").first();
  return row?.value || "";
}

async function existingForAi(env) {
  const { results } = await env.DB.prepare(
    "SELECT id, title, area, status FROM requests WHERE status != 'rejected' ORDER BY id DESC LIMIT 60",
  ).all();
  return results || [];
}

async function callOpenAI(env, system, messages) {
  if (!env.OPENAI_API_KEY) throw new HttpError(500, "ai_not_configured", "ИИ не настроен");
  const base = String(env.OPENAI_BASE_URL || "https://api.openai.com/v1").replace(/\/$/, "");
  const res = await fetch(`${base}/chat/completions`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.OPENAI_API_KEY}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: env.OPENAI_MODEL || "gpt-4o-mini",
      temperature: 0.2,
      response_format: { type: "json_object" },
      messages: [{ role: "system", content: system }, ...messages],
    }),
  });
  if (!res.ok) {
    const t = await res.text().catch(() => "");
    throw new HttpError(502, "ai_error", `ИИ недоступен (${res.status}) ${t.slice(0, 200)}`);
  }
  const data = await res.json();
  try {
    return JSON.parse(data?.choices?.[0]?.message?.content || "{}");
  } catch {
    return {};
  }
}

/** Диалог хранится как [{role:'user'|'assistant', text, at}] — для модели склеиваем в chat-формат. */
function toModelMessages(history) {
  return history.map((m) => ({
    role: m.role === "assistant" ? "assistant" : "user",
    content: m.role === "assistant" ? m.raw || m.text : m.text,
  }));
}

async function runAi(env, conv, history) {
  const maxRounds = Math.max(1, Number(env.MAX_ROUNDS || 3));
  const mustDraft = conv.rounds >= maxRounds;
  const system = buildSystemPrompt({
    product: await getProduct(env),
    existing: await existingForAi(env),
    context: conv.context,
    round: Math.min(conv.rounds + 1, maxRounds),
    maxRounds,
    mustDraft,
  });
  const raw = await callOpenAI(env, system, toModelMessages(history));
  const firstUser = history.find((m) => m.role === "user")?.text || "";
  const allUser = history.filter((m) => m.role === "user").map((m) => m.text).join("\n\n");
  const reply = normalizeAiReply(raw, { mustDraft, fallbackText: allUser || firstUser });
  return { reply, raw };
}

async function loadConversation(env, id, login) {
  const row = await env.DB.prepare("SELECT * FROM conversations WHERE id = ? AND login = ?")
    .bind(id, login)
    .first();
  if (!row) throw new HttpError(404, "not_found", "Диалог не найден");
  return {
    ...row,
    context: row.context_json ? JSON.parse(row.context_json) : {},
    history: JSON.parse(row.messages_json || "[]"),
  };
}

async function appendAndAnswer(env, conv, text) {
  if (conv.status !== "open") throw new HttpError(409, "closed", "Диалог уже завершён");
  if (conv.user_messages >= LIMITS.userMessagesPerConversation) {
    throw new HttpError(429, "too_many_messages", "Слишком много сообщений — отправьте заявку как есть");
  }
  const history = [...conv.history, { role: "user", text, at: now() }];
  const { reply, raw } = await runAi(env, conv, history);
  const assistantText = [reply.message, ...reply.questions.map((q, i) => `${i + 1}. ${q}`)]
    .filter(Boolean)
    .join("\n");
  history.push({ role: "assistant", text: assistantText, raw: JSON.stringify(raw), action: reply.action, at: now() });
  const rounds = conv.rounds + (reply.action === "ask" ? 1 : 0);
  await env.DB.prepare(
    `UPDATE conversations SET messages_json = ?, last_ai_json = ?, rounds = ?, user_messages = user_messages + 1, updated_at = ? WHERE id = ?`,
  )
    .bind(JSON.stringify(history), JSON.stringify(reply), rounds, now(), conv.id)
    .run();
  const maxRounds = Math.max(1, Number(env.MAX_ROUNDS || 3));
  return {
    id: conv.id,
    status: conv.status,
    rounds,
    max_rounds: maxRounds,
    reply,
  };
}

function rowToRequest(r, { admin = false } = {}) {
  const out = {
    id: r.id,
    login: r.login,
    type: r.type,
    title: r.title,
    area: r.area,
    problem: r.problem,
    proposal: r.proposal,
    benefit: r.benefit,
    acceptance: r.acceptance_json ? JSON.parse(r.acceptance_json) : [],
    status: r.status,
    status_label: REQUEST_STATUSES[r.status] || r.status,
    admin_comment: r.admin_comment,
    decided_at: r.decided_at,
    created_at: r.created_at,
    updated_at: r.updated_at,
    votes: Number(r.votes || 1),
  };
  if (admin) {
    out.original_text = r.original_text;
    out.assessment = r.assessment_json ? JSON.parse(r.assessment_json) : null;
    out.duplicate_hint = r.duplicate_hint;
    out.priority = r.priority;
    out.conversation_id = r.conversation_id;
    out.conversation = r.messages_json
      ? JSON.parse(r.messages_json).map((m) => ({ role: m.role, text: m.text, at: m.at }))
      : [];
    out.voters = r.voters ? String(r.voters).split(",") : [];
  }
  return out;
}

const REQUEST_SELECT = `
  SELECT r.*,
    1 + (SELECT COUNT(*) FROM votes v WHERE v.request_id = r.id) AS votes,
    (SELECT GROUP_CONCAT(login) FROM votes v WHERE v.request_id = r.id) AS voters
  FROM requests r`;

async function handle(request, env) {
  const url = new URL(request.url);
  const path = url.pathname.replace(/\/+$/, "") || "/";
  const method = request.method;
  let m;

  if (method === "GET" && path === "/") return { ok: true, service: "jarvis-feedback" };

  // ---------- auth ----------
  if (method === "POST" && path === "/auth/login") {
    const body = await readJson(request);
    const users = await loadUsers(env);
    const user = await verifyUserProof(users, body.login, body.proof);
    if (!user) {
      const known = (users?.users || []).find(
        (u) => String(u.login || "").toLowerCase() === String(body.login || "").trim().toLowerCase(),
      );
      if (known && !known.fb_verifier) {
        throw new HttpError(
          403,
          "needs_password_reset",
          "Для «Улучшений» администратору нужно заново задать вам пароль в Jarvis",
        );
      }
      throw new HttpError(401, "bad_credentials", "Неверный логин или пароль");
    }
    const token = await signToken(env.TOKEN_SECRET, { login: user.login });
    return { ok: true, token, login: user.login };
  }
  if (method === "GET" && path === "/me") {
    const user = await requireUser(request, env);
    return { ok: true, login: user.login, exp: user.exp };
  }

  // ---------- пользователь ----------
  if (method === "POST" && path === "/conversations") {
    const user = await requireUser(request, env);
    const body = await readJson(request);
    const text = clip(body.message, LIMITS.messageChars);
    if (text.length < 5) throw new HttpError(400, "too_short", "Опишите пожелание подробнее");
    const day = now().slice(0, 10);
    const cnt = await env.DB.prepare(
      "SELECT COUNT(*) AS n FROM conversations WHERE login = ? AND substr(created_at,1,10) = ?",
    )
      .bind(user.login, day)
      .first();
    if (Number(cnt?.n || 0) >= LIMITS.conversationsPerDay) {
      throw new HttpError(429, "daily_limit", "Лимит заявок на сегодня исчерпан — попробуйте завтра");
    }
    const context = {
      page: clip(body.context?.page, 80),
      tab: clip(body.context?.tab, 80),
      title: clip(body.context?.title, 120),
    };
    const ins = await env.DB.prepare(
      "INSERT INTO conversations (login, context_json, created_at, updated_at) VALUES (?, ?, ?, ?)",
    )
      .bind(user.login, JSON.stringify(context), now(), now())
      .run();
    const conv = await loadConversation(env, ins.meta.last_row_id, user.login);
    return { ok: true, conversation: await appendAndAnswer(env, conv, text) };
  }

  if (method === "POST" && (m = path.match(/^\/conversations\/(\d+)\/messages$/))) {
    const user = await requireUser(request, env);
    const body = await readJson(request);
    const text = clip(body.message, LIMITS.messageChars);
    if (!text) throw new HttpError(400, "empty");
    const conv = await loadConversation(env, Number(m[1]), user.login);
    return { ok: true, conversation: await appendAndAnswer(env, conv, text) };
  }

  if (method === "POST" && (m = path.match(/^\/conversations\/(\d+)\/submit$/))) {
    const user = await requireUser(request, env);
    const body = await readJson(request);
    const conv = await loadConversation(env, Number(m[1]), user.login);
    if (conv.status !== "open") throw new HttpError(409, "closed", "Заявка уже отправлена");
    const last = conv.last_ai_json ? JSON.parse(conv.last_ai_json) : null;
    if (!last?.draft) throw new HttpError(409, "no_draft", "ИИ ещё не оформил заявку");
    // пользователь мог поправить формулировки — берём его вариант, но тип/оценку оставляем от ИИ
    const draft = normalizeDraft({ ...last.draft, ...(body.draft || {}) });
    if (!draftIsComplete(draft)) throw new HttpError(400, "incomplete", "Заполните заголовок и суть изменения");
    const original = conv.history.filter((x) => x.role === "user").map((x) => x.text).join("\n\n");
    const edited = JSON.stringify(normalizeDraft(last.draft)) !== JSON.stringify(draft);
    const assessment = { ...(last.assessment || {}), edited_by_user: edited };
    const ins = await env.DB.prepare(
      `INSERT INTO requests (login, conversation_id, type, title, area, problem, proposal, benefit,
        acceptance_json, original_text, assessment_json, duplicate_hint, status, created_at, updated_at)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', ?, ?)`,
    )
      .bind(
        user.login,
        conv.id,
        draft.type,
        draft.title,
        draft.area,
        draft.problem,
        draft.proposal,
        draft.benefit,
        JSON.stringify(draft.acceptance),
        original,
        JSON.stringify(assessment),
        last.duplicate_of || null,
        now(),
        now(),
      )
      .run();
    await env.DB.prepare("UPDATE conversations SET status = 'submitted', updated_at = ? WHERE id = ?")
      .bind(now(), conv.id)
      .run();
    return { ok: true, id: ins.meta.last_row_id };
  }

  if (method === "POST" && (m = path.match(/^\/requests\/(\d+)\/vote$/))) {
    const user = await requireUser(request, env);
    const body = await request.json().catch(() => ({}));
    const id = Number(m[1]);
    const req = await env.DB.prepare("SELECT id, login, status FROM requests WHERE id = ?").bind(id).first();
    if (!req || req.status === "rejected") throw new HttpError(404, "not_found", "Заявка не найдена");
    if (req.login !== user.login) {
      await env.DB.prepare(
        "INSERT OR IGNORE INTO votes (request_id, login, comment, created_at) VALUES (?, ?, ?, ?)",
      )
        .bind(id, user.login, clip(body?.comment, 1000) || null, now())
        .run();
    }
    const convId = Number(body?.conversation_id);
    if (convId) {
      await env.DB.prepare(
        "UPDATE conversations SET status = 'merged', updated_at = ? WHERE id = ? AND login = ? AND status = 'open'",
      )
        .bind(now(), convId, user.login)
        .run();
    }
    return { ok: true };
  }

  if (method === "GET" && path === "/requests/mine") {
    const user = await requireUser(request, env);
    const { results } = await env.DB.prepare(
      `${REQUEST_SELECT}
       WHERE r.login = ? OR r.id IN (SELECT request_id FROM votes WHERE login = ?)
       ORDER BY r.updated_at DESC LIMIT 200`,
    )
      .bind(user.login, user.login)
      .all();
    return {
      ok: true,
      items: (results || []).map((r) => ({ ...rowToRequest(r), supported: r.login !== user.login })),
    };
  }

  // ---------- админ (Jarvis) ----------
  if (path.startsWith("/admin/")) {
    requireAdmin(request, env);

    if (method === "GET" && path === "/admin/requests") {
      const { results } = await env.DB.prepare(
        `${REQUEST_SELECT} ORDER BY r.created_at DESC LIMIT 1000`,
      ).all();
      // переписка — отдельным запросом на заявку (заявок немного)
      const items = [];
      for (const r of results || []) {
        const conv = r.conversation_id
          ? await env.DB.prepare("SELECT messages_json FROM conversations WHERE id = ?")
              .bind(r.conversation_id)
              .first()
          : null;
        items.push(rowToRequest({ ...r, messages_json: conv?.messages_json }, { admin: true }));
      }
      return { ok: true, items, statuses: REQUEST_STATUSES };
    }

    if (method === "PATCH" && (m = path.match(/^\/admin\/requests\/(\d+)$/))) {
      const body = await readJson(request);
      const id = Number(m[1]);
      const cur = await env.DB.prepare("SELECT * FROM requests WHERE id = ?").bind(id).first();
      if (!cur) throw new HttpError(404, "not_found");
      const status = body.status != null ? String(body.status) : cur.status;
      if (!REQUEST_STATUSES[status]) throw new HttpError(400, "bad_status");
      if (status === "rejected" && !clip(body.admin_comment ?? cur.admin_comment, 2000)) {
        throw new HttpError(400, "comment_required", "Укажите причину отклонения");
      }
      const comment = body.admin_comment != null ? clip(body.admin_comment, 2000) : cur.admin_comment;
      const priority =
        body.priority === null ? null : body.priority != null ? Number(body.priority) || null : cur.priority;
      const decided = status !== cur.status ? now() : cur.decided_at;
      await env.DB.prepare(
        "UPDATE requests SET status = ?, admin_comment = ?, priority = ?, decided_at = ?, updated_at = ? WHERE id = ?",
      )
        .bind(status, comment || null, priority, decided, now(), id)
        .run();
      return { ok: true };
    }

    if (method === "PUT" && path === "/admin/product") {
      const body = await readJson(request);
      const md = String(body.markdown || "").slice(0, 60_000);
      await env.DB.prepare(
        "INSERT INTO meta (key, value, updated_at) VALUES ('product', ?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
      )
        .bind(md, now())
        .run();
      return { ok: true, chars: md.length };
    }

    if (method === "GET" && path === "/admin/product") {
      const row = await env.DB.prepare("SELECT value, updated_at FROM meta WHERE key = 'product'").first();
      return { ok: true, chars: (row?.value || "").length, updated_at: row?.updated_at || null };
    }
  }

  throw new HttpError(404, "not_found");
}

export default {
  async fetch(request, env) {
    const cors = corsHeaders(request, env);
    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    try {
      const data = await handle(request, env);
      return new Response(JSON.stringify(data), {
        headers: { "Content-Type": "application/json; charset=utf-8", ...cors },
      });
    } catch (err) {
      const status = err instanceof HttpError ? err.status : 500;
      const body = {
        ok: false,
        error: err instanceof HttpError ? err.code : "internal",
        message: String(err?.message || err),
      };
      return new Response(JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json; charset=utf-8", ...cors },
      });
    }
  },
};
