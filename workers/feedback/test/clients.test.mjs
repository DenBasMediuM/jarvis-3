import assert from "node:assert/strict";
import test from "node:test";
import {
  DEFAULT_CONDITIONS,
  DEFAULT_TEMPLATES,
  ClientsInputError,
  clientsRights,
  normPhone,
  normalizeClient,
  normalizeConditionsCatalog,
  normalizeContract,
  normalizeDecision,
  normalizeSettings,
  normalizeStage,
  normalizeTouch,
  renderContract,
} from "../src/clients_lib.js";

test("rights", () => {
  assert.deepEqual(clientsRights(["processes.clients"]), { work: true, lead: false });
  assert.deepEqual(clientsRights(["processes.clients_lead"]), { work: true, lead: true });
  assert.deepEqual(clientsRights([]), { work: false, lead: false });
});

test("phones normalized and required", () => {
  assert.equal(normPhone("+38 (050) 111-22-33"), "0501112233");
  const c = normalizeClient({ name: "Іван", phones: "+380501112233, 0501112233; 067 000 00 00" });
  assert.deepEqual(JSON.parse(c.phones), ["0501112233", "0670000000"]);
  assert.throws(() => normalizeClient({ name: "Іван" }), ClientsInputError);
  assert.throws(() => normalizeClient({ name: "x", phones: "0501112233" }), ClientsInputError);
});

test("conditions values keep only catalog ids", () => {
  const c = normalizeClient({
    name: "ТОВ Ромашка",
    kind: "company",
    phones: ["0501112233"],
    conditions: { repair_days: { value: "5", status: "ok" }, hacker: { value: "1" } },
  });
  assert.deepEqual(JSON.parse(c.conditions), { repair_days: { value: "5", status: "ok", note: null } });
});

test("touch requires next step except paused/lost", () => {
  assert.throws(() => normalizeTouch({ text: "позвонил" }, { stage: "active" }), /следующий шаг/);
  assert.ok(normalizeTouch({ text: "позвонил" }, { stage: "lost" }));
  const t = normalizeTouch({ text: "позвонил", next_step: "отправить КП", next_step_at: "2026-11-25", channel: "call" }, { stage: "found" });
  assert.equal(t.next_step_at, "2026-11-25");
});

test("stage lost needs reason", () => {
  assert.throws(() => normalizeStage({ stage: "lost" }), /причину/);
  assert.equal(normalizeStage({ stage: "active" }).stage, "active");
});

test("contract dates", () => {
  assert.throws(() => normalizeContract({ client_id: 1, status: "active" }), /срок действия/);
  assert.throws(() => normalizeContract({ client_id: 1, valid_from: "2026-12-01", valid_to: "2026-01-01" }), /раньше/);
  const c = normalizeContract({ client_id: 1, status: "active", valid_from: "2026-11-21", valid_to: "2027-11-20", number: "К-1" });
  assert.equal(c.kind, "legal");
});

test("catalog editing", () => {
  const list = normalizeConditionsCatalog([...DEFAULT_CONDITIONS, { name: "Своё условие", unit: "text" }, { name: "x" }]);
  assert.equal(list.length, DEFAULT_CONDITIONS.length + 1);
  assert.ok(list.at(-1).id.startsWith("c_"));
  assert.throws(() => normalizeConditionsCatalog([]), ClientsInputError);
});

test("decision and settings", () => {
  assert.throws(() => normalizeDecision({ phone: "0501112233", decision: "dismissed" }), /почему/);
  const d = normalizeDecision({ phone: "0501112233", decision: "snoozed", days: 30 });
  assert.ok(d.until);
  const s = normalizeSettings({ thresholds: { orders: 1 }, excluded_phones: "0501112233\nabc" });
  assert.equal(s.thresholds.orders, 3);
  assert.deepEqual(s.excluded_phones, ["0501112233"]);
});

test("contract render fills fields and conditions", () => {
  const txt = renderContract(DEFAULT_TEMPLATES.legal, {
    client: {
      name: "ТОВ Ромашка",
      phones: ["0501112233"],
      legal: { full_name: "ТОВ «Ромашка»", code: "12345678", signer: "директора Петренка П.П." },
      conditions: { repair_days: { value: "5" }, discount_work: { value: "10" }, free_diag: { value: "1" } },
    },
    contract: { number: "К-7", signed_at: "2026-11-21", valid_to: "2027-11-20" },
    requisites: { name: "ФОП Ісаєв Д.І.", city: "Одеса" },
  });
  assert.match(txt, /ДОГОВІР № К-7/);
  assert.match(txt, /«21» листопада 2026 р\./);
  assert.match(txt, /не більше 5 робочих днів/);
  assert.match(txt, /Знижка на вартість робіт — 10%/);
  assert.match(txt, /Діагностика техніки Замовника виконується безоплатно/);
  assert.match(txt, /\+38 050 111 22 33/);
  assert.doesNotMatch(txt, /\{\{/);
  const p = renderContract(DEFAULT_TEMPLATES.person, { client: { name: "Іван", phones: [] }, contract: {}, requisites: {} });
  assert.match(p, /Індивідуальні умови не встановлені/);
  assert.doesNotMatch(p, /\{\{/);
});
