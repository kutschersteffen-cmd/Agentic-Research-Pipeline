import { test } from "node:test";
import assert from "node:assert/strict";
import { gateLine } from "../src/lib/walkthrough.ts";

// evidence-gate spec, AC-27 to AC-30
test("gate line", () => {
  assert.equal(gateLine({ kept: 5, of: 10, failed: false, skipped: null }), "Gate: kept 5 of 10");
  assert.equal(gateLine({ kept: 10, of: 10, failed: false, skipped: "high risk" }), "Gate: off (high risk)");
  assert.equal(gateLine({ kept: 10, of: 10, failed: true, skipped: null }), "Gate: failed, kept all 10");
  assert.equal(gateLine(undefined), null);
});
