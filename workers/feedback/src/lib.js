/**
 * Чистые функции модуля «Улучшения» (без env/D1) — покрыты тестами test/lib.test.mjs.
 */

export const REQUEST_TYPES = {
  feature: "Новая функция",
  improvement: "Улучшение",
  bug: "Ошибка",
  data: "Данные / расчёты",
  ux: "Удобство / интерфейс",
  other: "Другое",
};

export const REQUEST_STATUSES = {
  new: "На рассмотрении",
  approved: "Одобрено",
  in_progress: "В работе",
  done: "Готово",
  rejected: "Отклонено",
};

export const LIMITS = {
  messageChars: 2000,
  userMessagesPerConversation: 10,
  conversationsPerDay: 10,
  maxQuestions: 3,
  tokenTtlSec: 30 * 24 * 3600,
};

const enc = new TextEncoder();

export function b64url(bytes) {
  let s = "";
  for (const b of bytes) s += String.fromCharCode(b);
  return btoa(s).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function b64urlDecode(str) {
  const pad = str.length % 4 ? "=".repeat(4 - (str.length % 4)) : "";
  const bin = atob(str.replace(/-/g, "+").replace(/_/g, "/") + pad);
  return Uint8Array.from(bin, (c) => c.charCodeAt(0));
}

export function hexToBytes(hex) {
  const clean = String(hex || "");
  if (!/^[0-9a-f]*$/i.test(clean) || clean.length % 2) throw new Error("bad hex");
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(clean.substr(i * 2, 2), 16);
  return out;
}

export function bytesToHex(bytes) {
  return [...bytes].map((b) => b.toString(16).padStart(2, "0")).join("");
}

export function timingSafeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  let out = 0;
  for (let i = 0; i < a.length; i++) out |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return out === 0;
}

/**
 * Проверка входа без PBKDF2 на стороне Worker (Workers не умеют > 100k итераций):
 * браузер считает proof = PBKDF2(password, fb_salt, 200k) и присылает его,
 * Worker сверяет sha256(proof) с fb_verifier из docs/auth/users.json.
 * Возвращает {login, access} или null.
 */
export async function verifyUserProof(usersJson, login, proofHex) {
  const name = String(login || "").trim().toLowerCase();
  const proof = String(proofHex || "").toLowerCase();
  if (!name || !/^[0-9a-f]{64}$/.test(proof)) return null;
  const users = Array.isArray(usersJson?.users) ? usersJson.users : [];
  const user = users.find((u) => String(u.login || "").toLowerCase() === name);
  if (!user?.fb_verifier) return null;
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", hexToBytes(proof)));
  if (!timingSafeEqual(bytesToHex(digest), String(user.fb_verifier).toLowerCase())) return null;
  return { login: String(user.login), access: Array.isArray(user.access) ? user.access : [] };
}

async function hmac(secret, data) {
  const key = await crypto.subtle.importKey(
    "raw",
    enc.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"],
  );
  return new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(data)));
}

export async function signToken(secret, payload, nowSec = Math.floor(Date.now() / 1000)) {
  if (!secret) throw new Error("TOKEN_SECRET not set");
  const body = { ...payload, iat: nowSec, exp: nowSec + LIMITS.tokenTtlSec };
  const head = b64url(enc.encode(JSON.stringify(body)));
  const sig = b64url(await hmac(secret, head));
  return `${head}.${sig}`;
}

export async function verifyToken(secret, token, nowSec = Math.floor(Date.now() / 1000)) {
  if (!secret || typeof token !== "string") return null;
  const [head, sig] = token.split(".");
  if (!head || !sig) return null;
  const expect = b64url(await hmac(secret, head));
  if (!timingSafeEqual(expect, sig)) return null;
  try {
    const body = JSON.parse(new TextDecoder().decode(b64urlDecode(head)));
    if (!body?.login || !(Number(body.exp) > nowSec)) return null;
    return body;
  } catch {
    return null;
  }
}

export function clip(value, max) {
  const s = String(value ?? "").trim();
  return s.length > max ? s.slice(0, max) : s;
}

/** Санитизация черновика заявки (от ИИ или отредактированного пользователем). */
export function normalizeDraft(raw) {
  const d = raw && typeof raw === "object" ? raw : {};
  const type = REQUEST_TYPES[d.type] ? d.type : "improvement";
  const acceptance = Array.isArray(d.acceptance)
    ? d.acceptance.map((x) => clip(x, 300)).filter(Boolean).slice(0, 6)
    : [];
  return {
    type,
    title: clip(d.title, 140),
    area: clip(d.area, 120),
    problem: clip(d.problem, 1500),
    proposal: clip(d.proposal, 2000),
    benefit: clip(d.benefit, 1000),
    acceptance,
  };
}

export function draftIsComplete(d) {
  return Boolean(d && d.title && d.proposal && (d.problem || d.benefit));
}

