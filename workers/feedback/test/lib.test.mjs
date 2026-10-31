import { test } from "node:test";
import assert from "node:assert/strict";
import {
  verifyUserProof,
  signToken,
  verifyToken,
  normalizeAiReply,
  normalizeDraft,
  buildSystemPrompt,
} from "../src/lib.js";

// proof/verifier сгенерированы core.vitrine_auth (PBKDF2 200k + sha256) — совместимость с Python
const PROOF = "ce3e46f266bf144b371dc98e3205148a7b33a197ef162caadb78b9054e0826b6";
const USERS = {
  users: [
    { login: "Demo", fb_salt: "00112233445566778899aabbccddeeff", fb_verifier: "79c95d0cd087405c8b8f506a63f619f4cfcd8bc093f90ec17613083942ec1690", access: ["quality"] },
    { login: "old", salt: "aa", hash: "bb" },
  ],
};

test("verifyUserProof: совместимо с Python-верификатором", async () => {
  assert.deepEqual(await verifyUserProof(USERS, "demo", PROOF), { login: "Demo", access: ["quality"] });
  assert.equal(await verifyUserProof(USERS, "demo", "0".repeat(64)), null);
  assert.equal(await verifyUserProof(USERS, "demo", "short"), null);
  assert.equal(await verifyUserProof(USERS, "old", PROOF), null);
  assert.equal(await verifyUserProof(USERS, "nobody", PROOF), null);
});

test("token: подпись, срок, подделка", async () => {
  const t = await signToken("s3cret", { login: "Demo" }, 1000);
  assert.equal((await verifyToken("s3cret", t, 1001)).login, "Demo");
  assert.equal(await verifyToken("other", t, 1001), null);
  assert.equal(await verifyToken("s3cret", t, 1000 + 31 * 24 * 3600), null);
  const [head, sig] = t.split(".");
  const forged = Buffer.from(JSON.stringify({ login: "admin", exp: 9e9 })).toString("base64url");
  assert.equal(await verifyToken("s3cret", `${forged}.${sig}`, 1001), null);
  assert.equal(await verifyToken("s3cret", "garbage", 1001), null);
});

test("normalizeAiReply: обрезает вопросы и мусор", () => {
  const r = normalizeAiReply({ action: "ask", message: "?", questions: ["a", "b", "c", "d", ""] });
  assert.equal(r.action, "ask");
  assert.deepEqual(r.questions, ["a", "b", "c"]);
  assert.equal(r.draft, null);
  const bad = normalizeAiReply({ action: "hack" });
  assert.equal(bad.action, "ask");
});

test("normalizeAiReply: лимит раундов → принудительный черновик", () => {
  const r = normalizeAiReply(
    { action: "ask", questions: ["зачем?"] },
    { mustDraft: true, fallbackText: "Хочу фильтр по филиалу\nв дебиторке" },
  );
  assert.equal(r.action, "draft");
  assert.equal(r.draft.title, "Хочу фильтр по филиалу");
  assert.ok(r.draft.proposal.includes("дебиторке"));
  assert.ok(r.assessment.notes_for_admin.includes("Лимит уточнений"));
  assert.deepEqual(r.questions, []);
});

test("normalizeAiReply: offtopic без черновика", () => {
  const r = normalizeAiReply({ action: "offtopic", draft: { title: "x", proposal: "y" } });
  assert.equal(r.action, "offtopic");
  assert.equal(r.draft, null);
  assert.ok(r.message.length > 0);
});

test("normalizeDraft: тип по умолчанию, длины", () => {
  const d = normalizeDraft({ type: "weird", title: "x".repeat(500), acceptance: ["a", 1, ""] });
  assert.equal(d.type, "improvement");
  assert.equal(d.title.length, 140);
  assert.deepEqual(d.acceptance, ["a", "1"]);
});

test("buildSystemPrompt: включает продукт, заявки и флаг лимита", () => {
  const p = buildSystemPrompt({
    product: "## Дебиторка",
    existing: [{ id: 7, status: "new", title: "Фильтр", area: "Дебиторка" }],
    context: { page: "vyrobotka" },
    round: 3,
    maxRounds: 3,
    mustDraft: true,
  });
  assert.ok(p.includes("## Дебиторка"));
  assert.ok(p.includes("#7 [new] Фильтр"));
  assert.ok(p.includes("ЛИМИТ ИСЧЕРПАН"));
});
