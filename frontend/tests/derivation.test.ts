import test from "node:test";
import assert from "node:assert/strict";
import { derivationLines } from "../src/lib/derivation.ts";

const F = "scope1_tco2e__status == 'approved' ? scope1_tco2e : prov_esg_demo_scope1";

const a = {
  value: 90,
  unit: "tCO2e",
  status: "value",
  reason: null,
  derivation: {
    inputs: {
      scope1_tco2e: { value: 90, status: "approved", source: "extraction", provider: null, period_end: "2025-12-31", unit: "tCO2e", observation_id: 12 },
      prov_esg_demo_scope1: { value: 100, status: "auto_accepted", source: "provider", provider: "esg_demo", period_end: "2026-09-30", unit: "tCO2e", observation_id: 11 },
    },
    trace: [{ node: "Authoritative", expressions: [F], output: { auth_scope1: 90 } }],
  },
};

test("AC-30 lines: value, inputs and expression", () => {
  const lines = derivationLines(a);
  assert.equal(lines.value, "90 tCO2e");
  assert.ok(lines.inputs.includes("scope1_tco2e = 90 · approved · extraction · 2025-12-31"));
  assert.ok(lines.inputs.includes("prov_esg_demo_scope1 = 100 · auto_accepted · provider esg_demo · 2026-09-30"));
  assert.deepEqual(lines.expressions, [F]);
});

test("no value shows the reason", () => {
  const lines = derivationLines({ ...a, value: null, status: "no_value", reason: "not_in_dataset", derivation: { inputs: {}, trace: [] } });
  assert.equal(lines.value, "No value (not_in_dataset)");
  assert.deepEqual(lines.inputs, []);
});

test("a blank input reads as a dash", () => {
  const blank = { value: null, status: null, source: null, provider: null, period_end: null, unit: null, observation_id: null };
  const lines = derivationLines({ ...a, derivation: { inputs: { scope1_tco2e: blank }, trace: [] } });
  assert.deepEqual(lines.inputs, ["scope1_tco2e = —"]);
});

test("an object value is shown as JSON, not [object Object]", () => {
  const lines = derivationLines({ ...a, value: { low: 1, high: 2 }, unit: null });
  assert.equal(lines.value, '{"low":1,"high":2}');
});