function normalizeAssessment(raw) {
  const a = raw && typeof raw === "object" ? raw : {};
  const num = (v) => {
    const n = Math.round(Number(v));
    return n >= 1 && n <= 5 ? n : null;
  };
  return {
    clarity: num(a.clarity),
    value: num(a.value),
    complexity: ["low", "medium", "high"].includes(a.complexity) ? a.complexity : null,
    fits_product: typeof a.fits_product === "boolean" ? a.fits_product : null,
    already_exists: typeof a.already_exists === "boolean" ? a.already_exists : null,
    risks: clip(a.risks, 800),
    notes_for_admin: clip(a.notes_for_admin, 1500),
  };
}

/**
 * Привести ответ модели к контракту. mustDraft — лимит раундов исчерпан:
 * «ask» превращаем в черновик (лучшая интерпретация), а не продолжаем допрос.
 */
export function normalizeAiReply(raw, { mustDraft = false, fallbackText = "" } = {}) {
  const r = raw && typeof raw === "object" ? raw : {};
  let action = ["ask", "draft", "offtopic"].includes(r.action) ? r.action : "ask";
  const questions = Array.isArray(r.questions)
    ? r.questions
        .map((q) => {
          const text = clip(typeof q === "string" ? q : q?.text ?? q?.question, 300);
          const options = Array.isArray(q?.options)
            ? q.options.map((o) => clip(o, 120)).filter(Boolean).slice(0, 4)
            : [];
          return text ? { text, options } : null;
        })
        .filter(Boolean)
        .slice(0, LIMITS.maxQuestions)
    : [];
  let draft = normalizeDraft(r.draft);
  const assessment = normalizeAssessment(r.assessment);
  const dup = Number(r.duplicate_of);
  const out = {
    action,
    message: clip(r.message, 1200),
    questions,
    draft: null,
    assessment,
    duplicate_of: Number.isInteger(dup) && dup > 0 ? dup : null,
    duplicate_reason: clip(r.duplicate_reason, 400),
  };
  if (action === "ask" && !questions.length) action = draftIsComplete(draft) ? "draft" : "ask";
  if (mustDraft && action === "ask") {
    action = "draft";
    if (!draftIsComplete(draft)) {
      const text = clip(fallbackText, 2000);
      draft = normalizeDraft({
        ...draft,
        title: draft.title || clip(text.split("\n")[0], 120) || "Заявка без названия",
        proposal: draft.proposal || text,
        problem: draft.problem || "Автор не уточнил — см. исходный текст.",
      });
    }
    out.assessment.notes_for_admin = [
      out.assessment.notes_for_admin,
      "Лимит уточнений исчерпан: заявка оформлена по лучшей интерпретации, возможны неточности.",
    ]
      .filter(Boolean)
      .join(" ");
    out.questions = [];
  }
  out.action = action;
  if (action === "draft") out.draft = draft;
  if (action !== "ask") out.questions = [];
  if (!out.message) {
    out.message =
      action === "draft"
        ? "Я оформил вашу заявку. Проверьте и при необходимости поправьте перед отправкой."
        : action === "offtopic"
          ? "Я помогаю только оформить заявку на улучшение витрины. Опишите, что хотелось бы изменить."
          : "Уточните, пожалуйста, несколько моментов.";
  }
  return out;
}

export const DEFAULT_RULES = `Ты — ассистент приёма заявок на улучшение внутренней системы Jarvis.
Сначала черновик: если понятно, что и где изменить, — сразу action "draft". Спрашивай только если без ответа заявка будет о другом:
1–2 конкретных вопроса с вариантами ответа, никогда не переспрашивай уже сказанное. На посторонние темы — action "offtopic".`;

export function buildSystemPrompt({ rules, product, existing, context, round, maxRounds, mustDraft }) {
  const list = (existing || [])
    .slice(0, 60)
    .map((r) => `#${r.id} [${r.status}] ${r.title}${r.area ? ` — ${r.area}` : ""}`)
    .join("\n");
  return `${(rules || DEFAULT_RULES).trim()}

Раунд уточнений: ${round} из ${maxRounds}.${
    mustDraft
      ? " ЛИМИТ ИСЧЕРПАН: обязательно action \"draft\" по лучшей интерпретации, неясности — в assessment.notes_for_admin."
      : ""
  }

Ответ — строго JSON-объект:
{
  "action": "ask" | "draft" | "offtopic",
  "message": "1–2 предложения пользователю",
  "questions": [{ "text": "конкретный вопрос", "options": ["вариант 1", "вариант 2"] }],
  "draft": {
    "type": "feature|improvement|bug|data|ux|other",
    "title": "...",
    "area": "раздел/вкладка системы",
    "problem": "что сейчас не так / какая потребность",
    "proposal": "что конкретно изменить",
    "benefit": "какая польза и кому",
    "acceptance": ["критерий готовности", "..."]
  },
  "assessment": {
    "clarity": 1-5, "value": 1-5, "complexity": "low|medium|high",
    "fits_product": true/false, "already_exists": true/false,
    "risks": "...", "notes_for_admin": "допущения и что важно знать администратору"
  },
  "duplicate_of": null | число,
  "duplicate_reason": "..."
}

Контекст пользователя (где он был, когда открыл форму): ${JSON.stringify(context || {})}

Существующие заявки:
${list || "(пока нет)"}

Описание продукта:
${product || "(описание не загружено — опирайся на текст пользователя)"}`;
}
