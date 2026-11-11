import test from "node:test";
import assert from "node:assert/strict";
import { ITEM_KIND_LABEL, decisionChoices } from "../src/lib/reviewKeys.ts";

test("a conflict is labelled Conflict and decided by keeping or accepting", () => {
  assert.equal(ITEM_KIND_LABEL.conflict, "Conflict");
  assert.deepEqual(decisionChoices("conflict"), ["reject", "approve", "escalate"]);
});
