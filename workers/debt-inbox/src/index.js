/**
 * Inbox решений дебиторки: витрина POST /decision, Jarvis GET /inbox + POST /inbox/ack.
 * Secrets: WRITE_KEY, READ_KEY. Binding: INBOX (KV).
 */

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Authorization, Content-Type",
  "Access-Control-Max-Age": "86400",
};

const DECISION_CODES = new Set(["mgmt_ok", "paid_fact", "no_pay"]);

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
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) {
    return false;
  }
  let out = 0;
  for (let i = 0; i < a.length; i++) out |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return out === 0;
}

export default {
  async fetch(request, env) {
    if (request.method === "OPTIONS") {
      return new Response(null, { status: 204, headers: CORS });
    }

    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    try {
      if (request.method === "POST" && path === "/decision") {
        if (!timingSafeEqual(bearer(request), env.WRITE_KEY || "")) {
          return unauthorized();
        }
        const body = await request.json().catch(() => null);
        if (!body || typeof body !== "object") {
          return json({ ok: false, error: "invalid_json" }, 400);
        }
        const ticket = String(body.ticket || "").trim();
        const decision_code = String(body.decision_code || "").trim();
        const decision_by = String(body.decision_by || "").trim().slice(0, 80);
        if (!/^\d{4,}$/.test(ticket)) {
          return json({ ok: false, error: "bad_ticket" }, 400);
        }
        if (!DECISION_CODES.has(decision_code)) {
          return json({ ok: false, error: "bad_decision_code" }, 400);
        }
        const at = new Date().toISOString();
        const id = `${Date.now()}_${ticket}`;
        const key = `inbox:${id}`;
        const payload = {
          id,
          ticket,
          decision_code,
          decision_by: decision_by || null,
          at,
        };
        await env.INBOX.put(key, JSON.stringify(payload), {
          metadata: { ticket, decision_code },
        });
        return json({ ok: true, id, at });
      }

      if (request.method === "GET" && path === "/inbox") {
        if (!timingSafeEqual(bearer(request), env.READ_KEY || "")) {
          return unauthorized();
        }
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
        return json({ ok: true, items, cursor: listed.list_complete ? null : listed.cursor });
      }

      if (request.method === "POST" && path === "/inbox/ack") {
        if (!timingSafeEqual(bearer(request), env.READ_KEY || "")) {
          return unauthorized();
        }
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
        return json({ ok: true, service: "jarvis-debt-inbox" });
      }

      return json({ ok: false, error: "not_found" }, 404);
    } catch (err) {
      return json({ ok: false, error: String(err?.message || err) }, 500);
    }
  },
};
