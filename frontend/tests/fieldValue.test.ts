import test from "node:test";
import assert from "node:assert/strict";
import { isReleased, valueLabel } from "../src/lib/fieldValue.ts";

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
