import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { ruleInputs, ruleSentence, sameRule } from "../src/lib/ruleSentence.ts";
import type { FieldDefinition, FieldRule } from "../src/types.ts";

// Names of the spec's fixture schema F; the renderer reads only field_id and name.
const names: Record<string, string> = {
  ambition: "Halving target", pct: "Target reduction", year: "Target year", nz: "Net-zero target", nz2050: "Net zero by 2050",
  int1: "Scope 1 intensity", declined: "Intensity declined", kind: "Target type", s1: "Scope 1 target",
  green: "Green capex", total: "Total capex", other: "Other capex", share: "Green capex share",
};
const fields = Object.entries(names).map(([field_id, name]) => ({ field_id, name })) as FieldDefinition[];
const cases: { field_id: string; rule: FieldRule; sentence: string }[] = JSON.parse(
  readFileSync(new URL("../../backend/tests/fixtures/rule_sentences.json", import.meta.url), "utf8"),
);

test("every fixture rule renders its expected sentence", () => {
  assert.ok(cases.length >= 7);
  for (const c of cases) assert.equal(ruleSentence(c.rule, c.field_id, fields), c.sentence);
});

test("an unknown field id falls back to the id, and non-whole numbers keep their decimals", () => {
  const rule: FieldRule = { rule_id: "R", kind: "threshold", when: null, conditions: [{ field: "gone", op: "<", value: 0.5 }] };
  assert.equal(ruleSentence(rule, "pct", fields), "Needs gone < 0.5.");
});

test("rules read their inputs in naming order without repeats", () => {
  const rule: FieldRule = { rule_id: "R", kind: "threshold", conditions: [{ field: "b", op: ">", value: 1 }, { field: "a", op: ">", value: 1 }, { field: "b", op: "<", value: 9 }] };
  assert.deepEqual(ruleInputs(rule), ["b", "a"]);
  assert.deepEqual(ruleInputs({ rule_id: "R", kind: "computed", formula: "sum", inputs: ["x", "y"], tolerance: 0 }), ["x", "y"]);
  assert.deepEqual(ruleInputs({ rule_id: "R", kind: "label", field: "k", not_in: ["a"] }), ["k"]);
});

test("sameRule ignores rule_id but not the field, when or any parameter", () => {
  const a = { fieldId: "nz2050", rule: { rule_id: "R2", kind: "requires", when: true, field: "nz", equals: true } as FieldRule };
  assert.equal(sameRule(a, { fieldId: "nz2050", rule: { ...a.rule, rule_id: "R9" } }), true);
  assert.equal(sameRule(a, { fieldId: "nz2050", rule: { ...a.rule, when: false } }), false);
  assert.equal(sameRule(a, { fieldId: "nz2050", rule: { ...a.rule, when: null } }), false);
  assert.equal(sameRule(a, { fieldId: "other", rule: a.rule }), false);
  assert.equal(sameRule(a, { fieldId: "nz2050", rule: { ...a.rule, equals: false } as FieldRule }), false);
  const t = (op: ">=" | ">") => ({ fieldId: "x", rule: { rule_id: "R", kind: "threshold", conditions: [{ field: "p", op, value: 50 }] } as FieldRule });
  assert.equal(sameRule(t(">="), t(">=")), true);
  assert.equal(sameRule(t(">="), t(">")), false);
});
