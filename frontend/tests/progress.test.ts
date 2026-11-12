import test from "node:test";
import assert from "node:assert/strict";
import { draftingLine, elapsedLabel } from "../src/lib/progress.ts";

test("elapsedLabel", () => {  // AC-86
  assert.deepEqual([0, 42, 196, 3600].map(elapsedLabel), ["0:00", "0:42", "3:16", "60:00"]);
});

test("draftingLine names what is drafted and for how long", () => {  // AC-87
  assert.equal(draftingLine("house_deck", 5), "Drafting the storyline… 0:05 elapsed. This can take a few minutes; keep this page open.");
  assert.equal(draftingLine("pptx", 65), "Drafting the content plan… 1:05 elapsed. This can take a few minutes; keep this page open.");
});
