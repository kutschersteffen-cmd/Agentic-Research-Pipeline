import { test } from "node:test";
import assert from "node:assert/strict";
import { routedLine } from "../src/lib/routeReasons.ts";

// showcase-stewardship-fixes AC-65..AC-67
test("route reasons read as words; failed checks are left out (they are listed above)", () => {
  assert.equal(routedLine(["unreleased_version", "check_failed", "check:consistency.entity"]),
    "Routed for review: the template is not released yet, a check failed");
  assert.equal(routedLine(["some_new_code"]), "Routed for review: some new code");
  assert.equal(routedLine(["check:consistency.entity"]), null);
  assert.equal(routedLine([]), null);
  assert.equal(routedLine(["low_confidence", "conflict", "verifier_disagrees"]),
    "Routed for review: low confidence, sources conflict, the verifier disagrees");
});
