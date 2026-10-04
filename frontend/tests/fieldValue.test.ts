import test from "node:test";
import assert from "node:assert/strict";
import { failedChecks, isReleased, isZero, routeLabel, valueLabel, withEditedValue } from "../src/lib/fieldValue.ts";
import { isTrialRun } from "../src/lib/runs.ts";

const f = (o: object) => ({ field_id: "x", field_name: "X", value: null, ...o }) as never;

test("valueLabel by state", () => {
  assert.equal(valueLabel(f({ value_state: "zero", value: 0, unit: "tCO2e" })), "0 tCO2e");
  assert.equal(valueLabel(f({ value_state: "zero", value: 0 })), "0");
  assert.equal(valueLabel(f({ value_state: "not_found" })), "not disclosed");
  assert.equal(valueLabel(f({ value_state: "not_applicable" })), "not applicable");
  assert.equal(valueLabel(f({ value_state: "found", value: 12.5, unit: "%" })), "12.5 %");
});

test("valueLabel legacy field without value_state", () => {
  assert.equal(valueLabel(f({})), "not disclosed");
  assert.equal(valueLabel(f({ value: 42 })), "42");
});

test("isReleased needs the flag and every field released", () => {
  assert.equal(isReleased({ release_flag: true, fields: [{ status: "draft" }] }), false);
  assert.equal(isReleased({ fields: [{ status: "released" }] }), false);
  assert.equal(isReleased({ release_flag: true, fields: [{ status: "released" }, { status: "released" }] }), true);
});

test("withEditedValue resets state and drops stale canonical", () => {
  const base = f({ value_state: "not_found", unit: "t", canonical_value: 1, canonical_unit: "kg", fx_rate: 2 });
  const e = withEditedValue(base, "5");
  assert.equal(valueLabel(e), "5 t");
  assert.deepEqual([e.canonical_value, e.canonical_unit, e.fx_rate], [null, null, null]);
  assert.equal(withEditedValue(f({ value_state: "found", value: 3 }), "0").value_state, "zero");
});

test("withEditedValue also drops scale and FX reference", () => {
  const e = withEditedValue(f({ value: 9, scale_applied: 1000, fx_rate: 1.1, fx_rate_ref: "fx_v1:EUR:2024" }), "7");
  assert.deepEqual([e.scale_applied, e.fx_rate, e.fx_rate_ref], [null, null, null]);
});

test("isZero matches the backend rule", () => {
  for (const v of ["0", "0.0", " 0 ", 0]) assert.equal(isZero(v), true, String(v));
  for (const v of [false, true, "", "abc", null, undefined, "5"]) assert.equal(isZero(v), false, String(v));
});

test("isTrialRun reads manifest params.trial", () => {
  assert.equal(isTrialRun({ params: { trial: true } }), true);
  assert.equal(isTrialRun({ params: { trial: false } }), false);
  assert.equal(isTrialRun({ params: {} }), false);
  assert.equal(isTrialRun(null), false);
});

test("routeLabel by route; legacy shows nothing", () => {
  assert.equal(routeLabel(f({ route: "auto_accept" })), "auto-accepted (system)");
  assert.equal(routeLabel(f({ route: "review" })), "in review");
  assert.equal(routeLabel(f({ route: "hold", route_reasons: ["entity_mismatch"] })), "held: entity_mismatch");
  assert.equal(routeLabel(f({})), null);
});

test("failedChecks keeps warn and block failures only", () => {
  const c = (check_id: string, outcome: string, severity: string) => ({ check_id, layer: 1, outcome, severity, detail: "d" });
  const checks = [c("a", "fail", "warn"), c("b", "fail", "block"), c("c", "fail", "info"), c("d", "pass", "block")];
  assert.deepEqual(failedChecks(f({ checks })).map((x) => x.check_id), ["a", "b"]);
  assert.deepEqual(failedChecks(f({})), []);
});
