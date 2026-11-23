import assert from "node:assert/strict";
import test from "node:test";
import { DiagInputError, diagRights, normalizeCase, normalizeDiagPlan, normalizePrices, statusLine, validateCase } from "../src/diag_lib.js";

test("rights", () => {
  assert.deepEqual(diagRights(["processes.diag"]), { work: true, lead: false, view: true });
  assert.deepEqual(diagRights(["processes.diag_lead"]), { work: false, lead: true, view: true });
});

test("case validation by status", () => {
  const base = { ticket: "125430", device: "ноутбук", source: "buffer" };
  assert.ok(validateCase(normalizeCase({ ...base, status: "consult" })));
  assert.throws(() => validateCase(normalizeCase({ ...base, status: "offered" })), /мастера/);
  assert.throws(() => validateCase(normalizeCase({ ...base, status: "agreed", master: "Галанчук" })), /цену/);
  const ok = validateCase(normalizeCase({ ...base, status: "agreed", master: "Галанчук", price: "1 500", prepay: true }));
  assert.equal(ok.price, 1500);
  assert.equal(ok.prepay, 1);
  assert.throws(() => validateCase(normalizeCase({ ...base, status: "declined", master: "x" })), /отказался/);
  assert.throws(() => validateCase(normalizeCase({ ...base, status: "not_needed", master: "x" })), /не нужна/);
  assert.throws(() => validateCase(normalizeCase({ ticket: "12", status: "consult" })), DiagInputError);
  assert.throws(() => normalizeCase({ ticket: "1234", price: "-5" }), /Цена/);
});

test("partial patch keeps only passed keys", () => {
  assert.deepEqual(Object.keys(normalizeCase({ status: "agreed", price: 750 }, { partial: true })).sort(), ["price", "status"]);
});

test("plan, prices, status line", () => {
  assert.deepEqual(normalizeDiagPlan({ daily_agreed: 2, daily_offered: "x" }), { daily_agreed: 2, daily_offered: 2 });
  assert.equal(normalizePrices({ laptop: 1200 }).laptop, 1200);
  assert.equal(normalizePrices({}).console, 1500);
  assert.equal(statusLine({ status: "offered" }, { status: "agreed", price: 1000, prepay: 1 }), "Предложено клиенту → Согласовано · 1000 грн (предоплата)");
  assert.equal(statusLine({ status: "agreed" }, { status: "agreed" }), null);
});
