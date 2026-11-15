import { test } from "node:test";
import assert from "node:assert/strict";
import { CONTRIBUTOR_STATUS, fmtMt, fmtShare } from "../src/lib/cockpit.ts";

test("financed emissions read in Mt CO₂e with two decimals (AC-60, AC-63)", () => {
  assert.equal(fmtMt(750_000), "0.75");
  assert.equal(fmtMt(1_840_000), "1.84");
  assert.equal(fmtMt(12_345_678), "12.35");
  assert.equal(fmtMt(0), "0.00");
});

test("contributor share is a whole percent, rounded half up", () => {
  assert.equal(fmtShare(0.5), "50%");
  assert.equal(fmtShare(0.158), "16%");
  assert.equal(fmtShare(0.0865), "9%");
  assert.equal(fmtShare(0.0849), "8%");
});

test("every contributor status has its label", () => {
  assert.deepEqual(Object.keys(CONTRIBUTOR_STATUS), ["in_escalation", "engaged", "selected", "not_selected"]);
});
