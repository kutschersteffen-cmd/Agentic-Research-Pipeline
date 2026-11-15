import { test } from "node:test";
import assert from "node:assert/strict";
import { CONTRIBUTOR_STATUS, fmtShare, fmtTonnes } from "../src/lib/cockpit.ts";

test("financed emissions read in whole tonnes with thousands separators, never 0 above 0 (AC-60, AC-63)", () => {
  assert.equal(fmtTonnes(37_936.4), "37,936");
  assert.equal(fmtTonnes(11_716.68), "11,717");
  assert.equal(fmtTonnes(376.65), "377");
  assert.equal(fmtTonnes(0.01), "0.01"); // the API rounds to 0.01 t
  assert.equal(fmtTonnes(0.04), "0.04");
  assert.equal(fmtTonnes(0), "0");
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
