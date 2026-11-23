import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";
import {
  normalizeCandidate,
  normalizeStage,
  normalizeTrial,
  normalizeTrialResult,
  normalizePlan,
  outsourceRights,
  stageAfterDecision,
  describeChanges,
  OutsourceInputError,
} from "../src/outsource_lib.js";
import { handleOutsource } from "../src/outsource.js";

test("права: lead включает work", () => {
  assert.deepEqual(outsourceRights(["processes.outsource"]), { work: true, lead: false, view: true });
  assert.deepEqual(outsourceRights(["processes.outsource_lead"]), { work: false, lead: true, view: true });
  assert.deepEqual(outsourceRights(["quality"]), { work: false, lead: false, view: false });
});

test("кандидат: нужен контакт или объявление, ссылка дополняется схемой", () => {
  assert.throws(() => normalizeCandidate({ name: "Вася" }), OutsourceInputError);
  const c = normalizeCandidate({ name: "  Вася  ремонт ", source_url: "olx.ua/x", kind: "service" });
  assert.equal(c.name, "Вася ремонт");
  assert.equal(c.source_url, "https://olx.ua/x");
  assert.equal(c.kind, "service");
  const p = normalizeCandidate({ crm_engineer: "Саша Андрусяк" }, { partial: true });
  assert.deepEqual(Object.keys(p), ["crm_engineer"]);
});

test("отказ требует причину", () => {
  assert.throws(() => normalizeStage({ stage: "lost" }), OutsourceInputError);
  assert.equal(normalizeStage({ stage: "lost", lost_reason: "дорого" }).lost_reason, "дорого");
  assert.equal(normalizeStage({ stage: "regular", lost_reason: "x" }).lost_reason, null);
});

test("передача: квитанция, срок не раньше передачи", () => {
  const base = { candidate_id: 1, ticket: "№ 124 450", device: "iPhone 11", issue: "экран", handed_at: "2026-11-19", due_at: "2026-11-25" };
  const t = normalizeTrial(base);
  assert.equal(t.ticket, "124450");
  assert.equal(t.source, "client");
  assert.throws(() => normalizeTrial({ ...base, due_at: "2026-11-01" }), OutsourceInputError);
  assert.throws(() => normalizeTrial({ ...base, due_at: "" }), OutsourceInputError);
  assert.equal(normalizeTrial({ ...base, price: "1 200,5" }).price, 1200.5);
});

test("результат пробника и стадия", () => {
  assert.throws(() => normalizeTrialResult({ quality: 6, decision: "take" }), OutsourceInputError);
  assert.throws(() => normalizeTrialResult({ quality: 2, decision: "reject" }), OutsourceInputError);
  assert.equal(normalizeTrialResult({ quality: 5, decision: "take", on_time: true }).result_on_time, 1);
  assert.equal(stageAfterDecision("trial", "take"), "regular");
  assert.equal(stageAfterDecision("trial", "reject"), "lost");
  assert.equal(stageAfterDecision("regular", "reject"), null);
  assert.equal(stageAfterDecision("trial", "again"), null);
});

test("план: значения по умолчанию и target_max >= target_min", () => {
  assert.deepEqual(normalizePlan({}), { candidates: 10, trials: 3, regular: 1, target_min: 5, target_max: 10 });
  assert.equal(normalizePlan({ target_min: 8, target_max: 3 }).target_max, 8);
});

test("describeChanges", () => {
  assert.deepEqual(describeChanges({ contact: "1" }, { contact: "2", area: null }), ["контакт"]);
});

// ---------- маршруты на фейковом D1 (node:sqlite) ----------
class HttpError extends Error {
  constructor(status, code, message) {
    super(message || code);
    this.status = status;
    this.code = code;
  }
}

function fakeD1() {
  const db = new DatabaseSync(":memory:");
  db.exec(readFileSync(new URL("../schema.sql", import.meta.url), "utf8"));
  const stmt = (sql, args = []) => ({
    bind: (...a) => stmt(sql, a),
    run: async () => {
      const r = db.prepare(sql).run(...args);
      return { meta: { last_row_id: Number(r.lastInsertRowid), changes: r.changes } };
    },
    first: async () => db.prepare(sql).get(...args) || null,
    all: async () => ({ results: db.prepare(sql).all(...args) }),
  });
  return { prepare: (sql) => stmt(sql) };
}

function makeCtx(env, login, method, path, body) {
  const users = {
    users: [
      { login: "manager", access: ["processes.outsource"] },
      { login: "boss", access: ["processes.outsource_lead"] },
      { login: "other", access: ["quality"] },
    ],
  };
  return {
    request: { json: async () => body },
    env,
    path,
    method,
    requireUser: async () => ({ login }),
    requireAdmin: () => {},
    loadUsers: async () => users,
    readJson: async () => body || {},
    HttpError,
  };
}

test("сценарий: кандидат → пробник → постоянный, журнал и права", async () => {
  const env = { DB: fakeD1() };
  const call = (login, method, path, body) => handleOutsource(makeCtx(env, login, method, path, body));

  await assert.rejects(call("other", "GET", "/outsource/state"), (e) => e.status === 403);
  assert.equal(await call("manager", "GET", "/feedback/x"), undefined);

  const created = await call("manager", "POST", "/outsource/candidates", {
    name: "Андрусяк",
    contact: "+380000000000",
    kind: "master_home",
  });
  const id = created.id;
  assert.equal(created.candidates[0].stage, "found");

  await call("manager", "PATCH", `/outsource/candidates/${id}`, { crm_engineer: "Саша Андрусяк" });
  await call("manager", "POST", `/outsource/candidates/${id}/note`, { text: "созвонились, согласен" });

  const tr = await call("manager", "POST", "/outsource/trials", {
    candidate_id: id,
    ticket: "124450",
    source: "donor",
    device: "iPhone 11",
    issue: "экран",
    handed_at: "2026-11-19",
    due_at: "2026-11-22",
  });
  assert.equal(tr.candidates[0].stage, "trial");
  await assert.rejects(
    call("manager", "POST", "/outsource/trials", {
      candidate_id: id,
      ticket: "124450",
      device: "iPhone 11",
      issue: "экран",
      handed_at: "2026-11-19",
      due_at: "2026-11-22",
    }),
    (e) => e.status === 409,
  );

  const res = await call("manager", "POST", `/outsource/trials/${tr.id}/result`, {
    quality: 5,
    on_time: true,
    decision: "take",
  });
  assert.equal(res.candidates[0].stage, "regular");
  assert.equal(res.trials[0].result_decision, "take");
  const actions = res.log.map((l) => l.action);
  for (const a of ["candidate_created", "candidate_updated", "note", "trial_created", "trial_result", "stage_changed"]) {
    assert.ok(actions.includes(a), a);
  }

  await assert.rejects(call("manager", "PUT", "/outsource/plan", { trials: 5 }), (e) => e.status === 403);
  const planned = await call("boss", "PUT", "/outsource/plan", { trials: 5 });
  assert.equal(planned.plan.trials, 5);
  assert.equal(planned.plan.updated_by, "boss");
  assert.equal(planned.rights, undefined);

  const st = await call("boss", "GET", "/outsource/state");
  assert.equal(st.rights.lead, true);
  const admin = await call("x", "GET", "/admin/outsource/state");
  assert.equal(admin.candidates.length, 1);

  await assert.rejects(
    call("manager", "POST", `/outsource/candidates/${id}/stage`, { stage: "lost" }),
    (e) => e.status === 400 && e.code === "reason_required",
  );
});
