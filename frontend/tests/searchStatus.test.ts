import { test } from "node:test";
import assert from "node:assert/strict";
import { searchStatusText } from "../src/lib/argusFlow.ts";

test("an unfinished search with files listed says how many so far (showcase-stewardship-fixes AC-45, AC-46)", () => {
  assert.equal(searchStatusText("running", 3), "3 found so far, still checking other sources…");
  assert.equal(searchStatusText("running", 1), "1 found so far, still checking other sources…");
  assert.equal(searchStatusText("running", 0), "Searching…");
});
