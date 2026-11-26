// Thematic Universe quick fixes (spec thematic-universe-quick-fixes): the mapping button wording.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const page = readFileSync(new URL("../src/pages/ThemeBuilder.tsx", import.meta.url), "utf8");

test("the mapping button reads Match activities to file labels", () => {  // AC-24
  assert.ok(page.includes("Match activities to file labels"));
  assert.ok(!page.includes("Suggest activity"));
  assert.ok(!page.includes("catalogue-label mapping"));
});
