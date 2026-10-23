/**
 * Inbox сбора отзывов: витрина POST /result и /google-stats, Jarvis GET /inbox + POST /inbox/ack.
 * Secrets: WRITE_KEY, READ_KEY. Binding: INBOX (KV).
 */

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
  "Access-Control-Max-Age": "86400",
};

const OUTCOMES = new Set(["will_review", "no_answer", "wont_review", "unhappy"]);
const BRANCH_IDS = new Set(["karetnaya", "segedskaya", "levitana"]);

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json; charset=utf-8", ...CORS },
  });
}

function unauthorized() {
  return json({ ok: false, error: "unauthorized" }, 401);
}

function bearer(req) {
  const h = req.headers.get("Authorization") || "";
  const m = h.match(/^Bearer\s+(.+)$/i);
  return m ? m[1].trim() : "";
}

function timingSafeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let out = 0;
  for (let i = 0; i < a.length; i++) out |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return out === 0;
}

async function putInbox(env, payload) {
  const id = payload.id;
  await env.INBOX.put(`inbox:${id}`, JSON.stringify(payload), {
    metadata: { type: payload.type || "call" },
  });
  return id;
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    try {
      if (request.method === "POST" && path === "/result") {
        if (!timingSafeEqual(bearer(request), env.WRITE_KEY || "")) return unauthorized();
        const body = await request.json().catch(() => null);
        if (!body || typeof body !== "object") return json({ ok: false, error: "invalid_json" }, 400);
        const ticket = String(body.ticket || "").trim();
        const outcome = String(body.outcome || "").trim();
        if (!/^\d{4,}$/.test(ticket)) return json({ ok: false, error: "bad_ticket" }, 400);
        if (!OUTCOMES.has(outcome)) return json({ ok: false, error: "bad_outcome" }, 400);
        if (outcome === "unhappy" && !String(body.comment || "").trim()) {
          return json({ ok: false, error: "comment_required" }, 400);
        }
        const at = new Date().toISOString();
        const id = `${Date.now()}_call_${ticket}`;
        await putInbox(env, {
          id,
          type: "call",
          ticket,
          outcome,
          comment: String(body.comment || "").trim().slice(0, 2000) || null,
          manager: String(body.manager || "").trim().slice(0, 80) || null,
          phone: String(body.phone || "").trim().slice(0, 40) || null,
          client_name: String(body.client_name || "").trim().slice(0, 120) || null,
          device: String(body.device || "").trim().slice(0, 120) || null,
          branch_id: BRANCH_IDS.has(String(body.branch_id || "")) ? String(body.branch_id) : null,
          issued_at: String(body.issued_at || "").trim().slice(0, 32) || null,
          repair_days: body.repair_days ?? null,
          at,
        });
        return json({ ok: true, id, at });
      }

      if (request.method === "POST" && path === "/google-stats") {
        if (!timingSafeEqual(bearer(request), env.WRITE_KEY || "")) return unauthorized();
        const body = await request.json().catch(() => null);
        if (!body || typeof body !== "object") return json({ ok: false, error: "invalid_json" }, 400);
        const day = String(body.day || "").trim().slice(0, 10);
        const branches = Array.isArray(body.branches) ? body.branches : [];
        if (day.length < 8) return json({ ok: false, error: "bad_day" }, 400);
        const cleaned = [];
        const seen = new Set();
        for (const b of branches) {
          if (!b || typeof b !== "object") continue;
          const id = String(b.id || "");
          if (!BRANCH_IDS.has(id) || seen.has(id)) continue;
          const rating = Number(b.rating);
          const review_count = Number(b.review_count);
          if (!(rating >= 1 && rating <= 5) || !(review_count >= 0) || !Number.isFinite(review_count)) {
            return json({ ok: false, error: `bad_stats:${id}` }, 400);
          }
          seen.add(id);
          cleaned.push({ id, rating, review_count: Math.floor(review_count) });
        }
        if (seen.size < BRANCH_IDS.size) {
          return json({ ok: false, error: "need_all_branches" }, 400);
        }
        const at = new Date().toISOString();
        const id = `${Date.now()}_google_${day}`;
        await putInbox(env, {
          id,
          type: "google_stats",
          day,
          manager: String(body.manager || "").trim().slice(0, 80) || null,
          branches: cleaned,
          at,
        });
        return json({ ok: true, id, at });
      }

      if (request.method === "GET" && path === "/inbox") {
        if (!timingSafeEqual(bearer(request), env.READ_KEY || "")) return unauthorized();
        const listed = await env.INBOX.list({ prefix: "inbox:" });
        const items = [];
        for (const k of listed.keys) {
          const raw = await env.INBOX.get(k.name);
          if (!raw) continue;
          try {
            items.push(JSON.parse(raw));
          } catch {
            /* skip */
          }
        }
        items.sort((a, b) => String(a.at || "").localeCompare(String(b.at || "")));
        return json({ ok: true, items });
      }

      if (request.method === "POST" && path === "/inbox/ack") {
        if (!timingSafeEqual(bearer(request), env.READ_KEY || "")) return unauthorized();
        const body = await request.json().catch(() => null);
        const ids = Array.isArray(body?.ids) ? body.ids : [];
        let deleted = 0;
        for (const id of ids) {
          const sid = String(id || "").trim();
          if (!sid) continue;
          await env.INBOX.delete(`inbox:${sid}`);
          deleted += 1;
        }
        return json({ ok: true, deleted });
      }

      if (request.method === "GET" && path === "/") {
        return json({ ok: true, service: "jarvis-reviews-inbox" });
      }

      return json({ ok: false, error: "not_found" }, 404);
    } catch (err) {
      return json({ ok: false, error: String(err?.message || err) }, 500);
    }
  },
};
